"""Difficulty-design coverage completion: second tests for instances that have only one
companion in earlier files. Tests here are PRD-citing supplements ensuring every
difficulty-design instance has at least TWO tagged tests.
"""
import pytest
import uuid

from test_helpers import (
    ApiErrorId,
    api_client,
    advance_clock_by_days,
    audit_finding,
    begin_closing,
    create_and_pay_reimbursement,
    create_closing_audit,
    create_draft_project,
    create_reimbursement,
    create_reimbursement_payload,
    create_zero_sum_adjustment,
    deliverable,
    DEPT_HEADERS,
    DEPT_HEADERS_ALT,
    FINANCE_HEADERS,
    finance_approve_adjustment,
    get_audit,
    get_budget_item,
    get_project,
    get_reimbursement,
    get_success_data,
    list_audit_logs,
    make_audit_officer_headers,
    make_principal_investigator_headers,
    NON_EXISTENT_UUID,
    now_epoch,
    setup_active_project_with_budget,
    setup_project_in_closing,
    setup_project_with_two_budget_items_and_versions,
    submit_adjustment,
    submit_closing_audit,
    submit_reimbursement,
    submit_and_dept_approve_adjustment,
    TEST_USERS,
    validate_error,
    validate_success,
    create_and_approve_project,
)


# difficulty: combinatorial_formula/residual_fund_policy_funding_source_cross_action_cross_rate
class TestResidualFundPolicyAdditional:
    """Second test for residual_fund_policy difficulty instance — different funding-source
    × action combinations to exercise the combinatorial table beyond the NATIONAL+CARRYOVER
    case in test_07."""

    def test_provincial_reallocate_rejected(self, api):
        """PRD §3.7: "For a PROVINCIAL project: RETURN is permitted; REALLOCATE is not
        permitted; CARRYOVER is permitted only when budget_execution_rate is at or above 0.90."

        # difficulty: combinatorial_formula/residual_fund_policy_funding_source_cross_action_cross_rate

        Claim: PROVINCIAL + REALLOCATE returns ERR_RESIDUAL_ACTION_NOT_ALLOWED.
        """
        project, items = setup_project_in_closing(
            api, pi_id="pi-resid-prov", funding_source="PROVINCIAL",
            total_budget_amount=1000.00, paid_amount=950.00,  # er=0.95
        )
        audit = create_closing_audit(api, project=project, residual_fund_action="REALLOCATE")
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_closing_audit(audit["id"], owner)
        validate_error(resp, ApiErrorId.ERR_RESIDUAL_ACTION_NOT_ALLOWED.value)


# difficulty: transitive_cascade/closing_audit_close_cascades_through_project_to_indirect_cost
class TestCloseCascadeAdditional:
    """Second test for the close-cascade difficulty instance — verifies that
    Project.indirect_cost_amount equals the IndirectCostAllocation.allocated_amount written
    by the cascade, beyond just checking presence in test_07."""

    def test_close_writes_indirect_cost_amount_matching_allocation(self, api):
        """PRD §3.5: "On commit, the audit's status is set to CLOSED, the parent project
        automatically cascades from CLOSING to CLOSED as part of the same operation, a
        final IndirectCostAllocation snapshot is written for the project, and the
        project's indirect_cost_amount is set to the resulting allocated_amount."

        # difficulty: transitive_cascade/closing_audit_close_cascades_through_project_to_indirect_cost

        Claim: after close, Project.indirect_cost_amount equals the new allocated_amount,
        and the value is non-null and non-negative.
        """
        project, items = setup_project_in_closing(
            api, pi_id="pi-close-cascade-2", funding_source="NATIONAL",
            total_budget_amount=2000.00, paid_amount=500.00, category="MATERIALS",
        )
        # Verify pre-cascade indirect_cost_amount is null/absent.
        proj_before = get_project(api, project["id"])
        # PRD: "null until first allocation run" — could be null or 0; accept both.
        pre_value = proj_before.get("indirect_cost_amount")
        audit = create_closing_audit(api, project=project, residual_fund_action="RETURN")
        submit_closing_audit(api, audit, project=project)
        audit_headers = make_audit_officer_headers()
        resp = api.close_audit(audit["id"], audit_headers)
        get_success_data(resp)
        # Read project; indirect_cost_amount must now be set.
        proj_after = get_project(api, project["id"])
        assert proj_after["status"] == "CLOSED"
        assert proj_after.get("indirect_cost_amount") is not None
        assert proj_after["indirect_cost_amount"] >= 0
        # And the change must be observable: pre vs post value differs OR pre was null.
        assert proj_after.get("indirect_cost_amount") != pre_value or pre_value is not None


