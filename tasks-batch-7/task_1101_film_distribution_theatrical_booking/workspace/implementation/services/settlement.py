"""Settlement pipeline, marketing waterfall, weekly close."""
from datetime import timedelta
from decimal import Decimal

from db import db
from services.core import touch, compute_current_week_rental_pct, new_entity_common
from services.clock import get_logical_clock
from util import parse_dt, iso_from_dt, new_id, utcnow_iso, dec_pct, round_half_up_int


HOLD_THRESHOLD_PER_SCREEN_CENTS = 100000  # $1000/wk/screen committed


def get_or_create_provisional_settlement(booking):
    """Get the in-week PROVISIONAL settlement for this booking, or create one.

    week_index = distributor.week_epoch (current epoch).
    """
    film = db.films.get(booking["film_id"])
    if not film:
        return None
    dist = db.distributors.get(film["distributor_id"])
    if not dist:
        return None
    week_idx = dist["week_epoch"]
    for s in db.settlements.values():
        if (s["booking_agreement_id"] == booking["id"]
                and s["week_index"] == week_idx
                and s["status"] in ("PROVISIONAL", "PENDING_FINAL", "FINALIZED")):
            return s
    # Create a new PROVISIONAL settlement for the current epoch
    common = new_entity_common()
    s = {
        **common,
        "booking_agreement_id": booking["id"],
        "week_index": week_idx,
        "gross_cents": 0,
        "house_allowance_cents": 0,
        "net_cents": 0,
        "rental_pct_applied": Decimal("0.0000"),
        "distributor_share_cents": 0,
        "exhibitor_share_cents": 0,
        "marketing_offset_cents": 0,
        "final_distributor_payout_cents": 0,
        "variant": "PROVISIONAL",
        "status": "PROVISIONAL",
    }
    db.settlements[s["id"]] = s
    recompute_provisional_settlement(s)
    return s


def _reports_for_week(booking_id, week_idx, statuses):
    out = []
    for r in db.box_office_reports.values():
        if r["booking_agreement_id"] != booking_id:
            continue
        if r["status"] not in statuses:
            continue
        if r.get("week_index") is not None and r["week_index"] != week_idx:
            continue
        # For DRAFT reports (week_index=None) only include them if week_idx is None (i.e., we don't filter)
        out.append(r)
    return out


def recompute_provisional_settlement(s):
    """Recompute provisional variant from DRAFT + SUBMITTED + LOCKED reports for the current epoch."""
    booking = db.booking_agreements.get(s["booking_agreement_id"])
    if not booking:
        return
    week_idx = s["week_index"]
    reports = []
    for r in db.box_office_reports.values():
        if r["booking_agreement_id"] != booking["id"]:
            continue
        if r["status"] not in ("DRAFT", "SUBMITTED", "LOCKED"):
            continue
        # include reports that haven't been stamped (current-week) or stamped with this week
        wi = r.get("week_index")
        if wi is not None and wi != week_idx:
            continue
        reports.append(r)
    gross = sum(r["gross_cents"] for r in reports)
    admissions = sum(r["admissions"] for r in reports)
    theatre = db.theatres.get(booking["theatre_id"])
    house = theatre["house_allowance_cents"] if theatre else 0
    net = max(0, gross - house)
    pct = compute_current_week_rental_pct(booking)
    share_before_floor = round_half_up_int(Decimal(net) * pct)
    per_capita_floor = admissions * booking["per_capita_floor_cents"]
    distributor_share = max(share_before_floor, per_capita_floor)
    exhibitor_share = net - distributor_share
    # Marketing offset for PROVISIONAL: same waterfall as final (PRD §3.7 step 9-10)
    offset = _compute_marketing_offset(booking, distributor_share)
    final_payout = distributor_share + offset

    s["gross_cents"] = gross
    s["house_allowance_cents"] = house
    s["net_cents"] = net
    s["rental_pct_applied"] = pct
    s["distributor_share_cents"] = distributor_share
    s["exhibitor_share_cents"] = exhibitor_share
    s["marketing_offset_cents"] = offset
    s["final_distributor_payout_cents"] = final_payout
    s["variant"] = "PROVISIONAL"
    # Do NOT touch version/updated_at here for mere recompute unless we want version bump;
    # PRD: every mutation refreshes updated_at + version.
    touch(s)


