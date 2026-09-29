"""Event settlement, dispute resolution and arbitration (PRD 3.9)."""

from datetime import timedelta

from flask import Blueprint

import calc
import clock
import lookups
import validate
from db import db
from errors import err
from middleware import actor, body, endpoint, filter_rows, require_owner, touch
from response import entity_response
from routes.common import LINE_KINDS, SETTLEMENT_BASES, body_fk, listing
from services import engine
from util import iso_instant, parse_instant

bp = Blueprint("settlements", __name__)


@bp.post("/bookings/<booking_id>/settlement")
@endpoint("SettlementAnalyst")
def open_settlement(booking_id):
    booking = lookups.fetch("booking", booking_id)
    payload = body()
    basis = validate.req_enum(payload, "basis", SETTLEMENT_BASES)
    if lookups.settlements_of_booking(booking["id"]):
        raise err("ERR_SETTLEMENT_ALREADY_EXISTS")

    settlement = db.insert(
        "settlement",
        {
            "booking_id": booking["id"],
            "basis": basis,
            "status": "DRAFT",
            "line_subtotal_cents": 0,
            "facility_service_fee_cents": 0,
            "deposit_applied_cents": 0,
            "grand_total_cents": 0,
            "revision_round": 0,
            "dispute_reason": None,
            "issued_by_user_id": None,
            "issued_at_utc": None,
            "dispute_deadline_utc": None,
            "finalized_by_user_id": None,
        },
    )
    return entity_response(settlement, 201)


@bp.get("/settlements")
@endpoint("VenueAdmin", "SettlementAnalyst", "Licensee")
def list_settlements():
    return listing(filter_rows("settlement", {"booking_id": "booking_id", "status": "status"}))


@bp.get("/settlements/<settlement_id>")
@endpoint("VenueAdmin", "SettlementAnalyst", "Licensee")
def read_settlement(settlement_id):
    return entity_response(lookups.fetch("settlement", settlement_id))


# --------------------------------------------------------------------------
# SettlementLineItem
# --------------------------------------------------------------------------
@bp.post("/settlement-line-items")
@endpoint("SettlementAnalyst")
def append_line_item():
    payload = body()
    settlement = body_fk(payload, "settlement_id", "settlement")
    line_kind = validate.req_enum(payload, "line_kind", LINE_KINDS)
    amount = validate.req_int(payload, "amount_cents")
    source_ref_id = validate.opt_string(payload, "source_ref_id")
    memo = validate.opt_string(payload, "memo")

    # ladder step 18: the sign rule, enforced at append time
    if line_kind != "ADJUSTMENT" and amount <= 0:
        raise err("ERR_LINE_AMOUNT_INVALID")
    existing = calc.settlement_line_extension(lookups.line_items_of_settlement(settlement["id"]))
    if existing + amount <= 0:
        raise err("ERR_LINE_AMOUNT_INVALID")

    line = db.insert(
        "line_item",
        {
            "settlement_id": settlement["id"],
            "line_kind": line_kind,
            "source_ref_id": source_ref_id,
            "amount_cents": amount,
            "memo": memo,
        },
        versioned=False,
    )
    return entity_response(line, 201)


@bp.get("/settlement-line-items")
@endpoint("VenueAdmin", "SettlementAnalyst", "Licensee")
def list_line_items():
    rows = filter_rows("line_item", {"settlement_id": "settlement_id", "line_kind": "line_kind"})
    return listing(rows)


@bp.get("/settlements/<settlement_id>/line-items")
@endpoint("VenueAdmin", "SettlementAnalyst", "Licensee")
def list_line_items_of_settlement(settlement_id):
    settlement = lookups.fetch("settlement", settlement_id)
    return listing(lookups.line_items_of_settlement(settlement["id"]))


