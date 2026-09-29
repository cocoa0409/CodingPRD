"""Shared business services: ledgers, risk scoring, selectors, interval
geometry and the cross-aggregate cascades of PRD §2.11."""

from datetime import timedelta

import calc
import db
from db import ordered, store, touch
from util import plus_days


# --------------------------------------------------------------------------- #
# lookups
# --------------------------------------------------------------------------- #

def lots_of_event(event_id):
    return ordered([l for l in store.auction_lots.values() if l["auction_event_id"] == event_id])


def lots_of_asset(asset_listing_id):
    return ordered([l for l in store.auction_lots.values()
                    if l["asset_listing_id"] == asset_listing_id])


def bids_of_lot(lot_id):
    return ordered([b for b in store.bids.values() if b["auction_lot_id"] == lot_id])


def holds_of_lot(lot_id):
    return ordered([h for h in store.deposit_holds.values() if h["auction_lot_id"] == lot_id])


def holds_of_bidder(bidder_id):
    return ordered([h for h in store.deposit_holds.values() if h["bidder_id"] == bidder_id])


def exclusions_of_bidder(bidder_id):
    return ordered([e for e in store.exclusions.values() if e["bidder_id"] == bidder_id])


def events_of_sale(trustee_sale_id):
    return ordered([e for e in store.auction_events.values()
                    if e["trustee_sale_id"] == trustee_sale_id])


def live_hold(bidder_id, lot_id):
    """The bidder's encumbered hold on the lot, if any."""
    for h in holds_of_lot(lot_id):
        if h["bidder_id"] == bidder_id and h["status"] in calc.HOLD_ENCUMBERED:
            return h
    return None


def active_bid_of_lot(lot_id):
    for b in bids_of_lot(lot_id):
        if b["bid_status"] == "ACTIVE":
            return b
    return None


def winning_bid_of_lot(lot_id):
    for b in bids_of_lot(lot_id):
        if b["bid_status"] == "WINNING":
            return b
    return None


# --------------------------------------------------------------------------- #
# deposit ledger (PRD §3.4) and screen score refresh
# --------------------------------------------------------------------------- #

def recompute_ledger(bidder):
    """Recompute the ledger from scratch. Returns True when a figure moved."""
    held_total = 0
    forfeited_total = 0
    for h in holds_of_bidder(bidder["id"]):
        if h["status"] in calc.HOLD_ENCUMBERED:
            held_total += h["amount_cents"]
        elif h["status"] == "CAPTURED":
            forfeited_total += h["amount_cents"]
    available = bidder["deposit_funded_cents"] - held_total - forfeited_total
    changed = (bidder["deposit_forfeited_cents"] != forfeited_total
               or bidder["deposit_available_cents"] != available)
    bidder["deposit_forfeited_cents"] = forfeited_total
    bidder["deposit_available_cents"] = available
    return changed


def recompute_screen_score(bidder):
    result = risk_assessment(bidder, "SCREEN", None, None)
    changed = bidder["screen_risk_score"] != result["risk_score"]
    bidder["screen_risk_score"] = result["risk_score"]
    return changed


def refresh_bidder(bidder, force=False, with_score=False):
    """Apply the computed-field recomputations, touching only on real change."""
    changed = recompute_ledger(bidder)
    if with_score:
        changed = recompute_screen_score(bidder) or changed
    if changed or force:
        touch(bidder)
    return changed


def refresh_bidders(bidder_ids, with_score=False):
    for bid_id in sorted(bidder_ids):
        bidder = store.bidders.get(bid_id)
        if bidder is not None:
            refresh_bidder(bidder, with_score=with_score)


# --------------------------------------------------------------------------- #
# bidder_risk_score (PRD §3.4)
# --------------------------------------------------------------------------- #

