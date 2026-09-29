"""Policy profiles, passengers, bookings, the exposure view and the logical clock."""

from flask import Blueprint, request

import calc
import ledger
from auth import ADMIN, AUDITOR, OFFICER, OPS, PASSENGER, authorize, own_booking, own_passenger
from envelope import created, listing, ok
from errors import ApiError
from store import S, fmt_domain, new_row, serialize
from validation import (
    body_fk,
    field,
    json_body,
    must_exist,
    page,
    pagination,
    validate,
)

bp = Blueprint("core", __name__)

PAYMENT_METHODS = ["CREDIT_CARD", "CASH_OR_CHECK", "TRAVEL_CREDIT", "MILES"]
POSTURES = ["NORMAL", "DISRUPTED", "REFUND_OBLIGATED", "CLOSED_OUT"]

PROFILE_INT_FIELDS = (
    ("domestic_significant_delay_minutes", 180),
    ("international_significant_delay_minutes", 360),
    ("credit_card_refund_deadline_days", 7),
    ("other_method_refund_deadline_days", 20),
    ("bag_delay_threshold_hours_domestic", 12),
    ("bag_delay_threshold_hours_international", 30),
    ("tarmac_deplane_deadline_minutes_domestic", 180),
    ("tarmac_deplane_deadline_minutes_international", 240),
    ("complaint_ack_deadline_days", 30),
    ("complaint_answer_deadline_days_general", 60),
    ("complaint_answer_deadline_days_disability", 30),
)

PROFILE_SPEC = [field("carrier_code", "string", True, exact_len=2, pattern="upper_alnum")]
for _name, _default in PROFILE_INT_FIELDS:
    PROFILE_SPEC.append(field(_name, "int", False, min=1))
PROFILE_SPEC.append(field("travel_credit_default_permitted", "bool", False))
PROFILE_SPEC.append(field("travel_credit_election_bonus_pct", "number", False, min=0, max=0.5))


@bp.post("/compliance/policy-profiles")
def create_policy_profile():
    authorize([ADMIN])
    body = json_body()
    data = validate(body, PROFILE_SPEC)

    for existing in S.policy_profiles.values():
        if existing["carrier_code"] == data["carrier_code"]:
            raise ApiError("ERR_DUPLICATE_CARRIER_CODE")

    fields = {"carrier_code": data["carrier_code"]}
    for name, default in PROFILE_INT_FIELDS:
        fields[name] = data.get(name, default)
    fields["travel_credit_default_permitted"] = data.get("travel_credit_default_permitted", False)
    fields["travel_credit_election_bonus_pct"] = data.get("travel_credit_election_bonus_pct", 0.10)
    fields["report_count"] = 0
    fields["open_violation_count"] = 0

    row = new_row(fields)
    S.policy_profiles[row["id"]] = row
    return created(serialize(row))


@bp.get("/compliance/policy-profiles/<profile_id>")
def read_policy_profile(profile_id):
    authorize([ADMIN, OFFICER, OPS, AUDITOR])
    row = must_exist("policy_profile", profile_id)
    return ok(serialize(row))


