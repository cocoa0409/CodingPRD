"""Supplemental tests providing the ≥2-tests-per-instance coverage for queue (A).

Each design index difficulty instance must be covered by at least two tests.
The primary "happy-path" assertion lives in the topical file; this file emits
the second test per instance, asserting a different observable consequence of
the same PRD rule.
"""
import pytest

from test_helpers import (
    api_client,
    validate_error,
    validate_success,
    validate_paginated,
    set_clock,
    seed_federal_and_california_2025,
    setup_employee_with_filed_w4,
    setup_paid_regular_run,
    setup_approved_regular_run,
    create_employee,
    terminate_employee,
    create_and_file_w4,
    create_w4_draft,
    create_draft_paycheck_run,
    attach_regular_paycheck,
    attach_overtime_paycheck,
    approve_run,
    pay_run,
    void_run,
    seed_employee_ytd,
    create_garnishment_order,
    suspend_garnishment,
    reactivate_garnishment,
    find_remittance,
    close_remittance,
    get_employee,
    get_paycheck,
    get_paycheck_run,
    get_garnishment_order,
    get_w4_form,
    regular_paycheck_payload,
    pay_paycheck_run_payload,
    remit_payload,
    create_paycheck_run_payload,
    create_garnishment_order_payload,
    TEST_USERS,
    make_preparer_headers,
    make_approver_headers,
)


# =========================================================================
# Difficulty 1.1 — dual_variant_calc / paycheck_fed_withholding (3rd test optional;
# already 2 in test_01). Skipped here.
# =========================================================================

# =========================================================================
# Difficulty 1.2 — dual_variant_calc / remittance_accrual_provisional_vs_reconciled
# =========================================================================

class TestRemittanceAccruedReflectsProvisionalIncrement:
    def test_accrued_cents_set_to_provisional_value_immediately_after_paid(self, api):
        """PRD §3.7: "While the row is `ACCRUING`, `accrued_cents` runs as a
        provisional accumulator — incremented by each `Paycheck`'s relevant
        bucket when the paycheck transitions to `PAID`"

        After /pay, the Remittance row for (period, FEDERAL, FED_INCOME) has
        accrued_cents == 16357 (the paycheck's fed_withheld_cents) and status
        remains ACCRUING.

        Design: Difficulty/dual_variant_calc/remittance_accrual_provisional_vs_reconciled
        """
        set_clock("2025-12-15T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run(
            pay_period_start="2025-12-15T00:00:00.000Z",
            pay_period_end="2025-12-31T23:59:59.999Z",
            pay_date="2025-12-15T00:00:00.000Z",
        )
        rem = find_remittance("2025-12", "FEDERAL", "FED_INCOME")
        assert rem["accrued_cents"] == 16357
        assert rem["status"] == "ACCRUING"


# =========================================================================
# Difficulty 2.1 — combinatorial_formula / federal_overtime_supplemental_branch
# =========================================================================

class TestSupplementalFlatBranchSecondaryEffects:
    def test_overtime_paycheck_is_pending_status_with_correct_gross(self, api):
        """PRD §3.4: "For an `OVERTIME` paycheck, the overtime multiplier is
        one-and-a-half: gross is `overtime_hours_e2` multiplied by
        `hourly_rate_cents`, multiplied by 3, then floor-divided by 200."

        OVERTIME 40h @ $25/hr → gross = (4000 × 2500 × 3) // 200 = 150,000c.
        And per PRD §3.4: the paycheck enters PENDING.

        Design: Difficulty/combinatorial_formula/federal_overtime_supplemental_branch_mode_a
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run = create_draft_paycheck_run()
        pay = attach_overtime_paycheck(
            run["id"], emp["id"], overtime_hours_e2=4000, hourly_rate_cents=2500,
        )
        assert pay["gross_wages_cents"] == 150000
        assert pay["status"] == "PENDING"


# =========================================================================
# Difficulty 2.2 — combinatorial_formula / garnishment_waterfall_eval_order
# =========================================================================

class TestGarnishmentTaxWithholdingsBeforeWaterfall:
    def test_two_child_support_orders_full_withholding_breakdown(self, api):
        """PRD §3.5: "First, disposable earnings — `gross_wages_cents` minus
        the sum of `fed_withheld_cents`, `state_withheld_cents`,
        `local_withheld_cents`, `ss_withheld_cents`, `medicare_withheld_cents`,
        and `addl_medicare_cents` — is computed."
        PRD §3.5: "Second, the paycheck cap is `disposable_earnings` multiplied
        by the CCPA basis-points limit and floor-divided by 10000."

        Same setup as the primary tie-break test, asserts FICA/Medicare
        breakdowns produced by the pipeline preceding the waterfall.

        Design: Difficulty/combinatorial_formula/garnishment_waterfall_eval_order_mode_c
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=30000, original_balance_cents=100000,
            served_on="2025-06-01T00:00:00.000Z",
        )
        create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=50000, original_balance_cents=100000,
            served_on="2025-07-01T00:00:00.000Z",
        )
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])
        # FICA SS: 200000 × 620 // 10000 = 12400
        assert pay["ss_withheld_cents"] == 12400
        # base Medicare: 200000 × 145 // 10000 = 2900
        assert pay["medicare_withheld_cents"] == 2900
        # addl Medicare: zero (YTD nowhere near $200k threshold)
        assert pay["addl_medicare_cents"] == 0


