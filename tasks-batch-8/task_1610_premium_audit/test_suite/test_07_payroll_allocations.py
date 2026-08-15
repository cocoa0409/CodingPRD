"""Payroll allocations: auditable-payroll derivation, closed-interval overlap,
derived premium-base reconciliation, and issuance blocking."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_allocation,
    add_exposure,
    create_payroll_allocation_payload,
    get_success_data,
    refresh_work_order,
    setup_selected_work_order,
    submit_draft,
    validate_error,
    validate_paginated,
    validate_success,
    wo_version,
)

MANAGER = TEST_USERS["audit_manager_headers"]


class TestAuditablePayroll:
    def test_auditable_payroll_overtime_documentation_flag(self, api):
        """PRD: "From these inputs the system derives
        `auditable_payroll_dollars`: start from gross payroll, subtract
        severance and other statutory exclusions always, subtract the overtime
        excess **only when** `overtime_documented` is true, and floor the
        result at zero."

        Design: Corner/entities/allocation_computed_auditable_overtime_flag
        """
        ctx = setup_selected_work_order(policy_number="WC-C1")

        undocumented = add_allocation(
            ctx, 60000, period_start="2026-01-01T00:00:00Z",
            period_end="2026-03-31T00:00:00Z", overtime_excess_dollars=3000,
            overtime_documented=False)
        assert undocumented["auditable_payroll_dollars"] == 60000, (
            "Undocumented overtime excess must NOT be excluded")

        documented = add_allocation(
            ctx, 60000, period_start="2026-04-01T00:00:00Z",
            period_end="2026-06-30T00:00:00Z", overtime_excess_dollars=3000,
            overtime_documented=True)
        assert documented["auditable_payroll_dollars"] == 57000, (
            "Documented overtime excess 3000 must be excluded: "
            "60000 - 3000 = 57000")


class TestAllocationPeriodOverlap:
    def _setup_with_first_allocation(self, api):
        ctx = setup_selected_work_order(policy_number="WC-1700")
        add_allocation(ctx, 40000, period_start="2026-01-01T00:00:00Z",
                       period_end="2026-03-31T00:00:00Z")
        return ctx

    def test_shared_boundary_day_conflicts(self, api):
        """PRD: "Within one work order, allocations to the *same* class code
        must not double-count a period: the closed intervals of all
        non-`REJECTED` allocations sharing a `class_code_id` are compared
        pairwise, and two periods conflict when each starts on or before the
        other's end — which means sharing a boundary day already conflicts and
        is rejected with `ERR_ALLOCATION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/payroll_allocation_closed_interval_overlap
        """
        ctx = self._setup_with_first_allocation(api)

        resp = api.create_payroll_allocation(
            ctx["work_order"]["id"],
            create_payroll_allocation_payload(
                class_code_id=ctx["cc"]["id"],
                period_start="2026-03-31T00:00:00Z",
                period_end="2026-06-30T00:00:00Z", gross_payroll_dollars=20000,
                expected_work_order_version=wo_version(ctx)),
            ctx["auditor_headers"])
        validate_error(resp, ApiErrorId.ERR_ALLOCATION_PERIOD_OVERLAP)

    def test_disjoint_successor_period_accepted(self, api):
        """PRD: "Within one work order, allocations to the *same* class code
        must not double-count a period: the closed intervals of all
        non-`REJECTED` allocations sharing a `class_code_id` are compared
        pairwise, and two periods conflict when each starts on or before the
        other's end — which means sharing a boundary day already conflicts and
        is rejected with `ERR_ALLOCATION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/payroll_allocation_closed_interval_overlap
        """
        ctx = self._setup_with_first_allocation(api)

        ok = api.create_payroll_allocation(
            ctx["work_order"]["id"],
            create_payroll_allocation_payload(
                class_code_id=ctx["cc"]["id"],
                period_start="2026-04-01T00:00:00Z",
                period_end="2026-06-30T00:00:00Z", gross_payroll_dollars=20000,
                expected_work_order_version=wo_version(ctx)),
            ctx["auditor_headers"])
        created = validate_success(ok, 201)
        assert created["status"] == "DRAFT"

        allocations, meta = validate_paginated(
            api.list_work_order_payroll_allocations(ctx["work_order"]["id"],
                                                    MANAGER))
        assert meta["total_count"] == 2, (
            "The rejected attempt must leave no trace; exactly the first and "
            "the disjoint successor exist")


class TestPremiumBaseReconciliation:
    def test_premium_base_ignores_draft_and_rejected_allocations(self, api):
        """PRD: "Its `total_premium_base_dollars` — the running exposure base
        — is recomputed on every allocation or certificate mutation as the sum
        of `auditable_payroll_dollars` over the work order's `VERIFIED`
        payroll allocations plus the sum of `included_dollars` over all of its
        subcontractor exposures."

        Design: Difficulty/compensating_invariant/verified_payroll_total_reconciles_after_verify_reject_cycle
        """
        ctx = setup_selected_work_order(policy_number="WC-1900",
                                        receive_requests=True)
        al1 = add_allocation(ctx, 40000,
                             period_start="2026-01-01T00:00:00Z",
                             period_end="2026-03-31T00:00:00Z", verify=True)
        assert refresh_work_order(ctx)["total_premium_base_dollars"] == 40000

        al2 = add_allocation(ctx, 5000,
                             period_start="2026-04-01T00:00:00Z",
                             period_end="2026-06-30T00:00:00Z")
        assert al2["status"] == "DRAFT"
        assert refresh_work_order(ctx)["total_premium_base_dollars"] == 40000, (
            "A DRAFT allocation must not move the premium base")

        get_success_data(api.reject_payroll_allocation(al2["id"],
                                                       ctx["auditor_headers"]))
        assert refresh_work_order(ctx)["total_premium_base_dollars"] == 40000, (
            "Create-then-reject must compensate exactly, leaving no drift")

    def test_premium_base_reconciles_verified_plus_subcontractor(self, api):
        """PRD: "Its `total_premium_base_dollars` — the running exposure base
        — is recomputed on every allocation or certificate mutation as the sum
        of `auditable_payroll_dollars` over the work order's `VERIFIED`
        payroll allocations plus the sum of `included_dollars` over all of its
        subcontractor exposures."
        PRD: "A new exposure starts `INCLUDED` at full value:
        `included_dollars` equals `payments_dollars`, and the work order's
        `total_premium_base_dollars` is recomputed immediately."

        Design: Difficulty/compensating_invariant/verified_payroll_total_reconciles_after_verify_reject_cycle
        """
        ctx = setup_selected_work_order(policy_number="WC-1900",
                                        receive_requests=True)
        add_allocation(ctx, 40000, period_start="2026-01-01T00:00:00Z",
                       period_end="2026-03-31T00:00:00Z", verify=True)
        al2 = add_allocation(ctx, 5000,
                             period_start="2026-04-01T00:00:00Z",
                             period_end="2026-06-30T00:00:00Z")
        get_success_data(api.reject_payroll_allocation(al2["id"],
                                                       ctx["auditor_headers"]))

        add_allocation(ctx, 5000, period_start="2026-04-01T00:00:00Z",
                       period_end="2026-06-30T00:00:00Z", verify=True)
        add_exposure(ctx, subcontractor_name="RiskyCo", payments_dollars=10000)

        total = refresh_work_order(ctx)["total_premium_base_dollars"]
        assert total == 55000, (
            f"VERIFIED 40000 + VERIFIED 5000 + included subcontractor 10000 "
            f"must total 55000, got {total}")


class TestDerivedTotalConsistency:
    def test_immediate_consistency_derived_total(self, api):
        """PRD: "All derived figures are recomputed **within the mutating
        request** — the consistency model is immediate, with no background
        settlement."
        PRD: "Its `total_premium_base_dollars` — the running exposure base —
        is recomputed on every allocation or certificate mutation as the sum
        of `auditable_payroll_dollars` over the work order's `VERIFIED`
        payroll allocations plus the sum of `included_dollars` over all of its
        subcontractor exposures."

        Design: Corner/consistency_model/immediate_consistency_derived_total
        """
        ctx = setup_selected_work_order(policy_number="WC-M1")
        al1 = add_allocation(ctx, 40000)
        assert refresh_work_order(ctx)["total_premium_base_dollars"] == 0, (
            "A DRAFT allocation is excluded from the verified base")

        get_success_data(api.verify_payroll_allocation(al1["id"],
                                                       ctx["auditor_headers"]))
        after = get_success_data(api.get_work_order(ctx["work_order"]["id"],
                                                    MANAGER))
        assert after["total_premium_base_dollars"] == 40000, (
            "The very next read must reflect the recomputed total")


class TestIssuanceBlocking:
    def test_issue_result_blocked_by_draft_allocation(self, api):
        """PRD: "Issuance belongs to an `AuditManager`. It is blocked while
        any payroll allocation of the work order is still `DRAFT`
        (`ERR_DRAFT_ALLOCATIONS_PENDING`)."
        PRD: "Draft allocations are provisional-only material: they feed the
        draft result (§3.7) but block issuance until resolved."

        Design: Corner/validations/issue_with_draft_allocations_pending
        """
        ctx = setup_selected_work_order(policy_number="WC-V2",
                                        receive_requests=True)
        add_allocation(ctx, 40000)  # left DRAFT
        submit_draft(ctx)

        resp = api.issue_result(ctx["work_order"]["id"],
                                ctx["manager"])
        validate_error(resp, ApiErrorId.ERR_DRAFT_ALLOCATIONS_PENDING)
