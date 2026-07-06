"""Checkout settlement, loyalty points, and loyalty-tier recomputation."""
import pytest
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    ApiErrorId,
    create_customer,
    customer_with_store_credit,
    customer_with_confirmed_preorder,
    checkout,
    create_checkout_payload,
    create_credit_adjustment_payload,
    TEST_USERS,
    make_customer_headers,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ---------------------------------------------------------------------------
# Queue A — combinatorial_formula: loyalty points floor-per-line then sum
# ---------------------------------------------------------------------------
def test_loyalty_points_floor_each_line_then_sum(api, clerk_headers):
    """PRD §3.8: "the system computes, for each line item independently, the line's total in cents divided by 100 and multiplied by the multiplier, takes the floor of that per-line value, and sums those floored per-line values into a single integer `loyalty_points_earned`."

    Design: Difficulty/combinatorial_formula/loyalty_points_floor_per_line_then_sum
    """
    cust = create_customer()
    resp = checkout(cust["id"], [
        {"unit_price_cents": 12550, "quantity": 1},
        {"unit_price_cents": 3375, "quantity": 1},
    ])
    # floor(125.50) + floor(33.75) = 125 + 33 = 158 (BRONZE multiplier 1.0)
    assert resp["loyalty_points_earned"] == 158


def test_loyalty_points_per_line_order_reflected_in_balance(api, clerk_headers):
    """PRD §3.8: "The flooring is applied per line item and only then summed;
    summing the raw cents first and flooring once would yield a different total,
    so the per-line order is mandatory."

    Design: Difficulty/combinatorial_formula/loyalty_points_floor_per_line_then_sum
    """
    cust = create_customer()
    checkout(cust["id"], [
        {"unit_price_cents": 12550, "quantity": 1},
        {"unit_price_cents": 3375, "quantity": 1},
    ])
    after = validate_success(api.get_customer(cust["id"], clerk_headers), 200)
    # 158 (per-line floor), not floor(159.25)=159 (sum-then-floor)
    assert after["loyalty_points_balance"] == 158


# ---------------------------------------------------------------------------
# Queue A — dual_variant_calc: forward-looking vs settled-only loyalty tier
# ---------------------------------------------------------------------------
def test_confirmed_preorder_lifts_tier_forward_looking(api, clerk_headers):
    """PRD §3.8: "The system computes a settled figure equal to the customer's `lifetime_spend_cents`, then a forward-looking figure equal to that settled figure plus the sum of `estimated_total_cents` across the customer's pre-orders currently in `CONFIRMED` status. The tier the system persists uses the forward-looking figure: if it is at least 150000 cents the tier is `GOLD`; otherwise if it is at least 50000 cents the tier is `SILVER`; otherwise the tier is `BRONZE`."

    Design: Difficulty/dual_variant_calc/loyalty_tier_forward_looking_vs_settled_only
    """
    cust, _issue, pre_order = customer_with_confirmed_preorder(
        cover_price_cents=20000, quantity=1, lifetime_checkout_cents=40000
    )
    assert cust["lifetime_spend_cents"] == 40000
    assert pre_order["estimated_total_cents"] == 20000
    # forward-looking 40000 + 20000 = 60000 >= 50000 -> SILVER (settled 40000 -> BRONZE)
    assert cust["loyalty_tier"] == "SILVER"


def test_settled_spend_below_silver_but_forward_reaches_it(api, clerk_headers):
    """PRD §3.8: "a settled-only figure — using `lifetime_spend_cents` alone and excluding confirmed pre-orders — serves as a chronological audit basis and can yield a lower tier than the forward-looking one for the same customer."

    Design: Difficulty/dual_variant_calc/loyalty_tier_forward_looking_vs_settled_only
    """
    cust, _issue, _pre_order = customer_with_confirmed_preorder(
        cover_price_cents=20000, quantity=1, lifetime_checkout_cents=40000
    )
    # settled spend (40000) is below the 50000 SILVER threshold; the persisted
    # tier is nonetheless SILVER because the forward-looking basis reaches it.
    assert cust["lifetime_spend_cents"] == 40000
    assert cust["loyalty_tier"] == "SILVER"


# ---------------------------------------------------------------------------
# Queue A — boundary_precision_check: store credit exactly covers charge
# ---------------------------------------------------------------------------
def test_store_credit_exactly_covers_charge_is_zero(api, clerk_headers):
    """PRD §3.8: "the store credit applied (`store_credit_applied_cents`) is the smaller of the customer's `store_credit_cents` and the amount due, and the amount charged (`charge_cents`) is the amount due minus the applied credit — exactly 0 when credit fully covers the sale."

    Design: Difficulty/boundary_precision_check/checkout_store_credit_exactly_covers_charge_zero
    """
    cust, _txn = customer_with_store_credit(5000)
    resp = checkout(cust["id"], [{"unit_price_cents": 5000, "quantity": 1}],
                    pay_with_store_credit_only=True)
    assert resp["charge_cents"] == 0
    assert resp["store_credit_applied_cents"] == 5000
    after = validate_success(api.get_customer(cust["id"], clerk_headers), 200)
    assert after["store_credit_cents"] == 0


