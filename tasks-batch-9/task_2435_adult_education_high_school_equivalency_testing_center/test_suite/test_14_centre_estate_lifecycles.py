"""Edges on the testing-estate side: one-way authorisation grants, the certification cycle and
its lazy lapse, maintenance retirement, and the two sitting states that accept nothing further.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.test_users import (
    make_center_administrator_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    CenterAuthorizationStatus,
    CenterDecision,
    ProctorCertificationStatus,
    ProctorDecision,
    RoomStatus,
    SessionStatus,
    Subtest,
)

ALL_FOUR_SUBTESTS = ["MATH", "RLA", "SCIENCE", "SOCIAL_STUDIES"]
FULL_WEEKLY_CEILING = 20

USABLE_EXPIRY = "2027-01-01T00:00:00Z"
SHORT_EXPIRY = "2026-08-10T00:00:00Z"
PAST_THE_EXPIRY = "2026-08-11T00:00:00Z"

SITTING = ("2026-08-20T09:00:00Z", "2026-08-20T12:00:00Z")
NEXT_DAY_SITTING = ("2026-08-21T09:00:00Z", "2026-08-21T12:00:00Z")

SERVICE_NOTE = "HVAC replacement"
FIRST_CANCEL_REASON = "instructor illness"
SECOND_CANCEL_REASON = "duplicate cancellation"


def _decide_center(center_id, decision):
    return api_client.decide_center_authorization(
        center_id,
        factories.center_authorization_decision_payload(decision),
        headers=make_state_authority_headers(),
    )


def _decide_proctor(proctor_id, decision, certification_expires_at=None):
    return api_client.decide_proctor_certification(
        proctor_id,
        factories.proctor_certification_decision_payload(
            decision, certification_expires_at=certification_expires_at
        ),
        headers=make_state_authority_headers(),
    )


def _assign(center_id, session_id, proctor_id):
    return api_client.assign_proctor(
        session_id,
        factories.proctor_assignment_payload(proctor_id),
        headers=make_center_administrator_headers(center_id),
    )


def _retire(center_id, room_id):
    return api_client.take_room_out_of_service(
        room_id,
        factories.out_of_service_payload(SERVICE_NOTE),
        headers=make_center_administrator_headers(center_id),
    )


def _cancel(center_id, session_id, cancel_reason):
    return api_client.cancel_exam_session(
        session_id,
        factories.cancel_exam_session_payload(cancel_reason),
        headers=make_center_administrator_headers(center_id),
    )


def test_01_a_fully_authorised_centre_cannot_be_downgraded_to_provisional():
    """"Any decision that does not match the centre's current posture — a provisional grant
    against an already fully authorised centre, a promotion of a centre still `APPLIED` through
    the wrong decision value, or any decision at all against a `WITHDRAWN` or `SUSPENDED` centre
    — is refused with `ERR_CENTER_DECISION_NOT_ALLOWED`."

    Design: Corner/state_machines/center_grant_provisional_after_full_authorized_rejected
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="One Way Center", state_code="NV"
    )
    assert center["authorization_status"] == CenterAuthorizationStatus.FULL_AUTHORIZED

    response = _decide_center(center["id"], CenterDecision.GRANT_PROVISIONAL)
    validate_error(response, ApiErrorId.CENTER_DECISION_NOT_ALLOWED, expected_status=409)

    stored = fixtures.read_testing_center(center["id"])
    assert stored["authorization_status"] == CenterAuthorizationStatus.FULL_AUTHORIZED
    assert stored["allowed_subtests"] == ALL_FOUR_SUBTESTS
    assert stored["max_sessions_per_week"] == FULL_WEEKLY_CEILING


