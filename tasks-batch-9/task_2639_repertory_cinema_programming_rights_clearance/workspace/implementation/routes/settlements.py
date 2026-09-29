"""Distributor settlement (PRD 3.9)."""
from flask import Blueprint

import serialize
from auth import ROLE_BOX, ROLE_EXEC, authorize
from calc import settlement_figures
from errors import ApiError
from response import object_response, paged
from store import new_record, ordered, touch
from validate import (SETTLEMENT_VARIANTS, body, find, insert, must_find, opt_str,
                      query_str, req_enum, req_id, req_int, req_str, rows)

bp = Blueprint("settlements", __name__)

BLOCKING_STATUSES = ("SUBMITTED", "RECONCILED", "PAID")


def require_settlement_state(settlement, allowed):
    if settlement["status"] not in allowed:
        raise ApiError("ERR_SETTLEMENT_INVALID_STATE",
                       "A settlement in %s does not admit this transition."
                       % settlement["status"])


def _apply_figures(settlement, booking, venue, variant):
    figures = settlement_figures(booking, venue, variant)
    settlement.update(figures)
    settlement["variant"] = variant
    return settlement


@bp.post("/settlements")
def create_settlement():
    authorize((ROLE_BOX,))
    payload = body()
    variant = req_enum(payload, "variant", SETTLEMENT_VARIANTS)
    expected_version = req_int(payload, "expected_booking_version", minimum=0)
    booking_id = req_id(payload, "booking_id")
    booking = must_find("bookings", booking_id)
    if expected_version != booking["version"]:
        raise ApiError("ERR_STALE_BOOKING_VERSION",
                       "expected_booking_version %d does not match %d."
                       % (expected_version, booking["version"]))
    if booking["status"] != "CLOSED":
        raise ApiError("ERR_SETTLEMENT_NOT_PERMITTED",
                       "Only a closed engagement can be settled.")
    for other in rows("settlements"):
        if other["booking_id"] == booking_id and other["status"] in BLOCKING_STATUSES:
            raise ApiError("ERR_SETTLEMENT_NOT_PERMITTED",
                           "A live settlement already exists on this engagement.")
    venue = must_find("venues", booking["venue_id"])
    row = new_record(
        booking_id=booking_id,
        variant=variant,
        status="DRAFT",
        min_run_penalty_cents=booking["min_run_penalty_cents"],
        submitted_by_user_id=None,
        finalized_by_user_id=None,
        dispute_note=None,
    )
    _apply_figures(row, booking, venue, variant)
    insert("settlements", row)
    touch(booking)
    return object_response(serialize.settlement(row), 201)


@bp.get("/settlements/<settlement_id>")
def read_settlement(settlement_id):
    authorize((ROLE_BOX, ROLE_EXEC))
    return object_response(serialize.settlement(must_find("settlements", settlement_id)))


@bp.get("/settlements")
def list_settlements():
    authorize((ROLE_BOX, ROLE_EXEC))
    found = rows("settlements")
    for name in ("booking_id", "variant", "status"):
        value = query_str(name)
        if value is not None:
            found = [s for s in found if s[name] == value]
    return paged(ordered(found), serialize.settlement)


@bp.post("/settlements/<settlement_id>/submit")
def submit_settlement(settlement_id):
    role, uid = authorize((ROLE_BOX,))
    body()
    settlement = must_find("settlements", settlement_id)
    require_settlement_state(settlement, ("DRAFT", "DISPUTED"))
    booking = find("bookings", settlement["booking_id"])
    if booking is None or booking["status"] != "CLOSED":
        raise ApiError("ERR_SETTLEMENT_NOT_PERMITTED",
                       "The engagement must still be closed to submit.")
    settlement["status"] = "SUBMITTED"
    settlement["submitted_by_user_id"] = uid
    touch(settlement)
    return object_response(serialize.settlement(settlement))


@bp.post("/settlements/<settlement_id>/finalize")
def finalize_settlement(settlement_id):
    role, uid = authorize((ROLE_EXEC,))
    body()
    settlement = must_find("settlements", settlement_id)
    require_settlement_state(settlement, ("SUBMITTED",))
    booking = must_find("bookings", settlement["booking_id"])
    venue = must_find("venues", booking["venue_id"])
    _apply_figures(settlement, booking, venue, "FINAL")
    settlement["finalized_by_user_id"] = uid
    settlement["status"] = "RECONCILED"
    touch(settlement)
    return object_response(serialize.settlement(settlement))


@bp.post("/settlements/<settlement_id>/resolve")
def resolve_settlement(settlement_id):
    authorize((ROLE_EXEC,))
    payload = body()
    outcome = req_enum(payload, "outcome", ("DISPUTED", "PAID"))
    dispute_note = req_str(payload, "dispute_note") if outcome == "DISPUTED" else None
    settlement = must_find("settlements", settlement_id)
    if outcome == "DISPUTED":
        require_settlement_state(settlement, ("SUBMITTED", "RECONCILED"))
        settlement["status"] = "DISPUTED"
        settlement["dispute_note"] = dispute_note
    else:
        require_settlement_state(settlement, ("RECONCILED",))
        settlement["status"] = "PAID"
    touch(settlement)
    return object_response(serialize.settlement(settlement))
