"""Auction pipeline and bids (PRD §3.7)."""
from datetime import timedelta

from flask import Blueprint, g, request

import db
from errors import fail
from middleware import body, require_roles
from models import auction_view, bid_view
from response import list_response, ok_object
from routes.common import field, load
from services import calc

bp = Blueprint("auctions", __name__)

WINDOW_INFLATION = timedelta(hours=12)


@bp.post("/registry/auctions")
@require_roles("Registrar")
def create_auction():
    data = body()
    recovery_intake_id = field(data, "recovery_intake_id", "string", required=True)
    starts_at = field(data, "starts_at", "datetime", required=True)
    ends_at = field(data, "ends_at", "datetime", required=True)
    if starts_at >= ends_at:
        fail("ERR_INVALID_REQUEST", "starts_at must precede ends_at")

    intake = load(db.intakes, recovery_intake_id, "ERR_RECOVERY_INTAKE_NOT_FOUND")

    # The single-auction constraint is deliberately evaluated BEFORE the
    # intake's state check (PRD §3.7).
    if any(a["recovery_intake_id"] == intake["id"] and a["status"] != "CANCELLED"
           for a in db.auctions.values()):
        fail("ERR_AUCTION_ALREADY_EXISTS", "A non-CANCELLED auction already exists for this intake")
    if intake["status"] != "UNCLAIMED":
        fail("ERR_RECOVERY_NOT_ACTIONABLE", "Intake is not UNCLAIMED")

    # Neighborhood rule: the new window, inflated 12h on each side, must not
    # overlap any other non-CANCELLED auction of the same partner org.
    new_start = starts_at - WINDOW_INFLATION
    new_end = ends_at + WINDOW_INFLATION
    for other in db.auctions.values():
        if other["status"] == "CANCELLED":
            continue
        other_intake = db.intakes.get(other["recovery_intake_id"])
        if other_intake is None or other_intake["partner_org_id"] != intake["partner_org_id"]:
            continue
        if new_start < other["ends_at"] and other["starts_at"] < new_end:
            fail("ERR_AUCTION_WINDOW_CONFLICT",
                 "Inflated auction window collides with another auction of this partner org")

    reserve = calc.reserve_price(intake["appraised_value_cents"])
    # Estimate variant of the settlement waterfall at creation.
    est_storage, est_commission, est_payout = calc.settlement_waterfall(reserve, ends_at, intake)

    rec = db.new_record({
        "recovery_intake_id": intake["id"],
        "starts_at": starts_at,
        "ends_at": ends_at,
        "reserve_price_cents": reserve,
        "estimated_storage_fee_cents": est_storage,
        "estimated_program_commission_cents": est_commission,
        "estimated_partner_payout_cents": est_payout,
        "final_storage_fee_cents": None,
        "final_program_commission_cents": None,
        "final_partner_payout_cents": None,
        "winning_bid_id": None,
        "status": "SCHEDULED",
        "closed_at": None,
    })
    db.auctions[rec["id"]] = rec
    intake["status"] = "DISPOSITION_SCHEDULED"
    db.bump(intake)
    return ok_object(auction_view(rec), status=201)