def test_02_renewal_is_not_a_synonym_for_certification():
    """"`RENEW` applies to a `LAPSED` proctor and returns them to `CERTIFIED`, writing the new
    `certification_expires_at`." and "Any decision that does not match the proctor's current
    posture — a renewal of a proctor still `PENDING`, a certification of one already
    `CERTIFIED`, or any decision at all against a `REVOKED` proctor — is refused with
    `ERR_PROCTOR_DECISION_NOT_ALLOWED`."

    Design: Corner/state_machines/proctor_renew_decision_from_pending_rejected
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Renew Guard Center", state_code="UT"
    )
    proctor = fixtures.create_proctor(
        center["id"], full_name="Rai Osman", daily_hour_cap=8.00
    )

    response = _decide_proctor(
        proctor["id"], ProctorDecision.RENEW, certification_expires_at=USABLE_EXPIRY
    )
    validate_error(response, ApiErrorId.PROCTOR_DECISION_NOT_ALLOWED, expected_status=409)

    stored = fixtures.read_proctor(proctor["id"])
    assert stored["certification_status"] == ProctorCertificationStatus.PENDING
    assert stored["certification_expires_at"] is None


def test_03_a_revoked_proctor_can_never_be_recertified():
    """"`REVOKE` applies to a proctor who is `PENDING`, `CERTIFIED` or `LAPSED`, and moves them
    to `REVOKED`, which is terminal. `certification_expires_at` is left exactly as it was — the
    record of what the expiry had been is preserved — while `assigned_session_count` is set
    to 0."

    Design: Corner/state_machines/proctor_certification_decision_after_revoked_rejected
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Revoke Terminal Center", state_code="AZ"
    )
    proctor = fixtures.create_proctor(
        center["id"], full_name="Suri Bhatt", daily_hour_cap=8.00
    )

    revoked = validate_success(_decide_proctor(proctor["id"], ProctorDecision.REVOKE))
    assert revoked["certification_status"] == ProctorCertificationStatus.REVOKED
    assert revoked["assigned_session_count"] == 0

    response = _decide_proctor(
        proctor["id"], ProctorDecision.CERTIFY, certification_expires_at=USABLE_EXPIRY
    )
    validate_error(response, ApiErrorId.PROCTOR_DECISION_NOT_ALLOWED, expected_status=409)

    stored = fixtures.read_proctor(proctor["id"])
    assert stored["certification_status"] == ProctorCertificationStatus.REVOKED
    assert stored["certification_expires_at"] is None


def test_04_the_lapse_is_written_before_the_request_that_discovered_it_is_refused():
    """"When the clock has reached or passed that instant, the proctor is moved from
    `CERTIFIED` to `LAPSED` and their `version` is increased by one, and *then* the triggering
    request is refused with `ERR_PROCTOR_CERTIFICATION_LAPSED`. The lapse is durable: the
    proctor stays `LAPSED` after the refused request, and only a renewal returns them to
    service."

    Design: Corner/state_machines/proctor_lapse_then_renew_restores_certified
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Lapse Cycle Center", state_code="CO"
    )
    room = fixtures.create_room(
        center["id"], room_code="R-401", seat_capacity=12, turnaround_buffer_minutes=45
    )
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=SHORT_EXPIRY,
        full_name="Tove Lind",
        daily_hour_cap=8.00,
    )
    session = fixtures.create_session(
        center["id"], room["id"], SITTING[0], SITTING[1], subtest=Subtest.MATH, requested_seats=5
    )
    fixtures.set_clock(PAST_THE_EXPIRY)

    refused = _assign(center["id"], session["id"], proctor["id"])
    validate_error(refused, ApiErrorId.PROCTOR_CERTIFICATION_LAPSED, expected_status=409)

    lapsed = fixtures.read_proctor(proctor["id"])
    assert lapsed["certification_status"] == ProctorCertificationStatus.LAPSED
    assert lapsed["certification_expires_at"] == SHORT_EXPIRY
    assert fixtures.read_session(session["id"])["status"] == SessionStatus.DRAFT


def test_05_a_renewal_closes_the_cycle_and_the_same_assignment_then_succeeds():
    """"Certification therefore cycles: a proctor may travel `CERTIFIED` to `LAPSED` and back
    to `CERTIFIED` as many times as the state renews them."

    Design: Corner/state_machines/proctor_lapse_then_renew_restores_certified
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Lapse Cycle Center", state_code="CO"
    )
    room = fixtures.create_room(
        center["id"], room_code="R-401", seat_capacity=12, turnaround_buffer_minutes=45
    )
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=SHORT_EXPIRY,
        full_name="Tove Lind",
        daily_hour_cap=8.00,
    )
    session = fixtures.create_session(
        center["id"], room["id"], SITTING[0], SITTING[1], subtest=Subtest.MATH, requested_seats=5
    )
    fixtures.set_clock(PAST_THE_EXPIRY)
    validate_error(
        _assign(center["id"], session["id"], proctor["id"]),
        ApiErrorId.PROCTOR_CERTIFICATION_LAPSED,
        expected_status=409,
    )

    renewed = validate_success(
        _decide_proctor(
            proctor["id"], ProctorDecision.RENEW, certification_expires_at=USABLE_EXPIRY
        )
    )
    assert renewed["certification_status"] == ProctorCertificationStatus.CERTIFIED
    assert renewed["certification_expires_at"] == USABLE_EXPIRY

    assigned = validate_success(_assign(center["id"], session["id"], proctor["id"]))
    assert assigned["status"] == SessionStatus.SCHEDULED
    assert assigned["proctor_id"] == proctor["id"]
    assert fixtures.read_proctor(proctor["id"])["assigned_session_count"] == 1


