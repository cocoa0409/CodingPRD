"""Three non-linear lifecycles: the registration's two independent axes, the bounded
accommodation review cycle, and the branching centre-authorisation fork.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import assert_accommodation_request, assert_testing_center
from test_helpers.test_users import (
    make_center_administrator_headers,
    make_proctor_headers,
    make_registrar_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    AccommodationDecision,
    AccommodationStatus,
    CenterAuthorizationStatus,
    CenterDecision,
    IdentityDecision,
    IdentityStatus,
    RegistrationStatus,
    ResultOutcome,
    SessionStatus,
    Subtest,
    TestFormat,
)

SITTING_STARTS = "2026-08-05T09:00:00Z"
SITTING_ENDS = "2026-08-05T11:00:00Z"
INSIDE_SEATING_WINDOW = "2026-08-05T08:30:00Z"

PROVISIONAL_SUBTESTS = [Subtest.MATH, Subtest.RLA]
FULL_SUBTESTS = [Subtest.MATH, Subtest.RLA, Subtest.SCIENCE, Subtest.SOCIAL_STUDIES]

SCIENCE_SESSION_STARTS = "2026-08-20T09:00:00Z"
SCIENCE_SESSION_ENDS = "2026-08-20T11:00:00Z"


def _setup_candidate_inside_window():
    context = fixtures.setup_registered_candidate(
        starts_at=SITTING_STARTS,
        ends_at=SITTING_ENDS,
        subtest=Subtest.MATH,
        self_pay_authorized=True,
        requested_seats=4,
        seat_capacity=8,
        turnaround_buffer_minutes=45,
        daily_hour_cap=8.00,
    )
    fixtures.ensure_clock(INSIDE_SEATING_WINDOW)
    return context


def _setup_submitted_braille_request():
    center = fixtures.create_authorized_center(CenterDecision.GRANT_FULL)
    student = fixtures.create_student(primary_track="ESL")
    request = fixtures.create_accommodation(
        student["id"], requested_format=TestFormat.BRAILLE, documentation_ref="DOC-A"
    )
    return {"center_id": center["id"], "student_id": student["id"], "request_id": request["id"]}


def test_01_a_rejected_document_leaves_the_seat_axis_untouched_and_blocks_seating():
    """"A `REJECTED` decision moves `identity_status` from `UNVERIFIED` to `ID_REJECTED`,
    writes the supplied `identity_document_type`, and leaves
    `identity_verified_by_proctor_id` null." and "both `UNVERIFIED` and `ID_REJECTED`
    are refused with `ERR_IDENTITY_NOT_VERIFIED`, which is the cross-axis gate."

    Design: Difficulty/non_linear_state_machine/exam_registration_parallel_identity_and_registration_dimensions
    """
    context = _setup_candidate_inside_window()

    rejected = fixtures.verify_candidate_identity(
        context["registration_id"],
        context["proctor_id"],
        decision=IdentityDecision.REJECTED,
        identity_document_type="SCHOOL_ID",
    )
    assert rejected["identity_status"] == IdentityStatus.ID_REJECTED
    assert rejected["identity_verified_by_proctor_id"] is None
    assert rejected["identity_document_type"] == "SCHOOL_ID"
    assert rejected["registration_status"] == RegistrationStatus.REGISTERED

    response = api_client.check_in(
        context["registration_id"], headers=make_proctor_headers(context["proctor_id"])
    )
    validate_error(response, ApiErrorId.IDENTITY_NOT_VERIFIED, expected_status=409)

    still_open = fixtures.read_registration(context["registration_id"])
    assert still_open["registration_status"] == RegistrationStatus.REGISTERED
    assert still_open["identity_status"] == IdentityStatus.ID_REJECTED


def test_02_verification_re_entry_from_id_rejected_then_seats_the_candidate():
    """"The `ID_REJECTED` state is not a dead end: a candidate who produces a second,
    acceptable document is verified from `ID_REJECTED` in the same way." and "on the
    *first* check-in for that sitting only — moves the sitting itself from `SCHEDULED`
    to `IN_PROGRESS`."

    Design: Difficulty/non_linear_state_machine/exam_registration_parallel_identity_and_registration_dimensions
    """
    context = _setup_candidate_inside_window()

    fixtures.verify_candidate_identity(
        context["registration_id"],
        context["proctor_id"],
        decision=IdentityDecision.REJECTED,
        identity_document_type="SCHOOL_ID",
    )
    verified = fixtures.verify_candidate_identity(
        context["registration_id"],
        context["proctor_id"],
        decision=IdentityDecision.VERIFIED,
        identity_document_type="PASSPORT",
    )
    assert verified["identity_status"] == IdentityStatus.VERIFIED
    assert verified["identity_verified_by_proctor_id"] == context["proctor_id"]
    assert verified["registration_status"] == RegistrationStatus.REGISTERED

    seated = fixtures.check_in_candidate(context["registration_id"], context["proctor_id"])
    assert seated["registration_status"] == RegistrationStatus.CHECKED_IN
    assert seated["checked_in_at"] is not None

    session = fixtures.read_session(context["session_id"])
    assert session["status"] == SessionStatus.IN_PROGRESS


def test_03_a_redundant_verification_is_refused_without_moving_either_axis():
    """"A redundant `VERIFIED` decision on an already `VERIFIED` registration is likewise
    not a declared transition and reports the same code."

    Design: Difficulty/non_linear_state_machine/exam_registration_parallel_identity_and_registration_dimensions
    """
    context = _setup_candidate_inside_window()

    fixtures.verify_candidate_identity(
        context["registration_id"],
        context["proctor_id"],
        decision=IdentityDecision.VERIFIED,
        identity_document_type="PASSPORT",
    )

    response = api_client.verify_identity(
        context["registration_id"],
        factories.identity_verification_payload(
            IdentityDecision.VERIFIED, identity_document_type="PASSPORT"
        ),
        headers=make_proctor_headers(context["proctor_id"]),
    )
    validate_error(response, ApiErrorId.IDENTITY_ALREADY_VERIFIED, expected_status=409)

    unchanged = fixtures.read_registration(context["registration_id"])
    assert unchanged["identity_status"] == IdentityStatus.VERIFIED
    assert unchanged["registration_status"] == RegistrationStatus.REGISTERED


def test_04_the_seat_axis_advances_to_scored_while_the_identity_axis_holds():
    """"Recording the result moves `registration_status` from `CHECKED_IN` to `SCORED`,
    stores the score, and derives `result_outcome` as `PASSED` when the score is at least
    145 and `FAILED` when it is below" and "`identity_status` tracks the document check
    alone, moving among `UNVERIFIED`, `VERIFIED` and `ID_REJECTED`, and it has no terminal
    state"

    Design: Difficulty/non_linear_state_machine/exam_registration_parallel_identity_and_registration_dimensions
    """
    context = _setup_candidate_inside_window()

    fixtures.verify_candidate_identity(context["registration_id"], context["proctor_id"])
    fixtures.check_in_candidate(context["registration_id"], context["proctor_id"])

    # A repeat verification while the seat axis has already advanced is refused by
    # one of the two gates the evaluation order places in the same band.
    repeat = api_client.verify_identity(
        context["registration_id"],
        factories.identity_verification_payload(IdentityDecision.VERIFIED),
        headers=make_proctor_headers(context["proctor_id"]),
    )
    validate_error_is_one_of(
        repeat,
        [ApiErrorId.IDENTITY_ALREADY_VERIFIED, ApiErrorId.REGISTRATION_NOT_OPEN],
    )
    assert (
        fixtures.read_registration(context["registration_id"])["registration_status"]
        == RegistrationStatus.CHECKED_IN
    )

    scored = fixtures.record_candidate_result(
        context["registration_id"], context["proctor_id"], 150
    )
    assert scored["registration_status"] == RegistrationStatus.SCORED
    assert scored["result_outcome"] == ResultOutcome.PASSED
    assert scored["identity_status"] == IdentityStatus.VERIFIED

    session = fixtures.read_session(context["session_id"])
    assert session["status"] == SessionStatus.COMPLETED


def test_05_the_review_cycle_returns_to_submitted_and_refuses_a_second_resubmission():
    """"This moves the request from `SUBMITTED` to `INFO_REQUESTED` and increments
    `info_request_rounds` by one. The learner or their registrar then resubmits,
    supplying a fresh `documentation_ref` that replaces the one on file, which returns
    the request from `INFO_REQUESTED` to `SUBMITTED`." and "a resubmission attempted on
    a request that is not `INFO_REQUESTED` is refused with
    `ERR_ACCOMMODATION_NOT_INFO_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/accommodation_request_info_request_resubmission_cycle
    """
    context = _setup_submitted_braille_request()

    queried = fixtures.request_accommodation_info(
        context["center_id"], context["request_id"], "Need an evaluator signature"
    )
    assert_accommodation_request(queried)
    assert queried["status"] == AccommodationStatus.INFO_REQUESTED
    assert queried["info_request_rounds"] == 1

    resubmitted = fixtures.resubmit_accommodation(context["request_id"], "DOC-B")
    assert resubmitted["status"] == AccommodationStatus.SUBMITTED
    assert resubmitted["documentation_ref"] == "DOC-B"

    response = api_client.resubmit_accommodation(
        context["request_id"],
        factories.accommodation_resubmission_payload("DOC-B2"),
        headers=make_registrar_headers(),
    )
    validate_error(response, ApiErrorId.ACCOMMODATION_NOT_INFO_REQUESTED, expected_status=409)

    unchanged = validate_success(
        api_client.get_accommodation_request(
            context["request_id"], headers=make_registrar_headers()
        )
    )
    assert unchanged["documentation_ref"] == "DOC-B"
    assert unchanged["info_request_rounds"] == 1


def test_06_the_third_information_request_is_refused_by_the_round_counter():
    """"That loop is bounded: an information request may only be issued while
    `info_request_rounds` is still below 2, so a request can travel `SUBMITTED` to
    `INFO_REQUESTED` and back at most twice before the reviewer must decide on the
    evidence in hand. A third attempt is refused with
    `ERR_INFO_REQUEST_LIMIT_REACHED`."

    Design: Difficulty/non_linear_state_machine/accommodation_request_info_request_resubmission_cycle
    """
    context = _setup_submitted_braille_request()

    fixtures.request_accommodation_info(context["center_id"], context["request_id"])
    fixtures.resubmit_accommodation(context["request_id"], "DOC-B")
    second_round = fixtures.request_accommodation_info(
        context["center_id"], context["request_id"], "Evaluation is older than 3 years"
    )
    assert second_round["info_request_rounds"] == 2

    back_to_review = fixtures.resubmit_accommodation(context["request_id"], "DOC-C")
    assert back_to_review["status"] == AccommodationStatus.SUBMITTED
    assert back_to_review["documentation_ref"] == "DOC-C"

    response = api_client.request_accommodation_info(
        context["request_id"],
        factories.accommodation_info_request_payload("Third request"),
        headers=make_center_administrator_headers(context["center_id"]),
    )
    validate_error(response, ApiErrorId.INFO_REQUEST_LIMIT_REACHED, expected_status=409)

    stalled = validate_success(
        api_client.get_accommodation_request(
            context["request_id"], headers=make_registrar_headers()
        )
    )
    assert stalled["status"] == AccommodationStatus.SUBMITTED
    assert stalled["info_request_rounds"] == 2


def test_07_a_request_that_exhausted_its_rounds_is_still_decidable():
    """"An information request or a decision attempted on a request that is not
    `SUBMITTED` is refused with `ERR_ACCOMMODATION_NOT_PENDING`"

    Design: Difficulty/non_linear_state_machine/accommodation_request_info_request_resubmission_cycle
    """
    context = _setup_submitted_braille_request()

    fixtures.request_accommodation_info(context["center_id"], context["request_id"])
    fixtures.resubmit_accommodation(context["request_id"], "DOC-B")
    fixtures.request_accommodation_info(context["center_id"], context["request_id"])
    fixtures.resubmit_accommodation(context["request_id"], "DOC-C")

    approved = fixtures.decide_accommodation(
        context["center_id"],
        context["request_id"],
        AccommodationDecision.APPROVE,
        granted_format=TestFormat.BRAILLE,
        valid_until="2026-12-31T00:00:00Z",
    )
    assert approved["status"] == AccommodationStatus.APPROVED
    assert approved["granted_format"] == TestFormat.BRAILLE
    assert approved["info_request_rounds"] == 2

    # A decision on a request that is no longer SUBMITTED is refused.
    repeat = api_client.decide_accommodation(
        context["request_id"],
        factories.accommodation_decision_payload(
            AccommodationDecision.APPROVE,
            granted_format=TestFormat.BRAILLE,
            valid_until="2026-12-31T00:00:00Z",
        ),
        headers=make_center_administrator_headers(context["center_id"]),
    )
    validate_error(repeat, ApiErrorId.ACCOMMODATION_NOT_PENDING, expected_status=409)


def test_08_the_three_authorisation_exits_write_three_different_side_effect_sets():
    """"`GRANT_PROVISIONAL` on an `APPLIED` centre moves it to `PROVISIONAL`. Its
    `allowed_subtests` becomes exactly `MATH` and `RLA` — a deliberately narrower
    scope — its `max_sessions_per_week` becomes 2, and `authorized_at` is stamped with
    the logical clock's current instant as the first authorisation grant." and
    "`WITHDRAW` on an `APPLIED` centre moves it to `WITHDRAWN`, which is terminal, and
    empties `allowed_subtests`. No other field is written by this branch."

    Design: Difficulty/non_linear_state_machine/testing_center_authorization_branch_divergent_side_effects
    """
    provisional = fixtures.decide_center(
        fixtures.create_center()["id"], CenterDecision.GRANT_PROVISIONAL
    )
    full = fixtures.decide_center(fixtures.create_center()["id"], CenterDecision.GRANT_FULL)
    withdrawn = fixtures.decide_center(fixtures.create_center()["id"], CenterDecision.WITHDRAW)

    for centre in (provisional, full, withdrawn):
        assert_testing_center(centre)

    assert provisional["authorization_status"] == CenterAuthorizationStatus.PROVISIONAL
    assert sorted(provisional["allowed_subtests"]) == sorted(PROVISIONAL_SUBTESTS)
    assert provisional["max_sessions_per_week"] == 2
    assert provisional["authorized_at"] is not None

    assert full["authorization_status"] == CenterAuthorizationStatus.FULL_AUTHORIZED
    assert sorted(full["allowed_subtests"]) == sorted(FULL_SUBTESTS)
    assert full["max_sessions_per_week"] == 20
    assert full["authorized_at"] is not None

    assert withdrawn["authorization_status"] == CenterAuthorizationStatus.WITHDRAWN
    assert withdrawn["allowed_subtests"] == []
    assert withdrawn["authorized_at"] is None


def test_09_promotion_widens_the_scope_while_preserving_the_first_grant_instant():
    """"`GRANT_FULL` on a centre already `PROVISIONAL` promotes it to `FULL_AUTHORIZED`,
    again widening `allowed_subtests` to all four subtests and raising
    `max_sessions_per_week` to 20. Here `authorized_at` is left exactly as it was: the
    field records the *first* grant, and a promotion does not restate it."

    Design: Difficulty/non_linear_state_machine/testing_center_authorization_branch_divergent_side_effects
    """
    centre = fixtures.decide_center(
        fixtures.create_center()["id"], CenterDecision.GRANT_PROVISIONAL
    )
    room = fixtures.create_room(centre["id"], room_code="P1", seat_capacity=6)

    refused = api_client.create_exam_session(
        factories.create_exam_session_payload(
            room["id"],
            SCIENCE_SESSION_STARTS,
            SCIENCE_SESSION_ENDS,
            subtest=Subtest.SCIENCE,
            requested_seats=4,
        ),
        headers=make_center_administrator_headers(centre["id"]),
    )
    validate_error(refused, ApiErrorId.SUBTEST_NOT_AUTHORIZED, expected_status=409)

    promoted = fixtures.decide_center(centre["id"], CenterDecision.GRANT_FULL)
    assert promoted["authorization_status"] == CenterAuthorizationStatus.FULL_AUTHORIZED
    assert sorted(promoted["allowed_subtests"]) == sorted(FULL_SUBTESTS)
    assert promoted["max_sessions_per_week"] == 20
    assert promoted["authorized_at"] == centre["authorized_at"]

    accepted = fixtures.create_session(
        centre["id"],
        room["id"],
        SCIENCE_SESSION_STARTS,
        SCIENCE_SESSION_ENDS,
        subtest=Subtest.SCIENCE,
        requested_seats=4,
    )
    assert accepted["status"] == SessionStatus.DRAFT


def test_10_the_withdrawn_exit_is_terminal_for_rooms_and_for_further_decisions():
    """"Rooms may only be added to a centre that is `PROVISIONAL` or `FULL_AUTHORIZED`; a
    centre still `APPLIED` or `WITHDRAWN` reports `ERR_CENTER_NOT_AUTHORIZED`" and "any
    decision at all against a `WITHDRAWN` or `SUSPENDED` centre — is refused with
    `ERR_CENTER_DECISION_NOT_ALLOWED`."

    Design: Difficulty/non_linear_state_machine/testing_center_authorization_branch_divergent_side_effects
    """
    centre = fixtures.decide_center(fixtures.create_center()["id"], CenterDecision.WITHDRAW)

    room_response = api_client.create_testing_room(
        centre["id"],
        factories.create_testing_room_payload(room_code="W1", seat_capacity=6),
        headers=make_center_administrator_headers(centre["id"]),
    )
    validate_error(room_response, ApiErrorId.CENTER_NOT_AUTHORIZED, expected_status=409)

    decision_response = api_client.decide_center_authorization(
        centre["id"],
        factories.center_authorization_decision_payload(CenterDecision.GRANT_FULL),
        headers=make_state_authority_headers(),
    )
    validate_error(decision_response, ApiErrorId.CENTER_DECISION_NOT_ALLOWED, expected_status=409)

    unchanged = validate_success(
        api_client.get_testing_center(centre["id"], headers=make_state_authority_headers())
    )
    assert unchanged["authorization_status"] == CenterAuthorizationStatus.WITHDRAWN
    assert unchanged["allowed_subtests"] == []
