"""Writes whose legality depends on the state of a *different* record: the sitting a
seat is sold against, the section an enrollment lands in, and the period a claim sits in.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import assert_section_seats_conserved
from test_helpers.test_users import (
    make_program_coordinator_headers,
    make_registrar_headers,
    make_state_authority_headers,
)
from test_helpers.types import (
    AllocationStatus,
    AllocationVariant,
    EnrollmentStatus,
    ExitReason,
    FundingPeriodStatus,
    IntakeStatus,
    MeasureType,
    OutcomeStatus,
    ProgramTrack,
    RegistrationStatus,
    SectionStatus,
    SessionStatus,
    Subtest,
    TestForm,
)

SITTING_STARTS = "2026-08-05T09:00:00Z"
SITTING_ENDS = "2026-08-05T11:00:00Z"
INSIDE_SEATING_WINDOW = "2026-08-05T08:30:00Z"

PRE_TEST_AT = "2026-08-02T09:00:00Z"


def _setup_draft_sitting_and_two_candidates():
    venue = fixtures.setup_center_with_room_and_proctor(
        seat_capacity=8,
        turnaround_buffer_minutes=45,
        daily_hour_cap=8.00,
        certification_expires_at="2027-01-01T00:00:00Z",
    )
    first = fixtures.create_placed_student(
        scale_score=205, self_pay_authorized=True, pre_test_at=PRE_TEST_AT
    )
    second = fixtures.create_placed_student(
        scale_score=225, self_pay_authorized=True, pre_test_at=PRE_TEST_AT
    )
    session = fixtures.create_session(
        venue["center_id"],
        venue["room_id"],
        SITTING_STARTS,
        SITTING_ENDS,
        subtest=Subtest.MATH,
        requested_seats=4,
    )
    venue.update(
        {
            "session": session,
            "session_id": session["id"],
            "first_student_id": first["student_id"],
            "second_student_id": second["student_id"],
        }
    )
    return venue


def _register(student_id, session_id, version):
    return api_client.create_exam_registration(
        factories.create_exam_registration_payload(student_id, session_id, version),
        headers=make_registrar_headers(),
    )


def _setup_planned_esl_section_and_two_learners():
    learners = [
        fixtures.create_placed_student(
            scale_score=410,
            test_form=TestForm.BEST_PLUS,
            primary_track=ProgramTrack.ESL,
            pre_test_at=PRE_TEST_AT,
        )
        for _ in range(2)
    ]
    section = fixtures.create_section(
        status=SectionStatus.PLANNED,
        program_track=ProgramTrack.ESL,
        title="ESL Level 2",
        instructor_user_id="instructor-2",
        min_efl_level=1,
        max_efl_level=4,
        seats_total=10,
        weekly_hours=6.00,
    )
    return {
        "section_id": section["id"],
        "student_ids": [learner["student_id"] for learner in learners],
    }


def _enroll(student_id, section_id):
    return api_client.create_enrollment(
        factories.create_enrollment_payload(student_id, section_id),
        headers=make_program_coordinator_headers(),
    )


def _setup_period_with_one_certified_and_one_standing_claim():
    period = fixtures.create_funding_period(rate_cents_per_weight=10000, total_cents=100000)
    first = fixtures.create_placed_student(pre_test_at=PRE_TEST_AT)
    second = fixtures.create_placed_student(pre_test_at=PRE_TEST_AT)
    certified = fixtures.certified_outcome(
        first["student_id"],
        period["id"],
        measure_type=MeasureType.EMPLOYMENT_Q2,
        evidence_ref="WAGE-A",
    )
    standing = fixtures.record_outcome(
        second["student_id"],
        period["id"],
        measure_type=MeasureType.EMPLOYMENT_Q2,
        evidence_ref="WAGE-B",
    )
    fixtures.run_allocation(period["id"], variant=AllocationVariant.FINAL)
    return {
        "period_id": period["id"],
        "certified_id": certified["id"],
        "standing_id": standing["id"],
        "second_student_id": second["student_id"],
    }


def test_01_a_draft_sitting_sells_nothing_until_a_proctor_is_assigned():
    """"The sitting itself must be `SCHEDULED`: a `DRAFT` sitting has no proctor and sells
    nothing, and an `IN_PROGRESS`, `COMPLETED` or `CANCELLED` one is past selling, so all
    four report `ERR_SESSION_NOT_OPEN_FOR_REGISTRATION`."

    Design: Difficulty/cross_entity_state_dependency/exam_registration_requires_scheduled_session
    """
    venue = _setup_draft_sitting_and_two_candidates()
    assert venue["session"]["status"] == SessionStatus.DRAFT

    refused = _register(
        venue["first_student_id"],
        venue["session_id"],
        venue["session"]["version"],
    )
    validate_error(refused, ApiErrorId.SESSION_NOT_OPEN_FOR_REGISTRATION, expected_status=409)
    assert fixtures.read_session(venue["session_id"])["seats_taken"] == 0

    scheduled = fixtures.assign_session_proctor(
        venue["center_id"], venue["session_id"], venue["proctor_id"]
    )
    accepted = validate_success(
        _register(venue["first_student_id"], venue["session_id"], scheduled["version"]),
        expected_status=201,
    )
    assert accepted["registration_status"] == RegistrationStatus.REGISTERED
    assert fixtures.read_session(venue["session_id"])["seats_taken"] == 1


def test_02_a_sitting_that_has_started_is_past_selling():
    """"**Session open for registration** (409). Only a `SCHEDULED` session sells seats; a
    session that is `DRAFT`, `IN_PROGRESS`, `COMPLETED` or `CANCELLED` reports
    `ERR_SESSION_NOT_OPEN_FOR_REGISTRATION`. Guards exam-registration creation."

    Design: Difficulty/cross_entity_state_dependency/exam_registration_requires_scheduled_session
    """
    venue = _setup_draft_sitting_and_two_candidates()
    fixtures.assign_session_proctor(venue["center_id"], venue["session_id"], venue["proctor_id"])
    first = fixtures.register_candidate(venue["first_student_id"], venue["session_id"])

    fixtures.ensure_clock(INSIDE_SEATING_WINDOW)
    fixtures.verify_candidate_identity(first["id"], venue["proctor_id"])
    fixtures.check_in_candidate(first["id"], venue["proctor_id"])
    assert fixtures.read_session(venue["session_id"])["status"] == SessionStatus.IN_PROGRESS

    # A fresh version rules out the stale-view guard, and seats and fees are both fine.
    refused = _register(
        venue["second_student_id"],
        venue["session_id"],
        fixtures.current_exam_session_version(venue["session_id"]),
    )
    validate_error(refused, ApiErrorId.SESSION_NOT_OPEN_FOR_REGISTRATION, expected_status=409)

    assert fixtures.read_session(venue["session_id"])["seats_taken"] == 1
    turned_away = fixtures.read_student(venue["second_student_id"])
    assert turned_away["voucher_spent_cents"] == 0
    assert turned_away["exam_fee_owed_cents"] == 0


def test_03_a_planned_section_takes_no_enrollments_but_an_open_one_does():
    """"First the section must be accepting: only `OPEN` and `IN_SESSION` sections take
    enrollments, and a `PLANNED` or `CLOSED` one reports
    `ERR_SECTION_NOT_ACCEPTING_ENROLLMENT`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_section_open_or_in_session
    """
    context = _setup_planned_esl_section_and_two_learners()
    first_student = context["student_ids"][0]

    refused = _enroll(first_student, context["section_id"])
    validate_error(refused, ApiErrorId.SECTION_NOT_ACCEPTING_ENROLLMENT, expected_status=409)
    assert fixtures.read_class_section(context["section_id"])["seats_taken"] == 0

    fixtures.transition_section(context["section_id"], SectionStatus.OPEN)
    accepted = validate_success(
        _enroll(first_student, context["section_id"]), expected_status=201
    )
    assert accepted["status"] == EnrollmentStatus.ACTIVE
    assert accepted["entry_efl_level"] == 2

    section = fixtures.read_class_section(context["section_id"])
    assert_section_seats_conserved(section)
    assert section["seats_taken"] == 1
    assert section["seats_available"] == 9
    assert fixtures.read_student(first_student)["intake_status"] == IntakeStatus.ENROLLED


def test_04_closing_the_section_settles_its_enrollments_and_stops_taking_more():
    """"**Link 1** walks that section's enrollments whose `status` is `ACTIVE`, in
    `created_at` ascending order, and decides each one's fate from its own hour total: an
    enrollment whose `posted_hours` has reached at least forty hours becomes `COMPLETED`,
    while one below that threshold becomes `WITHDRAWN`." and "**Link 2**, caused by link 1,
    decrements each affected learner's `active_enrollment_count`; when that count reaches
    zero and the learner's `intake_status` is `ENROLLED`, the learner moves back from
    `ENROLLED` to `PLACED`."

    Design: Difficulty/cross_entity_state_dependency/enrollment_requires_section_open_or_in_session
    """
    context = _setup_planned_esl_section_and_two_learners()
    first_student, second_student = context["student_ids"]

    fixtures.transition_section(context["section_id"], SectionStatus.OPEN)
    first_enrollment = fixtures.enroll(first_student, context["section_id"])
    fixtures.transition_section(context["section_id"], SectionStatus.IN_SESSION)
    second_enrollment = fixtures.enroll(second_student, context["section_id"])
    assert fixtures.read_class_section(context["section_id"])["seats_taken"] == 2

    fixtures.transition_section(context["section_id"], SectionStatus.CLOSED)

    for enrollment_id in (first_enrollment["id"], second_enrollment["id"]):
        settled = fixtures.read_enrollment(enrollment_id)
        assert settled["status"] == EnrollmentStatus.WITHDRAWN
        assert settled["exit_reason"] == ExitReason.SECTION_CLOSED
        assert settled["withdrawn_at"] is not None
    for student_id in (first_student, second_student):
        assert fixtures.read_student(student_id)["intake_status"] == IntakeStatus.PLACED

    refused = _enroll(first_student, context["section_id"])
    validate_error(refused, ApiErrorId.SECTION_NOT_ACCEPTING_ENROLLMENT, expected_status=409)


def test_05_closing_a_period_freezes_certification_of_a_standing_claim():
    """"Closing freezes the period in every direction: no further claim may be recorded
    against it, no standing claim may be certified or rejected, and no further allocation
    may run."

    Design: Difficulty/cross_entity_state_dependency/outcome_certification_requires_open_funding_period
    """
    context = _setup_period_with_one_certified_and_one_standing_claim()

    closed = fixtures.close_funding_period(context["period_id"])
    assert closed["status"] == FundingPeriodStatus.CLOSED
    assert closed["committed_cents"] == 12500
    assert closed["available_cents"] == 87500

    response = api_client.decide_outcome_certification(
        context["standing_id"],
        factories.outcome_certification_payload(),
        headers=make_state_authority_headers(),
    )
    validate_error(response, ApiErrorId.FUNDING_PERIOD_CLOSED, expected_status=409)

    standing = fixtures.read_outcome(context["standing_id"])
    assert standing["status"] == OutcomeStatus.RECORDED
    assert standing["certified_by_user_id"] is None

    certified = fixtures.read_outcome(context["certified_id"])
    assert certified["status"] == OutcomeStatus.CERTIFIED
    assert certified["allocated_cents"] == 12500
    assert certified["allocation_status"] == AllocationStatus.COMMITTED


def test_06_a_closed_period_accepts_no_new_claims_and_no_further_runs():
    """"A `StateAuthority` moves an `OPEN` period to `CLOSED`, which is terminal and raises
    the period's `version` by one; a second attempt reports `ERR_FUNDING_PERIOD_CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/outcome_certification_requires_open_funding_period
    """
    context = _setup_period_with_one_certified_and_one_standing_claim()
    fixtures.close_funding_period(context["period_id"])

    new_claim = api_client.create_outcome_record(
        factories.create_outcome_record_payload(
            context["second_student_id"],
            context["period_id"],
            measure_type=MeasureType.POSTSECONDARY_ENROLLMENT,
            evidence_ref="NSC-B",
        ),
        headers=make_program_coordinator_headers(),
    )
    validate_error(new_claim, ApiErrorId.FUNDING_PERIOD_CLOSED, expected_status=409)

    # A freshly read version rules out a 412, so the closed-period gate is what answers.
    rerun = api_client.run_allocation(
        context["period_id"],
        factories.allocation_run_payload(
            fixtures.current_funding_period_version(context["period_id"]),
            variant=AllocationVariant.FINAL,
        ),
        headers=make_state_authority_headers(),
    )
    validate_error(rerun, ApiErrorId.FUNDING_PERIOD_CLOSED, expected_status=409)

    period = fixtures.read_funding_period(context["period_id"])
    assert period["allocation_run_count"] == 1
    assert period["committed_cents"] == 12500
    assert (
        len(
            fixtures.list_all(
                api_client.list_outcome_records,
                make_state_authority_headers(),
                funding_period_id=context["period_id"],
            )
        )
        == 2
    )