@bp.get("/registry/auctions")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def list_auctions():
    recs = list(db.auctions.values())
    for param, key in (("recovery_intake_id", "recovery_intake_id"), ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            recs = [a for a in recs if a[key] == value]
    return list_response(recs, auction_view)


@bp.get("/registry/auctions/<auction_id>")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def read_auction(auction_id):
    rec = load(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    return ok_object(auction_view(rec))


@bp.post("/registry/auctions/<auction_id>/open")
@require_roles("Registrar")
def open_auction(auction_id):
    rec = load(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    if rec["status"] != "SCHEDULED":
        fail("ERR_AUCTION_NOT_OPEN", "Only a SCHEDULED auction can be opened")
    if db.now() < rec["starts_at"]:
        fail("ERR_AUCTION_NOT_YET_OPEN", "The bidding window has not started")
    if db.now() > rec["ends_at"]:
        fail("ERR_AUCTION_WINDOW_EXPIRED", "The bidding window has expired")
    rec["status"] = "OPEN"
    db.bump(rec)
    return ok_object(auction_view(rec))


@bp.post("/registry/auctions/<auction_id>/close")
@require_roles("Registrar")
def close_auction(auction_id):
    rec = load(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    if rec["status"] != "OPEN":
        fail("ERR_AUCTION_NOT_CLOSABLE", "Only an OPEN auction can be closed")
    if db.now() < rec["ends_at"]:
        fail("ERR_AUCTION_NOT_CLOSABLE", "The bidding window has not ended")

    rec["closed_at"] = db.now()
    rec["status"] = "CLOSED"
    db.bump(rec)

    # Rank the field: leader -> WINNING; every other ACTIVE bid -> OUTBID.
    active = [b for b in db.bids.values()
              if b["auction_id"] == rec["id"] and b["status"] == "ACTIVE"]
    if active:
        leader = max(active, key=lambda b: (b["amount_cents"], -b["_seq"]))
        for b in active:
            if b["id"] == leader["id"]:
                b["status"] = "WINNING"
                db.bump(b)
            else:
                b["status"] = "OUTBID"
                db.bump(b)
                db.notify(b["bidder_owner_id"], "BID_OUTBID",
                          "Your bid has been outbid.",
                          related_entity_type="Bid", related_entity_id=b["id"])
    return ok_object(auction_view(rec))


@bp.post("/registry/auctions/<auction_id>/settle")
@require_roles("Registrar")
def settle_auction(auction_id):
    rec = load(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    if rec["status"] != "CLOSED":
        fail("ERR_AUCTION_NOT_SETTLABLE", "Only a CLOSED auction can be settled")

    intake = db.intakes.get(rec["recovery_intake_id"])
    winning = next((b for b in db.bids.values()
                    if b["auction_id"] == rec["id"] and b["status"] == "WINNING"), None)

    if winning is not None:
        # Final waterfall: winning bid drives gross, closed_at is the cutoff.
        gross = winning["amount_cents"]
        storage, commission, payout = calc.settlement_waterfall(gross, rec["closed_at"], intake)
        rec["final_storage_fee_cents"] = storage
        rec["final_program_commission_cents"] = commission
        rec["final_partner_payout_cents"] = payout
        rec["winning_bid_id"] = winning["id"]

        winning["status"] = "WON"
        db.bump(winning)
        for b in db.bids.values():
            if b["auction_id"] == rec["id"] and b["status"] == "OUTBID":
                b["status"] = "LOST"
                db.bump(b)

        # Balanced ledger set (PRD §2.8): escrow in, then storage/commission/payout out.
        db.post_ledger("AUCTION_ESCROW", "DEBIT", "OWNER", gross,
                       owner_id=winning["bidder_owner_id"], auction_id=rec["id"],
                       reference_note=f"Auction {rec['id']} winning bid escrow")
        db.post_ledger("AUCTION_ESCROW", "CREDIT", "ESCROW", gross,
                       auction_id=rec["id"],
                       reference_note=f"Auction {rec['id']} winning bid escrow")
        db.post_ledger("STORAGE_FEE", "DEBIT", "ESCROW", storage,
                       auction_id=rec["id"],
                       reference_note=f"Auction {rec['id']} storage fee")
        db.post_ledger("STORAGE_FEE", "CREDIT", "PARTNER_ORG", storage,
                       partner_org_id=intake["partner_org_id"], auction_id=rec["id"],
                       reference_note=f"Auction {rec['id']} storage fee")
        db.post_ledger("AUCTION_COMMISSION", "DEBIT", "ESCROW", commission,
                       auction_id=rec["id"],
                       reference_note=f"Auction {rec['id']} program commission")
        db.post_ledger("AUCTION_COMMISSION", "CREDIT", "PROGRAM", commission,
                       auction_id=rec["id"],
                       reference_note=f"Auction {rec['id']} program commission")
        db.post_ledger("AUCTION_PARTNER_PAYOUT", "DEBIT", "ESCROW", payout,
                       auction_id=rec["id"],
                       reference_note=f"Auction {rec['id']} partner payout")
        db.post_ledger("AUCTION_PARTNER_PAYOUT", "CREDIT", "PARTNER_ORG", payout,
                       partner_org_id=intake["partner_org_id"], auction_id=rec["id"],
                       reference_note=f"Auction {rec['id']} partner payout")

        db.notify(winning["bidder_owner_id"], "AUCTION_WON",
                  "You won the auction.",
                  related_entity_type="Auction", related_entity_id=rec["id"])

    rec["status"] = "SETTLED"
    db.bump(rec)
    if intake is not None and intake["status"] == "DISPOSITION_SCHEDULED":
        intake["status"] = "DISPOSED"
        db.bump(intake)
    return ok_object(auction_view(rec))


@bp.post("/registry/auctions/<auction_id>/void-settlement")
@require_roles("Registrar")
def void_settlement(auction_id):
    rec = load(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    if rec["status"] != "SETTLED":
        fail("ERR_AUCTION_NOT_SETTLABLE", "Only a SETTLED auction can be voided")

    # Mirrored REVERSAL entries with directions swapped (double-entry preserved).
    originals = [e for e in db.ledger.values()
                 if e["auction_id"] == rec["id"] and e["entry_type"] != "REVERSAL"]
    for entry in sorted(originals, key=lambda e: e["_seq"]):
        swapped = "CREDIT" if entry["direction"] == "DEBIT" else "DEBIT"
        db.post_ledger("REVERSAL", swapped, entry["account"], entry["amount_cents"],
                       owner_id=entry["owner_id"], partner_org_id=entry["partner_org_id"],
                       auction_id=entry["auction_id"], bicycle_id=entry["bicycle_id"],
                       reference_note=f"Reversal of ledger entry {entry['id']}")
    rec["status"] = "VOIDED"
    db.bump(rec)
    # The void is financial only: the intake remains DISPOSED.
    return ok_object(auction_view(rec))


@bp.post("/registry/auctions/<auction_id>/cancel")
@require_roles("Registrar")
def cancel_auction(auction_id):
    rec = load(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    if rec["status"] == "SCHEDULED":
        pass
    elif rec["status"] == "OPEN":
        if any(b["auction_id"] == rec["id"] for b in db.bids.values()):
            fail("ERR_AUCTION_HAS_BIDS", "An OPEN auction with bids cannot be cancelled")
    else:
        fail("ERR_AUCTION_NOT_SETTLABLE", "Auction cannot be cancelled from its state")

    rec["status"] = "CANCELLED"
    db.bump(rec)
    intake = db.intakes.get(rec["recovery_intake_id"])
    if intake is not None and intake["status"] == "DISPOSITION_SCHEDULED":
        intake["status"] = "UNCLAIMED"
        db.bump(intake)
    return ok_object(auction_view(rec))


# ---- Bids -------------------------------------------------------------------

@bp.post("/registry/auctions/<auction_id>/bids")
@require_roles("Owner")
def place_bid(auction_id):
    data = body()
    amount_cents = field(data, "amount_cents", "integer", required=True, min_value=1)
    expected = field(data, "expected_auction_version", "integer", required=True)

    auction = load(db.auctions, auction_id, "ERR_AUCTION_NOT_FOUND")
    # OCC guard (stage 8) precedes the stage-10 from-state check.
    if expected != auction["version"]:
        fail("ERR_STALE_VERSION", "Auction version has advanced; re-read before bidding")
    if auction["status"] != "OPEN":
        fail("ERR_AUCTION_NOT_OPEN", "Auction is not open for bidding")
    if db.now() > auction["ends_at"]:
        fail("ERR_AUCTION_WINDOW_EXPIRED", "The bidding window has expired")

    active_amounts = [b["amount_cents"] for b in db.bids.values()
                      if b["auction_id"] == auction["id"] and b["status"] == "ACTIVE"]
    minimum = calc.next_minimum_bid(auction["reserve_price_cents"], active_amounts)
    if amount_cents < minimum:
        fail("ERR_BID_BELOW_MINIMUM", f"Bid is below the next minimum of {minimum}")

    rec = db.new_record({
        "auction_id": auction["id"],
        "bidder_owner_id": g.user_id,
        "amount_cents": amount_cents,
        "status": "ACTIVE",
    })
    db.bids[rec["id"]] = rec
    db.bump(auction)  # every accepted bid advances the auction's version
    return ok_object(bid_view(rec), status=201)


@bp.get("/registry/bids")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def list_bids():
    recs = list(db.bids.values())
    if g.role == "Owner":
        recs = [b for b in recs if b["bidder_owner_id"] == g.user_id]
    for param, key in (("auction_id", "auction_id"),
                       ("bidder_owner_id", "bidder_owner_id"), ("status", "status")):
        value = request.args.get(param)
        if value is not None:
            recs = [b for b in recs if b[key] == value]
    return list_response(recs, bid_view)


@bp.get("/registry/bids/<bid_id>")
@require_roles("Owner", "Partner", "Registrar", "Admin")
def read_bid(bid_id):
    rec = load(db.bids, bid_id, "ERR_BID_NOT_FOUND")
    if g.role == "Owner" and rec["bidder_owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Owners may read only their own bids")
    return ok_object(bid_view(rec))


@bp.post("/registry/bids/<bid_id>/retract")
@require_roles("Owner")
def retract_bid(bid_id):
    rec = load(db.bids, bid_id, "ERR_BID_NOT_FOUND")
    if rec["bidder_owner_id"] != g.user_id:
        fail("ERR_FORBIDDEN_RESOURCE_ACCESS", "Only the bidder may retract a bid")
    auction = db.auctions.get(rec["auction_id"])
    if rec["status"] != "ACTIVE":
        fail("ERR_BID_NOT_RETRACTABLE", "Only an ACTIVE bid can be retracted")
    if auction is None or auction["status"] != "OPEN":
        fail("ERR_BID_NOT_RETRACTABLE", "The auction is not open")
    active = [b for b in db.bids.values()
              if b["auction_id"] == rec["auction_id"] and b["status"] == "ACTIVE"]
    if active and rec["amount_cents"] == max(b["amount_cents"] for b in active):
        fail("ERR_BID_NOT_RETRACTABLE", "The leading bid is locked in")
    rec["status"] = "RETRACTED"
    db.bump(rec)
    return ok_object(bid_view(rec))
