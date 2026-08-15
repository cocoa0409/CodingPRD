"""Refund election endpoints: create, read, list, process."""

from flask import Blueprint, request

import errors
from db import db, now
from middleware import authenticate, check_booking_ownership, require_role
from response import success_list, success_object
from serializers import serialize_election
from services.core import post_cost_entry, stamp_new, touch
from validators import get_json_body, get_json_body_optional, opt_query_enum, pagination_params

bp = Blueprint("elections", __name__)

ELECTIONS = {"REFUND", "CREDIT"}
ELECTION_STATUSES = {"PENDING", "PROCESSED"}
ELECTION_READ_ROLES = ["ReaccommodationAgent", "FinanceProcessor", "DutyManager", "Passenger"]


def _event_id_for_booking(booking):
    for case in db.reaccommodation_cases.values():
        if case["booking_id"] == booking["id"] and case["disruption_event_id"]:
            return case["disruption_event_id"]
    return None


@bp.post("/irops/bookings/<bid>/refund-elections")
def create_election(bid):
    caller = authenticate()
    require_role(caller, ["ReaccommodationAgent", "Passenger"])
    body = get_json_body()
    election = body.get("election")
    if not isinstance(election, str):
        errors.raise_error(errors.ERR_INVALID_REQUEST, "election must be a string")
    if election not in ELECTIONS:
        errors.raise_error(errors.ERR_INVALID_ENUM,
                           "election value %r outside declared enum domain" % election)
    b = db.bookings.get(bid)
    if b is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "Booking not found")
    check_booking_ownership(caller, b)
    # eligibility gate before deadline gate
    if b["compensation_status"] != "ELIGIBLE_PENDING":
        errors.raise_error(errors.ERR_COMPENSATION_NOT_ELIGIBLE,
                           "Booking is not ELIGIBLE_PENDING")
    if b["election_deadline"] is not None and now() > b["election_deadline"]:
        errors.raise_error(errors.ERR_ELECTION_WINDOW_CLOSED,
                           "Election deadline has passed")
    e = stamp_new({
        "booking_id": b["id"],
        "election": election,
        "election_source": "USER",
        "refund_amount_cents": b["refund_amount_cents"],
        "credit_amount_cents": b["credit_amount_cents"],
        "compensation_amount_cents": b["compensation_amount_cents"],
        "election_status": "PENDING",
    })
    db.refund_elections[e["id"]] = e
    b["compensation_status"] = "ELECTED_REFUND" if election == "REFUND" else "ELECTED_CREDIT"
    touch(b)
    return success_object(serialize_election(e), 201)


@bp.get("/irops/refund-elections/<eid>")
def get_election(eid):
    caller = authenticate()
    require_role(caller, ELECTION_READ_ROLES)
    e = db.refund_elections.get(eid)
    if e is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "RefundElection not found")
    if caller.is_passenger:
        b = db.bookings.get(e["booking_id"])
        if b is not None:
            check_booking_ownership(caller, b)
    return success_object(serialize_election(e), 200)


@bp.get("/irops/refund-elections")
def list_elections():
    caller = authenticate()
    require_role(caller, ELECTION_READ_ROLES)
    booking_id = request.args.get("booking_id")
    status = opt_query_enum("election_status", ELECTION_STATUSES)
    limit, offset = pagination_params()
    items = sorted(db.refund_elections.values(), key=lambda e: e["created_at"])
    if caller.is_passenger:
        items = [e for e in items
                 if db.bookings.get(e["booking_id"]) is not None
                 and db.bookings[e["booking_id"]]["passenger_id"] == caller.user_id]
    if booking_id is not None:
        items = [e for e in items if e["booking_id"] == booking_id]
    if status is not None:
        items = [e for e in items if e["election_status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_election(e) for e in page], limit, offset, total)


@bp.post("/irops/refund-elections/<eid>/process")
def process_election(eid):
    caller = authenticate()
    require_role(caller, ["FinanceProcessor"])
    get_json_body_optional()
    e = db.refund_elections.get(eid)
    if e is None:
        errors.raise_error(errors.ERR_NOT_FOUND, "RefundElection not found")
    if e["election_status"] != "PENDING":
        errors.raise_error(errors.ERR_ELECTION_NOT_PENDING,
                           "Election is not PENDING")
    b = db.bookings.get(e["booking_id"])
    event_id = _event_id_for_booking(b) if b is not None else None
    if event_id is not None:
        if e["election"] == "REFUND":
            post_cost_entry(event_id, "REFUND", e["id"], "ACCRUAL",
                            e["refund_amount_cents"], note="refund election processed")
            post_cost_entry(event_id, "REFUND", e["id"], "SETTLEMENT",
                            e["refund_amount_cents"], note="refund election processed")
        else:
            post_cost_entry(event_id, "CREDIT", e["id"], "ACCRUAL",
                            e["credit_amount_cents"], note="credit election processed")
        post_cost_entry(event_id, "COMPENSATION", e["id"], "ACCRUAL",
                        e["compensation_amount_cents"], note="compensation paid")
        post_cost_entry(event_id, "COMPENSATION", e["id"], "SETTLEMENT",
                        e["compensation_amount_cents"], note="compensation paid")
    e["election_status"] = "PROCESSED"
    touch(e)
    if b is not None:
        b["compensation_status"] = "SETTLED"
        touch(b)
    return success_object(serialize_election(e), 200)
