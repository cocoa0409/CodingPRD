"""Two ceilings tested from both sides of their boundary: the weekly child-labor
hour cap, which accepts a week landing exactly on 18.00 hours and refuses one
hundredth more, and the learning-objective minimum, probed at zero.
"""

from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    api_client,
    create_timesheet_entry_payload,
    draft_plan_with_objectives,
    log_shifts,
    make_employer_supervisor_headers,
    read_placement,
    read_plan,
    read_student,
    set_clock,
    setup_active_placement,
    setup_proposed_placement,
    validate_error,
)

MAPLE_LANE = {
    "legal_name": "Maple Lane Library Services",
    "naics_code": "519120",
    "industry_sector": "PUBLIC_ADMINISTRATION",
}
JUNO_PARK = {
    "full_name": "Juno Park",
    "birth_date": "2011-04-20",
    "grade_level": 10,
    "gpa": 2.50,
    "attendance_rate": 0.95,
    "student_learner_certificate": False,
}
CINDER_PEAK = {
    "legal_name": "Cinder Peak Outfitters",
    "naics_code": "451110",
    "industry_sector": "HOSPITALITY",
}
ZARA_LINDQVIST = {"full_name": "Zara Lindqvist", "birth_date": "2009-12-01"}

# Six instructional-day shifts of 3.00 hours each inside the week that starts on
# Sunday 2026-09-06, summing to exactly the 18.00-hour weekly ceiling.
WEEK_OF_THREE_HOUR_SHIFTS = [
    ("2026-09-07", "15:00", "18:00"),
    ("2026-09-08", "15:00", "18:00"),
    ("2026-09-09", "15:00", "18:00"),
    ("2026-09-10", "15:00", "18:00"),
    ("2026-09-11", "15:00", "18:00"),
    ("2026-09-12", "15:00", "18:00"),
]


def _minor_14_15_placement_sitting_exactly_on_the_weekly_cap():
    scenario = setup_active_placement(
        clock="2026-09-06T08:00:00Z",
        course_code="LIB-101",
        credit_hours_target=60.00,
        partner_overrides=MAPLE_LANE,
        student_overrides=JUNO_PARK,
        permit_class="MINOR_14_15",
        placement_overrides={
            "pay_classification": "PAID",
            "hourly_wage_cents": 1500,
            "stipend_total_cents": 0,
            "scheduled_weekly_hours": 18.00,
            "start_on": "2026-09-06",
            "end_on": "2026-12-18",
            "credit_target_credits": 0.50,
            "credit_award_mode": "HOURS_BASED",
            "required_evaluation_cycles": 1,
            "transportation_mode": "PUBLIC_TRANSIT",
            "commute_round_trip_miles": 0.00,
        },
    )
    set_clock("2026-09-14T08:00:00Z")
    logged = log_shifts(scenario, WEEK_OF_THREE_HOUR_SHIFTS)
    return scenario, logged


def _plan_drafted_with_no_objectives_at_all():
    scenario = setup_proposed_placement(
        clock="2026-09-07T08:00:00Z",
        partner_overrides=CINDER_PEAK,
        student_overrides=ZARA_LINDQVIST,
        permit_class="MINOR_16_17",
        placement_overrides={
            "pay_classification": "PAID",
            "hourly_wage_cents": 1500,
            "stipend_total_cents": 0,
            "scheduled_weekly_hours": 12.00,
            "start_on": "2026-09-07",
            "end_on": "2026-12-18",
            "credit_target_credits": 0.50,
            "credit_award_mode": "HOURS_BASED",
            "required_evaluation_cycles": 1,
            "transportation_mode": "DISTRICT_BUS",
            "commute_round_trip_miles": 0.00,
        },
    )
    draft_plan_with_objectives(
        scenario, course_code="MKT-105", credit_hours_target=60.00, objective_count=0
    )
    return scenario


