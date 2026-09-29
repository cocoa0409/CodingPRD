"""Which code wins, and which codes a terminal or unproposed record answers with."""
from prd_bench_local_runner.testing import build_user_headers, validate_error

from test_helpers import (
    ApiErrorId,
    BreachSeverity,
    BreachStatus,
    MeetingStatus,
    RemedyBasis,
    SeatStatus,
    api_client,
    assert_eligibility_meeting,
    assert_timeline_breach,
    consent_event_payload,
    fixtures,
    receive_order_payload,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["district_admin_headers"]
SUPERVISOR = TEST_USERS["psych_services_supervisor_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
NO_AUTH_HEADERS = {"Content-Type": "application/json"}
UNKNOWN_ID = "00000000-0000-4000-8000-000000000000"
SECOND_UNKNOWN_ID = "00000000-0000-4000-8000-000000000001"


def test_the_left_most_path_identifier_is_resolved_first():
    """Two unknown ids on one path report the instrument, never the seat.

    "Whenever a path carries more than one identifier, the identifiers are resolved strictly left to right and the first one that fails to resolve determines the error."

    "A seat addressed under an instrument resolves the instrument first, so a request naming a non-existent instrument returns `ERR_INSTRUMENT_NOT_FOUND` before the seat is ever looked up; a seat that exists but belongs to a different instrument than the one in the path returns `ERR_SEAT_NOT_FOUND`."

    Design: Corner/errors/path_ids_resolve_left_to_right
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    instrument = fixtures.create_instrument(
        name="GORT-5",
        instrument_code="GORT5",
        license_seat_total=1,
        license_expires_on="2027-06-30",
    )

    response = api_client.release_license_seat(
        UNKNOWN_ID, SECOND_UNKNOWN_ID, SUPERVISOR
    )

    validate_error(response, ApiErrorId.ERR_INSTRUMENT_NOT_FOUND.value, 404)

    # With the instrument resolved, the second identifier becomes reachable.
    seat_missing = api_client.release_license_seat(
        instrument["id"], SECOND_UNKNOWN_ID, SUPERVISOR
    )
    validate_error(seat_missing, ApiErrorId.ERR_SEAT_NOT_FOUND.value, 404)

    referral_missing = api_client.create_consent_event(
        UNKNOWN_ID, consent_event_payload("CONSENT_RECEIVED"), INTAKE
    )
    validate_error(referral_missing, ApiErrorId.ERR_REFERRAL_NOT_FOUND.value, 404)

    order_missing = api_client.receive_protocol_order(
        UNKNOWN_ID, receive_order_payload(1), SUPERVISOR
    )
    validate_error(order_missing, ApiErrorId.ERR_ORDER_NOT_FOUND.value, 404)


def test_a_released_seat_cannot_be_released_a_second_time():
    """The compensating action is not repeatable, so no second seat is credited.

    "Releasing a seat that is already `RELEASED` is rejected with `ERR_SEAT_STATE_INVALID`, and `RELEASED` is terminal — a released seat is never revived, a fresh seat is assigned instead."

    Design: Corner/errors/released_seat_cannot_be_released_again
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Dunmore Elementary",
        building_code="DM59",
        grade_band="ELEMENTARY",
        concurrent_meeting_capacity=2,
        enrollment_count=260,
    )
    psychologist = fixtures.create_psychologist(
        [school["id"]],
        full_name="Vera Odom",
        employee_number="E-2032",
        credential_type="SSP",
    )
    instrument = fixtures.create_instrument(
        name="TAPS-4",
        instrument_code="TAPS4",
        license_seat_total=1,
        license_expires_on="2027-06-30",
    )
    seat = fixtures.assign_license_seat(instrument["id"], psychologist["id"])
    released = fixtures.release_license_seat(instrument["id"], seat["id"])

    response = api_client.release_license_seat(
        instrument["id"], seat["id"], SUPERVISOR
    )

    validate_error(response, ApiErrorId.ERR_SEAT_STATE_INVALID.value, 409)
    still_released = fixtures.instrument_seats(instrument["id"])[0]
    assert still_released["status"] == SeatStatus.RELEASED.value
    assert still_released["released_at"] == released["released_at"]
    # One seat total, none assigned, so exactly one free — not two.
    assert fixtures.get_instrument(instrument["id"])["license_seats_free"] == 1


def test_authentication_is_settled_before_the_body_is_read():
    """A malformed payload with no credentials answers 401, not 422.

    "If either header is absent, or if `X-User-Role` is not one of those five exact strings, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/missing_auth_headers_returns_unauthenticated
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    malformed = {"grade_band": "NOT_A_BAND"}

    response = api_client.create_school(malformed, NO_AUTH_HEADERS)

    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    unknown_role = api_client.create_school(
        malformed, build_user_headers("superintendent-1", "Superintendent")
    )
    validate_error(unknown_role, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # Reads are held to the same standard.
    unauthenticated_read = api_client.list_referrals(NO_AUTH_HEADERS)
    validate_error(unauthenticated_read, ApiErrorId.ERR_UNAUTHENTICATED.value, 401)

    # With credentials in place the same body finally reaches shape validation.
    authenticated = api_client.create_school(malformed, ADMIN)
    validate_error(authenticated, ApiErrorId.ERR_INVALID_REQUEST.value, 422)


def test_a_remedy_cannot_be_approved_before_it_is_proposed():
    """The approval has nothing to ratify while the breach is only DETECTED.

    "Approving a breach that is not `REMEDY_PROPOSED` — including one already approved, and including one that has been vacated — is rejected with `ERR_BREACH_STATE_INVALID`."

    Design: Corner/errors/remedy_approval_requires_a_proposal_first
    """
    fixtures.set_clock("2026-06-01T00:00:00Z")
    school = fixtures.create_school(
        name="Eastmoor High",
        building_code="EM60",
        grade_band="HIGH",
        concurrent_meeting_capacity=2,
        enrollment_count=850,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"],
        effective_at="2026-06-01T00:00:00Z",
        student_local_id="STU-51",
        requested_domains=["COGNITIVE"],
    )
    fixtures.set_clock("2026-08-10T00:00:00Z")
    fixtures.run_sweep()
    breach = fixtures.first_breach(evaluation["id"])

    response = api_client.approve_remedy(breach["id"], ADMIN)

    validate_error(response, ApiErrorId.ERR_BREACH_STATE_INVALID.value, 409)
    unapproved = fixtures.first_breach(evaluation["id"])
    assert_timeline_breach(unapproved)
    assert unapproved["status"] == BreachStatus.DETECTED.value
    assert unapproved["approved_by_user_id"] is None
    assert unapproved["remedy_minutes_awarded"] == 0
    assert unapproved["breach_days"] == 10
    assert unapproved["severity"] == BreachSeverity.MODERATE.value
    # 10 * 30 * 1.25 is 375; two whole missed weeks * 150 * 1.25 is also 375.
    assert unapproved["minutes_breach_day_basis"] == 375
    assert unapproved["minutes_missed_service_basis"] == 375

    unknown_breach = api_client.approve_remedy(UNKNOWN_ID, ADMIN)
    validate_error(unknown_breach, ApiErrorId.ERR_BREACH_NOT_FOUND.value, 404)

    fixtures.propose_remedy(
        breach["id"],
        RemedyBasis.BREACH_DAY_BASIS.value,
        corrective_action_note="Compensatory counselling blocks.",
    )
    approved = fixtures.approve_remedy(breach["id"])
    assert approved["status"] == BreachStatus.REMEDY_APPROVED.value


def test_a_notice_cannot_be_issued_twice_over_the_same_meeting():
    """The first notice freezes the lead figures and the second is a state error.

    "A notice may be issued from `PROPOSED` or re-issued from `RESCHEDULE_REQUESTED`, in both cases moving the meeting to `NOTICED`; from any other status the request is rejected with `ERR_MEETING_STATE_INVALID`."

    Design: Corner/errors/notice_cannot_be_sent_twice
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
    school = fixtures.create_school(
        name="Fallbrook Middle",
        building_code="FB61",
        grade_band="MIDDLE",
        concurrent_meeting_capacity=2,
        enrollment_count=470,
    )
    _, evaluation = fixtures.consented_referral(
        school["id"], student_local_id="STU-52", requested_domains=["COGNITIVE"]
    )
    noticed = fixtures.noticed_meeting(
        evaluation["id"],
        school["id"],
        "2026-09-20T15:00:00Z",
        "2026-09-20T16:00:00Z",
        notice_clock="2026-08-20T00:00:00Z",
    )
    assert_eligibility_meeting(noticed)
    assert noticed["status"] == MeetingStatus.NOTICED.value
    assert noticed["notice_lead_days"] == 31

    response = api_client.send_meeting_notice(noticed["id"], INTAKE)

    validate_error(response, ApiErrorId.ERR_MEETING_STATE_INVALID.value, 409)
    frozen = fixtures.get_meeting(noticed["id"])
    assert frozen["status"] == MeetingStatus.NOTICED.value
    assert frozen["parent_notice_sent_at"] == noticed["parent_notice_sent_at"]
    assert frozen["parent_notice_sent_at"].startswith("2026-08-20T00:00:00")
    assert frozen["notice_lead_days"] == 31
    assert frozen["reschedule_count"] == 0