def test_store_credit_applied_capped_at_amount_due(api, clerk_headers):
    """PRD §3.8: "the store credit applied (`store_credit_applied_cents`) is the smaller of the customer's `store_credit_cents` and the amount due, and the amount charged (`charge_cents`) is the amount due minus the applied credit — exactly 0 when credit fully covers the sale."

    Design: Difficulty/boundary_precision_check/checkout_store_credit_exactly_covers_charge_zero
    """
    cust, _txn = customer_with_store_credit(8000)
    resp = checkout(cust["id"], [{"unit_price_cents": 5000, "quantity": 1}],
                    pay_with_store_credit_only=True)
    # applied = min(8000, 5000) = 5000; charge = 5000 - 5000 = 0; 3000 credit remains.
    assert resp["store_credit_applied_cents"] == 5000
    assert resp["charge_cents"] == 0
    after = validate_success(api.get_customer(cust["id"], clerk_headers), 200)
    assert after["store_credit_cents"] == 3000


# ---------------------------------------------------------------------------
# Queue B — validations
# ---------------------------------------------------------------------------
def test_insufficient_store_credit_only_checkout_rejected(api, clerk_headers):
    """PRD §3.8: "If `pay_with_store_credit_only` is true and the customer's `store_credit_cents` is less than the amount due, the checkout is rejected with `ERR_INSUFFICIENT_STORE_CREDIT`."

    Design: Corner/validations/insufficient_store_credit_only_checkout_rejected
    """
    cust, _txn = customer_with_store_credit(1000)
    res = api.checkout(
        create_checkout_payload(
            cust["id"], [{"unit_price_cents": 5000, "quantity": 1}],
            pay_with_store_credit_only=True,
        ),
        clerk_headers,
    )
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STORE_CREDIT, expected_status=402)


# ---------------------------------------------------------------------------
# Queue B — endpoints: computed checkout read
# ---------------------------------------------------------------------------
def test_checkout_returns_derived_totals(api, clerk_headers):
    """PRD §3.8: "The amount due (`amount_due_cents`) is the sum over the line items of each line's `unit_price_cents` multiplied by its `quantity`."
    PRD §3.8: "the system computes, for each line item independently, the line's total in cents divided by 100 and multiplied by the multiplier, takes the floor of that per-line value, and sums those floored per-line values into a single integer `loyalty_points_earned`."

    Design: Corner/endpoints/checkout_computed_read_returns_derived_totals
    """
    cust = create_customer()
    resp = checkout(cust["id"], [{"unit_price_cents": 10000, "quantity": 1}])
    assert resp["amount_due_cents"] == 10000
    assert resp["charge_cents"] == 10000
    # BRONZE multiplier 1.0: floor(100.0) = 100
    assert resp["loyalty_points_earned"] == 100


# ---------------------------------------------------------------------------
# Queue B — cross_cutting: loyalty tier recomputes on pre-order cancel
# ---------------------------------------------------------------------------
def test_loyalty_tier_recomputes_on_preorder_cancel(api):
    """PRD §3.4: "A pre-order may also be cancelled by the customer from either `PENDING` or `CONFIRMED`, moving it to `CANCELLED`; cancellation likewise recomputes the customer's loyalty tier, because a cancelled pre-order no longer contributes to forward spend."

    Design: Corner/cross_cutting_complexity_layers/loyalty_tier_recomputes_on_preorder_cancel
    """
    cust, _issue, pre_order = customer_with_confirmed_preorder(
        cover_price_cents=60000, quantity=1, lifetime_checkout_cents=0
    )
    assert cust["loyalty_tier"] == "SILVER"
    owner = make_customer_headers(cust["id"])
    cancelled = validate_success(
        api.transition_pre_order(pre_order["id"], {"to_status": "CANCELLED"}, owner), 200
    )
    assert cancelled["status"] == "CANCELLED"
    after = validate_success(api.get_customer(cust["id"], CLERK), 200)
    assert after["loyalty_tier"] == "BRONZE"


# ---------------------------------------------------------------------------
# Queue B — consistency_model: checkout debit visible immediately
# ---------------------------------------------------------------------------
def test_checkout_debit_visible_immediately(api, clerk_headers):
    """PRD §3.8: "The customer's `store_credit_cents` is reduced by the applied credit"

    Design: Corner/consistency_model/checkout_changes_visible_same_response
    """
    cust, _txn = customer_with_store_credit(2000)
    checkout(cust["id"], [{"unit_price_cents": 500, "quantity": 1}],
             pay_with_store_credit_only=True)
    after = validate_success(api.get_customer(cust["id"], clerk_headers), 200)
    assert after["store_credit_cents"] == 1500