def risk_assessment(bidder, mode, lot, event):
    exclusions = exclusions_of_bidder(bidder["id"])
    clock = db.now()

    if mode == "SCREEN":
        identity_applies = bidder["identity_verification_status"] != "VERIFIED"
        county = event["county_code"] if event is not None else None
        counted = []
        for e in exclusions:
            if e["status"] != "ACTIVE":
                continue
            if e["county_code"] == "ALL" or (county is not None and e["county_code"] == county):
                counted.append(e)
    else:
        ref = event["starts_at"]
        verified_at = bidder["identity_verified_at"]
        identity_applies = verified_at is None or verified_at > ref
        county = event["county_code"]
        counted = []
        for e in exclusions:
            if e["effective_at"] is None or e["effective_at"] > ref:
                continue
            still_counted = (
                e["status"] == "ACTIVE"
                or (e["status"] == "LIFTED" and e["lifted_at"] is not None and e["lifted_at"] > ref)
            )
            if not still_counted:
                continue
            if e["county_code"] == "ALL" or e["county_code"] == county:
                counted.append(e)

    deposit_applies = lot is not None and \
        bidder["deposit_available_cents"] < lot["required_deposit_cents"]

    identity_points = calc.IDENTITY_PENALTY if identity_applies else 0
    exclusion_points = calc.EXCLUSION_PENALTY * len(counted)
    fallout_points = calc.FALLOUT_PENALTY * bidder["fallout_count"]
    deposit_points = calc.DEPOSIT_PENALTY if deposit_applies else 0

    total = identity_points + exclusion_points + fallout_points + deposit_points
    score = min(calc.RISK_SCORE_CAP, total)
    _ = clock
    return {
        "bidder_id": bidder["id"],
        "mode": mode,
        "risk_score": score,
        "eligible": score < calc.ELIGIBILITY_MAX_SCORE,
        "counted_exclusion_count": len(counted),
        "identity_penalty_applied": identity_points,
        "exclusion_penalty_applied": exclusion_points,
        "fallout_penalty_applied": fallout_points,
        "deposit_penalty_applied": deposit_points,
    }


def is_excluded_now(bidder_id, county_code):
    """Ladder rung 36."""
    clock = db.now()
    for e in exclusions_of_bidder(bidder_id):
        if e["status"] != "ACTIVE":
            continue
        if e["effective_at"] is None or e["effective_at"] > clock:
            continue
        if e["county_code"] == "ALL" or e["county_code"] == county_code:
            return True
    return False


# --------------------------------------------------------------------------- #
# selectors
# --------------------------------------------------------------------------- #

def winning_bid_candidates(lot):
    cands = [b for b in bids_of_lot(lot["id"])
             if b["bid_status"] == "ACTIVE" and b["is_above_reserve"]]
    cands.sort(key=lambda b: (-b["amount_cents"], b["created_at"], b["placed_at"], b["_seq"]))
    return cands


def backup_bid_candidates(lot):
    """PRD §3.8 — OUTBID, at or above reserve, bidder REGISTERED and VERIFIED."""
    cands = []
    for b in bids_of_lot(lot["id"]):
        if b["bid_status"] != "OUTBID":
            continue
        if b["amount_cents"] < lot["reserve_price_cents"]:
            continue
        bidder = store.bidders.get(b["bidder_id"])
        if bidder is None:
            continue
        if bidder["registration_status"] != "REGISTERED":
            continue
        if bidder["identity_verification_status"] != "VERIFIED":
            continue
        cands.append((b, bidder))
    cands.sort(key=lambda pair: (
        -pair[0]["amount_cents"],
        pair[0]["created_at"],
        pair[1]["created_at"],
        pair[1]["_seq"],
        pair[0]["_seq"],
    ))
    return cands


# --------------------------------------------------------------------------- #
# interval geometry (PRD §2.12)
# --------------------------------------------------------------------------- #

def county_slot_conflict(county_code, starts_at, ends_at, exclude_event_id=None):
    buffer = timedelta(minutes=calc.COUNTY_BUFFER_MINUTES)
    for other in store.auction_events.values():
        if other["county_code"] != county_code:
            continue
        if exclude_event_id is not None and other["id"] == exclude_event_id:
            continue
        if other["event_status"] not in ("SCHEDULED", "LIVE", "POSTPONED"):
            continue
        if starts_at <= other["ends_at"] + buffer and other["starts_at"] <= ends_at + buffer:
            return True
    return False


def lot_window_conflict(asset_listing_id, start_at, end_at, exclude_lot_id=None,
                        overrides=None):
    overrides = overrides or {}
    for other in store.auction_lots.values():
        if other["asset_listing_id"] != asset_listing_id:
            continue
        if exclude_lot_id is not None and other["id"] == exclude_lot_id:
            continue
        if other["lot_status"] not in calc.LOT_NON_TERMINAL:
            continue
        o_start, o_end = overrides.get(
            other["id"], (other["lot_window_start_at"], other["lot_window_end_at"]))
        if start_at < o_end and o_start < end_at:
            return True
    return False


# --------------------------------------------------------------------------- #
# derived-field maintenance
# --------------------------------------------------------------------------- #

def recompute_lot_count(event):
    count = len([l for l in store.auction_lots.values()
                 if l["auction_event_id"] == event["id"]])
    changed = event["lot_count"] != count
    event["lot_count"] = count
    return changed


def recompute_provisional_premium(lot):
    asset = store.asset_listings.get(lot["asset_listing_id"])
    if asset is None:
        return False
    value = calc.buyer_premium(
        lot["hammer_price_cents"], asset["occupancy_status"], asset["title_condition"])
    changed = lot["provisional_buyer_premium_cents"] != value
    lot["provisional_buyer_premium_cents"] = value
    return changed


