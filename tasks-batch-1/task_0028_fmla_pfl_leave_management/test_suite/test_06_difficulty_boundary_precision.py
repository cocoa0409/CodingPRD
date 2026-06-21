"""Difficulty Rule 6 — boundary_precision_check.

Numeric-threshold boundaries: 1250-hour eligibility threshold (X-1, X), and
the cumulative 480-hour FMLA quota flipping job_restoration_protected.
"""
from test_helpers import (
    ApiErrorId,
    create_employee,
    create_employer,
    evaluate_eligibility,
    get_case,
    record_interval,
    seed_historic_interval,
    set_clock,
    setup_approved_case,
    submit_case,
    TEST_USERS,
    validate_error,
)


class TestHoursThresholdAt1250:
    """PRD §3.3: hours_worked_trailing_12mo >= 1250 passes; < 1250 fails."""

    def test_employee_with_exactly_1250_hours_advances_to_certification_pending(self, api):
        """PRD §3.3: "The second threshold is hours worked: the employee's `hours_worked_trailing_12mo` must be at least 1250."
        PRD §3.3: "The case advances to `CERTIFICATION_PENDING` only when both thresholds hold; otherwise the case is moved straight to `DENIED`."

        Design: Difficulty/boundary_precision_check/hours_threshold_exactly_1250_passes_1249_fails
        """
        employer = create_employer(state_code="FED")
        emp = create_employee(
            employer["id"],
            hire_date="2024-01-01T00:00:00.000Z",
            hours_worked_trailing_12mo=1250,  # exactly at threshold
            home_state_code="FED",
        )
        set_clock("2026-05-01T00:00:00.000Z")
        case = submit_case(
            emp["id"],
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        case_after = evaluate_eligibility(case["id"])
        assert case_after["status"] == "CERTIFICATION_PENDING", (
            f"1250 hours satisfies 'at least 1250'; got status {case_after['status']!r}"
        )
        assert case_after["hours_at_request"] == 1250

    def test_employee_with_1249_hours_returns_ineligible(self, api):
        """PRD §3.3: "The second threshold is hours worked: the employee's `hours_worked_trailing_12mo` must be at least 1250."
        PRD §3.3: "The threshold-failure branch returns `ERR_INELIGIBLE` to the caller when the call was driven against an employee who fails one or both checks at the moment of evaluation."

        Design: Difficulty/boundary_precision_check/hours_threshold_exactly_1250_passes_1249_fails
        """
        employer = create_employer(state_code="FED")
        emp = create_employee(
            employer["id"],
            hire_date="2024-01-01T00:00:00.000Z",
            hours_worked_trailing_12mo=1249,  # 1 under threshold
            home_state_code="FED",
        )
        set_clock("2026-05-01T00:00:00.000Z")
        case = submit_case(
            emp["id"],
            qualifying_reason="OWN_SERIOUS_HEALTH_CONDITION",
            leave_type="CONTINUOUS",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-07-01T00:00:00.000Z",
        )
        res = api.evaluate_eligibility(case["id"], TEST_USERS["hr_admin_headers"])
        validate_error(res, ApiErrorId.ERR_INELIGIBLE)


class TestFmlaQuota480FlipsProtection:
    """PRD §3.6: cumulative fmla_hours_charged == 480 flips job_restoration_protected
    to false; below 480 it remains true.
    """

    def test_cumulative_480_flips_protection_to_false(self, api):
        """PRD §3.6: "once the case's cumulative `fmla_hours_charged` reaches 480, `job_restoration_protected` flips to false."

        Design: Difficulty/boundary_precision_check/fmla_quota_exactly_480_flips_protection
        """
        bundle = setup_approved_case(
            employer_state="FED",
            fmla_method="CALENDAR_YEAR",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        # Seed 479 historic FMLA hours on this case.
        seed_historic_interval(
            bundle.case["id"],
            "2026-02-01T00:00:00.000Z",
            "2026-04-30T00:00:00.000Z",
            479,
            479,
            0,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        # Add exactly 1 more hour → cumulative 480.
        interval = record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-01T01:00:00.000Z",
            1,
        )
        assert interval["fmla_hours_charged"] == 1
        case_after = get_case(bundle.case["id"])
        assert case_after["fmla_hours_charged"] == 480, (
            f"cumulative must be exactly 480; got {case_after['fmla_hours_charged']!r}"
        )
        assert case_after["job_restoration_protected"] is False, (
            f"at cumulative 480, protection flips to false; got {case_after['job_restoration_protected']!r}"
        )

    def test_cumulative_479_keeps_protection_true(self, api):
        """PRD §3.6: "once the case's cumulative `fmla_hours_charged` reaches 480, `job_restoration_protected` flips to false."

        Design: Difficulty/boundary_precision_check/fmla_quota_exactly_480_flips_protection
        """
        # X-1 boundary: at 479 the case must still be protected.
        bundle = setup_approved_case(
            employer_state="FED",
            fmla_method="CALENDAR_YEAR",
            requested_start_at="2026-06-01T00:00:00.000Z",
            requested_end_at="2026-08-15T00:00:00.000Z",
            cert_expected_duration_weeks=10,
        )
        seed_historic_interval(
            bundle.case["id"],
            "2026-02-01T00:00:00.000Z",
            "2026-04-30T00:00:00.000Z",
            478,
            478,
            0,
        )
        set_clock("2026-06-01T00:00:00.000Z")
        record_interval(
            bundle.case["id"],
            "2026-06-01T00:00:00.000Z",
            "2026-06-01T01:00:00.000Z",
            1,
        )
        case_after = get_case(bundle.case["id"])
        assert case_after["fmla_hours_charged"] == 479
        assert case_after["job_restoration_protected"] is True, (
            f"at cumulative 479 (< 480), protection must remain true; got {case_after['job_restoration_protected']!r}"
        )
