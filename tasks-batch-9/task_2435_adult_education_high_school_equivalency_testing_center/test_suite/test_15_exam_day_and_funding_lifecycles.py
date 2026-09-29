"""Edges on the candidate and funding side: the seat that must be taken before a score exists,
the two accommodation queues that guard different edges, and the decisions that close a period.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.test_users import (
    make_center_administrator_headers,
    make_program_coordinator_headers,
    make_proctor_headers,
    make_registrar_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    AccommodationDecision,
    AccommodationStatus,
    AllocationStatus,
    AllocationVariant,
    CenterDecision,
    FundingPeriodStatus,
    IdentityStatus,
    MeasureType,
    OutcomeDecision,
    OutcomeStatus,
    ProgramTrack,
    RegistrationStatus,
    SessionStatus,
    TestFormat,
)

SITTING = ("2026-08-20T09:00:00Z", "2026-08-20T12:00:00Z")
PRE_TEST_AT = "2026-08-02T09:00:00Z"
UNSEATED_SCORE = 160

APPROVAL_HORIZON = "2027-01-01T00:00:00Z"
INFO_REQUEST_NOTE = "need a dated evaluation"
DENIAL_NOTE = "documentation unrelated to testing"

RATE_CENTS_PER_WEIGHT = 10000
EMPLOYMENT_WEIGHT = 1.25
POSTSECONDARY_WEIGHT = 1.40

RECORDING_COORDINATOR = "coordinator-1"
FIRST_CERTIFIER = "state-1"
SECOND_CERTIFIER = "state-2"
REJECTING_AUTHORITY = "state-9"


def _decide_accommodation(center_id, request_id, decision, **payload_overrides):
    return api_client.decide_accommodation(
        request_id,
        factories.accommodation_decision_payload(decision, **payload_overrides),
        headers=make_center_administrator_headers(center_id),
    )


def _decide_outcome(outcome_id, decision, user_id):
    return api_client.decide_outcome_certification(
        outcome_id,
        factories.outcome_certification_payload(decision),
        headers=make_state_authority_headers(user_id),
    )


def _setup_verified_but_unseated_candidate():
    """A verified candidate holding a REGISTERED seat that has never been checked in."""
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Seat First Center", state_code="OR"
    )
    room = fixtures.create_room(center["id"], room_code="R-801", seat_capacity=12)
    proctor = fixtures.create_certified_proctor(
        center["id"],
        certification_expires_at=APPROVAL_HORIZON,
        full_name="Dara Vogt",
        daily_hour_cap=8.00,
    )
    session = fixtures.create_session(
        center["id"], room["id"], SITTING[0], SITTING[1], requested_seats=5
    )
    fixtures.assign_session_proctor(center["id"], session["id"], proctor["id"])

    placed = fixtures.create_placed_student(
        scale_score=205,
        full_name="Elia Marsh",
        email="elia.marsh@example.org",
        primary_track=ProgramTrack.HSE_PREP,
        self_pay_authorized=True,
        pre_test_at=PRE_TEST_AT,
    )
    registration = fixtures.register_candidate(placed["student_id"], session["id"])
    fixtures.verify_candidate_identity(registration["id"], proctor["id"])

    return {
        "session_id": session["id"],
        "proctor_id": proctor["id"],
        "registration_id": registration["id"],
    }


def _setup_info_requested_accommodation():
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Queue Order Center", state_code="NM"
    )
    student = fixtures.create_student(
        full_name="Fen Okabe", email="fen.okabe@example.org", primary_track=ProgramTrack.HSE_PREP
    )
    request = fixtures.create_accommodation(
        student["id"], requested_format=TestFormat.EXTRA_TIME, documentation_ref="doc-fen-1"
    )
    fixtures.request_accommodation_info(
        center["id"], request["id"], decision_note=INFO_REQUEST_NOTE
    )
    return {"center_id": center["id"], "request_id": request["id"]}


def _setup_denied_accommodation():
    center = fixtures.create_authorized_center(
        CenterDecision.GRANT_FULL, name="Denial Terminal Center", state_code="KS"
    )
    student = fixtures.create_student(
        full_name="Gita Roan", email="gita.roan@example.org", primary_track=ProgramTrack.HSE_PREP
    )
    request = fixtures.create_accommodation(
        student["id"], requested_format=TestFormat.BRAILLE, documentation_ref="doc-gita-1"
    )
    denied = validate_success(
        _decide_accommodation(
            center["id"],
            request["id"],
            AccommodationDecision.DENY,
            granted_format=None,
            valid_until=None,
            decision_note=DENIAL_NOTE,
        )
    )
    return {"center_id": center["id"], "request_id": request["id"], "denied": denied}


def _setup_recorded_employment_claim(label, start_date, end_date, total_cents=500000):
    period = fixtures.create_funding_period(
        label=label,
        start_date=start_date,
        end_date=end_date,
        rate_cents_per_weight=RATE_CENTS_PER_WEIGHT,
        total_cents=total_cents,
    )
    placed = fixtures.create_placed_student(
        scale_score=205,
        full_name="Hana Bright",
        email="hana.bright@example.org",
        primary_track=ProgramTrack.HSE_PREP,
        pre_test_at=PRE_TEST_AT,
    )
    outcome = fixtures.record_outcome(
        placed["student_id"],
        period["id"],
        measure_type=MeasureType.EMPLOYMENT_Q2,
        evidence_ref="wage-record-h1",
        headers=make_program_coordinator_headers(RECORDING_COORDINATOR),
    )
    return {"period_id": period["id"], "outcome_id": outcome["id"]}


def test_01_a_score_cannot_be_recorded_for_a_candidate_who_never_took_a_seat():
    """"The registration must be `CHECKED_IN`; anything else reports
    `ERR_REGISTRATION_NOT_CHECKED_IN`." and "An accepted check-in moves `registration_status`
    from `REGISTERED` to `CHECKED_IN`, stamps `checked_in_at` from the logical clock, and — on
    the *first* check-in for that sitting only — moves the sitting itself from `SCHEDULED` to
    `IN_PROGRESS`."

    Design: Corner/state_machines/registration_result_before_check_in_rejected
    """
    context = _setup_verified_but_unseated_candidate()

    response = api_client.record_result(
        context["registration_id"],
        factories.record_result_payload(UNSEATED_SCORE),
        headers=make_proctor_headers(context["proctor_id"]),
    )
    validate_error(response, ApiErrorId.REGISTRATION_NOT_CHECKED_IN, expected_status=409)

    registration = fixtures.read_registration(context["registration_id"])
    assert registration["registration_status"] == RegistrationStatus.REGISTERED
    assert registration["identity_status"] == IdentityStatus.VERIFIED
    assert registration["scale_score"] is None
    assert registration["result_outcome"] is None
    assert registration["checked_in_at"] is None

    assert fixtures.read_session(context["session_id"])["status"] == SessionStatus.SCHEDULED


def test_02_a_request_awaiting_paperwork_is_out_of_the_decision_queue():
    """"This moves the request from `SUBMITTED` to `INFO_REQUESTED` and increments
    `info_request_rounds` by one." and "An information request or a decision attempted on a
    request that is not `SUBMITTED` is refused with `ERR_ACCOMMODATION_NOT_PENDING`"

    Design: Corner/state_machines/accommodation_decision_from_info_requested_rejected
    """
    context = _setup_info_requested_accommodation()

    response = _decide_accommodation(
        context["center_id"],
        context["request_id"],
        AccommodationDecision.APPROVE,
        granted_format=TestFormat.EXTRA_TIME,
        valid_until=APPROVAL_HORIZON,
    )
    validate_error(response, ApiErrorId.ACCOMMODATION_NOT_PENDING, expected_status=409)

    stored = fixtures.read_accommodation(context["request_id"])
    assert stored["status"] == AccommodationStatus.INFO_REQUESTED
    assert stored["info_request_rounds"] == 1
    assert stored["granted_format"] is None
    assert stored["valid_until"] is None


def test_03_a_denial_grants_nothing_and_cannot_be_reversed_by_a_later_approval():
    """"A `DENY` decision moves the request from `SUBMITTED` to `DENIED`, which is terminal,
    records the `decision_note`, and leaves `granted_format` null — a denial grants nothing, not
    even the requested format at a reduced scope."

    Design: Corner/state_machines/accommodation_denied_is_terminal
    """
    context = _setup_denied_accommodation()
    assert context["denied"]["status"] == AccommodationStatus.DENIED
    assert context["denied"]["granted_format"] is None
    assert context["denied"]["decision_note"] == DENIAL_NOTE

    response = _decide_accommodation(
        context["center_id"],
        context["request_id"],
        AccommodationDecision.APPROVE,
        granted_format=TestFormat.BRAILLE,
        valid_until=APPROVAL_HORIZON,
    )
    validate_error(response, ApiErrorId.ACCOMMODATION_NOT_PENDING, expected_status=409)

    stored = fixtures.read_accommodation(context["request_id"])
    assert stored["status"] == AccommodationStatus.DENIED
    assert stored["granted_format"] is None


def test_04_a_denied_request_cannot_be_revived_by_fresh_paperwork_either():
    """"a resubmission attempted on a request that is not `INFO_REQUESTED` is refused with
    `ERR_ACCOMMODATION_NOT_INFO_REQUESTED`."

    Design: Corner/state_machines/accommodation_denied_is_terminal
    """
    context = _setup_denied_accommodation()

    response = api_client.resubmit_accommodation(
        context["request_id"],
        factories.accommodation_resubmission_payload("doc-gita-2"),
        headers=make_registrar_headers(),
    )
    validate_error(response, ApiErrorId.ACCOMMODATION_NOT_INFO_REQUESTED, expected_status=409)

    stored = fixtures.read_accommodation(context["request_id"])
    assert stored["status"] == AccommodationStatus.DENIED
    assert stored["granted_format"] is None
    assert stored["documentation_ref"] == "doc-gita-1"


def test_05_certification_cannot_be_reassigned_by_replaying_the_call():
    """"Both require the claim to be `RECORDED` — one already `CERTIFIED`, `REJECTED` or
    `RESCINDED` reports `ERR_OUTCOME_NOT_CERTIFIABLE`" and "Both write `certified_by_user_id`
    from the acting `X-User-ID` and raise the claim's `version` by one"

    Design: Corner/state_machines/outcome_certification_repeated_rejected
    """
    context = _setup_recorded_employment_claim("PY26-Q1", "2026-07-01", "2026-09-30")

    certified = validate_success(
        _decide_outcome(context["outcome_id"], OutcomeDecision.CERTIFY, FIRST_CERTIFIER)
    )
    assert certified["status"] == OutcomeStatus.CERTIFIED
    assert certified["certified_by_user_id"] == FIRST_CERTIFIER
    assert float(certified["weight"]) == EMPLOYMENT_WEIGHT
    assert certified["allocation_status"] == AllocationStatus.UNALLOCATED
    assert certified["allocated_cents"] == 0

    replay = _decide_outcome(context["outcome_id"], OutcomeDecision.CERTIFY, SECOND_CERTIFIER)
    validate_error(replay, ApiErrorId.OUTCOME_NOT_CERTIFIABLE, expected_status=409)

    stored = fixtures.read_outcome(context["outcome_id"])
    assert stored["certified_by_user_id"] == FIRST_CERTIFIER
    assert stored["recorded_by_user_id"] == RECORDING_COORDINATOR


def test_06_a_rejection_records_its_decider_and_leaves_the_pool_untouched():
    """"a rejection is as much a recorded decision as an approval, and its decider is recorded
    identically." and "an `EMPLOYMENT_Q2` weighs 1.25 and a `POSTSECONDARY_ENROLLMENT`
    weighs 1.40."

    Design: Corner/state_machines/outcome_reject_decision_records_the_rejecting_user
    """
    period = fixtures.create_funding_period(
        label="PY26-Q2",
        start_date="2026-10-01",
        end_date="2026-12-31",
        rate_cents_per_weight=RATE_CENTS_PER_WEIGHT,
        total_cents=500000,
    )
    placed = fixtures.create_placed_student(
        scale_score=205,
        full_name="Ivo Sandu",
        email="ivo.sandu@example.org",
        primary_track=ProgramTrack.HSE_PREP,
        pre_test_at=PRE_TEST_AT,
    )
    outcome = fixtures.record_outcome(
        placed["student_id"],
        period["id"],
        measure_type=MeasureType.POSTSECONDARY_ENROLLMENT,
        evidence_ref="clearinghouse-i1",
        headers=make_program_coordinator_headers(RECORDING_COORDINATOR),
    )

    rejected = validate_success(
        _decide_outcome(outcome["id"], OutcomeDecision.REJECT, REJECTING_AUTHORITY)
    )
    assert rejected["status"] == OutcomeStatus.REJECTED
    assert rejected["certified_by_user_id"] == REJECTING_AUTHORITY
    assert float(rejected["weight"]) == POSTSECONDARY_WEIGHT
    assert rejected["allocation_status"] == AllocationStatus.UNALLOCATED
    assert rejected["allocated_cents"] == 0

    stored_period = fixtures.read_funding_period(period["id"])
    assert stored_period["committed_cents"] == 0
    assert stored_period["available_cents"] == 500000
    assert stored_period["allocation_run_count"] == 0


def test_07_a_current_version_does_not_buy_an_allocation_run_on_a_closed_period():
    """"A closed period refuses the run with `ERR_FUNDING_PERIOD_CLOSED`." and "a run supersedes
    the previous view of the pool, so a stale `expected_funding_period_version` is refused with
    `ERR_STALE_FUNDING_PERIOD_VERSION` before the period's own `OPEN` status is even examined."

    Design: Corner/state_machines/funding_period_close_is_terminal_for_run_and_close
    """
    period = fixtures.create_funding_period(
        label="PY26-Q3",
        start_date="2027-01-01",
        end_date="2027-03-31",
        rate_cents_per_weight=RATE_CENTS_PER_WEIGHT,
        total_cents=300000,
    )
    closed = fixtures.close_funding_period(period["id"])
    assert closed["status"] == FundingPeriodStatus.CLOSED

    response = api_client.run_allocation(
        period["id"],
        factories.allocation_run_payload(closed["version"], variant=AllocationVariant.FINAL),
        headers=make_state_authority_headers(),
    )
    validate_error(response, ApiErrorId.FUNDING_PERIOD_CLOSED, expected_status=409)

    stored = fixtures.read_funding_period(period["id"])
    assert stored["version"] == closed["version"]
    assert stored["allocation_run_count"] == 0
    assert stored["committed_cents"] == 0
    assert stored["available_cents"] == 300000


def test_08_a_closed_period_refuses_a_second_closure_without_moving_its_version():
    """"A `StateAuthority` moves an `OPEN` period to `CLOSED`, which is terminal and raises the
    period's `version` by one; a second attempt reports `ERR_FUNDING_PERIOD_CLOSED`."

    Design: Corner/state_machines/funding_period_close_is_terminal_for_run_and_close
    """
    period = fixtures.create_funding_period(
        label="PY26-Q3",
        start_date="2027-01-01",
        end_date="2027-03-31",
        rate_cents_per_weight=RATE_CENTS_PER_WEIGHT,
        total_cents=300000,
    )
    closed = fixtures.close_funding_period(period["id"])
    assert closed["version"] == period["version"] + 1

    response = api_client.close_funding_period(
        period["id"], headers=make_state_authority_headers()
    )
    validate_error(response, ApiErrorId.FUNDING_PERIOD_CLOSED, expected_status=409)

    stored = fixtures.read_funding_period(period["id"])
    assert stored["status"] == FundingPeriodStatus.CLOSED
    assert stored["version"] == closed["version"]
    assert stored["available_cents"] == 300000
