"""Role-based access control — segregation-of-duties role boundaries (PRD §2.1, §4)."""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    create_employee,
    create_paycheck_run_payload,
    create_garnishment_order_payload,
    TEST_USERS,
)


# =========================================================================
# Queue (B) Corner — rbac hrclerk_cannot_create_paycheck_run
# =========================================================================

class TestHrClerkCannotCreatePaycheckRun:
    def test_hrclerk_post_paycheck_runs_forbidden(self, api):
        """PRD §2.1: "`HRClerk` manages employees and W-4 forms but cannot
        create or approve paycheck runs. `PayrollPreparer` creates paycheck
        runs and the paychecks attached to them."
        PRD §2.1: "If both headers are present but the named role lacks
        permission for the requested endpoint, the request is rejected with
        `ERR_FORBIDDEN` and HTTP status 403."

        Design: Corner/rbac/hrclerk_cannot_create_paycheck_run
        """
        res = api_client.create_paycheck_run(
            create_paycheck_run_payload(),
            TEST_USERS["hr_clerk_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)


# =========================================================================
# Queue (B) Corner — rbac payroll_preparer_cannot_create_garnishment
# =========================================================================

class TestPreparerCannotCreateGarnishment:
    def test_payroll_preparer_post_garnishment_orders_forbidden(self, api):
        """PRD §2.1: "`ComplianceOfficer` owns garnishment orders, closes
        accrual periods, remits to tax authorities"
        PRD §2.1: "If both headers are present but the named role lacks
        permission for the requested endpoint, the request is rejected with
        `ERR_FORBIDDEN` and HTTP status 403."

        Design: Corner/rbac/payroll_preparer_cannot_create_garnishment
        """
        emp = create_employee()
        res = api_client.create_garnishment_order(
            create_garnishment_order_payload(
                employee_id=emp["id"],
                order_type="CHILD_SUPPORT",
                weekly_cap_cents=30000,
                original_balance_cents=100000,
                served_on="2025-06-01T00:00:00.000Z",
            ),
            TEST_USERS["payroll_preparer_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN", expected_status=403)
