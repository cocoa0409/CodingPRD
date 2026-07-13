"""Refund valuation (wallet vs card) and the store-credit conservation invariant."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    setup_approved_project, place_order, pay_order, cancel_order,
)


def _paid_card_order(ctx, quantity=10):
    """Place + pay a qty-`quantity` MATTE STANDARD CARD order. Returns the paid Order."""
    order = place_order(ctx, quantity=quantity, finish="MATTE", ship_method="STANDARD", payment_method="CARD")
    return pay_order(order, ctx["headers"])


class TestRefundValuation:
    """Same paid order (paid_cents 10299) refunds differently by destination."""

    def test_wallet_refund_returns_full_paid_cents(self, api):
        """PRD 3.7: "A wallet refund is a goodwill full refund — the entire captured paid_cents is
        credited, with no fee, and the customer's store_credit_cents is increased by that amount,
        conserving the customer's money across the pay-then-cancel round trip."

        Design: Difficulty/dual_variant_calc/refund_wallet_vs_cash_valuation
        """
        ctx = setup_approved_project()
        order = _paid_card_order(ctx)  # qty 10 -> subtotal 9500 + shipping 799 = total 10299
        cancelled = validate_success(api.cancel_order(order["id"], {"refund_destination": "WALLET"}, ctx["headers"]), 200)
        assert cancelled["refund_cents"] == 10299, f"wallet -> full 10299, got {cancelled['refund_cents']}"

    def test_card_refund_retains_restocking_fee(self, api):
        """PRD 3.7: "A card refund keeps a restocking fee: the fee is the order's subtotal_cents
        multiplied by 10 percent, rounded half up to whole cents, and the refund_cents is the
        captured paid_cents minus that fee, floored at 0 (and no store credit is granted)."

        Design: Difficulty/dual_variant_calc/refund_wallet_vs_cash_valuation
        """
        ctx = setup_approved_project()
        order = _paid_card_order(ctx)
        cancelled = validate_success(api.cancel_order(order["id"], {"refund_destination": "CARD"}, ctx["headers"]), 200)
        # restock = round(9500 * 0.10) = 950; refund = 10299 - 950 = 9349
        assert cancelled["refund_cents"] == 9349, f"card -> 9349, got {cancelled['refund_cents']}"

    def test_wallet_refund_credits_store_credit(self, api):
        """PRD 3.7: "A wallet refund is a goodwill full refund — the entire captured paid_cents is
        credited, with no fee, and the customer's store_credit_cents is increased by that amount,
        conserving the customer's money across the pay-then-cancel round trip."

        Design: Difficulty/dual_variant_calc/refund_wallet_vs_cash_valuation
        """
        ctx = setup_approved_project()
        order = _paid_card_order(ctx)  # customer starts with 0 store credit
        api.cancel_order(order["id"], {"refund_destination": "WALLET"}, ctx["headers"])
        cust = validate_success(api.get_customer(ctx["cust"]["id"], ctx["headers"]), 200)
        assert cust["store_credit_cents"] == 10299, f"wallet credited to store credit, got {cust['store_credit_cents']}"


class TestStoreCreditConservation:
    """Pay-with-credit then cancel-to-wallet leaves store credit at its pre-pay value."""

    def test_pay_with_store_credit_debits_total(self, api):
        """PRD 3.5: "On success the order's payment_status becomes PAID and its paid_cents is set
        equal to total_cents; if the method was STORE_CREDIT, the customer's store_credit_cents is
        debited by total_cents."

        Design: Difficulty/compensating_invariant/store_credit_conserved_pay_then_cancel
        """
        ctx = setup_approved_project(seed_credit_cents=20000)
        order = place_order(ctx, quantity=10, finish="MATTE", ship_method="STANDARD", payment_method="STORE_CREDIT")
        pay_order(order, ctx["headers"])
        cust = validate_success(api.get_customer(ctx["cust"]["id"], ctx["headers"]), 200)
        assert cust["store_credit_cents"] == 9701, f"20000 - 10299, got {cust['store_credit_cents']}"

    def test_cancel_to_wallet_restores_prepay_balance(self, api):
        """PRD 3.7: "A wallet refund is a goodwill full refund — the entire captured paid_cents is
        credited, with no fee, and the customer's store_credit_cents is increased by that amount,
        conserving the customer's money across the pay-then-cancel round trip."

        Design: Difficulty/compensating_invariant/store_credit_conserved_pay_then_cancel
        """
        ctx = setup_approved_project(seed_credit_cents=20000)
        order = place_order(ctx, quantity=10, finish="MATTE", ship_method="STANDARD", payment_method="STORE_CREDIT")
        paid = pay_order(order, ctx["headers"])
        cancelled = validate_success(api.cancel_order(paid["id"], {"refund_destination": "WALLET"}, ctx["headers"]), 200)
        assert cancelled["refund_cents"] == 10299
        cust = validate_success(api.get_customer(ctx["cust"]["id"], ctx["headers"]), 200)
        assert cust["store_credit_cents"] == 20000, f"conserved to pre-pay 20000, got {cust['store_credit_cents']}"


class TestStoreCreditGate:

    def test_insufficient_store_credit_rejected(self, api):
        """PRD 3.5: "if the payment_method is STORE_CREDIT, the customer's store_credit_cents must be
        at least the order's total_cents (else ERR_INSUFFICIENT_STORE_CREDIT, HTTP 402)."

        Design: Corner/validations/corner_insufficient_store_credit_rejected
        """
        ctx = setup_approved_project(seed_credit_cents=5000)
        order = place_order(ctx, quantity=10, finish="MATTE", ship_method="STANDARD", payment_method="STORE_CREDIT")
        res = api.pay_order(order["id"], ctx["headers"])
        validate_error(res, "ERR_INSUFFICIENT_STORE_CREDIT", 402)
