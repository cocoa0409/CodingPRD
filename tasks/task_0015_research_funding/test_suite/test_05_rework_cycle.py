"""Reimbursement reject-rework cycle: cyclic state machine with rework_count cap.

PRD §3.3 reject-rework loop and rework_count rules.
"""
import pytest
import uuid

from test_helpers import (
    ApiErrorId,
    api_client,
    create_reimbursement,
    dept_approve_reimbursement,
    DEPT_HEADERS,
    finance_approve_reimbursement,
    get_budget_item,
    get_reimbursement,
    make_principal_investigator_headers,
    pi_approve_reimbursement,
    reject_payload,
    setup_active_project_with_budget,
    submit_reimbursement,
    validate_error,
    validate_success,
)


def _do_reject_cycle(api, r, dept_headers):
    """One full reject cycle: submit + pi-approve + dept-approve + reject (DEPT)."""
    submit_reimbursement(api, r)
    r = get_reimbursement(api, r["id"])
    pi_approve_reimbursement(api, r)
    r = get_reimbursement(api, r["id"])
    dept_approve_reimbursement(api, r)
    resp = api.reject_reimbursement(
        r["id"],
        reject_payload(rejection_reason=f"cycle reason {uuid.uuid4().hex[:4]}"),
        dept_headers,
    )
    return validate_success(resp)


