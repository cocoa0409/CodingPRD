"""Inclusive thresholds probed one increment either side: the forty-hour post-test
gate, the proctor's daily hour cap, and the funding pool a single cent short.
"""

from __future__ import annotations

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client, factories, fixtures
from test_helpers.assertions import assert_funding_pool_conserved, assert_hours_value
from test_helpers.test_users import (
    make_center_administrator_headers,
    make_registrar_headers,
)
from test_helpers.types import (
    AllocationStatus,
    AllocationVariant,
    MeasureType,
    ProctorCertificationStatus,
    SectionStatus,
    SessionStatus,
    Subtest,
    TestEventPurpose,
    TestEventStatus,
)

THIRTY_DAYS_AFTER_PRE_TEST = "2026-09-02T09:00:00Z"
POST_TEST_AT = "2026-09-02T10:00:00Z"

CAP_DATE = "2026-08-12"
LONG_SITTING = ("2026-08-12T08:00:00Z", "2026-08-12T14:00:00Z")
SECOND_SITTING = ("2026-08-12T14:45:00Z", "2026-08-12T16:45:00Z")
THIRD_SITTING = ("2026-08-12T17:30:00Z", "2026-08-12T18:30:00Z")

EXACT_POOL_CENTS = 12500
SHORT_POOL_CENTS = 12499


def _setup_learner_one_increment_short():
    """The interval gate is satisfied; the ledger stands one quarter-hour short of forty."""
    placed = fixtures.create_placed_student(pre_test_at="2026-08-03T09:00:00Z")
    section = fixtures.create_section(
        status=SectionStatus.OPEN, title="HSE Boundary", seats_total=12, weekly_hours=8.00
    )
    enrollment = fixtures.enroll(placed["student_id"], section["id"])
    fixtures.set_clock(THIRTY_DAYS_AFTER_PRE_TEST)
    for date, hours in (
        ("2026-08-04", 8.00),
        ("2026-08-05", 8.00),
        ("2026-08-06", 8.00),
        ("2026-08-07", 8.00),
        ("2026-08-10", 7.75),
    ):
        fixtures.post_attendance(enrollment["id"], date, hours)
    return {"student_id": placed["student_id"], "enrollment_id": enrollment["id"]}


def _request_post_test(student_id, enrollment_id):
    return api_client.create_test_event(
        factories.create_test_event_payload(
            student_id,
            POST_TEST_AT,
            purpose=TestEventPurpose.POST_TEST,
            enrollment_id=enrollment_id,
        ),
        headers=make_registrar_headers(),
    )


def _setup_three_sittings_on_one_date():
    venue = fixtures.setup_center_with_room_and_proctor(
        seat_capacity=10,
        turnaround_buffer_minutes=45,
        daily_hour_cap=8.00,
        certification_expires_at="2027-01-01T00:00:00Z",
    )
    subtests = (Subtest.MATH, Subtest.RLA, Subtest.SCIENCE)
    windows = (LONG_SITTING, SECOND_SITTING, THIRD_SITTING)
    venue["sessions"] = [
        fixtures.create_session(
            venue["center_id"],
            venue["room_id"],
            starts_at,
            ends_at,
            subtest=subtest,
            requested_seats=6,
        )
        for subtest, (starts_at, ends_at) in zip(subtests, windows)
    ]
    return venue


def _setup_period_with_one_certified_line(total_cents, evidence_ref):
    period = fixtures.create_funding_period(
        rate_cents_per_weight=10000, total_cents=total_cents
    )
    student = fixtures.create_student()
    outcome = fixtures.certified_outcome(
        student["id"],
        period["id"],
        measure_type=MeasureType.EMPLOYMENT_Q2,
        evidence_ref=evidence_ref,
    )
    return {"period_id": period["id"], "outcome_id": outcome["id"]}


def test_01_one_quarter_hour_short_of_forty_is_refused():
    """"**Post-testing hours** (409). The enrollment's `posted_hours` must be at least
    forty hours — otherwise `ERR_POST_TEST_HOURS_NOT_MET`."

    Design: Difficulty/boundary_precision_check/post_test_hours_exactly_forty_allowed
    """
    context = _setup_learner_one_increment_short()

    enrollment = fixtures.read_enrollment(context["enrollment_id"])
    assert_hours_value(enrollment["posted_hours"], 39.75)
    assert enrollment["post_test_eligible"] is False

    response = _request_post_test(context["student_id"], context["enrollment_id"])
    validate_error(response, ApiErrorId.POST_TEST_HOURS_NOT_MET, expected_status=409)


def test_02_exactly_forty_hours_clears_the_inclusive_gate():
    """"The stored `post_test_eligible` flag on an enrollment tracks the hour gate alone:
    it is true exactly when `posted_hours` has reached at least forty hours, and false
    otherwise." and "Attendance is posted in quarter-hour increments, so the hour
    aggregates are always exact multiples of 0.25 and no rounding residue accumulates."

    Design: Difficulty/boundary_precision_check/post_test_hours_exactly_forty_allowed
    """
    context = _setup_learner_one_increment_short()

    fixtures.post_attendance(context["enrollment_id"], "2026-08-11", 0.25)
    enrollment = fixtures.read_enrollment(context["enrollment_id"])
    assert_hours_value(enrollment["posted_hours"], 40.00)
    assert enrollment["post_test_eligible"] is True

    accepted = validate_success(
        _request_post_test(context["student_id"], context["enrollment_id"]),
        expected_status=201,
    )
    assert accepted["status"] == TestEventStatus.SCHEDULED

    student = fixtures.read_student(context["student_id"])
    assert_hours_value(student["total_instructional_hours"], 40.00)