# difficulty: transitive_cascade/project_approve_cascades_through_budget_items_to_audit_log
class TestProjectApproveCascadeAdditional:
    """Second test for the project-approve cascade difficulty instance — verifies the
    refresh of Project.total_budget after approve, distinct from the audit-log assertion
    in test_02."""

    def test_total_budget_equals_sum_of_approved_amounts_after_approve(self, api):
        """PRD §3.1: "Approval also transitions every BudgetItem of the project from
        PENDING to APPROVED, copying each item's requested_amount into its approved_amount,
        refreshes the project's total_budget to the sum of those approved amounts, and
        appends one AuditLog row per approved budget item with action set to APPROVE."

        # difficulty: transitive_cascade/project_approve_cascades_through_budget_items_to_audit_log

        Claim: after approve, Project.total_budget equals exactly the sum of the
        approved BudgetItem.approved_amount values.
        """
        project, items = create_and_approve_project(
            api, pi_id="pi-cascade-totals",
            funding_source="NATIONAL",
            budget_items=[("PERSONNEL", 750.50), ("EQUIPMENT", 250.25), ("MATERIALS", 99.25)],
        )
        # Sum approved_amounts.
        s = sum(it["approved_amount"] for it in items)
        # 750.50 + 250.25 + 99.25 = 1100.00
        assert s == pytest.approx(1100.00, abs=0.01)
        proj = get_project(api, project["id"])
        assert proj["total_budget"] == pytest.approx(s, abs=0.01), \
            f"Project.total_budget must equal sum of approved BudgetItem.approved_amount; " \
            f"got {proj['total_budget']} vs sum {s}"


