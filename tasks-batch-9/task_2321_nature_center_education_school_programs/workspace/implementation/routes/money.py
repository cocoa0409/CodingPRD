"""Scholarship funds, the award waterfall and aid applications."""

from flask import Blueprint

import calc
import derive
import flows
from envelope import array_response, object_response
from errors import ApiError
from schema import (body_json, lookup, opt_num, opt_str, pagination, paginate,
                    query_enum, query_str, req_enum, req_int, req_str)
from security import authorize, teacher_scope
from store import db, new_entity, public, sorted_rows, touch

bp = Blueprint("money", __name__)

FUND_STATUSES = ("OPEN", "FROZEN", "CLOSED")
FUND_TRANSITIONS = {
    "OPEN": ("FROZEN", "CLOSED"),
    "FROZEN": ("OPEN",),
    "CLOSED": (),
}
AID_STATUSES = ("SUBMITTED", "APPROVED", "PARTIALLY_APPROVED", "DISBURSED", "DENIED", "REVOKED")


# -------------------------------------------------------- scholarship funds
@bp.post("/scholarship-funds")
def create_fund():
    authorize(("GrantsOfficer",))
    body = body_json()
    funder_name = req_str(body, "funder_name")
    fiscal_year = req_int(body, "fiscal_year", 2020, 2100)
    total_cents = req_int(body, "total_cents", high=100000000)
    if total_cents <= 0:
        raise ApiError("ERR_INVALID_REQUEST")
    sublimit = opt_num(body, "transport_sublimit_pct", low=0, high=1, default=0.25)

    fund = new_entity()
    fund.update({
        "funder_name": funder_name,
        "fiscal_year": fiscal_year,
        "total_cents": total_cents,
        "transport_sublimit_pct": sublimit,
        "pending_cents": 0,
        "committed_cents": 0,
        "disbursed_cents": 0,
        "available_cents": total_cents,
        "transport_awarded_cents": 0,
        "status": "OPEN",
    })
    db.funds[fund["id"]] = fund
    derive.sync()
    return object_response(public(fund), 201)


@bp.get("/scholarship-funds/<fund_id>")
def read_fund(fund_id):
    authorize(("GrantsOfficer", "EducationDirector", "BookingCoordinator"))
    fund = lookup("fund", fund_id)
    return object_response(public(fund))


@bp.post("/scholarship-funds/<fund_id>/set-status")
def set_fund_status(fund_id):
    authorize(("GrantsOfficer",))
    body = body_json()
    target = req_enum(body, "status", FUND_STATUSES)
    fund = lookup("fund", fund_id)

    if target not in FUND_TRANSITIONS.get(fund["status"], ()):
        raise ApiError("ERR_INVALID_FUND_STATE")
    if target == "CLOSED" and fund["pending_cents"] != 0:
        raise ApiError("ERR_FUND_HAS_PENDING_APPLICATIONS")

    fund["status"] = target
    touch(fund)
    derive.sync()
    return object_response(public(fund))


@bp.get("/scholarship-funds/<fund_id>/outcome-report")
def fund_outcome_report(fund_id):
    authorize(("GrantsOfficer", "EducationDirector"))
    fund = lookup("fund", fund_id)
    return object_response(flows.outcome_report(fund))