def recompute_second_chance_eligible(asset, lot):
    value = bool(backup_bid_candidates(lot))
    changed = asset["second_chance_eligible"] != value
    asset["second_chance_eligible"] = value
    return changed


def release_hold(hold, reason):
    hold["status"] = "RELEASED"
    hold["released_reason"] = reason
    touch(hold)


def create_hold(bidder_id, lot):
    hold = db.new_record(
        bidder_id=bidder_id,
        auction_lot_id=lot["id"],
        amount_cents=lot["required_deposit_cents"],
        status="HELD",
        expires_at=plus_days(db.now(), calc.HOLD_INITIAL_DAYS),
        extension_count=0,
        released_reason=None,
    )
    store.deposit_holds[hold["id"]] = hold
    return hold


# --------------------------------------------------------------------------- #
# cascades
# --------------------------------------------------------------------------- #

def reage_holds_for_suspension(lot, affected):
    """Link 4 of the postponement cascade (PRD §3.2)."""
    for hold in holds_of_lot(lot["id"]):
        if hold["status"] not in calc.HOLD_ENCUMBERED:
            continue
        hold["extension_count"] = hold["extension_count"] + 1
        if hold["extension_count"] <= calc.MAX_HOLD_EXTENSIONS:
            hold["status"] = "EXTENDED"
            hold["expires_at"] = plus_days(db.now(), calc.HOLD_EXTENSION_DAYS)
        else:
            hold["status"] = "RELEASED"
            hold["released_reason"] = "EXTENSION_LIMIT"
            for bid in bids_of_lot(lot["id"]):
                if bid["bidder_id"] == hold["bidder_id"] and \
                        bid["bid_status"] in ("ACTIVE", "OUTBID"):
                    bid["bid_status"] = "WITHDRAWN"
                    touch(bid)
        touch(hold)
        affected.add(hold["bidder_id"])


def cascade_postponement(sale):
    """Links 2..5 of the postponement cascade."""
    affected = set()
    for event in events_of_sale(sale["id"]):
        if event["event_status"] not in ("SCHEDULED", "LIVE"):
            continue
        event["event_status"] = "POSTPONED"
        touch(event)
        for lot in lots_of_event(event["id"]):
            if lot["lot_status"] not in ("OPEN", "EXTENDED"):
                continue
            lot["lot_status"] = "SUSPENDED"
            touch(lot)
            reage_holds_for_suspension(lot, affected)
    refresh_bidders(affected)


def cascade_cancellation(sale):
    """The terminal cascade (PRD §2.11 / §3.2)."""
    affected = set()
    assets = []
    for event in events_of_sale(sale["id"]):
        if event["event_status"] not in ("SCHEDULED", "LIVE", "POSTPONED"):
            continue
        event["event_status"] = "CANCELLED"
        touch(event)
        for lot in lots_of_event(event["id"]):
            if lot["lot_status"] not in calc.LOT_NON_TERMINAL:
                continue
            lot["lot_status"] = "WITHDRAWN"
            touch(lot)
            for bid in bids_of_lot(lot["id"]):
                if bid["bid_status"] in ("ACTIVE", "OUTBID"):
                    bid["bid_status"] = "WITHDRAWN"
                    touch(bid)
            for hold in holds_of_lot(lot["id"]):
                if hold["status"] in calc.HOLD_ENCUMBERED:
                    release_hold(hold, "EVENT_CANCELLED")
                    affected.add(hold["bidder_id"])
            if lot["asset_listing_id"] not in assets:
                assets.append(lot["asset_listing_id"])
    refresh_bidders(affected)
    for asset_id in assets:
        asset = store.asset_listings.get(asset_id)
        if asset is not None and asset["listing_status"] == "LISTED":
            asset["listing_status"] = "UNSOLD"
            touch(asset)


def bubble_up_event_close(event):
    """A lot reaching a terminal status may close its LIVE event (PRD §3.6)."""
    if event["event_status"] != "LIVE":
        return
    for lot in lots_of_event(event["id"]):
        if lot["lot_status"] in calc.LOT_NON_TERMINAL:
            return
    event["event_status"] = "CLOSED"
    touch(event)


def bar_bidder_if_needed(bidder):
    """PRD §3.8 — repeat defaulters are barred with a PRIOR_FALLOUT exclusion."""
    if bidder["fallout_count"] < calc.BARRING_FALLOUT_THRESHOLD:
        return
    if bidder["registration_status"] not in ("REGISTERED", "SUSPENDED"):
        return
    bidder["registration_status"] = "BARRED"
    exclusion = db.new_record(
        bidder_id=bidder["id"],
        exclusion_type="PRIOR_FALLOUT",
        county_code="ALL",
        effective_at=db.now(),
        status="ACTIVE",
        lifted_at=None,
        notes=None,
    )
    store.exclusions[exclusion["id"]] = exclusion