class TestWeeklyHourCapBoundary:
    def test_a_week_landing_exactly_on_eighteen_hours_is_accepted(self):
        """For the `MINOR_14_15` band, work may not start before 07:00 and may not end
        after 19:00; the daily ceiling is 3.00 hours on an instructional day and 8.00 hours
        otherwise; the weekly ceiling is 18.00 hours on an instructional day and 40.00
        hours otherwise. Both cap comparisons are strictly greater-than, so a candidate
        that lands exactly on the ceiling is accepted and one hundredth of an hour more is
        not.

        Design: Difficulty/boundary_precision_check/weekly_hour_cap_accepts_exactly_18_00_then_rejects_18_25
        """
        scenario, logged = _minor_14_15_placement_sitting_exactly_on_the_weekly_cap()

        assert len(logged) == 6
        assert all(entry["status"] == "LOGGED" for entry in logged)
        assert float(logged[-1]["hours_worked"]) == 3.00

        placement = read_placement(scenario.placement_id)
        assert float(placement["total_verified_hours"]) == 18.00
        assert float(read_student(scenario.student_id)["ytd_wbl_hours"]) == 18.00

    def test_one_more_quarter_hour_in_the_same_week_is_refused(self):
        """Third the **weekly ledger**: identify the Sunday-start week containing the
        `work_date` — the week runs from the Sunday on or before `work_date` through the
        following six days, so Sunday through Saturday — add up `hours_worked` over every
        `LOGGED` entry of the same student, across all their placements, whose `work_date`
        falls in that seven-day span, add the candidate's computed hours, select the weekly
        ceiling by the candidate entry's `is_school_day` flag, and refuse with
        `ERR_WEEKLY_HOUR_CAP_EXCEEDED` if the result is strictly greater than that ceiling.
        Both cap comparisons are strictly greater-than, so a candidate that lands exactly on
        the ceiling is accepted and one hundredth of an hour more is not.

        Design: Difficulty/boundary_precision_check/weekly_hour_cap_accepts_exactly_18_00_then_rejects_18_25
        """
        scenario, _logged = _minor_14_15_placement_sitting_exactly_on_the_weekly_cap()

        response = api_client.create_timesheet_entry(
            create_timesheet_entry_payload(
                scenario.placement_id, "2026-09-06", "15:00", "15:15"
            ),
            make_employer_supervisor_headers(scenario.supervisor_id),
        )

        validate_error(response, ApiErrorId.ERR_WEEKLY_HOUR_CAP_EXCEEDED.value)
        assert response.status_code == 422

        placement = read_placement(scenario.placement_id)
        assert float(placement["total_verified_hours"]) == 18.00


class TestLearningObjectiveMinimumBoundary:
    def test_submitting_a_plan_with_zero_objectives_is_refused(self):
        """Submission enforces two counting rules with distinct error codes:
        `objective_count` must be at least 3, or the submission is refused with
        `ERR_LEARNING_OBJECTIVES_INSUFFICIENT`, and `aligned_objective_count` must also be
        at least 3 — at least three objectives whose `aligned_course_code` matches the
        plan's `course_code` — or it is refused with `ERR_CREDIT_ALIGNMENT_MISSING`.

        Design: Difficulty/boundary_precision_check/plan_submit_with_zero_objectives_rejected_at_minimum_boundary
        """
        scenario = _plan_drafted_with_no_objectives_at_all()

        response = api_client.submit_training_plan(scenario.plan_id, {}, COORDINATOR)

        validate_error(response, ApiErrorId.ERR_LEARNING_OBJECTIVES_INSUFFICIENT.value)
        assert response.status_code == 422

    def test_the_refused_submission_leaves_the_plan_in_draft(self):
        """A new plan starts at `status` of `DRAFT` with `revision_round` of 0,
        `objective_count` of 0 and `aligned_objective_count` of 0, and with `submitted_at`,
        `approved_by_user_id`, `approved_at` and `change_request_note` all null.
        `lifecycle_status` starts at `PROPOSED` and tracks the placement as an assignment.

        Design: Difficulty/boundary_precision_check/plan_submit_with_zero_objectives_rejected_at_minimum_boundary
        """
        scenario = _plan_drafted_with_no_objectives_at_all()

        api_client.submit_training_plan(scenario.plan_id, {}, COORDINATOR)

        plan = read_plan(scenario.plan_id)
        assert plan["status"] == "DRAFT"
        assert plan["objective_count"] == 0
        assert read_placement(scenario.placement_id)["lifecycle_status"] == "PROPOSED"