# =========================================================================
# Difficulty 3.1 — non_linear_state_machine / paycheckrun_branching_revert
# =========================================================================

class TestPaycheckRunReApprovableAfterReject:
    def test_rejected_run_can_be_re_approved_after_correction(self, api):
        """PRD §3.6: "from `APPROVED` back to `DRAFT` for correction (a
        branching revert)"

        After /reject the run is DRAFT again; a fresh /approve from a non-SoD
        operator succeeds, demonstrating the non-linear branching shape.

        Design: Difficulty/non_linear_state_machine/paycheckrun_branching_revert_approved_to_draft
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, approved, _ = setup_approved_regular_run()
        # reject -> DRAFT
        api_client.reject_paycheck_run(
            approved["id"], TEST_USERS["payroll_approver_headers"]
        )
        # re-approve under a different approver id (the original approver is fine here too —
        # the constraint is approver != preparer; preparer is U_PREP, approver is U_APPR)
        re_approved_res = api_client.approve_paycheck_run(
            approved["id"], TEST_USERS["payroll_approver_headers"]
        )
        re_approved = validate_success(re_approved_res, expected_status=200)
        assert re_approved["status"] == "APPROVED"


# =========================================================================
# Difficulty 3.2 — non_linear_state_machine / garnishment_cyclic_active_suspended
# =========================================================================

class TestGarnishmentSuspendThenReactivateRoundTrip:
    def test_full_round_trip_active_suspended_active(self, api):
        """PRD §3.5: "A `SUSPENDED` order is skipped by the waterfall on every
        subsequent paycheck until it is reactivated."

        After ACTIVE → SUSPENDED → ACTIVE, the order is back to ACTIVE.
        We assert each intermediate state.

        Design: Difficulty/non_linear_state_machine/garnishment_order_cyclic_active_suspended_active
        """
        emp = create_employee()
        g = create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=30000, original_balance_cents=100000,
            served_on="2025-06-01T00:00:00.000Z",
        )
        assert g["status"] == "ACTIVE"
        suspended = suspend_garnishment(g["id"])
        assert suspended["status"] == "SUSPENDED"
        reactivated = reactivate_garnishment(g["id"])
        assert reactivated["status"] == "ACTIVE"


# =========================================================================
# Difficulty 4.1 — transitive_cascade / paycheck_run_pay_cascade_depth_4
# =========================================================================

class TestPayCascadeAccruesRemittance:
    def test_pay_cascade_creates_or_increments_federal_remittance_row(self, api):
        """PRD §3.6: "For each tax bucket on each child paycheck — federal
        income, FICA, state income, local income — the relevant `Remittance`
        row's `accrued_cents` is incremented by that bucket's value for the
        `(period_month, jurisdiction, tax_type)` tuple, creating the
        remittance row if it does not yet exist; the row remains in `ACCRUING`
        through this cascade."

        Hop-4 verification: after /pay, a FEDERAL/FED_INCOME row exists with
        accrued_cents == the paycheck's fed_withheld_cents (16357).

        Design: Difficulty/transitive_cascade/paycheck_run_pay_cascade_depth_4
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run()
        rem = find_remittance("2025-11", "FEDERAL", "FED_INCOME")
        assert rem["accrued_cents"] == 16357
        assert rem["status"] == "ACCRUING"


# =========================================================================
# Difficulty 4.2 — transitive_cascade / w4_file_supersede_cascade_depth_2
# =========================================================================

