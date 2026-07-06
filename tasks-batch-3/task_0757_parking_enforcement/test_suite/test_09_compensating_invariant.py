"""Difficulty rule: compensating_invariant.

A forward action and its compensation conserve a quantity with no drift:
  (A) settle then refund conserves Vehicle.outstanding_balance_cents (money);
  (B) issue then void conserves Vehicle.unpaid_citation_count (count).
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    setup_issuing_context,
    issue_in_context,
    create_payment,
    settle_payment,
)

ADMIN = TEST_USERS["admin_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


class TestRefundConservesOutstandingBalance:
    def _paid_citation(self):
        ctx = setup_issuing_context(base_fine_cents=15000, code="HYDRANT")
        cit = issue_in_context(ctx)
        pay = create_payment(cit["id"], 15000, method="CARD")
        settle_payment(pay["id"])
        return ctx, cit, pay

    def test_refund_reverts_payment_and_citation(self, api):
        """PRD §3.5: "it moves the payment from `SETTLED` to `REFUNDED` and decreases
        the citation's `amount_paid_cents` by that payment's `amount_cents`. If the
        citation had been `PAID` and was made so by the very payment now refunded, it
        reverts from `PAID` back to `ISSUED`."

        Design: Difficulty/compensating_invariant/payment_refund_conserves_outstanding_balance
        """
        ctx, cit, pay = self._paid_citation()
        refunded = validate_success(api.refund_payment(pay["id"], SUPERVISOR))
        assert refunded["status"] == "REFUNDED"
        after = validate_success(api.get_citation(cit["id"], ADMIN))
        assert after["status"] == "ISSUED", \
            f"refunded PAID citation must revert to ISSUED, got {after['status']}"

    def test_refund_restores_outstanding_balance(self, api):
        """PRD §3.4: "The `outstanding_balance_cents` is the settled-basis balance and
        is authoritative for enforcement: for each unpaid citation it takes the fine
        less only that citation's `SETTLED` payments and applied waivers (floored at
        0), and sums those across the set — `PENDING` payments do not reduce it."

        Design: Difficulty/compensating_invariant/payment_refund_conserves_outstanding_balance
        """
        ctx, cit, pay = self._paid_citation()
        # settled basis before refund is 0 (fully paid); refund restores it to 15000.
        validate_success(api.refund_payment(pay["id"], SUPERVISOR))
        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["outstanding_balance_cents"] == 15000, \
            f"outstanding must be restored to 15000, got {veh['outstanding_balance_cents']}"


class TestVoidConservesUnpaidCount:
    def _one_issued_citation(self):
        ctx = setup_issuing_context(base_fine_cents=5000, code="EXP_METER")
        cit = issue_in_context(ctx)
        return ctx, cit

    def test_void_returns_unpaid_count_to_zero(self, api):
        """PRD §3.4: "The unpaid set is the vehicle's citations whose `status` is
        either `ISSUED` or `UPHELD`; a citation that is `CONTESTED`, `DISMISSED`,
        `PAID`, or `VOID` is not in the unpaid set. The `unpaid_citation_count` is the
        size of that set."

        Design: Difficulty/compensating_invariant/citation_void_conserves_unpaid_count
        """
        ctx, cit = self._one_issued_citation()
        before = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert before["unpaid_citation_count"] == 1
        validate_success(api.void_citation(cit["id"], SUPERVISOR))
        after = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert after["unpaid_citation_count"] == 0, \
            f"void must return unpaid_citation_count to 0, got {after['unpaid_citation_count']}"

    def test_void_zeroes_outstanding_balance(self, api):
        """PRD §3.7: "Voiding a citation is permitted only while it is `ISSUED`; it
        moves the citation from `ISSUED` to `VOID`, removes it from the vehicle's
        unpaid set, and recomputes the vehicle balance and scofflaw tier, which may
        de-escalate the vehicle and thereby cancel a still-`ORDERED` order and clear
        its hold."

        Design: Difficulty/compensating_invariant/citation_void_conserves_unpaid_count
        """
        ctx, cit = self._one_issued_citation()
        voided = validate_success(api.void_citation(cit["id"], SUPERVISOR))
        assert voided["status"] == "VOID"
        veh = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ADMIN))
        assert veh["outstanding_balance_cents"] == 0, \
            f"void must zero the outstanding balance, got {veh['outstanding_balance_cents']}"
