"""Wallet-credit conservation across pay (debit) and cancel (restore)."""
import pytest
from test_helpers import (
    validate_success, ApiErrorId,
    create_member, create_bottle, create_order, pay_order, fulfill_order, cancel_order,
    unit_line, make_customer_headers,
)


def _seed_wallet_5995_and_pay_order_b(api):
    """Fulfill+return a 5995 UNIT order to seed wallet=5995, then pay order B with that credit."""
    member = create_member(api)
    product = create_bottle(api, unit_price_cents=5000)  # subtotal 5000 + ship 995 = 5995
    order_a = create_order(api, member, [unit_line(product["id"], 1)])
    order_a = pay_order(api, member, order_a)
    order_a = fulfill_order(api, order_a)
    cancel_order(api, order_a, as_staff=True)  # return: wallet += final_total 5995
    order_b = create_order(api, member, [unit_line(product["id"], 1)], use_wallet_credit=True)
    order_b = pay_order(api, member, order_b)
    return member, order_b


# ── Difficulty: compensating_invariant / wallet_credit_conserved_across_pay_and_cancel ──

def test_wallet_debit_at_pay_applies_min_of_balance_and_total(api):
    """PRD §3.4: "If `use_wallet_credit` is true, the `wallet_credit_applied_cents` is the smaller
    of the member's `wallet_credit_cents` and the order's `provisional_total_cents`; otherwise it
    is zero. The member's wallet balance is reduced by the applied amount, and the
    `amount_charged_cents` billed externally is the provisional total minus the applied credit."

    Design: Difficulty/compensating_invariant/wallet_credit_conserved_across_pay_and_cancel
    """
    member, order_b = _seed_wallet_5995_and_pay_order_b(api)
    assert order_b["wallet_credit_applied_cents"] == 5995, order_b["wallet_credit_applied_cents"]
    assert order_b["amount_charged_cents"] == 0, order_b["amount_charged_cents"]
    member_data = validate_success(api.get_member(member["id"], make_customer_headers(member["id"])))
    assert member_data["wallet_credit_cents"] == 0, member_data["wallet_credit_cents"]


def test_cancel_restores_exact_wallet_portion_debited(api):
    """PRD §3.6: "the exact `wallet_credit_applied_cents` debited at payment is restored to the
    member's `wallet_credit_cents`, and the `amount_refunded_cents` is set to the provisional
    total."

    Design: Difficulty/compensating_invariant/wallet_credit_conserved_across_pay_and_cancel
    """
    member, order_b = _seed_wallet_5995_and_pay_order_b(api)
    cancel_order(api, order_b, member=member)
    member_data = validate_success(api.get_member(member["id"], make_customer_headers(member["id"])))
    assert member_data["wallet_credit_cents"] == 5995, \
        f"wallet must return to pre-pay 5995, got {member_data['wallet_credit_cents']}"