def _compute_marketing_offset(booking, distributor_share):
    """Step 9: marketing_offset = min(outstanding, committed * coop_share_pct) across linked commitments.

    PRD wording: "min(linked MarketingCommitment.outstanding_cents, committed_cents * coop_share_pct)".
    We find commitments matching (film_id, theatre_id) in {COMMITTED, ACCRUING}.
    Total offset is the min over the sum.
    """
    film_id = booking["film_id"]
    theatre_id = booking["theatre_id"]
    total_offset = 0
    for mc in db.marketing_commitments.values():
        if mc["film_id"] != film_id:
            continue
        if mc["theatre_id"] != theatre_id:
            continue
        if mc["status"] not in ("COMMITTED", "ACCRUING"):
            continue
        outstanding = mc["committed_cents"] - mc["spent_cents"]
        cap = round_half_up_int(Decimal(mc["committed_cents"]) * mc["coop_share_pct"])
        line_offset = min(outstanding, cap)
        total_offset += line_offset
    return total_offset


def _apply_marketing_waterfall(booking, offset_cents):
    """Step 9-10 waterfall: draw down each matching commitment in created_at ASC order."""
    film_id = booking["film_id"]
    theatre_id = booking["theatre_id"]
    candidates = []
    for mc in db.marketing_commitments.values():
        if mc["film_id"] != film_id:
            continue
        if mc["theatre_id"] != theatre_id:
            continue
        if mc["status"] not in ("COMMITTED", "ACCRUING"):
            continue
        candidates.append(mc)
    candidates.sort(key=lambda m: m["created_at"])
    remaining = offset_cents
    for mc in candidates:
        if remaining <= 0:
            break
        outstanding = mc["committed_cents"] - mc["spent_cents"]
        draw = min(remaining, outstanding)
        if draw <= 0:
            continue
        mc["spent_cents"] += draw
        # Flip COMMITTED -> ACCRUING on first draw
        if mc["status"] == "COMMITTED":
            mc["status"] = "ACCRUING"
        # If outstanding now 0 -> SETTLED
        if mc["committed_cents"] - mc["spent_cents"] == 0:
            mc["status"] = "SETTLED"
        touch(mc)
        remaining -= draw


def _recompute_final_fields(s):
    """Recompute the final-variant fields from LOCKED reports only (PRD §3.7:
    gross sums LOCKED reports only; aggregate allowance split applies).
    Used both when the first LOCKED report moves the settlement to
    PENDING_FINAL and at FINALIZED."""
    booking = db.booking_agreements.get(s["booking_agreement_id"])
    if not booking:
        return None
    week_idx = s["week_index"]
    locked = [r for r in db.box_office_reports.values()
              if r["booking_agreement_id"] == booking["id"]
              and r["status"] == "LOCKED"
              and r.get("week_index") == week_idx]
    gross = sum(r["gross_cents"] for r in locked)
    admissions = sum(r["admissions"] for r in locked)
    # House allowance: aggregate split if active aggregate, else per-theatre
    house = _compute_house_allowance(booking)
    net = max(0, gross - house)
    pct = compute_current_week_rental_pct(booking)
    share_before_floor = round_half_up_int(Decimal(net) * pct)
    per_capita_floor = admissions * booking["per_capita_floor_cents"]
    distributor_share = max(share_before_floor, per_capita_floor)
    exhibitor_share = net - distributor_share
    offset = _compute_marketing_offset(booking, distributor_share)
    final_payout = distributor_share + offset

    s["gross_cents"] = gross
    s["house_allowance_cents"] = house
    s["net_cents"] = net
    s["rental_pct_applied"] = pct
    s["distributor_share_cents"] = distributor_share
    s["exhibitor_share_cents"] = exhibitor_share
    s["marketing_offset_cents"] = offset
    s["final_distributor_payout_cents"] = final_payout
    s["variant"] = "FINAL"
    return booking


