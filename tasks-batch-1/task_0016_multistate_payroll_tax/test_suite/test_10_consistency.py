"""Consistency model — POST returns and GET sees identical values."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    set_clock,
    seed_federal_and_california_2025,
    setup_employee_with_filed_w4,
    create_draft_paycheck_run,
    attach_regular_paycheck,
    TEST_USERS,
)


# =========================================================================
# Queue (B) Corner — consistency_model immediate_visibility_paycheck_after_create
# =========================================================================

class TestImmediateConsistencyPaycheck:
    def test_subsequent_get_paycheck_sees_same_computed_values_as_post(self, api):
        """PRD §3.4: "Creating a paycheck advances `Paycheck.status` to
        `PENDING` and runs the withholding pipeline in a fixed order: gross
        wages, then federal, then state, then local, then Social Security,
        then base Medicare, then additional Medicare, then garnishment
        waterfall, then net pay. Every output is integer cents."

        Design: Corner/consistency_model/immediate_visibility_paycheck_after_create
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run = create_draft_paycheck_run()
        created = attach_regular_paycheck(run["id"], emp["id"])

        get_res = api_client.get_paycheck(
            created["id"], TEST_USERS["payroll_preparer_headers"]
        )
        retrieved = validate_success(get_res, expected_status=200)
        assert retrieved["gross_wages_cents"] == 200000
        assert retrieved["fed_withheld_cents"] == 16357
        assert retrieved["status"] == "PENDING"
        assert retrieved["id"] == created["id"]
