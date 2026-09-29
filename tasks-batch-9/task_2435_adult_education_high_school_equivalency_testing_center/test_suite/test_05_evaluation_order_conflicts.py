"""Requests carrying two genuine defects at once, where the evaluation order in the
request pipeline decides which one is reported.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.test_users import (
    make_instructor_headers,
    make_program_coordinator_headers,
    make_proctor_headers,
    make_registrar_headers,
)
from test_helpers.types import (
    IdentityStatus,
    RegistrationStatus,
    SectionStatus,
    SessionStatus,
    Subtest,
    TestEventPurpose,
    TestEventStatus,
)

FISCAL_SITTING_STARTS = "2026-08-10T09:00:00Z"
FISCAL_SITTING_ENDS = "2026-08-10T11:00:00Z"

SEATING_SITTING_STARTS = "2026-08-05T09:00:00Z"
SEATING_SITTING_ENDS = "2026-08-05T11:00:00Z"
AFTER_SEATING_WINDOW = "2026-08-05T11:30:00Z"

EARLY_POST_TEST_AT = "2026-08-06T09:00:00Z"
THIRTIETH_DAY = "2026-09-02T09:00:00Z"
LATE_POST_TEST_AT = "2026-09-02T10:00:00Z"


def _setup_unfunded_candidate():
    """A learner who cannot cover a 3000-cent MATH seat, on a SCHEDULED sitting."""
    venue = fixtures.setup_scheduled_session(
        starts_at=FISCAL_SITTING_STARTS,
        ends_at=FISCAL_SITTING_ENDS,
        subtest=Subtest.MATH,
        requested_seats=4,
        seat_capacity=8,
        turnaround_buffer_minutes=45,
        daily_hour_cap=8.00,
    )
    placed = fixtures.create_placed_student(pre_test_at="2026-08-02T09:00:00Z")
    student = fixtures.read_student(placed["student_id"])
    assert student["self_pay_authorized"] is False
    assert student["voucher_balance_cents"] == 0
    venue["student_id"] = placed["student_id"]
    return venue


def _register(student_id, session_id, version):
    return api_client.create_exam_registration(
        factories.create_exam_registration_payload(student_id, session_id, version),
        headers=make_registrar_headers(),
    )


def _setup_unverified_candidate_after_the_window():
    context = fixtures.setup_registered_candidate(
        starts_at=SEATING_SITTING_STARTS,
        ends_at=SEATING_SITTING_ENDS,
        subtest=Subtest.MATH,
        self_pay_authorized=True,
        requested_seats=4,
        seat_capacity=8,
        turnaround_buffer_minutes=45,
        daily_hour_cap=8.00,
    )
    fixtures.ensure_clock(AFTER_SEATING_WINDOW)
    return context


def _setup_learner_short_on_both_gates():
    """16.00 posted hours and three elapsed days since the pre-test."""
    placed = fixtures.create_placed_student(pre_test_at="2026-08-03T09:00:00Z")
    section = fixtures.create_section(
        status=SectionStatus.OPEN, title="HSE Bridge", seats_total=12, weekly_hours=8.00
    )
    enrollment = fixtures.enroll(placed["student_id"], section["id"])
    fixtures.post_attendance(enrollment["id"], "2026-08-04", 8.00)
    fixtures.post_attendance(enrollment["id"], "2026-08-05", 8.00)
    return {"student_id": placed["student_id"], "enrollment_id": enrollment["id"]}


def _post_hours_without_moving_the_clock(enrollment_id, attendance_date, hours):
    """Post hours for a date the clock has already reached, leaving the clock alone."""
    return validate_success(
        api_client.create_attendance_entry(
            enrollment_id,
            factories.create_attendance_entry_payload(attendance_date, hours),
            headers=make_instructor_headers(),
        ),
        expected_status=201,
    )


def _schedule_post_test(student_id, enrollment_id, scheduled_for):
    return api_client.create_test_event(
        factories.create_test_event_payload(
            student_id,
            scheduled_for,
            purpose=TestEventPurpose.POST_TEST,
            enrollment_id=enrollment_id,
        ),
        headers=make_registrar_headers(),
    )


def test_01_the_fiscal_gate_genuinely_refuses_the_unfunded_seat():
    """"The fiscal gate is the last one and it depends on `self_pay_authorized`. When that
    flag is `false`, the learner may not be left owing anything: their
    `voucher_balance_cents` must cover the whole post-discount net, so that the computed
    `fee_due_cents` would be zero. If it would not, the registration is refused with
    `ERR_VOUCHER_INSUFFICIENT` (402) and no ledger movement is persisted."

    Design: Difficulty/priority_pair_validation_conflict/center_suspended_state_beats_voucher_insufficient_fiscal
    """
    context = _setup_unfunded_candidate()

    response = _register(
        context["student_id"],
        context["session_id"],
        fixtures.current_exam_session_version(context["session_id"]),
    )
    validate_error(response, ApiErrorId.VOUCHER_INSUFFICIENT, expected_status=402)

    student = fixtures.read_student(context["student_id"])
    assert student["voucher_balance_cents"] == 0
    assert student["exam_fee_owed_cents"] == 0


def test_02_the_suspension_state_gate_reports_ahead_of_the_fiscal_gate():
    """"**Centre authorisation** (409). The testing centre owning the addressed room or
    session must be `PROVISIONAL` or `FULL_AUTHORIZED`. A centre still `APPLIED` or
    already `WITHDRAWN` reports `ERR_CENTER_NOT_AUTHORIZED`; a `SUSPENDED` centre reports
    `ERR_CENTER_SUSPENDED` — the two are deliberately distinguishable." and "This band is
    last: the fee is only assessed once every eligibility, capacity and scheduling
    question has been answered."

    Design: Difficulty/priority_pair_validation_conflict/center_suspended_state_beats_voucher_insufficient_fiscal
    """
    context = _setup_unfunded_candidate()

    _register(
        context["student_id"],
        context["session_id"],
        fixtures.current_exam_session_version(context["session_id"]),
    )
    fixtures.suspend_center(context["center_id"], "Security breach")

    # Re-read the version so the stale-view guard cannot pre-empt the comparison.
    fresh_version = fixtures.current_exam_session_version(context["session_id"])
    response = _register(context["student_id"], context["session_id"], fresh_version)
    validate_error(response, ApiErrorId.CENTER_SUSPENDED, expected_status=409)

    student = fixtures.read_student(context["student_id"])
    assert student["voucher_balance_cents"] == 0
    assert student["exam_fee_owed_cents"] == 0
    assert (
        fixtures.list_all(
            api_client.list_exam_registrations,
            make_registrar_headers(),
            student_id=context["student_id"],
        )
        == []
    )


def test_03_the_identity_gate_reports_ahead_of_the_closed_seating_window():
    """"**Identity before seating** (409). Check-in requires `identity_status` to be
    `VERIFIED`; both `UNVERIFIED` and `ID_REJECTED` report
    `ERR_IDENTITY_NOT_VERIFIED`. Guards check-in only."

    Design: Difficulty/priority_pair_validation_conflict/identity_safety_beats_check_in_window_temporal
    """
    context = _setup_unverified_candidate_after_the_window()

    response = api_client.check_in(
        context["registration_id"], headers=make_proctor_headers(context["proctor_id"])
    )
    validate_error(response, ApiErrorId.IDENTITY_NOT_VERIFIED, expected_status=409)

    registration = fixtures.read_registration(context["registration_id"])
    assert registration["registration_status"] == RegistrationStatus.REGISTERED
    assert fixtures.read_session(context["session_id"])["status"] == SessionStatus.SCHEDULED


def test_04_the_temporal_gate_surfaces_once_identity_is_settled():
    """"Timing is enforced as a **seating window** that opens sixty minutes before the
    sitting's `starts_at` and closes at its `ends_at`, with the opening instant included
    and the closing instant excluded. A check-in outside that window — an hour and one
    minute early, or at the exact instant the sitting ends — is refused with
    `ERR_CHECK_IN_WINDOW_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/identity_safety_beats_check_in_window_temporal
    """
    context = _setup_unverified_candidate_after_the_window()

    # Identity verification carries no temporal gate of its own.
    verified = fixtures.verify_candidate_identity(
        context["registration_id"], context["proctor_id"]
    )
    assert verified["identity_status"] == IdentityStatus.VERIFIED

    response = api_client.check_in(
        context["registration_id"], headers=make_proctor_headers(context["proctor_id"])
    )
    validate_error(response, ApiErrorId.CHECK_IN_WINDOW_CLOSED, expected_status=409)

    registration = fixtures.read_registration(context["registration_id"])
    assert registration["registration_status"] == RegistrationStatus.REGISTERED
    assert registration["checked_in_at"] is None
    assert fixtures.read_session(context["session_id"])["status"] == SessionStatus.SCHEDULED


def test_05_the_interval_gate_reports_ahead_of_the_hour_gate():
    """"Of the two, the interval gate is evaluated first, so a learner who is short on
    both hours and days is told `ERR_POST_TEST_INTERVAL_NOT_MET`; a learner who has
    waited long enough but has banked too few hours is told
    `ERR_POST_TEST_HOURS_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/post_test_interval_temporal_beats_hours_constraint
    """
    context = _setup_learner_short_on_both_gates()

    response = _schedule_post_test(
        context["student_id"], context["enrollment_id"], EARLY_POST_TEST_AT
    )
    validate_error(response, ApiErrorId.POST_TEST_INTERVAL_NOT_MET, expected_status=409)

    enrollment = fixtures.read_enrollment(context["enrollment_id"])
    assert float(enrollment["posted_hours"]) == 16.00
    assert enrollment["post_test_eligible"] is False

    # The rejected attempt left no test event behind.
    events = fixtures.list_all(
        api_client.list_test_events,
        make_program_coordinator_headers(),
        student_id=context["student_id"],
    )
    assert [event["purpose"] for event in events] == [TestEventPurpose.PRE_TEST]


def test_06_the_hour_gate_surfaces_once_thirty_whole_days_have_passed():
    """"The stored `post_test_eligible` flag on an enrollment tracks the hour gate alone:
    it is true exactly when `posted_hours` has reached at least forty hours, and false
    otherwise." and "at least thirty whole UTC days must separate the learner's earliest
    scored pre-test's `test_date` from the logical clock's current instant, counting
    whole days and discarding any partial day, with the thirtieth day itself
    sufficient."

    Design: Difficulty/priority_pair_validation_conflict/post_test_interval_temporal_beats_hours_constraint
    """
    context = _setup_learner_short_on_both_gates()

    fixtures.set_clock(THIRTIETH_DAY)
    response = _schedule_post_test(
        context["student_id"], context["enrollment_id"], LATE_POST_TEST_AT
    )
    validate_error(response, ApiErrorId.POST_TEST_HOURS_NOT_MET, expected_status=409)

    for date in ("2026-08-31", "2026-09-01", "2026-09-02"):
        _post_hours_without_moving_the_clock(context["enrollment_id"], date, 8.00)
    enrollment = fixtures.read_enrollment(context["enrollment_id"])
    assert float(enrollment["posted_hours"]) == 40.00
    assert enrollment["post_test_eligible"] is True

    accepted = validate_success(
        _schedule_post_test(
            context["student_id"], context["enrollment_id"], LATE_POST_TEST_AT
        ),
        expected_status=201,
    )
    assert accepted["status"] == TestEventStatus.SCHEDULED
    assert accepted["purpose"] == TestEventPurpose.POST_TEST
    assert accepted["test_date"] is None
    assert accepted["efl_level"] is None

    events = fixtures.list_all(
        api_client.list_test_events,
        make_program_coordinator_headers(),
        student_id=context["student_id"],
    )
    assert len(events) == 2
