"""Retail orders: provisional vs. final pricing divergence, round-per-line
discounting, the fulfill->points->tier->other-order cascade, loyalty standing,
inventory conservation, and order-state guards."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_member_headers, make_staff_headers,
    TEST_USERS,
    fixtures as fx,
)
import test_helpers.factories as f

SM = TEST_USERS["store_manager_headers"]


def _member_active_sub(api, tier):
    member = fx.new_member(api)
    hdr = make_member_headers(member["id"])
    sub = fx.new_subscription(api, member["id"], member["version"], tier=tier)
    get_success_data(api.activate_subscription(sub["id"], hdr))
    return member, sub


# ---- Rule 1: provisional vs. final divergence on subscription lapse ----

def test_provisional_total_reads_active_subscription_at_place(api):
    """PRD §3.6: "At placement this fills `provisional_discount_cents` and
    `provisional_total_cents` (the provisional variant), reading the member's
    `loyalty_tier` and subscription status as of placement."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_diverge_on_subscription_lapse
    """
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    member, sub = _member_active_sub(api, "CLUB_PRO")
    product = fx.new_product(api, sku="SK-12000", category="GEAR", name="Vest", price_cents=12000, stock_on_hand=10)
    placed = fx.new_placed_order(api, member["id"], product["id"], qty=1)
    assert placed["provisional_discount_cents"] == 2400
    assert placed["provisional_total_cents"] == 9600


def test_final_total_reads_lapsed_subscription_at_fulfill(api):
    """PRD §3.6: "Pricing is recomputed as the **final variant** using the member's
    `loyalty_tier` and subscription state as of the fulfillment instant — which may
    differ from placement time if the subscription lapsed to `PAST_DUE` or the tier
    changed — writing `final_discount_cents` and `final_total_cents`; the same lines
    can therefore yield a `final_total_cents` different from `provisional_total_cents`."

    Design: Difficulty/dual_variant_calc/order_pricing_provisional_vs_final_diverge_on_subscription_lapse
    """
    fx.set_clock(api, "2026-07-01T00:00:00Z")
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member, sub = _member_active_sub(api, "CLUB_PRO")
    product = fx.new_product(api, sku="SK-12000", category="GEAR", name="Vest", price_cents=12000, stock_on_hand=10)
    placed = fx.new_placed_order(api, member["id"], product["id"], qty=1)
    # Subscription lapses to PAST_DUE before fulfillment (club discount now 0).
    get_success_data(api.renew_subscription(sub["id"], f.renew_payload("FAILED"), SM))
    fulfilled = get_success_data(api.fulfill_order(placed["id"], make_staff_headers(staff["id"])))
    assert fulfilled["final_total_cents"] == 12000
    assert fulfilled["final_total_cents"] != placed["provisional_total_cents"]


# ---- Rule 2b: round-per-line-then-sum ----

def test_order_discount_rounds_per_line_then_sums(api):
    """PRD §2.6: "In order pricing specifically, rounding is applied **per line item
    before summing** — each line's discount is rounded to whole cents first, and only
    then are the rounded per-line discounts added together (round-per-line-then-sum,
    never sum-then-round)."

    Design: Difficulty/combinatorial_formula/order_pricing_round_per_line_then_sum_mode_b
    """
    member, sub = _member_active_sub(api, "CLUB_BASIC")
    product = fx.new_product(api, sku="SK-105", category="GEAR", name="Socks", price_cents=105, stock_on_hand=10)
    order = fx.new_cart_order(api, member["id"])
    fx.add_line(api, order["id"], member["id"], product["id"], qty=1)
    fx.add_line(api, order["id"], member["id"], product["id"], qty=1)
    placed = get_success_data(api.place_order(order["id"], make_member_headers(member["id"])))
    assert placed["subtotal_cents"] == 210
    assert placed["provisional_discount_cents"] == 22


def test_order_provisional_total_after_per_line_rounding(api):
    """PRD §3.6: "The discount is then computed per line and summed: each line's
    `line_gross_cents` is multiplied by that effective rate and rounded half-up to
    whole cents, and these rounded per-line discounts are added together to form the
    order's discount. The order total is `subtotal_cents` minus that summed discount."

    Design: Difficulty/combinatorial_formula/order_pricing_round_per_line_then_sum_mode_b
    """
    member, sub = _member_active_sub(api, "CLUB_BASIC")
    product = fx.new_product(api, sku="SK-105", category="GEAR", name="Socks", price_cents=105, stock_on_hand=10)
    order = fx.new_cart_order(api, member["id"])
    fx.add_line(api, order["id"], member["id"], product["id"], qty=1)
    fx.add_line(api, order["id"], member["id"], product["id"], qty=1)
    placed = get_success_data(api.place_order(order["id"], make_member_headers(member["id"])))
    assert placed["provisional_total_cents"] == 188


# ---- Rule 4a: fulfill cascade points -> tier -> other placed order ----

def test_fulfill_awards_points_and_recomputes_tier(api):
    """PRD §3.6: "Fulfillment then awards loyalty: the member's `loyalty_points`
    increases by `final_total_cents` divided by 100 and rounded down, and the
    member's `loyalty_tier` is recomputed from the new points total."

    Design: Difficulty/transitive_cascade/order_fulfill_cascades_points_then_tier_then_other_order_pricing
    """
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member = fx.new_member(api)
    pb = fx.new_product(api, sku="PB-120000", category="GEAR", name="Coat", price_cents=120000, stock_on_hand=5)
    pa = fx.new_product(api, sku="PA-160000", category="GEAR", name="GPS", price_cents=160000, stock_on_hand=5)
    fx.new_placed_order(api, member["id"], pb["id"], qty=1)      # OB stays PLACED
    oa = fx.new_placed_order(api, member["id"], pa["id"], qty=1)  # OA to be fulfilled
    fulfilled = get_success_data(api.fulfill_order(oa["id"], make_staff_headers(staff["id"])))
    assert fulfilled["final_total_cents"] == 160000
    m = fx.get_member(api, member["id"])
    assert m["loyalty_points"] == 1600
    assert m["loyalty_tier"] == "GOLD"


def test_fulfill_cascade_reprices_other_placed_order(api):
    """PRD §3.6: "Finally, a cascade runs: if that recomputation changed the member's
    `loyalty_tier`, every other order of the member still in `PLACED` status has its
    `provisional_discount_cents` and `provisional_total_cents` recomputed under the
    new tier, keeping each placed order's provisional pricing reconciled with the
    member's current standing."

    Design: Difficulty/transitive_cascade/order_fulfill_cascades_points_then_tier_then_other_order_pricing
    """
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member = fx.new_member(api)
    pb = fx.new_product(api, sku="PB-120000", category="GEAR", name="Coat", price_cents=120000, stock_on_hand=5)
    pa = fx.new_product(api, sku="PA-160000", category="GEAR", name="GPS", price_cents=160000, stock_on_hand=5)
    ob = fx.new_placed_order(api, member["id"], pb["id"], qty=1)
    oa = fx.new_placed_order(api, member["id"], pa["id"], qty=1)
    assert ob["provisional_total_cents"] == 120000  # priced at BRONZE (no discount)
    get_success_data(api.fulfill_order(oa["id"], make_staff_headers(staff["id"])))
    ob_after = fx.get_order(api, ob["id"])
    assert ob_after["provisional_discount_cents"] == 12000  # GOLD 10% of 120000
    assert ob_after["provisional_total_cents"] == 108000


# ---- Rule 1b: loyalty earned vs. projected ----

def test_loyalty_earned_points_and_current_tier(api):
    """PRD §3.1: "the earned balance is the total of `final_total_cents` across all
    of the member's orders in `FULFILLED` status, divided by 100 and rounded down to a
    whole number of points."

    Design: Difficulty/dual_variant_calc/loyalty_earned_vs_projected_tier_diverge_on_member
    """
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member = fx.new_member(api)
    pc = fx.new_product(api, sku="PC-60000", category="GEAR", name="Jacket", price_cents=60000, stock_on_hand=5)
    fx.new_fulfilled_order(api, member["id"], pc["id"], staff["id"], qty=1)  # earns 600 -> SILVER
    standing = get_success_data(api.get_member_loyalty(member["id"], make_member_headers(member["id"])))
    assert standing["earned_points"] == 600
    assert standing["current_tier"] == "SILVER"


def test_loyalty_projected_points_include_placed_orders(api):
    """PRD §3.1: "The `projected_points` figure adds, to that same fulfilled total,
    the sum of `provisional_total_cents` across the member's orders currently in
    `PLACED` status, the combined cents total again divided by 100 and rounded down;
    `projected_tier` is the tier derived from `projected_points` using the identical
    thresholds, and it can therefore exceed `current_tier`."

    Design: Difficulty/dual_variant_calc/loyalty_earned_vs_projected_tier_diverge_on_member
    """
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member = fx.new_member(api)
    pc = fx.new_product(api, sku="PC-60000", category="GEAR", name="Jacket", price_cents=60000, stock_on_hand=5)
    pd = fx.new_product(api, sku="PD-120000", category="GEAR", name="Watch", price_cents=120000, stock_on_hand=5)
    fx.new_fulfilled_order(api, member["id"], pc["id"], staff["id"], qty=1)  # -> SILVER persisted
    fx.new_placed_order(api, member["id"], pd["id"], qty=1)                  # provisional at SILVER 0.05 -> 114000
    standing = get_success_data(api.get_member_loyalty(member["id"], make_member_headers(member["id"])))
    assert standing["projected_points"] == 1740
    assert standing["projected_tier"] == "GOLD"


# ---- Rule 9a: inventory conservation ----

def test_place_reserves_inventory(api):
    """PRD §3.6: "On success the order moves from `CART` to `PLACED`: for each line
    the product's `stock_on_hand` is decreased by the line quantity and its
    `stock_reserved` increased by the same amount, provisional pricing is computed
    (below), and `placed_at` is stamped from the logical clock."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_across_place_then_cancel
    """
    member = fx.new_member(api)
    product = fx.new_product(api, sku="INV-1", category="GEAR", name="Cap", price_cents=2000, stock_on_hand=10)
    fx.new_placed_order(api, member["id"], product["id"], qty=3)
    p = fx.get_product(api, product["id"])
    assert p["stock_on_hand"] == 7
    assert p["stock_reserved"] == 3


def test_cancel_placed_order_releases_reservation(api):
    """PRD §3.6: "Cancelling a `PLACED` order releases its reservation — for each
    line the product's `stock_reserved` is decreased and its `stock_on_hand`
    increased by the line quantity — while cancelling a `CART` order releases nothing,
    since nothing was reserved."

    Design: Difficulty/compensating_invariant/inventory_units_conserved_across_place_then_cancel
    """
    member = fx.new_member(api)
    product = fx.new_product(api, sku="INV-1", category="GEAR", name="Cap", price_cents=2000, stock_on_hand=10)
    placed = fx.new_placed_order(api, member["id"], product["id"], qty=3)
    get_success_data(api.cancel_order(placed["id"], make_member_headers(member["id"])))
    p = fx.get_product(api, product["id"])
    assert p["stock_on_hand"] == 10
    assert p["stock_reserved"] == 0


# ---- Corner: insufficient stock, invalid state, immediate visibility, validation ----

def test_place_order_insufficient_stock_rejected(api):
    """PRD §3.6: "every line's product must have `stock_on_hand` at least equal to
    that line's `qty`; if any line is short, the placement is rejected with
    `ERR_INSUFFICIENT_STOCK` (409)."

    Design: Corner/validations/place_order_insufficient_stock_returns_error
    """
    member = fx.new_member(api)
    product = fx.new_product(api, sku="ST-1", category="GEAR", name="Band", price_cents=800, stock_on_hand=1)
    order = fx.new_cart_order(api, member["id"])
    fx.add_line(api, order["id"], member["id"], product["id"], qty=5)
    resp = api.place_order(order["id"], make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK, 409)


def test_fulfill_cart_order_rejected(api):
    """PRD §3.6: "Fulfilling an order that is not `PLACED`, placing one that is not
    `CART`, or cancelling one already terminal each yields `ERR_INVALID_STATE`
    (409)."

    Design: Corner/state_machines/fulfill_cart_order_returns_invalid_state
    """
    store = fx.new_store(api)
    staff = fx.new_staff(api, store["id"], role_type="BOTH")
    member = fx.new_member(api)
    product = fx.new_product(api, sku="C-1", category="GEAR", name="Tee", price_cents=3000, stock_on_hand=5)
    order = fx.new_cart_order(api, member["id"])
    fx.add_line(api, order["id"], member["id"], product["id"], qty=1)
    resp = api.fulfill_order(order["id"], make_staff_headers(staff["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_reservation_visible_immediately_after_place(api):
    """PRD §3.6: "On success the order moves from `CART` to `PLACED`: for each line
    the product's `stock_on_hand` is decreased by the line quantity and its
    `stock_reserved` increased by the same amount, provisional pricing is computed
    (below), and `placed_at` is stamped from the logical clock."

    Design: Corner/consistency_model/place_order_reservation_visible_immediately
    """
    member = fx.new_member(api)
    product = fx.new_product(api, sku="IM-1", category="GEAR", name="Z", price_cents=1000, stock_on_hand=10)
    fx.new_placed_order(api, member["id"], product["id"], qty=3)
    p = validate_success(api.get_product(product["id"], SM))
    assert p["stock_on_hand"] == 7
    assert p["stock_reserved"] == 3


def test_add_line_missing_qty_rejected(api):
    """PRD §2.8: "Third, request-body well-formedness is checked — required fields
    present, enum values legal, numeric quantities and amounts at least their declared
    minimums, `end_at` strictly after `start_at`, and `expected_member_version`
    present on subscription create — with any violation yielding `ERR_VALIDATION`
    (400)."

    Design: Corner/validations/order_line_missing_required_qty_returns_validation
    """
    member = fx.new_member(api)
    product = fx.new_product(api, sku="V-1", category="GEAR", name="Hat", price_cents=1000, stock_on_hand=5)
    order = fx.new_cart_order(api, member["id"])
    resp = api.add_order_line(order["id"], {"product_id": product["id"]}, make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)
