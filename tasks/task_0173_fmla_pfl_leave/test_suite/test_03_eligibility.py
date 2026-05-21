"""FMLA eligibility — three thresholds (tenure, hours, worksite headcount),
evaluated at case submission and via the synchronous snapshot.

Covers PRD §3.2 (eligibility), §3.3 (eligibility at submission),
§5 (error codes).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    assert_eligibility_snapshot,
    create_employee,
    create_employer,
    create_leave_case_payload,
    create_worksite,
    make_employee_headers,
    setup_eligible_employee,
    setup_employer_worksite_employee,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Tenure threshold (12 months inclusive) — PRD §3.2
# ===========================================================================
class TestTenure:

    def test_exactly_12_months_passes(self, api):
        """PRD §3.2: "months of service at the moment of evaluation
        must be at least twelve; ... a hire date on the same day of the
        month twelve months earlier exactly satisfies the threshold"."""
        # Anchor clock to 2026-03-01, hire on 2025-03-01 = exactly 12 months.
        employer = create_employer()
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2025-03-01",
            hours_worked_trailing_12mo=2080,
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_case(
            employee["id"],
            create_leave_case_payload(
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-04-01",
                expected_end_date="2026-04-30",
            ),
            h,
        )
        validate_success(resp, expected_status=201)

    def test_just_under_12_months_returns_err_not_eligible_tenure(self, api):
        """PRD §3.2: "Failing this check yields `ERR_NOT_ELIGIBLE_TENURE`"."""
        employer = create_employer()
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        # Hire on 2025-04-01 → only ~11 months on 2026-03-01.
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2025-04-01",
            hours_worked_trailing_12mo=2080,
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_case(
            employee["id"],
            create_leave_case_payload(
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-04-01",
                expected_end_date="2026-04-30",
            ),
            h,
        )
        validate_error(resp, "ERR_NOT_ELIGIBLE_TENURE")


# ===========================================================================
# Hours threshold (1250 inclusive) — PRD §3.2
# ===========================================================================
class TestHours:

    def test_exactly_1250_hours_passes(self, api):
        """PRD §3.2: "exactly 1250 hours passes"."""
        employer = create_employer()
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01",
            hours_worked_trailing_12mo=1250,
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_case(
            employee["id"],
            create_leave_case_payload(
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-04-01",
                expected_end_date="2026-04-30",
            ),
            h,
        )
        validate_success(resp, expected_status=201)

    def test_1249_hours_returns_err_not_eligible_hours(self, api):
        """PRD §3.2: "`hours_worked_trailing_12mo` must be at least
        1250; failing this check yields `ERR_NOT_ELIGIBLE_HOURS`"."""
        employer = create_employer()
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01",
            hours_worked_trailing_12mo=1249,
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_case(
            employee["id"],
            create_leave_case_payload(
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-04-01",
                expected_end_date="2026-04-30",
            ),
            h,
        )
        validate_error(resp, "ERR_NOT_ELIGIBLE_HOURS")


# ===========================================================================
# Worksite headcount threshold (50 inclusive) — PRD §3.2
# ===========================================================================
class TestWorksiteHeadcount:

    def test_exactly_50_employees_passes(self, api):
        """PRD §3.2: "exactly 50 employees passes"."""
        employer = create_employer()
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=50,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_case(
            employee["id"],
            create_leave_case_payload(
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-04-01",
                expected_end_date="2026-04-30",
            ),
            h,
        )
        validate_success(resp, expected_status=201)

    def test_49_employees_returns_err_not_eligible_worksite(self, api):
        """PRD §3.2: "the employee's worksite must have an
        `employee_count_within_75_miles` of at least 50; failing this
        check yields `ERR_NOT_ELIGIBLE_WORKSITE`"."""
        employer = create_employer()
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=49,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01", hours_worked_trailing_12mo=2080,
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_case(
            employee["id"],
            create_leave_case_payload(
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-04-01",
                expected_end_date="2026-04-30",
            ),
            h,
        )
        validate_error(resp, "ERR_NOT_ELIGIBLE_WORKSITE")


# ===========================================================================
# Eligibility ordering — PRD §3.2
# ===========================================================================
class TestEligibilityOrdering:

    def test_tenure_fails_first_before_hours(self, api):
        """PRD §3.2: "The three checks are evaluated in the order
        tenure, hours, worksite, so a worker who fails on tenure does
        not see a worksite-headcount error"."""
        employer = create_employer()
        # Worksite below threshold AND hire date below threshold AND
        # hours below threshold — implementation must report tenure.
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=10,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2025-09-01",      # ~6 months → fails tenure
            hours_worked_trailing_12mo=100,  # fails hours too
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_case(
            employee["id"],
            create_leave_case_payload(
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-04-01",
                expected_end_date="2026-04-30",
            ),
            h,
        )
        validate_error(resp, "ERR_NOT_ELIGIBLE_TENURE")

    def test_hours_fails_before_worksite_when_tenure_ok(self, api):
        """PRD §3.2: "The three checks are evaluated in the order
        tenure, hours, worksite"."""
        employer = create_employer()
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=10,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2023-01-01",       # tenure OK
            hours_worked_trailing_12mo=100,  # fails hours
        )
        h = make_employee_headers(employee["id"])
        resp = api.create_leave_case(
            employee["id"],
            create_leave_case_payload(
                reason="OWN_SERIOUS_HEALTH",
                leave_pattern="CONTINUOUS",
                requested_start_date="2026-04-01",
                expected_end_date="2026-04-30",
            ),
            h,
        )
        validate_error(resp, "ERR_NOT_ELIGIBLE_HOURS")


# ===========================================================================
# Eligibility snapshot — PRD §3.2
# ===========================================================================
class TestEligibilitySnapshot:

    def test_eligibility_snapshot_returns_all_fields(self, api):
        """PRD §3.2: "it returns an object containing `eligible`,
        `reason_code` (the specific failing threshold's error id, or
        null if all three pass), `months_of_service`, `hours_trailing`,
        and `worksite_headcount`"."""
        _e, _w, employee = setup_employer_worksite_employee(
            hours_worked_trailing_12mo=2080, worksite_headcount=80,
        )
        h = make_employee_headers(employee["id"])
        resp = api.get_eligibility_snapshot(employee["id"], h)
        data = validate_success(resp, expected_status=200)
        assert_eligibility_snapshot(data)
        assert data["eligible"] is True
        assert data["reason_code"] is None, (
            f"PRD §3.2: reason_code is null when all three pass; "
            f"got {data['reason_code']!r}"
        )

    def test_eligibility_snapshot_failing_tenure_reports_tenure_error_id(
        self, api,
    ):
        """PRD §3.2: "the specific failing threshold's error id"."""
        employer = create_employer()
        worksite = create_worksite(
            employer_id=employer["id"], employee_count_within_75_miles=80,
        )
        advance_clock_to("2026-03-01T00:00:00.000Z")
        employee = create_employee(
            employer_id=employer["id"], worksite_id=worksite["id"],
            hire_date="2025-09-01",  # < 12 months
            hours_worked_trailing_12mo=2080,
        )
        h = make_employee_headers(employee["id"])
        resp = api.get_eligibility_snapshot(employee["id"], h)
        data = validate_success(resp, expected_status=200)
        assert data["eligible"] is False
        assert data["reason_code"] == "ERR_NOT_ELIGIBLE_TENURE", (
            f"reason_code should be ERR_NOT_ELIGIBLE_TENURE, "
            f"got {data['reason_code']!r}"
        )
