"""RBAC gates, eligibility/party validations, and invalid state transitions
(PRD §2.1, §2.10, §3.3, §3.6, §3.9)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    abort_flight_payload,
    create_tunnel_payload,
    make_instructor_headers,
    make_member,
    make_package,
    setup_aborted_flight,
    setup_checked_in_flight,
    setup_scheduled_flight,
    validate_error,
    validate_success,
)

MANAGER = TEST_USERS["manager_headers"]
FRONTDESK = TEST_USERS["frontdesk_headers"]
FLYER = TEST_USERS["flyer_headers"]


def test_flyer_cannot_create_tunnel_returns_forbidden(api):
    """PRD §2.1: "If the headers are valid but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/flyer_cannot_create_tunnel_returns_forbidden
    """
    resp = api.create_tunnel(create_tunnel_payload(), FLYER)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_frontdesk_cannot_create_instructor_returns_forbidden(api):
    """PRD §2.1: "If the headers are valid but the role is not permitted to perform the
    requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

    Design: Corner/rbac/frontdesk_cannot_create_instructor_returns_forbidden
    """
    resp = api.create_instructor({"name": "Ivy", "cert_level": "L2"}, FRONTDESK)
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


def test_unauthenticated_create_member_returns_401(api):
    """PRD §2.1: "If either header is missing or carries an unrecognized value, the
    request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/unauthenticated_create_member_returns_401
    """
    resp = api.create_member({"name": "Ada", "weight_kg": 80, "experience_status": "FIRST_TIME"}, {})
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_booking_returning_package_first_time_member_not_eligible(api):
    """PRD §3.3: "If the package's `min_experience` is `RETURNING` while the member is
    `FIRST_TIME`, the booking is rejected with `ERR_EXPERIENCE_NOT_ELIGIBLE`."

    Design: Corner/validations/booking_returning_package_first_time_member_returns_experience_not_eligible
    """
    pkg = make_package(api, name="Pro Coaching", included_minutes=4, base_price_cents=9000,
                       min_experience="RETURNING")
    member = make_member(api, name="Newbie", weight_kg=80, experience_status="FIRST_TIME")
    resp = api.create_booking(
        {"member_id": member["id"], "package_id": pkg["id"],
         "booking_type": "WALK_IN", "party_size": 1},
        FRONTDESK,
    )
    validate_error(resp, ApiErrorId.ERR_EXPERIENCE_NOT_ELIGIBLE.value)


def test_booking_party_size_zero_returns_invalid_party_size(api):
    """PRD §3.3: "A party size below one is rejected with `ERR_INVALID_PARTY_SIZE`."

    Design: Corner/validations/booking_party_size_zero_returns_invalid_party_size
    """
    pkg = make_package(api, included_minutes=2, base_price_cents=6000)
    member = make_member(api, name="Ada", weight_kg=80)
    resp = api.create_booking(
        {"member_id": member["id"], "package_id": pkg["id"],
         "booking_type": "WALK_IN", "party_size": 0},
        FRONTDESK,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_PARTY_SIZE.value)


def test_complete_flight_from_scheduled_returns_invalid_state(api):
    """PRD §3.6: "**Completion** advances `CHECKED_IN → FLOWN`, requiring `op_status`
    `RUNNING` else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/complete_flight_from_scheduled_returns_invalid_state
    """
    ctx = setup_scheduled_flight(api, booking_kw={"party_size": 1}, sign_waiver=False, start=True)
    instr = make_instructor_headers(ctx["instructor"]["id"])
    resp = api.complete_flight(ctx["flight"]["id"], instr)  # flight still SCHEDULED
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_abort_already_aborted_flight_returns_invalid_state(api):
    """PRD §3.6: "**Abort** advances `CHECKED_IN → ABORTED`, requiring `op_status`
    `RUNNING` else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/abort_already_aborted_flight_returns_invalid_state
    """
    ctx = setup_aborted_flight(api, flown_minutes=1, booking_kw={"party_size": 1}, scheduled_minutes=2)
    instr = make_instructor_headers(ctx["instructor"]["id"])
    resp = api.abort_flight(ctx["flight"]["id"], abort_flight_payload(1), instr)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_cancel_booking_with_flown_flight_returns_error(api):
    """PRD §3.9: "A `Booking` may be cancelled by a `Flyer` or `FrontDesk`, provided no
    flight on it is currently `FLOWN`; a booking with a flown flight is rejected with
    `ERR_BOOKING_HAS_FLOWN_FLIGHT`."

    Design: Corner/state_machines/cancel_booking_with_flown_flight_returns_error
    """
    ctx = setup_checked_in_flight(api, booking_kw={"party_size": 1}, scheduled_minutes=2, start=True)
    instr = make_instructor_headers(ctx["instructor"]["id"])
    validate_success(api.complete_flight(ctx["flight"]["id"], instr), 200)  # -> FLOWN
    resp = api.cancel_booking(ctx["booking"]["id"], FRONTDESK)
    validate_error(resp, ApiErrorId.ERR_BOOKING_HAS_FLOWN_FLIGHT.value)