def finalize_settlement(s):
    """FINAL variant recompute from LOCKED reports only + apply aggregate split + marketing waterfall."""
    booking = _recompute_final_fields(s)
    if not booking:
        return
    s["status"] = "FINALIZED"
    touch(s)

    # Apply marketing waterfall (decrement commitment outstanding / bump spent)
    _apply_marketing_waterfall(booking, s["marketing_offset_cents"])


def _compute_house_allowance(booking):
    """Per-theatre allowance OR aggregate split with remainder to earliest-created participant."""
    ad_id = booking.get("aggregate_deal_id")
    if ad_id:
        ad = db.aggregate_deals.get(ad_id)
        if ad and ad["deal_status"] == "ACTIVE":
            # Participating agreements: those with this aggregate_deal_id AND status in ACCEPTED/IN_PLAY/HELD_OVER
            participants = [b for b in db.booking_agreements.values()
                            if b.get("aggregate_deal_id") == ad_id
                            and b["deal_status"] in ("ACCEPTED", "IN_PLAY", "HELD_OVER")]
            participants.sort(key=lambda b: b["created_at"])
            n = len(participants)
            if n > 0:
                total = ad["aggregate_house_allowance_cents"]
                share = total // n
                remainder = total - share * n
                # remainder goes to earliest-created_at
                for i, p in enumerate(participants):
                    if p["id"] == booking["id"]:
                        return share + (remainder if i == 0 else 0)
                return share
    theatre = db.theatres.get(booking["theatre_id"])
    return theatre["house_allowance_cents"] if theatre else 0


