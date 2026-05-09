"""Concurrency tests for the Research Funding API.

PRD §2.5 (optimistic concurrency), §3.2 (BudgetAdjustment OCC), §3.3 (Reimbursement
mark-paid serialization).
"""
import pytest
import uuid

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    DEPT_HEADERS,
    DEPT_HEADERS_ALT,
    FINANCE_HEADERS,
    FINANCE_HEADERS_ALT,
    create_zero_sum_adjustment,
    dept_approve_adjustment,
    finance_approve_adjustment,
    create_reimbursement,
    create_and_approve_reimbursement,
    make_principal_investigator_headers,
    pi_approve_reimbursement,
    run_race,
    setup_active_project_with_budget,
    setup_project_with_two_budget_items_and_versions,
    submit_adjustment,
    submit_and_dept_approve_adjustment,
    submit_reimbursement,
    validate_error_is_one_of,
    validate_success,
)


class TestBudgetAdjustmentRace:
    """PRD §3.2 budget-adjustment concurrency."""

    def test_two_finance_approvals_race(self, api):
        """PRD §3.2: "Two simultaneous finance-approvals racing on the same adjustment
        serialize on BudgetAdjustment.status: at most one finance-approve succeeds, and
        the loser receives ERR_ALREADY_DECIDED."

        Claim: in a race of two finance-approves on the same adjustment, exactly one
        succeeds and the other returns ERR_ALREADY_DECIDED.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(
            api, item_a_amount=1000.00, item_b_amount=500.00,
        )
        adj = create_zero_sum_adjustment(api, project=project,
                                          lines=[(a["id"], -100.00), (b["id"], 100.00)])
        adj = submit_adjustment(api, adj)
        dept_approve_adjustment(api, adj)
        # Two simultaneous finance-approves on the same adjustment.
        results = run_race(
            lambda: api.finance_approve_budget_adjustment(adj["id"], FINANCE_HEADERS),
            lambda: api.finance_approve_budget_adjustment(adj["id"], FINANCE_HEADERS_ALT),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        loser = outcome["failures"][0]
        # The loser must report ERR_ALREADY_DECIDED.
        body = loser.json()
        loser_err = body.get("data", {}).get("error_id")
        assert loser_err == ApiErrorId.ERR_ALREADY_DECIDED.value, \
            f"Expected ERR_ALREADY_DECIDED on the loser, got {loser_err}"


class TestReimbursementMarkPaidRace:
    """PRD §3.3 reimbursement mark-paid concurrency."""

    def test_two_mark_paid_calls_race(self, api):
        """PRD §3.3: "Two simultaneous mark-paid calls on the same reimbursement serialize
        on Reimbursement.status: at most one PAID transition succeeds, and the loser
        receives ERR_INVALID_STATE."

        Claim: in a race of two mark-paid calls, exactly one succeeds and the loser
        returns ERR_INVALID_STATE.
        """
        project, items = setup_active_project_with_budget(
            api, pi_id="pi-pay-race", funding_source="NATIONAL",
            categories=[("MATERIALS", 1000.00)],
        )
        r = create_and_approve_reimbursement(api, project=project, budget_item=items[0],
                                                amount=200.00,
                                                invoice_number=f"INV-RACE-{uuid.uuid4().hex[:6]}")
        results = run_race(
            lambda: api.mark_paid_reimbursement(r["id"], FINANCE_HEADERS),
            lambda: api.mark_paid_reimbursement(r["id"], FINANCE_HEADERS_ALT),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        loser = outcome["failures"][0]
        body = loser.json()
        loser_err = body.get("data", {}).get("error_id")
        assert loser_err == ApiErrorId.ERR_INVALID_STATE.value, \
            f"Expected ERR_INVALID_STATE on the loser, got {loser_err}"


class TestDeptApproveRace:
    """PRD §3.2 dept-approve concurrency."""

    def test_two_dept_approvals_race(self, api):
        """PRD §3.2: "The same code covers the race in which two department approvers
        act simultaneously on the same adjustment: at most one wins, and the loser
        receives ERR_ALREADY_DECIDED."

        Claim: two simultaneous dept-approves on the same adjustment — exactly one
        succeeds and the loser returns ERR_ALREADY_DECIDED.
        """
        project, a, b = setup_project_with_two_budget_items_and_versions(api)
        adj = create_zero_sum_adjustment(api, project=project,
                                          lines=[(a["id"], -100.00), (b["id"], 100.00)])
        adj = submit_adjustment(api, adj)
        results = run_race(
            lambda: api.dept_approve_budget_adjustment(adj["id"], DEPT_HEADERS),
            lambda: api.dept_approve_budget_adjustment(adj["id"], DEPT_HEADERS_ALT),
        )
        outcome = assert_race_outcome(results, expected_successes=1, expected_failures=1)
        loser = outcome["failures"][0]
        body = loser.json()
        loser_err = body.get("data", {}).get("error_id")
        assert loser_err == ApiErrorId.ERR_ALREADY_DECIDED.value, \
            f"Expected ERR_ALREADY_DECIDED on dept-approve loser, got {loser_err}"
