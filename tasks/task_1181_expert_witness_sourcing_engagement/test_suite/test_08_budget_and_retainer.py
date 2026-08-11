"""Fiscal boundary precision and the retainer conservation invariant."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    assert_engagement, assert_retainer_invariant, ApiErrorId,
    submit_invoice, approve_invoice, terminate_engagement,
    setup_active_engagement,
    TEST_USERS,
)

CM = TEST_USERS["case_manager_headers"]
BILLING = TEST_USERS["billing_reviewer_headers"]


class TestBudgetBoundary:

    def _setup_budget_boundary(self, api):
        """Case budget 700000; invoice1 640000 APPROVED; invoice2 60000 SUBMITTED; invoice3
        (1 cent expense-only) SUBMITTED."""
        sc = setup_active_engagement(case_overrides={"budget_cents": 700_000},
                                     engagement_overrides={"expense_cap_cents": 50_000})
        eid = sc["expert"]["id"]
        gid = sc["engagement"]["id"]
        inv1 = submit_invoice(gid, eid,
                              [{"kind": "PREP", "hours": 10}, {"kind": "TESTIMONY", "hours": 4},
                               {"kind": "TRAVEL_TIME", "hours": 2}], 640_000)
        approve_invoice(inv1["id"])
        inv2 = submit_invoice(gid, eid, [{"kind": "PREP", "hours": 1.5}], 60_000,
                              period_start="2026-05-11T00:00:00Z",
                              period_end="2026-05-15T00:00:00Z")
        inv3 = submit_invoice(gid, eid, [], 1, travel_expense_cents=1,
                              period_start="2026-05-18T00:00:00Z",
                              period_end="2026-05-22T00:00:00Z")
        return sc, inv2, inv3

    def test_approve_exactly_at_remaining_budget_passes(self, api):
        """PRD §3.7: "the invoice's `computed_total_cents` must not exceed the case's
        remaining budget, defined as `budget_cents` minus `actuals_paid_cents` minus
        `approved_outstanding_cents`; an invoice exactly equal to the remaining budget
        passes, while exceeding it fails with `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/budget_exact_remaining_approve
        """
        sc, inv2, inv3 = self._setup_budget_boundary(api)
        approved = validate_success(api.approve_invoice(inv2["id"], BILLING), 200)
        assert approved["status"] == "APPROVED", "60000 == remaining 60000: equality passes"

    def test_one_cent_over_remaining_rejected(self, api):
        """PRD §3.7: "an invoice exactly equal to the remaining budget passes, while
        exceeding it fails with `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/budget_exact_remaining_approve
        """
        sc, inv2, inv3 = self._setup_budget_boundary(api)
        validate_success(api.approve_invoice(inv2["id"], BILLING), 200)

        res = api.approve_invoice(inv3["id"], BILLING)
        validate_error(res, ApiErrorId.ERR_BUDGET_EXCEEDED)

        case = validate_success(api.get_case(sc["case"]["id"], CM), 200)
        assert case["approved_outstanding_cents"] == 700_000, "rejected approval adds nothing"


class TestRetainerConservation:

    def _setup_funded_and_drawn(self, api):
        """ACTIVE engagement: retainer 300000 fully funded; one invoice (PREP 2.5h =
        100000) approved."""
        sc = setup_active_engagement(engagement_overrides={"retainer_cents": 300_000})
        inv = submit_invoice(sc["engagement"]["id"], sc["expert"]["id"],
                             [{"kind": "PREP", "hours": 2.5}], 100_000)
        approve_invoice(inv["id"])
        return sc

    def test_ledger_after_fund_and_approve(self, api):
        """PRD §2.8: "`retainer_funded_cents` records the total the client has funded;
        `retainer_drawn_cents` records the total applied to approved invoices and
        cancellation fees" and "One conservation invariant holds at all times: the funded
        amount always equals the sum of the drawn, refunded, and remaining amounts, and the
        remaining amount never goes negative."

        Design: Difficulty/compensating_invariant/retainer_funded_equals_drawn_refunded_remaining
        """
        sc = self._setup_funded_and_drawn(api)
        engagement = validate_success(api.get_engagement(sc["engagement"]["id"], CM), 200)
        assert engagement["retainer_funded_cents"] == 300_000
        assert engagement["retainer_drawn_cents"] == 100_000
        assert engagement["retainer_refunded_cents"] == 0
        assert engagement["retainer_remaining_cents"] == 200_000
        assert_retainer_invariant(engagement)

    def test_termination_refund_completes_the_conservation(self, api):
        """PRD §3.8: "The remaining retainer — funded minus drawn minus any amount already
        refunded — moves into `retainer_refunded_cents`."
        PRD §2.8: "One conservation invariant holds at all times: the funded amount always
        equals the sum of the drawn, refunded, and remaining amounts, and the remaining
        amount never goes negative."

        Design: Difficulty/compensating_invariant/retainer_funded_equals_drawn_refunded_remaining
        """
        sc = self._setup_funded_and_drawn(api)
        terminated = terminate_engagement(sc["engagement"]["id"], reason="settlement")
        assert terminated["status"] == "TERMINATED"
        assert terminated["retainer_funded_cents"] == 300_000
        assert terminated["retainer_drawn_cents"] == 100_000
        assert terminated["retainer_refunded_cents"] == 200_000
        assert terminated["retainer_remaining_cents"] == 0
        assert_retainer_invariant(terminated)


class TestStateBeatsFiscal:

    def test_approve_disputed_invoice_returns_invalid_state(self, api):
        """PRD §2.11: "then the target entity's state preconditions for the requested
        transition are checked, with violations yielding `ERR_INVALID_STATE` (HTTP 409); and
        only then do the endpoint's business rules run, in the explicit order each workflow
        lists them in §3."
        PRD §3.7: "Approval additionally requires the invoice to be `SUBMITTED`, the
        engagement to be `ACTIVE`, and the case not to be `CLOSED`."

        Design: Difficulty/priority_pair_validation_conflict/approve_disputed_invoice_state_beats_budget
        """
        sc = setup_active_engagement(case_overrides={"budget_cents": 30_000})
        inv = submit_invoice(sc["engagement"]["id"], sc["expert"]["id"],
                             [{"kind": "PREP", "hours": 1}], 40_000)
        validate_success(api.dispute_invoice(inv["id"], {"reason": "clarify"}, BILLING), 200)

        res = api.approve_invoice(inv["id"], BILLING)
        # DISPUTED (state violation) AND 40000 > 30000 (fiscal violation): state wins.
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_rejected_approval_has_no_fiscal_side_effects(self, api):
        """PRD §2.11: "then the target entity's state preconditions for the requested
        transition are checked, with violations yielding `ERR_INVALID_STATE` (HTTP 409); and
        only then do the endpoint's business rules run" — the business rules, including the
        budget gate of §3.7, never run for the state-violating call.
        PRD §3.7: "the invoice's `computed_total_cents` must not exceed the case's
        remaining budget, defined as `budget_cents` minus `actuals_paid_cents` minus
        `approved_outstanding_cents`; an invoice exactly equal to the remaining budget
        passes, while exceeding it fails with `ERR_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/approve_disputed_invoice_state_beats_budget
        """
        sc = setup_active_engagement(case_overrides={"budget_cents": 30_000})
        inv = submit_invoice(sc["engagement"]["id"], sc["expert"]["id"],
                             [{"kind": "PREP", "hours": 1}], 40_000)
        validate_success(api.dispute_invoice(inv["id"], {"reason": "clarify"}, BILLING), 200)

        res = api.approve_invoice(inv["id"], BILLING)
        assert res.status_code == 409
        body = res.json()
        assert body["data"]["error_id"] != "ERR_BUDGET_EXCEEDED", (
            "state precondition (409 ERR_INVALID_STATE) must fire before the fiscal rule")

        invoices = validate_success(api.list_invoices(sc["engagement"]["id"], BILLING), 200)
        after = [i for i in invoices if i["id"] == inv["id"]][0]
        assert after["status"] == "DISPUTED", "invoice unchanged by the rejected approval"
        case = validate_success(api.get_case(sc["case"]["id"], CM), 200)
        assert case["approved_outstanding_cents"] == 0