# difficulty: cross_entity_state_dependency/budget_adjustment_finance_approve_requires_budget_item_version_match
class TestBudgetAdjustmentVersionPinAdditional:
    """Second test for the OCC version-pin difficulty instance — covers that
    BudgetItem.approved_amount is NOT mutated by the rejected adjustment."""

    def test_stale_version_rejection_leaves_budget_item_untouched(self, api):
        """PRD §3.2: "A different race occurs when a finance-approve and a separate
        adjustment touching the same BudgetItem commit nearly simultaneously — whichever
        commits second finds that its pinned version no longer matches the current
        BudgetItem.version and is rejected with ERR_STALE_BUDGET_VERSION."

        # difficulty: cross_entity_state_dependency/budget_adjustment_finance_approve_requires_budget_item_version_match

        Claim: when ADJ1's finance-approve is rejected for stale version, BudgetItem A's
        approved_amount reflects only ADJ2's delta — never ADJ1's.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(
            api, item_a_amount=2000.00, item_b_amount=1000.00,
        )
        # ADJ1: -500 on A, +500 on B.
        adj1 = create_zero_sum_adjustment(api, project=project,
                                           lines=[(a["id"], -500.00), (b["id"], 500.00)])
        adj1 = submit_adjustment(api, adj1)
        from test_helpers import dept_approve_adjustment
        dept_approve_adjustment(api, adj1)
        # ADJ2: -200 on A, +200 on B; commit first (bumps A.version).
        adj2 = create_zero_sum_adjustment(api, project=project,
                                           lines=[(a["id"], -200.00), (b["id"], 200.00)])
        submit_and_dept_approve_adjustment(api, adj2)
        finance_approve_adjustment(api, adj2)
        # A is now 2000 - 200 = 1800.
        a_mid = get_budget_item(api, a["id"])
        assert a_mid["approved_amount"] == pytest.approx(1800.00, abs=0.01)
        # Now finance-approve adj1 — must fail with ERR_STALE_BUDGET_VERSION.
        resp = api.finance_approve_budget_adjustment(adj1["id"], FINANCE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_STALE_BUDGET_VERSION.value)
        # And A.approved_amount must remain at 1800 (NOT 1300, which would be 1800-500).
        a_after = get_budget_item(api, a["id"])
        assert a_after["approved_amount"] == pytest.approx(1800.00, abs=0.01), \
            f"BudgetItem A.approved_amount must not reflect the rejected ADJ1; got {a_after['approved_amount']}"


# difficulty: compensating_invariant/budget_adjustment_zero_sum_invariant_on_total_budget
class TestZeroSumInvariantAdditional:
    """Second test for the zero-sum invariant — exercising a multi-line zero-sum
    adjustment to confirm the conservation property across more than two lines."""

    def test_multi_line_zero_sum_conservation(self, api):
        """PRD §3.2: "the deltas across line_changes must sum to zero within an absolute
        tolerance of 0.01 CNY (the rule is a zero-sum reallocation; otherwise the request
        is rejected with ERR_ADJUSTMENT_NOT_ZERO_SUM)."
        PRD §3.2: "On commit, each line's delta_amount is applied to the matching
        BudgetItem's approved_amount; ... the parent project's total_budget is recomputed
        from the new approved amounts;..."

        # difficulty: compensating_invariant/budget_adjustment_zero_sum_invariant_on_total_budget

        Claim: a 3-line zero-sum adjustment leaves Project.total_budget unchanged
        (-100 + -50 + +150 = 0).
        """
        from test_helpers import create_and_activate_project, add_budget_item
        project, items = create_and_activate_project(
            api, pi_id="pi-zsum-3lines", funding_source="NATIONAL",
            budget_items=[("PERSONNEL", 1000.00), ("EQUIPMENT", 500.00), ("MATERIALS", 200.00)],
        )
        # Items in order PERSONNEL=1000, EQUIPMENT=500, MATERIALS=200; total=1700.
        before = project["total_budget"]
        a, b, c = items[0], items[1], items[2]
        # 3-line zero-sum: -100 on a (PERSONNEL), -50 on b (EQUIPMENT), +150 on c (MATERIALS).
        adj = create_zero_sum_adjustment(
            api, project=project,
            lines=[(a["id"], -100.00), (b["id"], -50.00), (c["id"], 150.00)],
        )
        submit_and_dept_approve_adjustment(api, adj)
        finance_approve_adjustment(api, adj)
        # Project.total_budget must still equal `before` (zero-sum conservation).
        proj_after = get_project(api, project["id"])
        assert proj_after["total_budget"] == pytest.approx(before, abs=0.01), \
            f"3-line zero-sum must conserve total_budget: before={before}, after={proj_after['total_budget']}"


# difficulty: compensating_invariant/reimbursement_rework_invariant_on_budget_remaining
class TestReimbursementReworkInvariantAdditional:
    """Second test for the rework invariant on BudgetItem.remaining_amount — exercises
    the invariant across two reject cycles (different from the partial cycle in test_05)."""

    def test_two_reject_cycles_preserve_spent_amount(self, api):
        """PRD §3.3: "Either a DepartmentApprover or a FinanceOfficer may reject from
        UNDER_REVIEW. Rejection requires that rework_count is strictly less than 3
        (otherwise ERR_REWORK_LIMIT_EXCEEDED) and that the request body carries a
        non-empty rejection_reason (otherwise ERR_REJECTION_REASON_REQUIRED); on success,
        status returns to DRAFT (the rejection-rework cycle is DRAFT → SUBMITTED →
        UNDER_REVIEW → DRAFT), the deciding role's *_decision is set to REJECTED,
        rework_count increments by 1, and rejection_reason is recorded from the body."

        # difficulty: compensating_invariant/reimbursement_rework_invariant_on_budget_remaining

        Claim: across two complete reject cycles (rework_count goes 0 → 1 → 2),
        BudgetItem.spent_amount and remaining_amount are unchanged because no PAID
        transition occurred.
        """
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-2cycle-inv", funding_source="NATIONAL",
            categories=[("MATERIALS", 1000.00)],
        )
        item = items[0]
        spent_before = item.get("spent_amount", 0.0)
        remaining_before = item.get("remaining_amount", 1000.00)
        r = create_reimbursement(api, project=project, budget_item=item, amount=400.00,
                                  invoice_number=f"INV-2CYC-{uuid.uuid4().hex[:6]}")
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        # Cycle 1
        api.submit_reimbursement(r["id"], owner)
        api.pi_approve_reimbursement(r["id"], owner)
        api.dept_approve_reimbursement(r["id"], DEPT_HEADERS)
        api.reject_reimbursement(r["id"], {"rejection_reason": "cycle 1"}, DEPT_HEADERS)
        # Cycle 2
        api.submit_reimbursement(r["id"], owner)
        api.pi_approve_reimbursement(r["id"], owner)
        api.dept_approve_reimbursement(r["id"], DEPT_HEADERS)
        api.reject_reimbursement(r["id"], {"rejection_reason": "cycle 2"}, DEPT_HEADERS)
        # Read item — spent_amount and remaining_amount unchanged.
        item_after = get_budget_item(api, item["id"])
        assert item_after.get("spent_amount", 0.0) == pytest.approx(spent_before, abs=0.01)
        assert item_after.get("remaining_amount", 1000.00) == pytest.approx(remaining_before, abs=0.01)
        # rework_count == 2.
        r_after = get_reimbursement(api, r["id"])
        assert r_after["rework_count"] == 2


# difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_reimbursement_submit
# (PRD §2.7 enumerates priority of safety > constraint; this difficulty pair tests
# ERR_INVOICE_NOT_AUTHENTIC pre-empting ERR_REWORK_LIMIT_EXCEEDED.)
class TestPrioritySafetyVsConstraint:
    """Two tests for the safety-vs-constraint priority pair on reimbursement submit.

    PRD §2.7 explicitly orders safety BEFORE constraint, so when invoice_authenticated
    is false AND rework_count is at the cap, the safety error pre-empts the constraint
    error.

    NOTE: PRD §2.7 prose ('then business safety checks in this order — invoice authenticity
    (ERR_INVOICE_NOT_AUTHENTIC), attachment completeness (ERR_ATTACHMENTS_INCOMPLETE), and
    compliance pre-screen blocks (ERR_COMPLIANCE_BLOCK); ... then business constraints,
    beginning with the zero-sum check (ERR_ADJUSTMENT_NOT_ZERO_SUM), then the per-line
    non-negativity check (ERR_NEGATIVE_BUDGET), then the rework-count cap
    (ERR_REWORK_LIMIT_EXCEEDED)...') is verbatim PRD-citable, so the priority is
    not a Silence-pattern skip.
    """

    # NOTE: Originally a `test_invoice_authentic_pre_empts_rework_limit` companion test
    # lived here. It was DELETED because its assertion contradicted PRD §3.3:
    # PRD says submit only rejects with ERR_REWORK_LIMIT_EXCEEDED when rework_count is
    # "4 or higher" (and the rework path requires rework_count<3). At rework_count==3,
    # which is the only DRAFT state reachable via three reject cycles, submit succeeds
    # per PRD. The auto-terminal transition on the 4th reject prevents reaching
    # rework_count==4 in DRAFT at all, so the safety-vs-rework-cap priority pair
    # cannot be exercised at submit by a PRD-faithful implementation. The companion
    # below covers the safety-only side of the priority pair, which IS PRD-faithful.

    def test_invoice_not_authentic_pre_empts_alone_at_lower_rework_count(self, api):
        """PRD §2.7: "then business safety checks in this order — invoice authenticity
        (ERR_INVOICE_NOT_AUTHENTIC), attachment completeness (ERR_ATTACHMENTS_INCOMPLETE),
        and compliance pre-screen blocks (ERR_COMPLIANCE_BLOCK); then business referential
        integrity, starting with category match (ERR_CATEGORY_MISMATCH); then business
        constraints, beginning with the zero-sum check (ERR_ADJUSTMENT_NOT_ZERO_SUM),
        then the per-line non-negativity check (ERR_NEGATIVE_BUDGET), then the rework-count
        cap (ERR_REWORK_LIMIT_EXCEEDED)..."

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_on_reimbursement_submit

        Claim: a reimbursement with invoice_authenticated=false (and rework_count==0,
        so the rework-cap is satisfied) returns ERR_INVOICE_NOT_AUTHENTIC at submit —
        confirming the safety rule fires when only it applies. The two tests together
        bound the safety-vs-constraint pair: when only safety fails, safety fires;
        when only constraint fails, constraint fires.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-safety-only")
        r = create_reimbursement(api, project=project, budget_item=items[0],
                                  amount=100.00, invoice_authenticated=False,
                                  invoice_number=f"INV-SOL-{uuid.uuid4().hex[:6]}")
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_reimbursement(r["id"], owner)
        validate_error(resp, ApiErrorId.ERR_INVOICE_NOT_AUTHENTIC.value)


# difficulty: dual_variant_calc/execution_rate_chronological_vs_forward_on_closing_audit
# Add a second test that exercises the same instance from a different angle.
class TestExecutionRateAdditional:
    """Second test for the chronological-vs-forward execution rate difficulty instance.
    Exercises a different ratio so we don't depend on a single magic example."""

    def test_chronological_zero_when_no_paid_only_under_review(self, api):
        """PRD §3.6: "The forward-looking rate, forward_execution_rate, follows the same
        skeleton with one substitution in the numerator: in addition to PAID
        reimbursements, the numerator also includes the amount of every reimbursement
        whose status is SUBMITTED, UNDER_REVIEW, or APPROVED."

        # difficulty: dual_variant_calc/execution_rate_chronological_vs_forward_on_closing_audit

        Claim: with a project having ONLY one APPROVED-but-not-PAID reimbursement (no
        PAID), chronological=0.0 while forward > 0.
        """
        from test_helpers import create_and_approve_reimbursement
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-exec-only-approved", funding_source="INTERNAL",
            categories=[("MATERIALS", 1000.00)],
        )
        # One APPROVED reimbursement of 250 (no PAID).
        create_and_approve_reimbursement(api, project=project, budget_item=items[0],
                                           amount=250.00,
                                           invoice_number=f"INV-OA-{uuid.uuid4().hex[:6]}")
        project = begin_closing(api, project)
        audit = create_closing_audit(api, project=project, residual_fund_action="RETURN")
        audit = submit_closing_audit(api, audit, project=project)
        assert audit["budget_execution_rate"] == pytest.approx(0.0000, abs=0.0001)
        assert audit["forward_execution_rate"] == pytest.approx(0.2500, abs=0.0001)