# --------------------------------------------------------------------------
# the dispute cycle
# --------------------------------------------------------------------------
@bp.post("/settlements/<settlement_id>/issue")
@endpoint("SettlementAnalyst")
def issue_settlement(settlement_id):
    settlement = lookups.fetch("settlement", settlement_id)
    if settlement["status"] not in ("DRAFT", "DISPUTED"):
        raise err("ERR_SETTLEMENT_STATE_INVALID")

    reissue = settlement["status"] == "DISPUTED"
    booking = db.bookings.get(settlement["booking_id"])
    if not reissue and (booking is None or booking["status"] != "CLOSED"):
        raise err("ERR_BOOKING_STATE_INVALID")
    if reissue and settlement["revision_round"] >= calc.MAX_SETTLEMENT_REVISIONS:
        raise err("ERR_SETTLEMENT_REVISION_LIMIT_REACHED")

    # ladder step 17: settlement composition
    if settlement["basis"] == "ACTUAL_USAGE" and not lookups.usage_records_of_booking(
        settlement["booking_id"]
    ):
        raise err("ERR_NO_USAGE_RECORDS")
    lines = lookups.line_items_of_settlement(settlement["id"])
    rental_lines = [l for l in lines if l["line_kind"] == "RENTAL"]
    if len(rental_lines) != 1:
        raise err("ERR_RENTAL_LINE_MISMATCH")
    if rental_lines[0]["amount_cents"] != engine.rental_basis_for(settlement):
        raise err("ERR_RENTAL_LINE_MISMATCH")

    issued_at = clock.now()
    engine.recompute_settlement_totals(settlement)
    if reissue:
        settlement["revision_round"] = settlement["revision_round"] + 1
        settlement["dispute_reason"] = None
    settlement["status"] = "ISSUED"
    settlement["issued_by_user_id"] = actor()
    settlement["issued_at_utc"] = iso_instant(issued_at)
    settlement["dispute_deadline_utc"] = iso_instant(
        issued_at + timedelta(hours=calc.DISPUTE_WINDOW_HOURS)
    )
    touch(settlement)
    return entity_response(settlement)


@bp.post("/settlements/<settlement_id>/dispute")
@endpoint("Licensee")
def dispute_settlement(settlement_id):
    settlement = lookups.fetch("settlement", settlement_id)
    booking = db.bookings.get(settlement["booking_id"])
    require_owner(booking["client_id"] if booking else None)
    payload = body()
    reason = validate.req_string(payload, "dispute_reason")

    if settlement["status"] != "ISSUED":
        raise err("ERR_SETTLEMENT_STATE_INVALID")
    deadline = parse_instant(settlement.get("dispute_deadline_utc"))
    if deadline is not None and clock.now() > deadline:
        raise err("ERR_DISPUTE_WINDOW_CLOSED")

    settlement["status"] = "DISPUTED"
    settlement["dispute_reason"] = reason
    touch(settlement)
    return entity_response(settlement)


@bp.post("/settlements/<settlement_id>/escalate")
@endpoint("SettlementAnalyst")
def escalate_settlement(settlement_id):
    settlement = lookups.fetch("settlement", settlement_id)
    if settlement["status"] != "DISPUTED":
        raise err("ERR_SETTLEMENT_STATE_INVALID")
    if settlement["revision_round"] < calc.MAX_SETTLEMENT_REVISIONS:
        raise err("ERR_SETTLEMENT_REVISION_LIMIT_REACHED")

    settlement["status"] = "ARBITRATION"
    touch(settlement)
    return entity_response(settlement)


@bp.post("/settlements/<settlement_id>/finalize")
@endpoint("SettlementAnalyst")
def finalize_settlement_route(settlement_id):
    settlement = lookups.fetch("settlement", settlement_id)
    if settlement["status"] != "ISSUED":
        raise err("ERR_SETTLEMENT_STATE_INVALID")
    if actor() == settlement.get("issued_by_user_id"):
        raise err("ERR_SEGREGATION_OF_DUTIES")
    deadline = parse_instant(settlement.get("dispute_deadline_utc"))
    if deadline is not None and not clock.now() > deadline:
        raise err("ERR_DISPUTE_WINDOW_OPEN")

    engine.finalize_settlement(settlement, actor())
    return entity_response(settlement)


@bp.post("/settlements/<settlement_id>/arbitrate-finalize")
@endpoint("VenueAdmin")
def arbitrate_finalize(settlement_id):
    settlement = lookups.fetch("settlement", settlement_id)
    if settlement["status"] != "ARBITRATION":
        raise err("ERR_SETTLEMENT_STATE_INVALID")
    engine.finalize_settlement(settlement, actor())
    return entity_response(settlement)