def test_06_maintenance_retirement_blocks_new_sittings_and_a_second_retirement():
    """"The important asymmetry is what it does *not* do: sittings already created in that room
    are left exactly as they are, keeping their own status and their sold seats, and only *new*
    sittings are blocked. A second attempt on a room already `OUT_OF_SERVICE` — whether it got
    there by maintenance retirement or by its centre's suspension cascade — is refused with
    `ERR_ROOM_OUT_OF_SERVICE`, and the same code is what a new sitting in such a room receives."

    Design: Corner/state_machines/room_out_of_service_blocks_new_session_and_second_retirement
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Maintenance Center", state_code="ID"
    )
    room = fixtures.create_room(center["id"], room_code="R-501", seat_capacity=12)
    existing = fixtures.create_session(
        center["id"], room["id"], SITTING[0], SITTING[1], subtest=Subtest.MATH, requested_seats=5
    )

    retired = validate_success(_retire(center["id"], room["id"]))
    assert retired["status"] == RoomStatus.OUT_OF_SERVICE
    assert retired["service_note"] == SERVICE_NOTE

    new_sitting = api_client.create_exam_session(
        factories.create_exam_session_payload(
            room["id"],
            NEXT_DAY_SITTING[0],
            NEXT_DAY_SITTING[1],
            subtest=Subtest.RLA,
            requested_seats=5,
        ),
        headers=make_center_administrator_headers(center["id"]),
    )
    validate_error(new_sitting, ApiErrorId.ROOM_OUT_OF_SERVICE, expected_status=409)

    second_retirement = _retire(center["id"], room["id"])
    validate_error(second_retirement, ApiErrorId.ROOM_OUT_OF_SERVICE, expected_status=409)

    assert (
        fixtures.read_testing_center(center["id"])["authorization_status"]
        == CenterAuthorizationStatus.FULL_AUTHORIZED
    )
    assert fixtures.read_session(existing["id"])["status"] == SessionStatus.DRAFT


def test_07_a_scheduled_sitting_refuses_a_second_supervisor():
    """"A session that is not `DRAFT` — one already `SCHEDULED`, or `IN_PROGRESS`, `COMPLETED`
    or `CANCELLED` — refuses the attempt with `ERR_SESSION_NOT_ASSIGNABLE`."

    Design: Corner/state_machines/exam_session_proctor_assignment_repeated_rejected
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Assign Once Center", state_code="MT"
    )
    room = fixtures.create_room(center["id"], room_code="R-601", seat_capacity=12)
    first_proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=USABLE_EXPIRY,
        full_name="Amir Sole",
        daily_hour_cap=8.00,
    )
    second_proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=USABLE_EXPIRY,
        full_name="Bea Croft",
        daily_hour_cap=8.00,
    )
    session = fixtures.create_session(
        center["id"], room["id"], SITTING[0], SITTING[1], subtest=Subtest.MATH, requested_seats=5
    )
    fixtures.assign_session_proctor(center["id"], session["id"], first_proctor["id"])

    response = _assign(center["id"], session["id"], second_proctor["id"])
    validate_error(response, ApiErrorId.SESSION_NOT_ASSIGNABLE, expected_status=409)

    stored = fixtures.read_session(session["id"])
    assert stored["status"] == SessionStatus.SCHEDULED
    assert stored["proctor_id"] == first_proctor["id"]
    assert fixtures.read_proctor(first_proctor["id"])["assigned_session_count"] == 1
    assert fixtures.read_proctor(second_proctor["id"])["assigned_session_count"] == 0


def test_08_a_cancelled_sitting_keeps_its_first_reason_and_refuses_a_repeat():
    """"It applies to a session that is `DRAFT` or `SCHEDULED`; one already `IN_PROGRESS`,
    `COMPLETED` or `CANCELLED` reports `ERR_SESSION_NOT_CANCELLABLE`." and "`COMPLETED` and
    `CANCELLED` are the two terminal session states."

    Design: Corner/state_machines/exam_session_cancel_after_cancelled_rejected
    """
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Cancel Once Center", state_code="WY"
    )
    room = fixtures.create_room(center["id"], room_code="R-701", seat_capacity=12)
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=USABLE_EXPIRY,
        full_name="Cato Reyes",
        daily_hour_cap=8.00,
    )
    session = fixtures.create_session(
        center["id"],
        room["id"],
        SITTING[0],
        SITTING[1],
        subtest=Subtest.SCIENCE,
        requested_seats=5,
    )
    fixtures.assign_session_proctor(center["id"], session["id"], proctor["id"])

    cancelled = validate_success(_cancel(center["id"], session["id"], FIRST_CANCEL_REASON))
    assert cancelled["status"] == SessionStatus.CANCELLED
    assert cancelled["cancel_reason"] == FIRST_CANCEL_REASON

    repeat = _cancel(center["id"], session["id"], SECOND_CANCEL_REASON)
    validate_error(repeat, ApiErrorId.SESSION_NOT_CANCELLABLE, expected_status=409)

    assert fixtures.read_session(session["id"])["cancel_reason"] == FIRST_CANCEL_REASON
    assert fixtures.read_proctor(proctor["id"])["assigned_session_count"] == 0
