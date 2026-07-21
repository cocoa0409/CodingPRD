"""Order placement, parallel payment/fulfillment dimensions, loyalty and discount
arithmetic, inventory reservation/release conservation, and placement guards.

Covers queue-A non_linear_state_machine, dual_variant_calc (loyalty),
combinatorial_formula (order discount), compensating_invariant (inventory + loyalty),
boundary_precision (zero stock), plus queue-B order state-machine instances.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    create_order_payload,
    ApiErrorId, TEST_USERS,
    make_customer_headers,
    new_customer,
    setup_order_with_line, setup_placed_order, setup_paid_order, setup_fulfilled_line,
    setup_gold_multiline_placed_order,
)

BC = TEST_USERS["billing_clerk_headers"]
SM = TEST_USERS["store_manager_headers"]


# ─── Parallel payment / fulfillment dimensions (queue A) ──────────────────
def test_place_sets_placed_and_leaves_unpaid(api):
    """PRD §3.3: "Placement, by the customer, advances fulfillment_status DRAFT →
    PLACED."
    PRD §3.3: "A new order begins with payment_status of UNPAID and fulfillment_status
    of DRAFT."

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment
    """
    ctx = setup_placed_order(base_price_cents=1000, initial_stock=5, quantity=1)
    order = ctx["order"]
    assert order["fulfillment_status"] == "PLACED", order
    assert order["payment_status"] == "UNPAID", order


def test_pay_advances_payment_only_not_fulfillment(api):
    """PRD §3.4: "Payment is recorded by a BillingClerk and advances payment_status
    UNPAID → PAID, but only when the order's fulfillment_status is already PLACED".

    Design: Difficulty/non_linear_state_machine/order_parallel_payment_and_fulfillment
    """
    ctx = setup_placed_order(base_price_cents=1000, initial_stock=5, quantity=1)
    paid = validate_success(api.pay_order(ctx["order"]["id"], BC), 200)
    assert paid["payment_status"] == "PAID", paid
    assert paid["fulfillment_status"] == "PLACED", paid


# ─── Loyalty provisional vs final (queue A) ───────────────────────────────
def test_provisional_points_no_multiplier_at_pay(api):
    """PRD §3.4: "The base points are the order's total_cents divided by 100 with the
    fractional part discarded. At payment the provisional variant applies no tier
    multiplier, so provisional_points equals those base points."

    Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_final_points
    """
    ctx = setup_gold_multiline_placed_order(unit_price_cents=525, n_lines=2)
    paid = validate_success(api.pay_order(ctx["order"]["id"], BC), 200)
    assert paid["total_cents"] == 944, paid
    assert paid["provisional_points"] == 9, paid


def test_final_points_apply_gold_multiplier_at_fulfill(api):
    """PRD §3.4: "the base points (again total_cents divided by 100, floored) are
    multiplied by the tier multiplier — 1 for BRONZE, 1 for SILVER, and 2 for GOLD —
    to produce final_points."
    PRD §3.4: "A reconciling LoyaltyEvent with reason FINAL_ADJUSTMENT and a
    points_delta equal to final_points minus provisional_points is appended, and the
    customer's loyalty_points is updated."

    Design: Difficulty/dual_variant_calc/loyalty_provisional_vs_final_points
    """
    ctx = setup_gold_multiline_placed_order(unit_price_cents=525, n_lines=2)
    validate_success(api.pay_order(ctx["order"]["id"], BC), 200)
    fulfilled = validate_success(api.fulfill_order(ctx["order"]["id"], SM), 200)
    assert fulfilled["final_points"] == 18, fulfilled
    # 5000 (seed) + 9 (ORDER_EARN) + 9 (FINAL_ADJUSTMENT) = 5018.
    cust = validate_success(api.get_customer(ctx["customer"]["id"], SM), 200)
    assert cust["loyalty_points"] == 5018, cust


# ─── Per-line round-then-sum discount (queue A) ───────────────────────────
def test_discount_rounds_per_line_then_sums_two_lines(api):
    """PRD §2.5: "when several lines each receive a percentage discount, each line's
    discount is rounded to whole cents first, and only then are the rounded per-line
    discounts summed. Summing the raw discounts and rounding once at the end is not
    permitted, because it can differ from the per-line result by a cent."

    Design: Difficulty/combinatorial_formula/order_discount_perline_round_then_sum
    """
    ctx = setup_gold_multiline_placed_order(unit_price_cents=525, n_lines=2)
    paid = validate_success(api.pay_order(ctx["order"]["id"], BC), 200)
    # Each line: round_half_up(525 * 0.10 = 52.5) = 53; 53 + 53 = 106 (sum-then-round would give 105).
    assert paid["subtotal_cents"] == 1050, paid
    assert paid["discount_cents"] == 106, paid
    assert paid["total_cents"] == 944, paid


def test_discount_rounds_per_line_then_sums_three_lines(api):
    """PRD §2.5: "when several lines each receive a percentage discount, each line's
    discount is rounded to whole cents first, and only then are the rounded per-line
    discounts summed. Summing the raw discounts and rounding once at the end is not
    permitted, because it can differ from the per-line result by a cent."

    Design: Difficulty/combinatorial_formula/order_discount_perline_round_then_sum
    """
    ctx = setup_gold_multiline_placed_order(unit_price_cents=525, n_lines=3)
    paid = validate_success(api.pay_order(ctx["order"]["id"], BC), 200)
    # Each line rounds 52.5 -> 53; 53*3 = 159 (sum-then-round of 157.5 would give 158).
    assert paid["subtotal_cents"] == 1575, paid
    assert paid["discount_cents"] == 159, paid


# ─── Inventory reserve / release conservation (queue A) ───────────────────
def test_place_reserves_inventory(api):
    """PRD §3.3: "each in-stock line's SKU has its reserved_count recomputed upward
    and its available_units and stock_status recomputed accordingly, reflecting the
    newly held inventory."
    PRD §2.6: "available_units is stock_on_hand minus reserved_count".

    Design: Difficulty/compensating_invariant/inventory_reserve_release_conserved
    """
    ctx = setup_placed_order(
        category="SPORTS_BRA", base_price_cents=3500, band_size=34, cup_size="D",
        initial_stock=5, quantity=2,
    )
    sku = validate_success(api.get_sku(ctx["sku"]["id"], SM), 200)
    assert sku["reserved_count"] == 2, sku
    assert sku["available_units"] == 3, sku


def test_cancel_releases_reservation_conserving_inventory(api):
    """PRD §3.5: "each cancelled line releases its reservation, so the affected SKUs
    have reserved_count recomputed downward and available_units and stock_status
    recomputed."
    PRD §2.6: "available_units is stock_on_hand minus reserved_count".

    Design: Difficulty/compensating_invariant/inventory_reserve_release_conserved
    """
    ctx = setup_placed_order(
        category="SPORTS_BRA", base_price_cents=3500, band_size=34, cup_size="D",
        initial_stock=5, quantity=2,
    )
    validate_success(
        api.cancel_order(ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])), 200
    )
    sku = validate_success(api.get_sku(ctx["sku"]["id"], SM), 200)
    assert sku["reserved_count"] == 0, sku
    assert sku["available_units"] == 5, sku
    assert sku["stock_on_hand"] == 5, sku


# ─── Loyalty earn / reverse conservation (queue A) ────────────────────────
def test_pay_earns_provisional_loyalty(api):
    """PRD §3.4: "The system records a LoyaltyEvent with reason ORDER_EARN and a
    points_delta equal to provisional_points, and updates the customer's
    loyalty_points."

    Design: Difficulty/compensating_invariant/loyalty_points_earn_reverse_conserved
    """
    ctx = setup_paid_order(
        base_price_cents=1000, band_size=34, cup_size="B", initial_stock=3, quantity=1
    )
    assert ctx["order"]["provisional_points"] == 10, ctx["order"]
    cust = validate_success(api.get_customer(ctx["customer"]["id"], SM), 200)
    assert cust["loyalty_points"] == 10, cust


def test_cancel_paid_order_reverses_loyalty_and_refunds(api):
    """PRD §3.5: "If the order's payment_status was PAID, it moves to REFUNDED, and
    the provisional loyalty is reversed by appending a LoyaltyEvent with reason
    ORDER_REVERSAL and a points_delta of the negative of provisional_points, updating
    the customer's loyalty_points so the balance conserves back to its pre-order
    value."

    Design: Difficulty/compensating_invariant/loyalty_points_earn_reverse_conserved
    """
    ctx = setup_paid_order(
        base_price_cents=1000, band_size=34, cup_size="B", initial_stock=3, quantity=1
    )
    cancelled = validate_success(
        api.cancel_order(ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])), 200
    )
    assert cancelled["payment_status"] == "REFUNDED", cancelled
    cust = validate_success(api.get_customer(ctx["customer"]["id"], SM), 200)
    assert cust["loyalty_points"] == 0, cust


# ─── Zero / insufficient stock boundary (queue A) ─────────────────────────
def test_place_zero_available_stock_rejected(api):
    """PRD §3.3: "the SKU's available_units must be greater than or equal to that
    line's quantity, or the placement is rejected with ERR_INSUFFICIENT_STOCK — an
    available_units of zero rejects any reservation."

    Design: Difficulty/boundary_precision_check/place_zero_available_stock_edge
    """
    ctx = setup_order_with_line(base_price_cents=2000, band_size=42, cup_size="G", initial_stock=0, quantity=1)
    res = api.place_order(ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STOCK)


def test_place_quantity_exceeds_available_rejected(api):
    """PRD §3.3: "the SKU's available_units must be greater than or equal to that
    line's quantity, or the placement is rejected with ERR_INSUFFICIENT_STOCK — an
    available_units of zero rejects any reservation."

    Design: Difficulty/boundary_precision_check/place_zero_available_stock_edge
    """
    ctx = setup_order_with_line(base_price_cents=2000, initial_stock=1, quantity=2)
    res = api.place_order(ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_INSUFFICIENT_STOCK)


# ─── Placement / payment / cancel preconditions (queue B) ─────────────────
def test_pay_before_place_rejected(api):
    """PRD §3.4: "Payment is recorded by a BillingClerk and advances payment_status
    UNPAID → PAID, but only when the order's fulfillment_status is already PLACED;
    paying before placing is rejected with ERR_ORDER_NOT_PLACED."

    Design: Corner/state_machines/pay_before_place_returns_order_not_placed
    """
    ctx = setup_order_with_line(base_price_cents=2000, initial_stock=5, quantity=1)
    res = api.pay_order(ctx["order"]["id"], BC)
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_PLACED)


def test_place_empty_order_rejected(api):
    """PRD §3.3: "The order must contain at least one ACTIVE line, or it is rejected
    with ERR_EMPTY_ORDER."

    Design: Corner/state_machines/place_empty_order_returns_empty_order
    """
    cust = new_customer()
    order = get_success_data(
        api.create_order(create_order_payload(cust["id"]), make_customer_headers(cust["id"]))
    )
    res = api.place_order(order["id"], make_customer_headers(cust["id"]))
    validate_error(res, ApiErrorId.ERR_EMPTY_ORDER)


def test_cancel_fulfilled_order_rejected(api):
    """PRD §3.5: "An order may be cancelled by the customer while its
    fulfillment_status is DRAFT or PLACED; a FULFILLED order cannot be cancelled and
    yields ERR_ORDER_NOT_CANCELLABLE."

    Design: Corner/state_machines/cancel_fulfilled_order_returns_not_cancellable
    """
    ctx = setup_fulfilled_line(base_price_cents=2000, initial_stock=5, quantity=1)
    res = api.cancel_order(ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE)


def test_place_inactive_sku_rejected(api):
    """PRD §3.3: "For each ACTIVE non-special line, the referenced SKU must have
    is_active true, or the placement is rejected with ERR_SKU_INACTIVE".

    Design: Corner/state_machines/place_inactive_sku_returns_sku_inactive
    """
    ctx = setup_order_with_line(base_price_cents=2000, initial_stock=5, quantity=1, is_active_sku=False)
    res = api.place_order(ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"]))
    validate_error(res, ApiErrorId.ERR_SKU_INACTIVE)