class TestRework:
    """PRD §3.3 rework cycle."""

    def test_rework_returns_to_draft_and_increments_count(self, api):
        """PRD §3.3: "The principal investigator may explicitly reset a SUBMITTED
        reimbursement to DRAFT via the rework path — this is allowed only while
        rework_count is strictly less than 3 (otherwise ERR_REWORK_LIMIT_EXCEEDED);
        on success, status returns to DRAFT, rework_count increments by 1, and all
        three of pi_decision, dept_decision, and finance_decision are reset to PENDING."

        Claim: PI rework on a SUBMITTED reimbursement returns it to DRAFT, increments
        rework_count by 1, and resets all three decision fields to PENDING.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-rework-1")
        r = create_reimbursement(api, project=project, budget_item=items[0], amount=100.00)
        from test_helpers import make_principal_investigator_headers
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        api.submit_reimbursement(r["id"], owner)
        resp = api.rework_reimbursement(r["id"], owner)
        data = validate_success(resp)
        assert data["status"] == "DRAFT"
        assert data["rework_count"] == 1
        assert data["pi_decision"] == "PENDING"
        assert data["dept_decision"] == "PENDING"
        assert data["finance_decision"] == "PENDING"

    def test_reject_returns_to_draft_increments_count(self, api, dept_headers):
        """PRD §3.3: "Either a DepartmentApprover or a FinanceOfficer may reject from
        UNDER_REVIEW. Rejection requires that rework_count is strictly less than 3
        (otherwise ERR_REWORK_LIMIT_EXCEEDED) and that the request body carries a
        non-empty rejection_reason (otherwise ERR_REJECTION_REASON_REQUIRED); on
        success, status returns to DRAFT (the rejection-rework cycle is
        DRAFT → SUBMITTED → UNDER_REVIEW → DRAFT), the deciding role's *_decision is
        set to REJECTED, rework_count increments by 1, and rejection_reason is recorded
        from the body."

        # difficulty: non_linear_state_machine/reimbursement_rejection_rework_cycle

        Claim: a dept-reject on UNDER_REVIEW returns reimbursement to DRAFT, increments
        rework_count by 1, sets dept_decision=REJECTED, and records rejection_reason.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-reject-once")
        r = create_reimbursement(api, project=project, budget_item=items[0], amount=100.00)
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        api.submit_reimbursement(r["id"], owner)
        api.pi_approve_reimbursement(r["id"], owner)
        # status now UNDER_REVIEW; perform dept-reject.
        resp = api.reject_reimbursement(
            r["id"],
            reject_payload(rejection_reason="missing receipt evidence"),
            dept_headers,
        )
        data = validate_success(resp)
        assert data["status"] == "DRAFT"
        assert data["rework_count"] == 1
        assert data["dept_decision"] == "REJECTED"
        assert data["rejection_reason"] == "missing receipt evidence"

    def test_rework_cycle_three_iterations(self, api, dept_headers):
        """PRD §3.3: "Either a DepartmentApprover or a FinanceOfficer may reject from
        UNDER_REVIEW. Rejection requires that rework_count is strictly less than 3
        (otherwise ERR_REWORK_LIMIT_EXCEEDED)..."
        PRD §3.3: "When rework_count reaches 3 and a further reject is attempted from
        UNDER_REVIEW, the system performs the terminal automatic transition
        UNDER_REVIEW → REJECTED."

        # difficulty: non_linear_state_machine/reimbursement_rejection_rework_cycle

        Claim: Reimbursement.status visits DRAFT and SUBMITTED multiple times across
        three reject cycles; rework_count reaches 3 after three completed cycles.

        (Note: PRD §3.3 says submit only rejects with ERR_REWORK_LIMIT_EXCEEDED when
        rework_count is "4 or higher"; at rework_count==3, submit is permitted and a
        4th cycle of reject would invoke the terminal auto-transition. We assert only
        the rework_count progression through 3 cycles, which is what PRD pins.)
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-rework-cycle")
        r = create_reimbursement(api, project=project, budget_item=items[0], amount=100.00,
                                  invoice_number=f"INV-CYC-{uuid.uuid4().hex[:6]}")
        # Cycle 1
        cycle1 = _do_reject_cycle(api, r, dept_headers)
        assert cycle1["status"] == "DRAFT"
        assert cycle1["rework_count"] == 1
        # Cycle 2
        r2 = get_reimbursement(api, r["id"])
        cycle2 = _do_reject_cycle(api, r2, dept_headers)
        assert cycle2["status"] == "DRAFT"
        assert cycle2["rework_count"] == 2
        # Cycle 3 — third reject. PRD says rejection requires rework_count<3, and at the
        # third reject rework_count==2 (entering the cycle), so the reject succeeds and
        # rework_count goes to 3. Final state per PRD: DRAFT, rework_count==3.
        r3 = get_reimbursement(api, r["id"])
        cycle3 = _do_reject_cycle(api, r3, dept_headers)
        assert cycle3["status"] == "DRAFT"
        assert cycle3["rework_count"] == 3

    def test_rework_invariant_on_budget_item_spent(self, api, dept_headers):
        """PRD §3.3: "On commit, the reimbursement's amount is added to the linked
        BudgetItem's spent_amount, the item's remaining_amount is recomputed (it equals
        approved_amount minus spent_amount), the item's version increments by 1, and its
        updated_at is refreshed."

        # difficulty: compensating_invariant/reimbursement_rework_invariant_on_budget_remaining

        Claim: as long as the reimbursement never reaches PAID, BudgetItem.spent_amount
        is unchanged across submit→reject→submit→rework cycles.
        """
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-rework-invariant",
            funding_source="NATIONAL",
            categories=[("MATERIALS", 1000.00)],
        )
        item = items[0]
        spent_before = item.get("spent_amount", 0.0)
        remaining_before = item.get("remaining_amount", 1000.00)
        # Create reimbursement of 400, run one reject cycle, then a partial cycle.
        r = create_reimbursement(api, project=project, budget_item=item, amount=400.00,
                                  invoice_number=f"INV-INV-{uuid.uuid4().hex[:6]}")
        # Cycle 1: submit → pi-approve → dept-approve → reject
        _do_reject_cycle(api, r, dept_headers)
        # Cycle 2 (partial): submit → rework
        r = get_reimbursement(api, r["id"])
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        api.submit_reimbursement(r["id"], owner)
        api.rework_reimbursement(r["id"], owner)
        # Read the budget item — spent_amount should be unchanged.
        item_after = get_budget_item(api, item["id"])
        assert item_after.get("spent_amount", 0.0) == pytest.approx(spent_before, abs=0.01), \
            f"BudgetItem.spent_amount must not change while reimbursement never reaches PAID; " \
            f"got {item_after.get('spent_amount')} vs initial {spent_before}"
        assert item_after.get("remaining_amount", 1000.00) == pytest.approx(remaining_before, abs=0.01)
        # Reimbursement.rework_count == 2 (one reject + one PI rework)
        r_after = get_reimbursement(api, r["id"])
        assert r_after["rework_count"] == 2, \
            f"Expected rework_count == 2 (1 reject + 1 rework), got {r_after['rework_count']}"

    def test_reject_requires_rejection_reason(self, api, dept_headers):
        """PRD §3.3: "Either a DepartmentApprover or a FinanceOfficer may reject from
        UNDER_REVIEW. Rejection requires that rework_count is strictly less than 3
        (otherwise ERR_REWORK_LIMIT_EXCEEDED) and that the request body carries a
        non-empty rejection_reason (otherwise ERR_REJECTION_REASON_REQUIRED)..."

        Claim: empty rejection_reason returns ERR_REJECTION_REASON_REQUIRED.
        """
        project, items = setup_active_project_with_budget(api, pi_id="pi-empty-rj")
        r = create_reimbursement(api, project=project, budget_item=items[0], amount=100.00)
        owner = make_principal_investigator_headers(project["principal_investigator_id"])
        api.submit_reimbursement(r["id"], owner)
        api.pi_approve_reimbursement(r["id"], owner)
        resp = api.reject_reimbursement(r["id"], {"rejection_reason": ""}, dept_headers)
        validate_error(resp, ApiErrorId.ERR_REJECTION_REASON_REQUIRED.value)
