"""Measurable goals and progress tracking: the divergent provisional vs cumulative
progress measures, the pinned round-per-report-then-average order, the automatic
bubble-up to MET, range validation, and progress-report immutability
(PRD §3.6, §3.7).
"""

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_case_manager_headers,
    create_goal_payload,
    create_progress_report_payload,
    set_clock,
    make_goal_on_eligible_student,
    setup_goal_with_reports,
    record_progress_report,
    get_goal,
)

CM = make_case_manager_headers("cm_1")


class TestProvisionalVsCumulative:
    def test_provisional_and_cumulative_diverge(self, api):
        """PRD §3.7: "The **provisional** measure, `latest_progress_pct`, reflects only the single most recent progress report for the goal."
        PRD §3.7: "The **cumulative** measure, `cumulative_progress_pct`, averages across all of the goal's progress reports regardless of period, and its rounding order is pinned: round each report first, then average."

        READING goal (baseline 0, target 3) with reports measured 0/2/2:
        provisional = (2-0)/(3-0)*100 = 66.67; cumulative = avg(0, 66.67, 66.67)
        rounded per-report-then-averaged = 44.45.

        Design: Difficulty/dual_variant_calc/goal_progress_provisional_vs_cumulative_diverge
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, _iep, goal_id = setup_goal_with_reports(
            [(1, 0), (2, 2)],
            goal_overrides={"domain": "READING", "baseline_value": 0, "target_value": 3},
            iep_overrides={"school_day_minutes": 360},
        )
        record_progress_report(goal_id, 3, 2)
        goal = get_goal(goal_id)
        assert goal["latest_progress_pct"] == 66.67, goal["latest_progress_pct"]
        assert goal["cumulative_progress_pct"] == 44.45, goal["cumulative_progress_pct"]

    def test_provisional_uses_only_most_recent_report(self, api):
        """PRD §3.7: 'The "most recent" report is the one with the greatest `reporting_period`'
        PRD §3.7: "For that one report, the progress is the measured value minus the baseline, divided by the target minus the baseline, multiplied by 100; the result is clamped to lie between 0 and 100 and then rounded half-up to two decimal places."

        With reports 0/2/2 on a (0,3) goal, the provisional figure reflects only the
        period-3 report (measured 2) → 66.67, ignoring the period-1 zero.

        Design: Difficulty/dual_variant_calc/goal_progress_provisional_vs_cumulative_diverge
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, _iep, goal_id = setup_goal_with_reports(
            [(1, 0), (2, 2), (3, 2)],
            goal_overrides={"domain": "READING", "baseline_value": 0, "target_value": 3},
        )
        goal = get_goal(goal_id)
        assert goal["latest_progress_pct"] == 66.67, goal["latest_progress_pct"]


class TestCumulativeRoundingOrder:
    def test_cumulative_round_per_report_then_average(self, api):
        """PRD §3.7: "for each progress report on the goal the system computes that report's progress ... clamps it between 0 and 100, and rounds that per-report figure half-up to two decimal places. It then sums those rounded per-report figures, divides by the number of reports, and rounds the average half-up to two decimal places. This is round-per-report-then-average, not average-then-round, and the two can differ."

        Reports 0/2/2 on (0,3): per-report 0.00, 66.67, 66.67; average 133.34/3 =
        44.4466.. → 44.45 (not 44.44 that average-then-round would give).

        Design: Difficulty/combinatorial_formula/goal_cumulative_rounding_order_pinned
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, _iep, goal_id = setup_goal_with_reports(
            [(1, 0), (2, 2)],
            goal_overrides={"domain": "READING", "baseline_value": 0, "target_value": 3},
        )
        record_progress_report(goal_id, 3, 2)
        goal = get_goal(goal_id)
        assert goal["cumulative_progress_pct"] == 44.45, goal["cumulative_progress_pct"]

    def test_cumulative_pinned_order_not_44_44(self, api):
        """PRD §3.7: "This is round-per-report-then-average, not average-then-round, and the two can differ."

        The pinned order yields exactly 44.45; the forbidden average-then-round path
        (133.3333../3 = 44.4444.. → 44.44) is explicitly excluded.

        Design: Difficulty/combinatorial_formula/goal_cumulative_rounding_order_pinned
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, _iep, goal_id = setup_goal_with_reports(
            [(1, 0), (2, 2), (3, 2)],
            goal_overrides={"domain": "READING", "baseline_value": 0, "target_value": 3},
        )
        goal = get_goal(goal_id)
        assert goal["cumulative_progress_pct"] == 44.45, goal["cumulative_progress_pct"]
        assert goal["cumulative_progress_pct"] != 44.44