@bp.get("/compliance/policy-profiles/<profile_id>/regulator-reports")
def list_profile_reports(profile_id):
    authorize([ADMIN, AUDITOR])
    must_exist("policy_profile", profile_id)
    limit, offset = pagination()
    rows = [r for r in S.regulator_reports.values() if r["policy_profile_id"] == profile_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    # "newest reporting period first"
    rows.sort(key=lambda r: (r["period_start_utc"], r["_seq"]), reverse=True)
    total = len(rows)
    return listing([serialize(r) for r in page(rows, limit, offset)], limit, offset, total)


PASSENGER_SPEC = [
    field("email", "string", True, min_len=3, max_len=254, pattern="email"),
    field("full_name", "string", True, min_len=1, max_len=120),
    field("requires_disability_assistance", "bool", False),
]


@bp.post("/compliance/passengers")
def register_passenger():
    authorize([ADMIN, OFFICER])
    body = json_body()
    data = validate(body, PASSENGER_SPEC)

    for existing in S.passengers.values():
        if existing["email"] == data["email"]:
            raise ApiError("ERR_DUPLICATE_PASSENGER_EMAIL")

    row = new_row(
        {
            "email": data["email"],
            "full_name": data["full_name"],
            "requires_disability_assistance": data.get("requires_disability_assistance", False),
            "travel_credit_balance_cents": 0,
            "open_complaint_count": 0,
        }
    )
    S.passengers[row["id"]] = row
    return created(serialize(row))


@bp.get("/compliance/passengers/<passenger_id>")
def read_passenger(passenger_id):
    user_id, role = authorize([ADMIN, OFFICER, AUDITOR, PASSENGER])
    own_passenger(user_id, role, passenger_id)
    row = must_exist("passenger", passenger_id)
    return ok(serialize(row))


BOOKING_SPEC = [
    field("passenger_id", "string", True),
    field("policy_profile_id", "string", True),
    field("record_locator", "string", True, exact_len=6, pattern="upper_alnum"),
    field("total_fare_cents", "int", True, cents=True, min=1),
    field("payment_method", "enum", True, values=PAYMENT_METHODS),
]


@bp.post("/compliance/bookings")
def create_booking():
    authorize([ADMIN, OFFICER])
    body = json_body()
    body_fk(body, "passenger_id", "passenger")
    body_fk(body, "policy_profile_id", "policy_profile")
    data = validate(body, BOOKING_SPEC)

    for existing in S.bookings.values():
        if existing["record_locator"] == data["record_locator"]:
            raise ApiError("ERR_DUPLICATE_RECORD_LOCATOR")

    row = new_row(
        {
            "passenger_id": data["passenger_id"],
            "policy_profile_id": data["policy_profile_id"],
            "record_locator": data["record_locator"],
            "total_fare_cents": data["total_fare_cents"],
            "payment_method": data["payment_method"],
            "itinerary_scope": "DOMESTIC",
            "collected_total_cents": data["total_fare_cents"],
            "total_refund_obligated_cents": 0,
            "earliest_refund_deadline_utc": None,
            "disruption_posture": "NORMAL",
            "segment_count": 0,
            "unused_segment_count": 0,
            "travel_commenced": False,
            "suppressed_obligation_count": 0,
        }
    )
    S.bookings[row["id"]] = row
    return created(serialize(row))


@bp.get("/compliance/bookings")
def list_bookings():
    user_id, role = authorize([ADMIN, OFFICER, OPS, AUDITOR, PASSENGER])
    limit, offset = pagination()
    rows = sorted(S.bookings.values(), key=lambda r: r["_seq"])
    if role == PASSENGER:
        rows = [r for r in rows if r["passenger_id"] == user_id]
    for param in ("passenger_id", "policy_profile_id", "disruption_posture"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    total = len(rows)
    return listing([serialize(r) for r in page(rows, limit, offset)], limit, offset, total)


@bp.get("/compliance/bookings/<booking_id>")
def read_booking(booking_id):
    user_id, role = authorize([ADMIN, OFFICER, OPS, AUDITOR, PASSENGER])
    own_booking(user_id, role, booking_id)
    row = must_exist("booking", booking_id)
    return ok(serialize(row))


@bp.get("/compliance/bookings/<booking_id>/flight-segments")
def list_booking_segments(booking_id):
    user_id, role = authorize([ADMIN, OFFICER, OPS, AUDITOR, PASSENGER])
    own_booking(user_id, role, booking_id)
    must_exist("booking", booking_id)
    limit, offset = pagination()
    rows = calc.segments_of(booking_id)
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    return listing([serialize(r) for r in page(rows, limit, offset)], limit, offset, total)


@bp.get("/compliance/bookings/<booking_id>/checked-bags")
def list_booking_bags(booking_id):
    user_id, role = authorize([ADMIN, OFFICER, AUDITOR, PASSENGER])
    own_booking(user_id, role, booking_id)
    must_exist("booking", booking_id)
    limit, offset = pagination()
    rows = calc.bags_of(booking_id)
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    total = len(rows)
    return listing([serialize(r) for r in page(rows, limit, offset)], limit, offset, total)


@bp.get("/compliance/bookings/<booking_id>/consumer-complaints")
def list_booking_complaints(booking_id):
    user_id, role = authorize([ADMIN, OFFICER, AUDITOR, PASSENGER])
    own_booking(user_id, role, booking_id)
    must_exist("booking", booking_id)
    limit, offset = pagination()
    rows = calc.complaints_of(booking_id)
    for param in ("category", "status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    rows.sort(key=lambda r: (r["received_at_utc"], r["_seq"]))
    total = len(rows)
    return listing([serialize(r) for r in page(rows, limit, offset)], limit, offset, total)


@bp.get("/compliance/bookings/<booking_id>/refund-exposure")
def refund_exposure(booking_id):
    user_id, role = authorize([ADMIN, OFFICER, AUDITOR])
    own_booking(user_id, role, booking_id)
    booking = must_exist("booking", booking_id)
    proactive = calc.fare_gross_proactive(booking)
    request_based = calc.fare_gross_request_based(booking)
    return ok(
        {
            "booking_id": booking_id,
            "proactive_full_itinerary_cents": proactive,
            "request_based_proration_cents": request_based,
            "variant_delta_cents": proactive - request_based,
            "obligated_total_cents": booking["total_refund_obligated_cents"],
            "remaining_headroom_cents": calc.headroom(booking),
            "collected_total_cents": calc.collected_total(booking),
            "segment_count": booking["segment_count"],
            "unused_segment_count": booking["unused_segment_count"],
            "travel_commenced": booking["travel_commenced"],
        }
    )


CLOCK_SPEC = [field("to_iso8601", "datetime", True)]


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorize([ADMIN])
    body = json_body()
    data = validate(body, CLOCK_SPEC)
    S.clock = data["to_iso8601"]
    return ok({"current_utc": fmt_domain(S.clock)})