# -------------------------------------------------------- aid applications
@bp.post("/aid-applications")
def create_aid():
    actor = authorize(("TeacherContact", "BookingCoordinator"))
    body = body_json()
    booking_id = req_str(body, "booking_id")
    fund_id = req_str(body, "fund_id")
    requested_scholarship = req_int(body, "requested_scholarship_cents", 0, 10000000)
    requested_transport = req_int(body, "requested_transport_cents", 0, 10000000)
    expected_fund_version = req_int(body, "expected_fund_version")

    # PRD 2.6 fixed body foreign-key order: fund_id before booking_id
    fund = lookup("fund", fund_id)
    booking = lookup("booking", booking_id)
    teacher_scope(actor, booking["school_id"])

    if booking["funding_status"] != "UNFUNDED":
        raise ApiError("ERR_INVALID_FUNDING_STATE")
    if booking["delivery_status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_BOOKING_STATE")
    if expected_fund_version != fund["version"]:
        raise ApiError("ERR_STALE_FUND_VERSION")
    if fund["status"] != "OPEN":
        raise ApiError("ERR_FUND_NOT_OPEN")

    for existing in derive.aid_for_booking(booking["id"]):
        if existing["status"] in ("SUBMITTED", "APPROVED", "PARTIALLY_APPROVED", "DISBURSED"):
            raise ApiError("ERR_DUPLICATE_AID_APPLICATION")

    school = db.schools.get(booking["school_id"])
    if school is None or school.get("equity_tier") == "NONE":
        raise ApiError("ERR_NOT_AID_ELIGIBLE")

    if requested_scholarship + requested_transport > fund["available_cents"]:
        raise ApiError("ERR_FUND_INSUFFICIENT")
    if requested_transport > 0:
        remaining = calc.transport_sublimit_cents(fund) - fund["transport_awarded_cents"]
        if remaining <= 0:
            raise ApiError("ERR_TRANSPORT_SUBLIMIT_EXCEEDED")

    application = new_entity()
    application.update({
        "booking_id": booking["id"],
        "fund_id": fund["id"],
        "requested_scholarship_cents": requested_scholarship,
        "requested_transport_cents": requested_transport,
        "awarded_scholarship_cents": 0,
        "awarded_transport_cents": 0,
        "status": "SUBMITTED",
        "submitted_by_user_id": actor.user_id,
        "reviewer_user_id": None,
        "decision_note": None,
    })
    db.aid[application["id"]] = application

    booking["funding_status"] = "AID_PENDING"
    touch(booking)
    touch(fund)
    derive.sync()
    return object_response(public(application), 201)


@bp.get("/aid-applications")
def list_aid():
    authorize(("GrantsOfficer", "EducationDirector"))
    limit, offset = pagination()
    booking_id = query_str("booking_id")
    fund_id = query_str("fund_id")
    status = query_enum("status", AID_STATUSES)

    rows = sorted_rows(db.aid.values())
    if booking_id is not None:
        rows = [r for r in rows if r["booking_id"] == booking_id]
    if fund_id is not None:
        rows = [r for r in rows if r["fund_id"] == fund_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return array_response([public(r) for r in page], limit, offset, total)


@bp.get("/aid-applications/<application_id>")
def read_aid(application_id):
    actor = authorize(("GrantsOfficer", "EducationDirector", "TeacherContact"))
    application = lookup("aid", application_id)
    booking = db.bookings.get(application["booking_id"])
    teacher_scope(actor, booking["school_id"] if booking else None)
    return object_response(public(application))


@bp.post("/aid-applications/<application_id>/review")
def review_aid(application_id):
    actor = authorize(("GrantsOfficer",))
    body = body_json()
    decision = req_enum(body, "decision", ("APPROVE", "DENY"))
    reviewer_note = opt_str(body, "reviewer_note")
    application = lookup("aid", application_id)

    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_AID_STATE")
    fund = db.funds.get(application["fund_id"])
    if fund is None or fund["status"] != "OPEN":
        raise ApiError("ERR_FUND_NOT_OPEN")

    booking = db.bookings.get(application["booking_id"])
    school = db.schools.get(booking["school_id"]) if booking else None

    if decision == "DENY":
        application["status"] = "DENIED"
        application["awarded_scholarship_cents"] = 0
        application["awarded_transport_cents"] = 0
        application["reviewer_user_id"] = actor.user_id
        application["decision_note"] = reviewer_note
        touch(application)
        if booking is not None and booking["funding_status"] == "AID_PENDING":
            booking["funding_status"] = "UNFUNDED"
            touch(booking)
        derive.sync()
        return object_response(public(application))

    scholarship, transport = calc.aid_award(
        application, booking, school, fund,
        fund["available_cents"], fund["transport_awarded_cents"],
    )
    if scholarship + transport <= 0:
        raise ApiError("ERR_FUND_INSUFFICIENT")
    if application["requested_transport_cents"] > 0:
        remaining = calc.transport_sublimit_cents(fund) - fund["transport_awarded_cents"]
        if remaining <= 0:
            raise ApiError("ERR_TRANSPORT_SUBLIMIT_EXCEEDED")

    application["awarded_scholarship_cents"] = scholarship
    application["awarded_transport_cents"] = transport
    if (scholarship == application["requested_scholarship_cents"]
            and transport == application["requested_transport_cents"]):
        application["status"] = "APPROVED"
    else:
        application["status"] = "PARTIALLY_APPROVED"
    application["reviewer_user_id"] = actor.user_id
    application["decision_note"] = reviewer_note
    touch(application)

    if booking is not None and booking["funding_status"] == "AID_PENDING":
        booking["funding_status"] = "AID_APPROVED"
        touch(booking)
    derive.sync()
    return object_response(public(application))
