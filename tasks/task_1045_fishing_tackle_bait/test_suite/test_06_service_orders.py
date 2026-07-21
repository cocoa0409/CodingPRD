"""Rod/reel service and line spooling: quoted vs final subtotal, the pinned
discount-then-tax grand total, the cyclic re-diagnosis edge, stock conservation
on consume/restore, and the insufficient-stock guard.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    new_product, new_customer, make_customer_at_tier,
    setup_service_order_in_progress, setup_service_order_ready,
    TEST_USERS,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── Difficulty: dual_variant_calc / service_order_quoted_vs_final_actual_meters_and_parts
def test_quoted_uses_estimated_meters_no_parts(api):
    """PRD §3.8: "computes and pins the `quoted_cents` from the quoted variant: the
    `base_service_cents` plus the `estimated_line_meters` multiplied by the
    `line_price_cents_per_meter`, using estimated meters and excluding parts."

    Design: Difficulty/dual_variant_calc/service_order_quoted_vs_final_actual_meters_and_parts
    """
    _, _, order = setup_service_order_in_progress(base=2500, rate=30, estimated=100, stock=50)
    assert order["quoted_cents"] == 5500  # 2500 + 100*30


def test_final_subtotal_uses_actual_meters_and_parts(api):
    """PRD §3.8: "It pins the `final_subtotal_cents` from the final variant: the
    `base_service_cents` plus the `actual_line_meters` multiplied by the
    `line_price_cents_per_meter`, plus the `parts_cents`."

    Design: Difficulty/dual_variant_calc/service_order_quoted_vs_final_actual_meters_and_parts
    """
    _, _, order = setup_service_order_ready(
        base=2500, rate=30, estimated=100, actual=120, parts=800, line_units=2, stock=50)
    assert order["final_subtotal_cents"] == 6900  # 2500 + 120*30 + 800
    assert order["quoted_cents"] == 5500
    assert order["final_subtotal_cents"] != order["quoted_cents"]


# ─── Difficulty: combinatorial_formula / service_order_grand_total_discount_then_tax_mode_c
def test_grand_total_discount_then_tax_silver(api):
    """PRD §3.8: "Apply the customer's tier discount — 0% for BRONZE, 5% for SILVER, 10% for
    GOLD — as a discount amount equal to the subtotal multiplied by the tier percentage,
    rounded half up; subtract that discount from the subtotal to get the discounted amount.
    Then apply an 8% sales tax computed as the discounted amount multiplied by 0.08, rounded
    half up; the grand total is the discounted amount plus that tax."

    Design: Difficulty/combinatorial_formula/service_order_grand_total_discount_then_tax_mode_c
    """
    silver = make_customer_at_tier("SILVER")
    _, _, order = setup_service_order_ready(
        customer=silver, base=2500, rate=30, estimated=100,
        actual=120, parts=800, line_units=2, stock=50)
    picked = validate_success(
        api.transition_service_order(order["id"], {"to_status": "PICKED_UP"}, CLERK), 200)
    assert picked["grand_total_cents"] == 7079  # 6900 - 345 = 6555; +round(6555*0.08)=524


def test_grand_total_pinned_order_is_observable(api):
    """PRD §2.6: "each rounding step is applied half up independently and in the fixed order
    stated, and that order is observable in the stored figures."

    Design: Difficulty/combinatorial_formula/service_order_grand_total_discount_then_tax_mode_c
    """
    silver = make_customer_at_tier("SILVER")
    _, _, order = setup_service_order_ready(
        customer=silver, base=2500, rate=30, estimated=100,
        actual=120, parts=800, line_units=2, stock=50)
    picked = validate_success(
        api.transition_service_order(order["id"], {"to_status": "PICKED_UP"}, CLERK), 200)
    # discounted = 6900 - round(6900*0.05)=6555; tax = round(6555*0.08)=524; total=7079.
    assert picked["grand_total_cents"] == 6555 + 524


# ─── Difficulty: non_linear_state_machine / service_order_cycle_reenters_diagnosed_from_in_progress
def test_reenter_diagnosed_from_in_progress(api):
    """PRD §3.8: "Work in progress may be re-diagnosed after a scope change
    (IN_PROGRESS → DIAGNOSED), which recomputes quoted_cents from the quoted variant again."

    Design: Difficulty/non_linear_state_machine/service_order_cycle_reenters_diagnosed_from_in_progress
    """
    _, _, order = setup_service_order_in_progress(base=2500, rate=30, estimated=100, stock=50)
    rediag = validate_success(
        api.transition_service_order(order["id"], {"to_status": "DIAGNOSED"}, CLERK), 200)
    assert rediag["status"] == "DIAGNOSED"


def test_reenter_diagnosed_recomputes_quote(api):
    """PRD §3.8: "Work in progress may be re-diagnosed after a scope change
    (IN_PROGRESS → DIAGNOSED), which recomputes quoted_cents from the quoted variant again."

    Design: Difficulty/non_linear_state_machine/service_order_cycle_reenters_diagnosed_from_in_progress
    """
    _, _, order = setup_service_order_in_progress(base=2500, rate=30, estimated=100, stock=50)
    rediag = validate_success(
        api.transition_service_order(order["id"], {"to_status": "DIAGNOSED"}, CLERK), 200)
    assert rediag["quoted_cents"] == 5500  # 2500 + 100*30, recomputed on the back-edge


# ─── Difficulty: compensating_invariant / product_line_stock_conserved_service_consume_then_restore
def test_ready_consumes_line_stock(api):
    """PRD §3.8: "When `line_units` is greater than zero the product's `stock_qty` is
    decremented by `line_units` and the order's `stock_consumed` flag is set true."

    Design: Difficulty/compensating_invariant/product_line_stock_conserved_service_consume_then_restore
    """
    product = new_product(stock_qty=50)
    _, product, order = setup_service_order_ready(
        product=product, base=2500, rate=30, estimated=100,
        actual=120, parts=800, line_units=2)
    assert order["stock_consumed"] is True
    refreshed = get_success_data(api.get_product(product["id"], CLERK))
    assert refreshed["stock_qty"] == 48  # 50 - 2


def test_cancel_from_ready_restores_line_stock(api):
    """PRD §3.8: "cancelling a `READY` order that already consumed stock (its `stock_consumed`
    is true) restores the inventory: the product's `stock_qty` is incremented by `line_units`
    and `stock_consumed` is set back to false."

    Design: Difficulty/compensating_invariant/product_line_stock_conserved_service_consume_then_restore
    """
    product = new_product(stock_qty=50)
    _, product, order = setup_service_order_ready(
        product=product, base=2500, rate=30, estimated=100,
        actual=120, parts=800, line_units=2)
    cancelled = validate_success(
        api.transition_service_order(order["id"], {"to_status": "CANCELLED"}, CLERK), 200)
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["stock_consumed"] is False
    refreshed = get_success_data(api.get_product(product["id"], CLERK))
    assert refreshed["stock_qty"] == 50  # restored to pre-service value


# ─── Corner: state_machines / service_ready_insufficient_stock_rejected
def test_ready_insufficient_stock_rejected(api):
    """PRD §3.8: "If line_units is greater than zero, the named product must have stock_qty of
    at least line_units; if it does not, the transition is refused with ERR_INSUFFICIENT_STOCK
    (HTTP 409)."

    Design: Corner/state_machines/service_ready_insufficient_stock_rejected
    """
    product = new_product(stock_qty=3)
    _, product, order = setup_service_order_in_progress(
        product=product, base=2500, rate=30, estimated=100)
    res = api.transition_service_order(
        order["id"],
        {"to_status": "READY", "actual_line_meters": 120, "parts_cents": 0, "line_units": 5},
        CLERK)
    validate_error(res, "ERR_INSUFFICIENT_STOCK", 409)
    refreshed = get_success_data(api.get_product(product["id"], CLERK))
    assert refreshed["stock_qty"] == 3  # untouched