def run_weekly_close(distributor):
    """Advance week_epoch, lock reports, transition settlements, holdover recs, complete agreements,
    expire clearances/keys, flag violated ancillary windows."""
    did = distributor["id"]
    # 1) advance epoch
    distributor["week_epoch"] += 1
    touch(distributor)
    new_epoch = distributor["week_epoch"]
    # "prior week" = new_epoch - 1
    prior_week = new_epoch - 1

    # 2) lock SUBMITTED reports (those not yet stamped with a week_index, or stamped == prior week)
    for r in list(db.box_office_reports.values()):
        b = db.booking_agreements.get(r["booking_agreement_id"])
        if not b:
            continue
        f = db.films.get(b["film_id"])
        if not f or f["distributor_id"] != did:
            continue
        if r["status"] == "SUBMITTED" and r.get("week_index") is None:
            r["week_index"] = prior_week
            r["status"] = "LOCKED"
            touch(r)

    # 3) settlement cascade PROVISIONAL -> PENDING_FINAL -> FINALIZED
    # First: PROVISIONAL -> PENDING_FINAL if any LOCKED report exists for that week
    for s in list(db.settlements.values()):
        b = db.booking_agreements.get(s["booking_agreement_id"])
        if not b:
            continue
        f = db.films.get(b["film_id"])
        if not f or f["distributor_id"] != did:
            continue
        if s["status"] == "PROVISIONAL":
            # Has any LOCKED report for this week?
            has_locked = any(
                r["booking_agreement_id"] == b["id"]
                and r["status"] == "LOCKED"
                and r.get("week_index") == s["week_index"]
                for r in db.box_office_reports.values()
            )
            if has_locked:
                # PRD §3.7: the first LOCKED report moves the settlement to
                # PENDING_FINAL, recomputing the final-variant fields from
                # locked reports.
                _recompute_final_fields(s)
                s["status"] = "PENDING_FINAL"
                touch(s)

    # Then: PENDING_FINAL -> FINALIZED when no DRAFT or SUBMITTED remain for that week
    for s in list(db.settlements.values()):
        b = db.booking_agreements.get(s["booking_agreement_id"])
        if not b:
            continue
        f = db.films.get(b["film_id"])
        if not f or f["distributor_id"] != did:
            continue
        if s["status"] != "PENDING_FINAL":
            continue
        has_open = any(
            r["booking_agreement_id"] == b["id"]
            and r["status"] in ("DRAFT", "SUBMITTED")
            and (r.get("week_index") is None or r.get("week_index") == s["week_index"])
            for r in db.box_office_reports.values()
        )
        if not has_open:
            finalize_settlement(s)

    # 4) holdover recommendations for IN_PLAY + eligible
    for b in list(db.booking_agreements.values()):
        f = db.films.get(b["film_id"])
        if not f or f["distributor_id"] != did:
            continue
        if b["deal_status"] != "IN_PLAY":
            continue
        if b["weeks_played"] < b["min_weeks_committed"]:
            continue
        # Compute prior-week gross (LOCKED, week_index == prior_week)
        prior_gross = sum(
            r["gross_cents"]
            for r in db.box_office_reports.values()
            if r["booking_agreement_id"] == b["id"]
            and r["status"] == "LOCKED"
            and r.get("week_index") == prior_week
        )
        threshold = b["min_weeks_committed"] * HOLD_THRESHOLD_PER_SCREEN_CENTS
        decision = "AUTO_HOLD" if prior_gross >= threshold else "AUTO_RELEASE"
        common = new_entity_common()
        hd = {
            **common,
            "booking_agreement_id": b["id"],
            "week_index": new_epoch,
            "prior_week_gross_cents": prior_gross,
            "decision": decision,
            "rationale": None,
        }
        db.holdover_decisions[hd["id"]] = hd

    # 5) auto-complete agreements
    for b in list(db.booking_agreements.values()):
        f = db.films.get(b["film_id"])
        if not f or f["distributor_id"] != did:
            continue
        if b["deal_status"] == "IN_PLAY":
            if b["weeks_played"] < b["min_weeks_committed"]:
                continue
            # No further holdover requested: check no HELD_OVER status currently. Since we're IN_PLAY, ok.
            # Latest settlement in SETTLED or WRITTEN_OFF
            settlements = [s for s in db.settlements.values() if s["booking_agreement_id"] == b["id"]]
            if not settlements:
                continue
            settlements.sort(key=lambda s: s["created_at"])
            latest = settlements[-1]
            if latest["status"] not in ("SETTLED", "WRITTEN_OFF"):
                continue
            _complete_agreement(b)
        elif b["deal_status"] == "HELD_OVER":
            # Need holdover released prior week. Look for a RELEASE HoldoverDecision with week_index == prior_week
            released = any(
                h["booking_agreement_id"] == b["id"]
                and h["decision"] == "RELEASE"
                and h["week_index"] == prior_week
                for h in db.holdover_decisions.values()
            )
            if not released:
                continue
            settlements = [s for s in db.settlements.values() if s["booking_agreement_id"] == b["id"]]
            if not settlements:
                continue
            settlements.sort(key=lambda s: s["created_at"])
            latest = settlements[-1]
            if latest["status"] != "SETTLED":
                continue
            _complete_agreement(b)

    # 6) expire zone clearances and KDMs and ancillary violations (clock-based)
    from services.cascade import _bump_zone_clearance_expiry, _bump_kdm_states
    _bump_zone_clearance_expiry()
    _bump_kdm_states()

    # 7) Ancillary window violations: SCHEDULED with scheduled_start < theatrical_window_end -> VIOLATED
    for w in list(db.ancillary_windows.values()):
        if w["status"] != "SCHEDULED":
            continue
        f = db.films.get(w["film_id"])
        if not f or f["distributor_id"] != did:
            continue
        ss = parse_dt(w["scheduled_start_utc"])
        twe = parse_dt(f["theatrical_window_end"])
        if ss is not None and twe is not None and ss < twe:
            w["status"] = "VIOLATED"
            touch(w)


def _complete_agreement(b):
    """Transition to COMPLETED with screen/screens_committed cascades and print_status -> PRINT_STRUCK."""
    b["deal_status"] = "COMPLETED"
    if b["print_status"] == "KEY_LIVE":
        b["print_status"] = "PRINT_STRUCK"
        # expire any LIVE KDM
        for k in db.kdm_keys.values():
            if k["booking_agreement_id"] == b["id"] and k["status"] == "LIVE":
                k["status"] = "EXPIRED"
                touch(k)
    touch(b)
    # Free screen
    screen = db.screens.get(b["screen_id"])
    if screen and screen["status"] == "BOOKED":
        screen["status"] = "AVAILABLE"
        touch(screen)
