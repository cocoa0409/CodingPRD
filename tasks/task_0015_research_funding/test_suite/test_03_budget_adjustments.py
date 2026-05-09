"""Budget adjustment workflow tests: zero-sum, version pinning, multi-step approval.

PRD §3.2 (active operations: budget adjustments).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_zero_sum_adjustment,
    dept_approve_adjustment,
    dept_approve_reimbursement,
    finance_approve_adjustment,
    finance_approve_reimbursement,
    get_budget_item,
    line_change,
    make_principal_investigator_headers,
    pi_approve_reimbursement,
    reject_payload,
    setup_active_project_with_budget,
    setup_project_with_two_budget_items_and_versions,
    submit_adjustment,
    submit_and_dept_approve_adjustment,
    create_budget_adjustment_payload,
    create_reimbursement,
    submit_reimbursement,
    validate_error,
    validate_success,
)


class TestAdjustmentSubmit:
    """PRD §3.2 submission preconditions."""

    def test_submit_requires_active_project(self, api):
        """PRD §3.2: "First, the parent project's status must be ACTIVE, otherwise the
        request is rejected with ERR_PROJECT_NOT_ACTIVE."

        Claim: submit on a non-ACTIVE project returns ERR_PROJECT_NOT_ACTIVE.
        """
        from test_helpers import create_and_approve_project
        # Project APPROVED but not yet activated.
        project, items = create_and_approve_project(
            api, pi_id="pi-adj-not-active",
            funding_source="NATIONAL",
            budget_items=[("MATERIALS", 1000.00), ("EQUIPMENT", 500.00)],
            start_offset_days=365,
        )
        adj = create_zero_sum_adjustment(api, project=project,
                                          lines=[(items[0]["id"], -100.00),
                                                  (items[1]["id"], 100.00)],
                                          pi_id=project["principal_investigator_id"])
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_budget_adjustment(adj["id"], headers)
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ACTIVE.value)

    def test_submit_zero_sum_violation(self, api):
        """PRD §3.2: "the deltas across line_changes must sum to zero within an absolute
        tolerance of 0.01 CNY (the rule is a zero-sum reallocation; otherwise the request
        is rejected with ERR_ADJUSTMENT_NOT_ZERO_SUM)."

        Claim: deltas summing to a non-zero amount return ERR_ADJUSTMENT_NOT_ZERO_SUM.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(api)
        adj = create_zero_sum_adjustment(
            api, project=project,
            lines=[(a["id"], -200.00), (b["id"], 100.00)],  # sum = -100, not zero
        )
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_budget_adjustment(adj["id"], headers)
        validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_NOT_ZERO_SUM.value)

    def test_submit_negative_budget_violation(self, api):
        """PRD §3.2: "for each line, the affected BudgetItem's current approved_amount
        plus the proposed delta_amount must be at or above zero (otherwise ERR_NEGATIVE_BUDGET)."

        Claim: a delta that would drive approved_amount below zero returns ERR_NEGATIVE_BUDGET.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(
            api, item_a_amount=100.00, item_b_amount=500.00,
        )
        # -200 on a (currently 100) drives it to -100; +200 on b balances zero-sum.
        adj = create_zero_sum_adjustment(
            api, project=project,
            lines=[(a["id"], -200.00), (b["id"], 200.00)],
        )
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_budget_adjustment(adj["id"], headers)
        validate_error(resp, ApiErrorId.ERR_NEGATIVE_BUDGET.value)

    def test_submit_justification_too_short(self, api):
        """PRD §3.2: "justification must be at least 20 characters long
        (otherwise ERR_JUSTIFICATION_TOO_SHORT)."

        Claim: short justification returns ERR_JUSTIFICATION_TOO_SHORT.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(api)
        adj = create_zero_sum_adjustment(
            api, project=project,
            lines=[(a["id"], -100.00), (b["id"], 100.00)],
            justification="too short",
        )
        headers = make_principal_investigator_headers(project["principal_investigator_id"])
        resp = api.submit_budget_adjustment(adj["id"], headers)
        validate_error(resp, ApiErrorId.ERR_JUSTIFICATION_TOO_SHORT.value)

    def test_submit_captures_pinned_versions(self, api):
        """PRD §3.2: "On a successful submission the adjustment's status advances to
        UNDER_REVIEW, pi_decision is set to APPROVED, and the system captures a snapshot
        of every affected budget item's current version into pinned_budget_versions —
        a map keyed by budget_item_id."

        Claim: after submit, status=UNDER_REVIEW and pinned_budget_versions includes
        every affected budget_item_id.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(api)
        adj = create_zero_sum_adjustment(
            api, project=project,
            lines=[(a["id"], -100.00), (b["id"], 100.00)],
        )
        adj = submit_adjustment(api, adj)
        assert adj["status"] == "UNDER_REVIEW"
        assert adj["pi_decision"] == "APPROVED"
        # pinned_budget_versions captured for both items
        pinned = adj.get("pinned_budget_versions", {})
        assert a["id"] in pinned, f"pinned_budget_versions missing item A: {pinned}"
        assert b["id"] in pinned, f"pinned_budget_versions missing item B: {pinned}"


class TestAdjustmentApprovalChain:
    """PRD §3.2 multi-step approval."""

    def test_dept_approve_already_decided(self, api):
        """PRD §3.2: "The precondition is that dept_decision is currently PENDING — a
        second department approval against an already-decided adjustment is rejected
        with ERR_ALREADY_DECIDED."

        Claim: a second dept-approve on an already-approved adjustment returns ERR_ALREADY_DECIDED.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(api)
        adj = create_zero_sum_adjustment(api, project=project,
                                          lines=[(a["id"], -100.00), (b["id"], 100.00)])
        adj = submit_adjustment(api, adj)
        dept_approve_adjustment(api, adj)
        from test_helpers import DEPT_HEADERS
        resp = api.dept_approve_budget_adjustment(adj["id"], DEPT_HEADERS)
        validate_error(resp, ApiErrorId.ERR_ALREADY_DECIDED.value)

    def test_finance_approve_requires_dept_approved(self, api):
        """PRD §3.2: "Finance approval requires that dept_decision already equals APPROVED
        (otherwise ERR_DEPT_DECISION_PENDING)..."

        Claim: finance-approve before dept-approve returns ERR_DEPT_DECISION_PENDING.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(api)
        adj = create_zero_sum_adjustment(api, project=project,
                                          lines=[(a["id"], -100.00), (b["id"], 100.00)])
        adj = submit_adjustment(api, adj)
        from test_helpers import FINANCE_HEADERS
        resp = api.finance_approve_budget_adjustment(adj["id"], FINANCE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_DEPT_DECISION_PENDING.value)

    def test_finance_approve_commits_deltas(self, api):
        """PRD §3.2: "On commit, each line's delta_amount is applied to the matching
        BudgetItem's approved_amount; each affected BudgetItem's version increments by 1
        and its updated_at is refreshed; the parent project's total_budget is recomputed
        from the new approved amounts..."

        # difficulty: compensating_invariant/budget_adjustment_zero_sum_invariant_on_total_budget

        Claim: finance-approve applies deltas, BudgetItem.version increments, total_budget
        unchanged (zero-sum conservation).
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(
            api, item_a_amount=1000.00, item_b_amount=500.00,
        )
        # Capture pre-state
        budget_before = project["total_budget"]
        version_a_before = a["version"]
        version_b_before = b["version"]
        # -300 on A; +300 on B (zero-sum).
        adj = create_zero_sum_adjustment(
            api, project=project,
            lines=[(a["id"], -300.00), (b["id"], 300.00)],
        )
        submit_and_dept_approve_adjustment(api, adj)
        adj_after = finance_approve_adjustment(api, adj)
        assert adj_after["status"] == "APPROVED"
        # Read back budget items to verify deltas applied + version bump
        a_after = get_budget_item(api, a["id"])
        b_after = get_budget_item(api, b["id"])
        assert a_after["approved_amount"] == pytest.approx(700.00, abs=0.01)
        assert b_after["approved_amount"] == pytest.approx(800.00, abs=0.01)
        assert a_after["version"] == version_a_before + 1
        assert b_after["version"] == version_b_before + 1
        # Project.total_budget conserved (PRD §3.2: "the parent project's total_budget is
        # recomputed from the new approved amounts" — and the deltas sum to zero).
        from test_helpers import get_project
        project_after = get_project(api, project["id"])
        assert project_after["total_budget"] == pytest.approx(budget_before, abs=0.01), (
            f"total_budget conservation violated: before={budget_before}, after={project_after['total_budget']}"
        )

    def test_finance_approve_stale_version(self, api):
        """PRD §3.2: "...for every line the current BudgetItem.version still equals the
        value pinned in pinned_budget_versions[budget_item_id] (otherwise ERR_STALE_BUDGET_VERSION)..."

        # difficulty: cross_entity_state_dependency/budget_adjustment_finance_approve_requires_budget_item_version_match

        Claim: when an intervening adjustment bumps BudgetItem.version after submit,
        finance-approve on the original adjustment returns ERR_STALE_BUDGET_VERSION.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(
            api, item_a_amount=1000.00, item_b_amount=500.00,
        )
        # ADJ1: PI submits; pins A.version=v, B.version=v
        adj1 = create_zero_sum_adjustment(api, project=project,
                                           lines=[(a["id"], -100.00), (b["id"], 100.00)])
        adj1 = submit_adjustment(api, adj1)
        dept_approve_adjustment(api, adj1)
        # ADJ2 — concurrent: also touches A only.
        adj2 = create_zero_sum_adjustment(api, project=project,
                                           lines=[(a["id"], -50.00), (b["id"], 50.00)])
        submit_and_dept_approve_adjustment(api, adj2)
        finance_approve_adjustment(api, adj2)  # bumps A.version
        # Now finance-approve adj1 — A.version drifted from pinned snapshot.
        from test_helpers import FINANCE_HEADERS
        resp = api.finance_approve_budget_adjustment(adj1["id"], FINANCE_HEADERS)
        validate_error(resp, ApiErrorId.ERR_STALE_BUDGET_VERSION.value)
        # And ADJ1 must still be UNDER_REVIEW (rejection was clean).
        from test_helpers import api_client as _ac, get_success_data
        adj1_after = get_success_data(_ac.get_budget_adjustment(adj1["id"], FINANCE_HEADERS))
        assert adj1_after["status"] == "UNDER_REVIEW", \
            f"After STALE rejection, ADJ1.status should remain UNDER_REVIEW, got {adj1_after['status']}"
        # And A's approved_amount should reflect adj2 only (1000 - 50 = 950).
        a_after = get_budget_item(api, a["id"])
        assert a_after["approved_amount"] == pytest.approx(950.00, abs=0.01), \
            f"BudgetItem A.approved_amount unchanged by ADJ1, only ADJ2 applied: got {a_after['approved_amount']}"


class TestAdjustmentReject:
    """PRD §3.2 rejection."""

    def test_reject_requires_rejection_reason(self, api, dept_headers):
        """PRD §3.2: "The reject endpoint accepts a body field rejection_reason, which
        is required and surfaced via ERR_REJECTION_REASON_REQUIRED when missing or empty."

        Claim: reject without rejection_reason returns ERR_REJECTION_REASON_REQUIRED.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(api)
        adj = create_zero_sum_adjustment(api, project=project,
                                          lines=[(a["id"], -100.00), (b["id"], 100.00)])
        adj = submit_adjustment(api, adj)
        resp = api.reject_budget_adjustment(adj["id"], {"rejection_reason": ""}, dept_headers)
        validate_error(resp, ApiErrorId.ERR_REJECTION_REASON_REQUIRED.value)

    def test_reject_no_mutation_to_budget_items(self, api, dept_headers):
        """PRD §3.2: "Rejection sets the deciding role's *_decision field to REJECTED
        and performs no mutation to any BudgetItem."

        Claim: after reject, BudgetItem.approved_amount is unchanged.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(
            api, item_a_amount=1000.00, item_b_amount=500.00,
        )
        adj = create_zero_sum_adjustment(api, project=project,
                                          lines=[(a["id"], -200.00), (b["id"], 200.00)])
        adj = submit_adjustment(api, adj)
        resp = api.reject_budget_adjustment(adj["id"],
                                              reject_payload(rejection_reason="Not justified."),
                                              dept_headers)
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
        a_after = get_budget_item(api, a["id"])
        b_after = get_budget_item(api, b["id"])
        assert a_after["approved_amount"] == pytest.approx(1000.00, abs=0.01)
        assert b_after["approved_amount"] == pytest.approx(500.00, abs=0.01)