def test_03_a_six_hour_sitting_is_accepted_and_reports_its_span_to_two_decimals():
    """"Its `duration_hours` is the span from `starts_at` to `ends_at` expressed in hours
    to two decimal places, rounded half up."

    Design: Difficulty/boundary_precision_check/proctor_daily_cap_exactly_eight_hours_allowed
    """
    venue = _setup_three_sittings_on_one_date()

    assigned = fixtures.assign_session_proctor(
        venue["center_id"], venue["sessions"][0]["id"], venue["proctor_id"]
    )
    assert assigned["status"] == SessionStatus.SCHEDULED
    assert float(assigned["duration_hours"]) == 6.00

    proctor = fixtures.read_proctor(venue["proctor_id"])
    assert proctor["certification_status"] == ProctorCertificationStatus.CERTIFIED
    assert proctor["assigned_session_count"] == 1


def test_04_a_projection_landing_exactly_on_the_cap_is_allowed():
    """"When the projected total is strictly greater than the proctor's `daily_hour_cap`
    the assignment is refused with `ERR_PROCTOR_DAILY_CAP_EXCEEDED`; a projection landing
    exactly on the cap is allowed."

    Design: Difficulty/boundary_precision_check/proctor_daily_cap_exactly_eight_hours_allowed
    """
    venue = _setup_three_sittings_on_one_date()

    fixtures.assign_session_proctor(
        venue["center_id"], venue["sessions"][0]["id"], venue["proctor_id"]
    )
    second = fixtures.assign_session_proctor(
        venue["center_id"], venue["sessions"][1]["id"], venue["proctor_id"]
    )
    assert second["status"] == SessionStatus.SCHEDULED
    assert float(second["duration_hours"]) == 2.00
    # 6.00 already scheduled plus 2.00 projected is exactly the 8.00 cap.
    assert fixtures.read_proctor(venue["proctor_id"])["assigned_session_count"] == 2


def test_05_one_hour_past_the_cap_is_refused_and_leaves_the_sitting_in_draft():
    """"`DRAFT` and `CANCELLED` sittings are excluded from the sum." and "a proctor with the
    default cap can cover eight hours of sittings on one date and not a minute more."

    Design: Difficulty/boundary_precision_check/proctor_daily_cap_exactly_eight_hours_allowed
    """
    venue = _setup_three_sittings_on_one_date()

    fixtures.assign_session_proctor(
        venue["center_id"], venue["sessions"][0]["id"], venue["proctor_id"]
    )
    fixtures.assign_session_proctor(
        venue["center_id"], venue["sessions"][1]["id"], venue["proctor_id"]
    )

    third_id = venue["sessions"][2]["id"]
    response = api_client.assign_proctor(
        third_id,
        factories.proctor_assignment_payload(venue["proctor_id"]),
        headers=make_center_administrator_headers(venue["center_id"]),
    )
    validate_error(response, ApiErrorId.PROCTOR_DAILY_CAP_EXCEEDED, expected_status=409)

    refused = fixtures.read_session(third_id)
    assert refused["status"] == SessionStatus.DRAFT
    assert refused["proctor_id"] is None
    assert fixtures.read_proctor(venue["proctor_id"])["assigned_session_count"] == 2
    assert CAP_DATE in refused["starts_at"]


def test_06_a_pool_of_exactly_the_line_amount_commits_in_full():
    """"When that line amount is no greater than what remains in the running pool, the
    claim is committed: its `allocated_cents` becomes the line amount, its
    `allocation_status` becomes `COMMITTED`, and the running pool falls by the line
    amount."

    Design: Difficulty/boundary_precision_check/allocation_deferred_when_line_exceeds_remaining_by_one_cent
    """
    context = _setup_period_with_one_certified_line(EXACT_POOL_CENTS, "WAGE-EXACT")

    period = fixtures.run_allocation(context["period_id"], variant=AllocationVariant.FINAL)
    assert_funding_pool_conserved(period)
    assert period["committed_cents"] == 12500
    assert period["available_cents"] == 0

    line = fixtures.read_outcome(context["outcome_id"])
    assert line["allocated_cents"] == 12500
    assert line["allocation_status"] == AllocationStatus.COMMITTED


def test_07_a_pool_one_cent_short_defers_the_whole_line():
    """"When the line amount exceeds what remains, the claim is deferred: its
    `allocated_cents` stays 0 and its `allocation_status` becomes `DEFERRED`. There is no
    partial allocation — a claim is paid in full or not at all"

    Design: Difficulty/boundary_precision_check/allocation_deferred_when_line_exceeds_remaining_by_one_cent
    """
    context = _setup_period_with_one_certified_line(SHORT_POOL_CENTS, "WAGE-SHORT")

    preview = fixtures.read_allocation_preview(
        context["period_id"], variant=AllocationVariant.FINAL
    )
    assert preview["line_count"] == 1
    assert preview["deferred_line_count"] == 1
    assert preview["projected_committed_cents"] == 0
    assert preview["projected_available_cents"] == 12499

    period = fixtures.run_allocation(context["period_id"], variant=AllocationVariant.FINAL)
    assert_funding_pool_conserved(period)
    assert period["committed_cents"] == 0
    assert period["available_cents"] == 12499

    line = fixtures.read_outcome(context["outcome_id"])
    assert line["allocated_cents"] == 0
    assert line["allocation_status"] == AllocationStatus.DEFERRED