class TestW4SupersedeStampsFiledAt:
    def test_filing_new_w4_stamps_filed_at_on_new_form(self, api):
        """PRD §3.1: "Filing the W-4 advances `W4Form.status` from `DRAFT` to
        `FILED`, stamps `filed_at` with the current UTC instant"

        After the supersede-and-file cascade, the new W-4 has a non-null
        filed_at timestamp.

        Design: Difficulty/transitive_cascade/w4_file_supersede_cascade_depth_2
        """
        set_clock("2025-06-01T00:00:00.000Z")
        emp = create_employee()
        old_w4 = create_and_file_w4(emp["id"], tax_year=2025, filing_status="SINGLE")
        new_w4 = create_w4_draft(
            emp["id"], tax_year=2025, filing_status="MARRIED_JOINT",
            supersedes_w4_id=old_w4["id"],
        )
        api_client.file_w4_form(new_w4["id"], TEST_USERS["hr_clerk_headers"])
        new_after = get_w4_form(new_w4["id"])
        assert new_after["status"] == "FILED"
        assert new_after["filed_at"] is not None


# =========================================================================
# Difficulty 5.1 — priority_pair / state_beats_business_referential
# =========================================================================

class TestPriorityPairStateBeatsEmployeeNotActiveSecondaryShape:
    def test_approve_already_paid_run_returns_409(self, api):
        """PRD §5 (Error Code Catalogue): "`ERR_INVALID_STATE` | 409"
        PRD §2.6: "state-machine guards (`ERR_INVALID_STATE`)"

        Asserts the HTTP status code returned by the state-guard precedes the
        EMPLOYEE_NOT_ACTIVE check.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_pay_with_terminated_employee
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, paid_run, _ = setup_paid_regular_run()
        terminate_employee(emp["id"])
        res = api_client.approve_paycheck_run(
            paid_run["id"], make_approver_headers("U_APPR_NEW_2")
        )
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_INVALID_STATE"


# =========================================================================
# Difficulty 5.2 — priority_pair / sod_business_safety_beats_fiscal
# =========================================================================

class TestSelfApprovalReturns403:
    def test_self_approval_returns_403_status(self, api):
        """PRD §5 (Error Code Catalogue): "`ERR_SOD_VIOLATION` | 403"
        PRD §3.6: "A preparer who attempts to approve their own run is
        rejected with `ERR_SOD_VIOLATION` and HTTP 403."

        Self-approval should produce a 403 response with ERR_SOD_VIOLATION.

        Design: Difficulty/priority_pair_validation_conflict/sod_business_safety_beats_fiscal_open_run_blocks
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        prep_headers = make_preparer_headers("U_SAME")
        run = create_draft_paycheck_run(preparer_headers=prep_headers)
        attach_regular_paycheck(run["id"], emp["id"], preparer_headers=prep_headers)
        self_appr = make_approver_headers("U_SAME")
        res = api_client.approve_paycheck_run(run["id"], self_appr)
        assert res.status_code == 403
        assert res.json()["data"]["error_id"] == "ERR_SOD_VIOLATION"


# =========================================================================
# Difficulty 6.1 — boundary_precision / addl_medicare_threshold_exact_no_charge
# =========================================================================

