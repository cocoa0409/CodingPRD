"""Validation error catalogue — ERR_NO_W4_ON_FILE, ERR_FK_NOT_FOUND, ERR_NOT_FOUND."""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    set_clock,
    seed_federal_and_california_2025,
    create_employee,
    create_w4_draft,
    create_draft_paycheck_run,
    regular_paycheck_payload,
    create_w4_form_payload,
    NON_EXISTENT_UUID,
    TEST_USERS,
)


# =========================================================================
# Queue (B) Corner — validations paychecks_without_w4_on_file
# =========================================================================

class TestPaychecksRequireFiledW4:
    def test_paycheck_create_without_filed_w4_rejected(self, api):
        """PRD §3.3: "the employee must have a `FILED` W-4 covering the parent
        run's `pay_date`-year (no filed W-4 yields `ERR_NO_W4_ON_FILE`)"

        Design: Corner/validations/paychecks_without_w4_on_file
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee()
        # W-4 created but NOT filed
        create_w4_draft(emp["id"], tax_year=2025, filing_status="SINGLE")
        run = create_draft_paycheck_run()
        res = api_client.create_paycheck(
            regular_paycheck_payload(
                paycheck_run_id=run["id"],
                employee_id=emp["id"],
                regular_hours_e2=4000,
                hourly_rate_cents=5000,
            ),
            TEST_USERS["payroll_preparer_headers"],
        )
        validate_error(res, "ERR_NO_W4_ON_FILE", expected_status=422)


# =========================================================================
# Queue (B) Corner — errors fk_not_found_paycheck_run_id
# =========================================================================

class TestFkNotFoundPaycheckRunId:
    def test_paycheck_create_with_nonexistent_run_id_returns_fk_not_found(self, api):
        """PRD §2.5: "Foreign keys in request bodies — `employee_id`,
        `paycheck_run_id`, `garnishment_order_id`, and a non-null
        `supersedes_w4_id` — must each resolve to an existing entity. A missing
        FK is rejected with `ERR_FK_NOT_FOUND` (HTTP 404)."

        Design: Corner/errors/fk_not_found_paycheck_run_id
        """
        emp = create_employee()
        # File a W-4 so the priority-9 W4 check doesn't fire first.
        from test_helpers import create_and_file_w4
        create_and_file_w4(emp["id"])

        res = api_client.create_paycheck(
            regular_paycheck_payload(
                paycheck_run_id=NON_EXISTENT_UUID,
                employee_id=emp["id"],
                regular_hours_e2=4000,
                hourly_rate_cents=5000,
            ),
            TEST_USERS["payroll_preparer_headers"],
        )
        validate_error(res, "ERR_FK_NOT_FOUND", expected_status=404)