class TestGoalAutoMet:
    def test_goal_bubbles_to_met_at_cumulative_100(self, api):
        """PRD §3.6: "when, after a newly recorded progress report, the goal's cumulative progress percentage is at least 100.0, the system bubbles the goal `ACTIVE → MET` (incrementing its `version`)."
        PRD §3.7: "When the resulting cumulative percentage is at least 100.0, the goal bubbles up from `ACTIVE` to `MET` as described above."

        A single report measured 50 on a (0,50) goal makes cumulative 100.00 → MET.

        Design: Corner/state_machines/goal_auto_transitions_to_met_on_cumulative_100
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, _iep, goal = make_goal_on_eligible_student(
            goal_overrides={"domain": "READING", "baseline_value": 0, "target_value": 50},
        )
        record_progress_report(goal["id"], 1, 50)
        fetched = get_goal(goal["id"])
        assert fetched["cumulative_progress_pct"] == 100.0, fetched["cumulative_progress_pct"]
        assert fetched["status"] == "MET", fetched["status"]


class TestGoalValidation:
    def test_create_goal_target_not_above_baseline_rejected(self, api):
        """PRD §3.6: "the `target_value` defines mastery and must be strictly greater than the `baseline_value`. A target that is not strictly above the baseline, or a baseline below zero, is rejected as out of range with `ERR_INVALID_RANGE`."

        baseline_value=50 and target_value=50 (equal, not strictly greater) → 422.

        Design: Corner/entities/create_goal_invalid_range_target_not_above_baseline
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, iep = _draft_iep_for("Val Reed", "2014-02-02")
        validate_error(
            api.create_goal(
                create_goal_payload(iep["id"], domain="MATH", baseline_value=50, target_value=50), CM
            ),
            ApiErrorId.ERR_INVALID_RANGE.value,
        )

    def test_progress_report_period_out_of_range_rejected(self, api):
        """PRD §3.6: "The `reporting_period` is the ordinal quarter within the program year and must be an integer from 1 through 4 inclusive; a value outside that range is rejected as out of range."

        reporting_period=5 → ERR_INVALID_RANGE (422).

        Design: Corner/validations/progress_report_period_out_of_range
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, _iep, goal = make_goal_on_eligible_student(
            student_overrides={"full_name": "Bo Vane", "date_of_birth": "2014-07-07"},
            goal_overrides={"domain": "READING", "baseline_value": 0, "target_value": 100},
        )
        validate_error(
            api.create_progress_report(
                create_progress_report_payload(goal["id"], reporting_period=5, measured_value=40), CM
            ),
            ApiErrorId.ERR_INVALID_RANGE.value,
        )


class TestProgressReportImmutability:
    def test_progress_report_has_no_version_field(self, api):
        """PRD §2.4: "The `ProgressReport` resource is the single exception: it is immutable after creation and therefore carries only `id` and `created_at`. A progress report has neither an `updated_at` field nor a `version` field; do not emit those fields for it."

        Design: Corner/entities/progress_report_is_immutable_no_version_field
        """
        set_clock("2026-03-01T09:00:00Z")
        _student, _iep, goal = make_goal_on_eligible_student(
            student_overrides={"full_name": "Lia Cruz", "date_of_birth": "2014-03-03"},
            goal_overrides={"domain": "READING", "baseline_value": 0, "target_value": 100},
        )
        pr = validate_success(
            api.create_progress_report(
                create_progress_report_payload(goal["id"], reporting_period=1, measured_value=25), CM
            ),
            201,
        )
        assert pr.get("id"), "progress report must carry an id"
        assert "version" not in pr, "ProgressReport must NOT carry a version field"
        assert "updated_at" not in pr, "ProgressReport must NOT carry an updated_at field"


def _draft_iep_for(name, dob):
    from test_helpers import make_draft_iep_for_eligible_student
    return make_draft_iep_for_eligible_student(
        student_overrides={"full_name": name, "date_of_birth": dob, "grade_level": 6}
    )