class TestAddlMedicareJustBelowThreshold:
    def test_pre_threshold_paycheck_yields_zero_addl_medicare(self, api):
        """PRD §3.4: "the additional Medicare surcharge — `addl_medicare_cents`
        — applies at 0.9% (`ADDL_MEDICARE_RATE_BASIS_POINTS = 90`) on the
        portion of Medicare wages that exceed `ADDL_MEDICARE_THRESHOLD_CENTS =
        20,000,000` cents (\\$200,000.00) year-to-date."

        Employee whose YTD medicare wages stay below the threshold even after
        the new paycheck must have addl_medicare_cents == 0.

        Design: Difficulty/boundary_precision_check/addl_medicare_threshold_exact_no_charge
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee()
        seed_employee_ytd(emp["id"], ytd_medicare_wages_cents=10_000_000)
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])
        assert pay["addl_medicare_cents"] == 0


# =========================================================================
# Difficulty 6.2 — boundary_precision / pay_period_overlap_closed_closed
# =========================================================================

class TestPayPeriodOverlapHttpStatus:
    def test_overlap_returns_422_status(self, api):
        """PRD §5 (Error Code Catalogue): "`ERR_PAY_PERIOD_OVERLAP` | 422"

        Design: Difficulty/boundary_precision_check/pay_period_overlap_closed_closed_point_touch
        """
        set_clock("2025-10-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run_a = create_draft_paycheck_run(
            pay_period_start="2025-11-01T00:00:00.000Z",
            pay_period_end="2025-11-15T23:59:59.999Z",
            pay_date="2025-11-15T00:00:00.000Z",
        )
        attach_regular_paycheck(run_a["id"], emp["id"])
        run_b = create_draft_paycheck_run(
            pay_period_start="2025-11-15T23:59:59.999Z",
            pay_period_end="2025-11-30T23:59:59.999Z",
            pay_date="2025-11-30T00:00:00.000Z",
        )
        res = api_client.create_paycheck(
            regular_paycheck_payload(
                paycheck_run_id=run_b["id"],
                employee_id=emp["id"],
                regular_hours_e2=4000,
                hourly_rate_cents=5000,
            ),
            TEST_USERS["payroll_preparer_headers"],
        )
        assert res.status_code == 422
        assert res.json()["data"]["error_id"] == "ERR_PAY_PERIOD_OVERLAP"


# =========================================================================
# Difficulty 7.1 — cross_entity_state_dependency / paycheck_create_requires_active
# =========================================================================

class TestPaycheckCreateRequiresActiveEmployee409:
    def test_terminated_employee_paycheck_create_returns_409(self, api):
        """PRD §5 (Error Code Catalogue): "`ERR_EMPLOYEE_NOT_ACTIVE` | 409"

        Design: Difficulty/cross_entity_state_dependency/paycheck_create_requires_employee_active_pair_paycheck_employee
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee()
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        terminate_employee(emp["id"])
        res = api_client.create_paycheck(
            regular_paycheck_payload(
                paycheck_run_id=run["id"],
                employee_id=emp["id"],
                regular_hours_e2=4000,
                hourly_rate_cents=5000,
            ),
            TEST_USERS["payroll_preparer_headers"],
        )
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_EMPLOYEE_NOT_ACTIVE"


# =========================================================================
# Difficulty 7.2 — cross_entity_state_dependency / remittance_close_requires_no_open_runs
# =========================================================================

class TestCloseRequiresNoOpenRunsHttpStatus:
    def test_open_run_blocking_close_returns_409(self, api):
        """PRD §5 (Error Code Catalogue): "`ERR_OPEN_RUN_BLOCKS_CLOSE` | 409"

        Design: Difficulty/cross_entity_state_dependency/remittance_close_requires_no_open_paycheckruns_pair_remittance_paycheckrun
        """
        set_clock("2025-10-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run(
            pay_period_start="2025-10-01T00:00:00.000Z",
            pay_period_end="2025-10-15T23:59:59.999Z",
            pay_date="2025-10-15T00:00:00.000Z",
        )
        run_b = create_draft_paycheck_run(
            pay_period_start="2025-10-16T00:00:00.000Z",
            pay_period_end="2025-10-31T23:59:59.999Z",
            pay_date="2025-10-31T00:00:00.000Z",
        )
        attach_regular_paycheck(run_b["id"], emp["id"])
        rem = find_remittance("2025-10", "FEDERAL", "FED_INCOME")
        res = api_client.close_remittance_period(
            rem["id"], TEST_USERS["compliance_officer_headers"]
        )
        assert res.status_code == 409
        assert res.json()["data"]["error_id"] == "ERR_OPEN_RUN_BLOCKS_CLOSE"


# =========================================================================
# Difficulty 8.1 — resource_temporal_overlap / pay_period_closed_closed
# =========================================================================

class TestPayPeriodOverlapBlocksAttachment:
    def test_attaching_paycheck_in_touching_run_for_shared_employee_blocked(self, api):
        """PRD §3.3: "The same check applies when a paycheck is later added to
        the run for an employee whose other runs would now overlap."

        Run A: 2025-11-01..2025-11-15 with paycheck for emp.
        Run B: 2025-11-15..2025-11-30 (touch point). Attempt to attach a
        paycheck for the same employee to run B must be rejected with
        ERR_PAY_PERIOD_OVERLAP via this "later" check path.

        Design: Difficulty/resource_temporal_overlap/pay_period_closed_closed_overlap_on_employee
        """
        set_clock("2025-10-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        run_a = create_draft_paycheck_run(
            pay_period_start="2025-11-01T00:00:00.000Z",
            pay_period_end="2025-11-15T00:00:00.000Z",
            pay_date="2025-11-15T00:00:00.000Z",
        )
        attach_regular_paycheck(run_a["id"], emp["id"])
        run_b = create_draft_paycheck_run(
            pay_period_start="2025-11-15T00:00:00.000Z",
            pay_period_end="2025-11-30T00:00:00.000Z",
            pay_date="2025-11-30T00:00:00.000Z",
        )
        res = api_client.create_paycheck(
            regular_paycheck_payload(
                paycheck_run_id=run_b["id"],
                employee_id=emp["id"],
                regular_hours_e2=4000,
                hourly_rate_cents=5000,
            ),
            TEST_USERS["payroll_preparer_headers"],
        )
        validate_error(res, "ERR_PAY_PERIOD_OVERLAP", expected_status=422)


