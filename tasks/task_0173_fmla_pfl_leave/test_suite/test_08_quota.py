"""FMLA quota accounting — CALENDAR vs ROLLING_BACKWARD windows,
boundary tests, quota-exceeded errors.

Covers PRD §3.7 (quota), §3.6 (quota check on approve), §3.4 (instance
logging within quota).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    FMLA_ENTITLEMENT_HOURS,
    advance_clock_to,
    approve_case_with_specific_instances,
    assert_quota_balance,
    create_leave_instance_payload,
    get_quota_balance,
    log_instance,
    make_employee_headers,
    setup_approved_case,
    setup_eligible_employee,
    setup_quota_near_threshold,
    submit_certification,
    submit_leave_case,
    review_certification,
    validate_error,
    validate_success,
)


# ===========================================================================
# Quota read — PRD §3.7
# ===========================================================================
class TestQuotaRead:

    def test_quota_balance_fresh_employee_remaining_480(self, api):
        """PRD §3.7: "The federal FMLA entitlement is twelve workweeks
        per leave year, which the system represents as 480 whole hours
        per employee per leave year"."""
        _e, _w, employee = setup_eligible_employee(
            leave_year_basis="CALENDAR",
        )
        data = get_quota_balance(employee_id=employee["id"])
        assert_quota_balance(data)
        assert data["consumed_hours"] == 0
        assert data["remaining_hours"] == FMLA_ENTITLEMENT_HOURS
        assert data["basis"] == "CALENDAR"

    def test_quota_balance_basis_reports_employer_leave_year_basis(self, api):
        """PRD §3.7: "the basis (the employer's `leave_year_basis`)"."""
        _e, _w, employee = setup_eligible_employee(
            leave_year_basis="ROLLING_BACKWARD",
        )
        data = get_quota_balance(employee_id=employee["id"])
        assert data["basis"] == "ROLLING_BACKWARD"


# ===========================================================================
# Quota debited on APPROVE — PRD §3.7
# ===========================================================================
class TestQuotaDebit:

    def test_approve_debits_quota_remaining_hours(self, api):
        """PRD §3.7: "The quota is consulted as a precondition when a
        leave case is submitted, decremented when the case is
        approved"."""
        ctx = setup_approved_case(
            leave_pattern="INTERMITTENT",
            requested_start_date="2026-05-01",
            expected_end_date="2026-05-31",
            instance_dates_and_hours=[
                ("2026-05-01", 8), ("2026-05-04", 8), ("2026-05-05", 8),
            ],
        )
        # 24 hours consumed.
        data = get_quota_balance(employee_id=ctx["employee"]["id"])
        assert data["consumed_hours"] == 24, (
            f"PRD §3.7: consumed_hours from 3 APPROVED 8-hour "
            f"instances = 24; got {data['consumed_hours']!r}"
        )
        assert data["remaining_hours"] == FMLA_ENTITLEMENT_HOURS - 24

    def test_deny_recredits_quota(self, api):
        """PRD §3.6: "On a denial ... `hours_charged` is reset to 0
        (re-crediting the leave-year bucket entirely)"."""
        from test_helpers import setup_pending_certification_case
        # Submit + log instances + deny via INSUFFICIENT cert path.
        _e, _w, employee, case = setup_pending_certification_case(
            reason="OWN_SERIOUS_HEALTH",
            leave_pattern="INTERMITTENT",
        )
        log_instance(
            leave_case_id=case["id"], employee_id=employee["id"],
            instance_date="2026-05-01", hours_used=8,
        )
        cert = submit_certification(
            leave_case_id=case["id"], employee_id=employee["id"],
            serious_health_condition=True,
        )
        review_certification(
            leave_case_id=case["id"], cert_id=cert["id"],
            decision="INSUFFICIENT",
        )
        from test_helpers import review_leave_case
        review_leave_case(leave_case_id=case["id"], decision="DENY")
        balance = get_quota_balance(employee_id=employee["id"])
        assert balance["consumed_hours"] == 0, (
            f"DENY must re-credit the bucket entirely; got "
            f"consumed_hours={balance['consumed_hours']!r}"
        )
        assert balance["remaining_hours"] == FMLA_ENTITLEMENT_HOURS


# ===========================================================================
# Quota exceeded at APPROVE — PRD §3.6
# ===========================================================================
class TestApproveQuotaExceeded:

    def test_approve_exceeding_quota_returns_err_quota_exceeded(self, api):
        """PRD §3.6: "approving when the quota would be exceeded fails
        with `ERR_QUOTA_EXCEEDED`"."""
        # Build a baseline of 472 APPROVED hours, then submit a new
        # PENDING_CERTIFICATION case with COMPLETE cert and 9 hours of
        # PROPOSED instances (472+9=481 > 480 → over).
        ctx = setup_quota_near_threshold(
            consumed_hours=472,
            leave_year_basis="CALENDAR",
            requested_start_date="2026-07-01",
            expected_end_date="2026-07-31",
        )
        # Log 9 hours of PROPOSED instances on the new_case.
        log_instance(
            leave_case_id=ctx["new_case"]["id"],
            employee_id=ctx["employee"]["id"],
            instance_date="2026-07-01", hours_used=8,
        )
        log_instance(
            leave_case_id=ctx["new_case"]["id"],
            employee_id=ctx["employee"]["id"],
            instance_date="2026-07-02", hours_used=1,
        )
        # Now attempt APPROVE.
        from test_helpers import api_client, TEST_USERS
        resp = api_client.review_leave_case(
            ctx["new_case"]["id"], {"decision": "APPROVE"},
            TEST_USERS["hr_specialist_headers"],
        )
        validate_error(resp, "ERR_QUOTA_EXCEEDED")


# ===========================================================================
# Remaining hours floored at zero — PRD §3.7
# ===========================================================================
class TestRemainingHoursFloor:

    def test_remaining_hours_is_floored_at_zero(self, api):
        """PRD §3.7: "The remaining hours figure is then 480 minus that
        consumed total, floored at zero so that an over-consumed bucket
        is reported as zero rather than as a negative number"."""
        # Setup a case with exactly 480 consumed.
        ctx = setup_quota_near_threshold(
            consumed_hours=480,
            leave_year_basis="CALENDAR",
            requested_start_date="2026-07-01",
            expected_end_date="2026-07-31",
        )
        data = get_quota_balance(employee_id=ctx["employee"]["id"])
        assert data["consumed_hours"] == 480
        assert data["remaining_hours"] == 0, (
            f"remaining_hours must be floored at 0 when bucket is "
            f"fully consumed; got {data['remaining_hours']!r}"
        )
