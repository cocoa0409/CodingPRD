"""Order totals, loyalty points (provisional vs final), tier thresholds, and
the loyalty-point compensating invariant on cancellation."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    create_order_payload, order_line,
    make_customer, make_product, make_order, place_order,
    make_placed_order, make_fulfilled_order, cancel_order, pay_order, fulfill_order,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]


# ---------------------------------------------------------------------------
# cf_order_total_tiered_discount_plus_hazmat_surcharge
# ---------------------------------------------------------------------------
def test_order_total_combines_subtotal_discount_and_hazmat_surcharge(api):
    """PRD 3.4: "The `total_cents` is then `subtotal_cents` minus
    `discount_cents` plus `hazmat_surcharge_cents`, with the surcharge added
    strictly after the discount has been taken."

    Design: Difficulty/combinatorial_formula/cf_order_total_tiered_discount_plus_hazmat_surcharge
    """
    buyer = make_customer(api, ack=True)
    kit = make_product(api, product_type="KIT", price_cents=10000, stock_on_hand=10)
    bat = make_product(api, product_type="BATTERY", price_cents=5000, stock_on_hand=10)
    order = make_order(api, buyer["id"], [
        order_line(kit["id"], 2, 10000),
        order_line(bat["id"], 1, 5000),
    ])
    placed = place_order(api, order["id"])
    assert placed["subtotal_cents"] == 25000
    assert placed["total_cents"] == 25500


def test_order_bronze_discount_zero_and_flat_hazmat_surcharge(api):
    """PRD 3.4: "The tier fixes a discount rate — 0 percent for `BRONZE`, 5
    percent for `SILVER`, 10 percent for `GOLD` — and `discount_cents` is the
    floor of `subtotal_cents` multiplied by that rate and divided by 100; the
    discount is keyed on the subtotal, never on the total."
    PRD 3.4: "The `hazmat_surcharge_cents` is a flat 500 cents if any line's
    product is a battery and 0 otherwise."

    Design: Difficulty/combinatorial_formula/cf_order_total_tiered_discount_plus_hazmat_surcharge
    """
    buyer = make_customer(api, ack=True)  # BRONZE
    kit = make_product(api, product_type="KIT", price_cents=10000, stock_on_hand=10)
    bat = make_product(api, product_type="BATTERY", price_cents=5000, stock_on_hand=10)
    order = make_order(api, buyer["id"], [
        order_line(kit["id"], 2, 10000),
        order_line(bat["id"], 1, 5000),
    ])
    placed = place_order(api, order["id"])
    assert placed["discount_cents"] == 0, "BRONZE tier discount is 0"
    assert placed["hazmat_surcharge_cents"] == 500, "flat surcharge when a battery line is present"


# ---------------------------------------------------------------------------
# cf_loyalty_points_per_line_floor_then_sum
# ---------------------------------------------------------------------------
def test_provisional_points_floor_each_line_then_sum(api):
    """PRD 3.4: "For each line, the line's points are the floor of `quantity`
    multiplied by `unit_price_cents` multiplied by the tier multiplier, all
    divided by 10,000; the floor is applied to each line individually and the
    floored line results are then summed — never summed first and floored once."

    Design: Difficulty/combinatorial_formula/cf_loyalty_points_per_line_floor_then_sum
    """
    buyer = make_customer(api)  # BRONZE, multiplier 100
    part = make_product(api, product_type="PART", price_cents=150, stock_on_hand=10)
    order = make_order(api, buyer["id"], [
        order_line(part["id"], 1, 150),
        order_line(part["id"], 1, 150),
    ])
    placed = place_order(api, order["id"])
    assert placed["subtotal_cents"] == 300
    # floor(150*100/10000)=1 per line, summed -> 2 (sum-then-floor would give 3)
    assert placed["provisional_points"] == 2


def test_provisional_points_rejects_sum_then_floor(api):
    """PRD 3.4: "the floor is applied to each line individually and the floored
    line results are then summed — never summed first and floored once."

    Design: Difficulty/combinatorial_formula/cf_loyalty_points_per_line_floor_then_sum
    """
    buyer = make_customer(api)
    part = make_product(api, product_type="PART", price_cents=150, stock_on_hand=10)
    order = make_order(api, buyer["id"], [
        order_line(part["id"], 1, 150),
        order_line(part["id"], 1, 150),
    ])
    placed = place_order(api, order["id"])
    assert placed["provisional_points"] != 3, "sum-then-floor (=3) must be rejected"
    assert placed["provisional_points"] == 2


# ---------------------------------------------------------------------------
# dv_order_loyalty_provisional_vs_final_on_tier_up
# ---------------------------------------------------------------------------
def test_provisional_points_use_placement_tier_snapshot(api):
    """PRD 3.4: "`provisional_points` is that per-line-floored sum under the
    placement tier, and it is added to the buyer's `loyalty_points_balance` at
    placement."

    Design: Difficulty/dual_variant_calc/dv_order_loyalty_provisional_vs_final_on_tier_up
    """
    buyer = make_customer(api)  # BRONZE at placement
    prod = make_product(api, product_type="KIT", price_cents=50000, stock_on_hand=10)
    o1 = make_order(api, buyer["id"], [order_line(prod["id"], 1, 50000)])
    o1_placed = place_order(api, o1["id"])
    # floor(1*50000*100/10000) = 500 under BRONZE
    assert o1_placed["provisional_points"] == 500


def test_final_points_use_fulfill_tier_after_tier_up(api):
    """PRD 3.4: "The order's `final_points` are then computed with the very same
    per-line-floor-then-sum method used for provisional points, but under the
    buyer's tier evaluated as of the moment immediately before this order's
    total was folded into lifetime spend; because a large order can itself push
    the buyer over a threshold, `final_points` can exceed `provisional_points`."
    PRD 3.1: "otherwise in `SILVER` once it reaches at least 50,000 cents (500
    dollars); otherwise in `BRONZE`."

    Design: Difficulty/dual_variant_calc/dv_order_loyalty_provisional_vs_final_on_tier_up
    """
    buyer = make_customer(api)  # BRONZE
    prod = make_product(api, product_type="KIT", price_cents=50000, stock_on_hand=10)
    # O1 placed while BRONZE (provisional 500), left unpaid for now.
    o1 = make_order(api, buyer["id"], [order_line(prod["id"], 1, 50000)])
    o1_placed = place_order(api, o1["id"])
    assert o1_placed["provisional_points"] == 500

    # O2 fulfilled to push lifetime_spend to 50000 -> SILVER.
    o2 = make_order(api, buyer["id"], [order_line(prod["id"], 1, 50000)])
    o2_placed = place_order(api, o2["id"])
    pay_order(api, o2["id"], o2_placed["total_cents"])
    fulfill_order(api, o2["id"])
    buyer_after = get_success_data(api.get_customer(buyer["id"], STAFF))
    assert buyer_after["loyalty_tier"] == "SILVER"

    # Now pay & fulfill O1: final uses SILVER tier (as of before O1's total booked).
    pay_order(api, o1["id"], o1_placed["total_cents"])
    o1_final = fulfill_order(api, o1["id"])
    # floor(1*50000*150/10000) = 750 under SILVER
    assert o1_final["final_points"] == 750


# ---------------------------------------------------------------------------
# bp_loyalty_tier_inclusive_spend_threshold
# ---------------------------------------------------------------------------
def test_lifetime_spend_sums_fulfilled_order_totals(api):
    """PRD 3.1: "Lifetime spend itself is the sum of `total_cents` across only
    those of the member's orders whose `fulfillment_status` is `FULFILLED`;
    unfulfilled, draft, or cancelled orders never contribute."

    Design: Difficulty/boundary_precision_check/bp_loyalty_tier_inclusive_spend_threshold
    """
    _order, buyer, _prod = make_fulfilled_order(api, unit_price_cents=50000, quantity=1)
    buyer_after = get_success_data(api.get_customer(buyer["id"], STAFF))
    assert buyer_after["lifetime_spend_cents"] == 50000


def test_tier_flips_to_silver_at_inclusive_50000_boundary(api):
    """PRD 3.1: "so lifetime spend of exactly 50,000 cents is `SILVER` and
    exactly 200,000 cents is `GOLD`."

    Design: Difficulty/boundary_precision_check/bp_loyalty_tier_inclusive_spend_threshold
    """
    _order, buyer, _prod = make_fulfilled_order(api, unit_price_cents=50000, quantity=1)
    buyer_after = get_success_data(api.get_customer(buyer["id"], STAFF))
    assert buyer_after["lifetime_spend_cents"] == 50000
    assert buyer_after["loyalty_tier"] == "SILVER"


# ---------------------------------------------------------------------------
# ci_loyalty_points_conserved_on_order_cancel
# ---------------------------------------------------------------------------
def test_cancel_reverses_provisional_points_to_zero(api):
    """PRD 3.4: "Cancellation restores stock by adding each line's `quantity`
    back to its product's `stock_on_hand`, reverses the provisional loyalty
    credit by subtracting `provisional_points` from the buyer's
    `loyalty_points_balance`".

    Design: Difficulty/compensating_invariant/ci_loyalty_points_conserved_on_order_cancel
    """
    order, buyer, _prod = make_placed_order(api, price_cents=10000,
                                            stock_on_hand=5, unit_price_cents=10000)
    assert order["provisional_points"] == 100
    buyer_placed = get_success_data(api.get_customer(buyer["id"], STAFF))
    assert buyer_placed["loyalty_points_balance"] == 100
    cancel_order(api, order["id"])
    buyer_after = get_success_data(api.get_customer(buyer["id"], STAFF))
    assert buyer_after["loyalty_points_balance"] == 0


def test_cancel_restores_stock(api):
    """PRD 3.4: "Cancellation restores stock by adding each line's `quantity`
    back to its product's `stock_on_hand`".

    Design: Difficulty/compensating_invariant/ci_loyalty_points_conserved_on_order_cancel
    """
    order, _buyer, prod = make_placed_order(api, price_cents=10000,
                                            stock_on_hand=5, unit_price_cents=10000)
    after_place = get_success_data(api.get_product(prod["id"], STAFF))
    assert after_place["stock_on_hand"] == 4, "one unit reserved at placement"
    cancel_order(api, order["id"])
    after_cancel = get_success_data(api.get_product(prod["id"], STAFF))
    assert after_cancel["stock_on_hand"] == 5, "stock restored on cancellation"


# ---------------------------------------------------------------------------
# cn_order_defaults_source_standard
# ---------------------------------------------------------------------------
def test_order_defaults_source_standard_and_initial_states(api):
    """PRD 3.4: "A buyer (or staff acting for them) creates it with the buyer's
    `customer_id`, an optional `source` that defaults to `STANDARD`, and an
    array of `lines`".
    PRD 3.4: "A new order rests in `status` `DRAFT`, `payment_status` `UNPAID`,
    and `fulfillment_status` `PENDING`, with all totals and points at 0 until it
    is placed."

    Design: Corner/entities/cn_order_defaults_source_standard
    """
    buyer = make_customer(api)
    prod = make_product(api, product_type="PART", price_cents=2000, stock_on_hand=5)
    order = make_order(api, buyer["id"], [order_line(prod["id"], 1, 2000)])
    assert order["source"] == "STANDARD"
    assert order["status"] == "DRAFT"
    assert order["payment_status"] == "UNPAID"
    assert order["fulfillment_status"] == "PENDING"


# ---------------------------------------------------------------------------
# cn_order_create_missing_customer_returns_400
# ---------------------------------------------------------------------------
def test_order_create_without_customer_id_rejected(api):
    """PRD 3.4: "A buyer (or staff acting for them) creates it with the buyer's
    `customer_id`, an optional `source` that defaults to `STANDARD`, and an
    array of `lines`".
    PRD 2.9: "Generic field-level validation — quantities and units at least 1,
    valid enum members, pagination bounds — is last, yielding `ERR_VALIDATION`."

    Design: Corner/entities/cn_order_create_missing_customer_returns_400
    """
    prod = make_product(api, product_type="PART", price_cents=1000, stock_on_hand=5)
    payload = create_order_payload(lines=[order_line(prod["id"], 1, 1000)])
    payload.pop("customer_id", None)
    resp = api.create_order(payload, STAFF)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