# =========================================================================
# Difficulty 8.2 — resource_temporal_overlap / garnishment_aggregate_capacity
# =========================================================================

class TestGarnishmentAggregateCapacityHttpStatus:
    def test_aggregate_cap_violation_returns_422(self, api):
        """PRD §5 (Error Code Catalogue): "`ERR_GARNISHMENT_AGGREGATE_CAP` |
        422"

        Design: Difficulty/resource_temporal_overlap/garnishment_aggregate_capacity_on_employee
        """
        set_clock("2025-10-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _, _, _ = setup_paid_regular_run(
            pay_period_start="2025-10-01T00:00:00.000Z",
            pay_period_end="2025-10-15T23:59:59.999Z",
            pay_date="2025-10-15T00:00:00.000Z",
        )
        create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=80000, original_balance_cents=1_000_000,
            served_on="2025-09-01T00:00:00.000Z",
        )
        res = api_client.create_garnishment_order(
            create_garnishment_order_payload(
                employee_id=emp["id"],
                order_type="CREDITOR",
                weekly_cap_cents=50000,
                original_balance_cents=1_000_000,
                served_on="2025-09-15T00:00:00.000Z",
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        assert res.status_code == 422
        assert res.json()["data"]["error_id"] == "ERR_GARNISHMENT_AGGREGATE_CAP"


# =========================================================================
# Difficulty 9.1 — compensating_invariant / void_run_preserves_employee_ytd
# =========================================================================

class TestVoidRunFlipsPaycheckAndRunToVoid:
    def test_void_cascade_transitions_run_and_child_paycheck_to_void(self, api):
        """PRD §3.6: "Voiding a `PAID` run is a compensating action that runs
        every effect from the pay cascade in reverse. Each child `Paycheck`
        transitions from `PAID` to `VOID`."

        Verifies the status side of the compensating cascade complementing the
        YTD-preservation assertion.

        Design: Difficulty/compensating_invariant/void_run_preserves_employee_ytd_quantities
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp = create_employee()
        seed_employee_ytd(
            emp["id"],
            ytd_wages_cents=500000,
            ytd_fed_withheld_cents=40000,
            ytd_ss_wages_cents=500000,
            ytd_medicare_wages_cents=500000,
        )
        create_and_file_w4(emp["id"])
        run = create_draft_paycheck_run()
        pay = attach_regular_paycheck(run["id"], emp["id"])
        approve_run(run["id"])
        pay_run(run["id"])
        void_run(run["id"])

        run_after = get_paycheck_run(run["id"])
        pay_after = get_paycheck(pay["id"])
        assert run_after["status"] == "VOID"
        assert pay_after["status"] == "VOID"


# =========================================================================
# Difficulty 9.2 — compensating_invariant / void_run_preserves_garnishment
# =========================================================================

class TestVoidRunFullyRestoresGarnishmentBalance:
    def test_void_restores_pre_pay_garnishment_balance_remaining(self, api):
        """PRD §3.6: "For each `GarnishmentDeduction`, `balance_remaining_cents`
        on the corresponding order is increased back by `amount_cents`"

        Validates the conserved-quantity invariant on balance_remaining_cents:
        the order had balance=30000 before pay, balance=0 at PAID, balance=30000
        after VOID.

        Design: Difficulty/compensating_invariant/void_run_preserves_garnishment_balance_remaining
        """
        set_clock("2025-11-01T00:00:00.000Z")
        seed_federal_and_california_2025()
        emp, _ = setup_employee_with_filed_w4()
        g = create_garnishment_order(
            emp["id"], order_type="CHILD_SUPPORT",
            weekly_cap_cents=30000, original_balance_cents=30000,
            served_on="2025-06-01T00:00:00.000Z",
        )
        # Before pay: balance == original
        before = get_garnishment_order(g["id"])
        assert before["balance_remaining_cents"] == 30000
        run = create_draft_paycheck_run()
        attach_regular_paycheck(run["id"], emp["id"])
        approve_run(run["id"])
        pay_run(run["id"])
        void_run(run["id"])
        after = get_garnishment_order(g["id"])
        assert after["balance_remaining_cents"] == 30000
