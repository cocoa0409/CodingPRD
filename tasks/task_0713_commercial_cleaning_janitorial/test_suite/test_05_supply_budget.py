"""Supply budget conservation, approval gates, and OCC on the budget version."""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_requisition_payload,
    setup_budget_with_requisition, assert_budget_conservation,
    TEST_USERS,
)

_OPS = TEST_USERS["operations_manager_headers"]


class TestBudgetConservation:
    """Difficulty rule: compensating_invariant / budget_conservation_approve_then_cancel."""

    def test_cancel_approved_requisition_credits_budget(self, api):
        """PRD §3.9: "Cancelling an APPROVED requisition is a compensating credit: it
        moves the requisition to CANCELLED, subtracts its amount_cents from the budget's
        committed_cents (preserving the committed-plus-remaining-equals-total
        invariant)".

        Design: Difficulty/compensating_invariant/budget_conservation_approve_then_cancel
        """
        acct, ctr, budget, req, budget_v = setup_budget_with_requisition(
            total_cents=50000, amount_cents=20000, approve=True, legal_name="Inv Co")
        validate_success(api.cancel_requisition(acct["id"], req["id"], _OPS), 200)
        budget_after = validate_success(api.get_supply_budget(acct["id"], budget["id"], _OPS), 200)
        assert budget_after["committed_cents"] == 0
        assert budget_after["remaining_cents"] == 50000

    def test_conservation_invariant_holds_after_approve(self, api):
        """PRD §3.9: "The conservation invariant is that committed plus remaining always
        equals total."
        PRD §3.9: "On approval the budget's committed_cents increases by the
        requisition's amount_cents, remaining_cents is recomputed".

        Design: Difficulty/compensating_invariant/budget_conservation_approve_then_cancel
        """
        acct, ctr, budget, req, budget_v = setup_budget_with_requisition(
            total_cents=50000, amount_cents=20000, approve=True, legal_name="Inv Co 2")
        budget_after = validate_success(api.get_supply_budget(acct["id"], budget["id"], _OPS), 200)
        assert budget_after["committed_cents"] == 20000
        assert budget_after["remaining_cents"] == 30000
        assert_budget_conservation(budget_after)


class TestStateBeforeBudgetPrecedence:
    """Difficulty rule: priority_pair_validation_conflict /
    state_vs_fiscal_approve_terminal_req_over_budget."""

    def test_state_check_wins_over_budget_check(self, api):
        """PRD §3.9: "The requisition must be REQUESTED (ERR_INVALID_STATE), its
        amount_cents must not exceed the budget's remaining_cents, otherwise
        ERR_BUDGET_EXCEEDED".
        PRD §2.7: "then target-state correctness for the transition (ERR_INVALID_STATE),
        then cross-entity state preconditions, then the domain-specific temporal,
        safety, capacity, fiscal, and concurrency checks described below."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_approve_terminal_req_over_budget
        """
        # A CANCELLED requisition for 90000 against remaining 50000: the state check
        # (not REQUESTED) fires before the over-budget check.
        acct, ctr, budget, req, budget_v = setup_budget_with_requisition(
            total_cents=50000, amount_cents=90000, approve=False, legal_name="Budg Co")
        validate_success(api.cancel_requisition(acct["id"], req["id"], _OPS), 200)
        res = api.approve_requisition(
            acct["id"], req["id"], {"expected_supply_budget_version": budget_v}, _OPS)
        validate_error(res, "ERR_INVALID_STATE")

    def test_cancelled_requisition_stays_cancelled(self, api):
        """PRD §3.9: "Cancelling a REQUESTED requisition simply moves it to CANCELLED
        with no budget change, because nothing was ever committed."
        PRD §3.9: "The requisition must be REQUESTED (ERR_INVALID_STATE)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_fiscal_approve_terminal_req_over_budget
        """
        acct, ctr, budget, req, budget_v = setup_budget_with_requisition(
            total_cents=50000, amount_cents=90000, approve=False, legal_name="Budg Co 2")
        validate_success(api.cancel_requisition(acct["id"], req["id"], _OPS), 200)
        validate_error(api.approve_requisition(
            acct["id"], req["id"], {"expected_supply_budget_version": budget_v}, _OPS),
            "ERR_INVALID_STATE")
        req_after = validate_success(api.get_requisition(acct["id"], req["id"], _OPS), 200)
        assert req_after["status"] == "CANCELLED"


class TestSupplyBudgetCornerClaims:
    """Corner sections: errors / cross_cutting_complexity_layers (OCC)."""

    def test_approve_over_remaining_rejected(self, api):
        """PRD §3.9: "its amount_cents must not exceed the budget's remaining_cents,
        otherwise ERR_BUDGET_EXCEEDED".

        Design: Corner/errors/budget_exceeded_on_approve_over_remaining
        """
        acct, ctr, budget, req, budget_v = setup_budget_with_requisition(
            total_cents=50000, amount_cents=60000, approve=False, legal_name="Over Co")
        res = api.approve_requisition(
            acct["id"], req["id"], {"expected_supply_budget_version": budget_v}, _OPS)
        validate_error(res, "ERR_BUDGET_EXCEEDED")
        budget_after = validate_success(api.get_supply_budget(acct["id"], budget["id"], _OPS), 200)
        assert budget_after["committed_cents"] == 0

    def test_stale_budget_version_on_approve_rejected(self, api):
        """PRD §2.9: "the approval is rejected with ERR_STALE_VERSION (HTTP 412),
        preventing the writer from committing funds against a stale view of the
        remaining balance."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_budget_version_on_requisition_approve
        """
        # Budget version captured pre-approval; first approval bumps it; the second
        # approval carries the now-stale version.
        acct, ctr, budget, req1, budget_v0 = setup_budget_with_requisition(
            total_cents=50000, amount_cents=10000, approve=False, legal_name="OCC Co")
        req2 = validate_success(api.create_requisition(
            acct["id"], budget["id"], create_requisition_payload(amount_cents=10000), _OPS), 201)
        # First approval with the fresh version succeeds and bumps budget.version.
        validate_success(api.approve_requisition(
            acct["id"], req1["id"], {"expected_supply_budget_version": budget_v0}, _OPS), 200)
        # Second approval re-using the pre-bump version is stale.
        res = api.approve_requisition(
            acct["id"], req2["id"], {"expected_supply_budget_version": budget_v0}, _OPS)
        validate_error(res, "ERR_STALE_VERSION")
        req2_after = validate_success(api.get_requisition(acct["id"], req2["id"], _OPS), 200)
        assert req2_after["status"] == "REQUESTED"
