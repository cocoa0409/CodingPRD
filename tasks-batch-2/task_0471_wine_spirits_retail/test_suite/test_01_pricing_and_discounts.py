"""Order pricing: case discount, provisional vs settled totals, rounding, exclusions.

Covers difficulty queue dual_variant_calc + combinatorial_formula, and corner
queue calculations + consistency_model instances that turn on the §3.6 pricing
narrative and the §3.8 club-tier roll-up.
"""
from test_helpers import (
    validate_success, get_success_data,
    TEST_USERS, make_customer_headers, fixtures as fx,
)
from test_helpers.api_client import api_client

ADMIN = TEST_USERS["admin_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_provisional_and_settled_diverge_on_bonded_line(api):
    """PRD §3.6: "The provisional total is the discounted subtotal plus the estimated tax."
    PRD §3.6: "The settled total is the discounted subtotal plus the excise total plus the final tax. The settled total diverges from the provisional total exactly when some line drew from a bonded lot."
    PRD §3.6: "The taxable base — and this ordering is pinned, because excise is itself taxable — is the discounted subtotal plus the excise total."

    Design: Difficulty/dual_variant_calc/provisional_vs_settled_total_diverge_on_bonded_line
    """
    fx.set_clock()
    cust = fx.create_verified_customer("dv1@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage(
        "DV-W-1", category="WINE", bottle_volume_ml=750, abv_pct=13.50,
        list_price_cents=5000, case_pack_size=6,
        tax_status="BONDED", qty_on_hand=6, excise_band_cents_per_unit=80,
        vintage_year=2019)

    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 6)
    submitted = fx.submit_order(cust, order["id"])
    assert submitted["provisional_total_cents"] == 27349, \
        f"provisional should be 27349, got {submitted['provisional_total_cents']}"

    fx.authorize(cust, order["id"])
    captured = validate_success(api_client.capture_payment(order["id"], ASSOCIATE))

    assert captured["provisional_total_cents"] == 27349
    assert captured["settled_total_cents"] == 27864, \
        f"settled should be 27864, got {captured['settled_total_cents']}"
    assert captured["settled_total_cents"] - captured["provisional_total_cents"] == 515


def test_case_discount_mixed_and_full_nonlinear(api):
    """PRD §3.6: "Full-case units always earn the full-case rate of fifteen percent. Mixed-case units earn the mixed-case rate of ten percent only when the total discountable unit count is at least 12; otherwise mixed-case units earn nothing."
    PRD §3.6: "the full-case unit count is the sum over discountable lines of the part of each line's `qty` that forms whole multiples of that line's own `case_pack_size`"

    Design: Difficulty/combinatorial_formula/case_discount_mixed_and_full_three_input_nonlinear
    """
    fx.set_clock()
    cust = fx.create_verified_customer("cf1@x.com", ship_state_code="CA")
    _, vA, _ = fx.setup_released_vintage("CF-A", list_price_cents=2000, case_pack_size=6,
                                         qty_on_hand=20, vintage_year=2020, abv_pct=13.00)
    _, vB, _ = fx.setup_released_vintage("CF-B", list_price_cents=1000, case_pack_size=12,
                                         qty_on_hand=20, vintage_year=2020, abv_pct=12.00)

    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vA["id"], 8)
    fx.add_line(cust, order["id"], vB["id"], 6)
    submitted = fx.submit_order(cust, order["id"])

    assert submitted["discount_cents"] == 2800, \
        f"discount should be 2800, got {submitted['discount_cents']}"
    assert submitted["provisional_total_cents"] == 20592, \
        f"provisional should be 20592, got {submitted['provisional_total_cents']}"


def test_case_discount_rounds_each_component_before_summing(api):
    """PRD §3.6: "The discount is then the full-case value times fifteen percent, rounded half up to the nearest cent, plus the mixed-case value times the applicable mixed-case rate (ten percent when the total discountable unit count is at least 12, otherwise zero), rounded half up to the nearest cent. The rounding order is pinned: round each of the two components independently and then sum them, never round a single product of total times rate."

    Design: Difficulty/combinatorial_formula/case_discount_rounding_per_component_then_sum_order_pinned
    """
    fx.set_clock()
    cust = fx.create_verified_customer("cf2@x.com", ship_state_code="CA")
    _, vA, _ = fx.setup_released_vintage("CF-RA", list_price_cents=85, case_pack_size=6,
                                         qty_on_hand=20, vintage_year=2021, abv_pct=13.00)
    _, vB, _ = fx.setup_released_vintage("CF-RB", list_price_cents=205, case_pack_size=12,
                                         qty_on_hand=20, vintage_year=2021, abv_pct=12.00)
    _, vC, _ = fx.setup_released_vintage("CF-RC", list_price_cents=50, case_pack_size=6,
                                         qty_on_hand=20, vintage_year=2021, abv_pct=11.00)

    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vA["id"], 6)
    fx.add_line(cust, order["id"], vB["id"], 1)
    fx.add_line(cust, order["id"], vC["id"], 6)
    submitted = fx.submit_order(cust, order["id"])

    assert submitted["discount_cents"] == 143, \
        f"per-component rounding must yield 143, not 142; got {submitted['discount_cents']}"


def test_provisional_total_and_discount_present_in_submit_response(api):
    """PRD §3.6: "The **case discount** is computed at submit and stored as the order's `discount_cents`."
    PRD §3.6: "The **provisional total**, stored as `provisional_total_cents`, is also computed at submit, before any bonded stock is withdrawn, and therefore carries an estimated excise of zero."
    PRD §2.5: "The system applies all such cascades immediately and synchronously within the triggering request; there is no eventual consistency."

    Design: Corner/consistency_model/immediate_consistency_totals_visible_in_submit_response
    """
    fx.set_clock()
    cust = fx.create_verified_customer("im2@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("IM-2", list_price_cents=5000, case_pack_size=6,
                                           qty_on_hand=6, vintage_year=2020)

    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vint["id"], 6)
    ver = fx.current_order_version(cust, order["id"])
    resp = api_client.submit_order(order["id"], {"expected_order_version": ver},
                                   make_customer_headers(cust["id"]))
    data = validate_success(resp)

    assert data["discount_cents"] == 4500, f"discount should be 4500, got {data['discount_cents']}"
    assert data["provisional_total_cents"] == 27349, \
        f"provisional should be 27349, got {data['provisional_total_cents']}"


def test_growler_line_excluded_from_case_discount(api):
    """PRD §3.6: "Growler and keg category lines are excluded entirely from the discount — neither their value nor their units count — because draft containers earn no case discount."

    Design: Corner/calculations/growler_keg_excluded_from_case_discount
    """
    fx.set_clock()
    cust = fx.create_verified_customer("gk1@x.com", ship_state_code="CA")
    _, vw, _ = fx.setup_released_vintage("GK-W", category="WINE", list_price_cents=5000,
                                         case_pack_size=6, qty_on_hand=10, vintage_year=2020)
    _, vg, _ = fx.setup_released_vintage("GK-G", category="GROWLER",
                                         container_type="GROWLER_FILL", bottle_volume_ml=1900,
                                         abv_pct=5.00, list_price_cents=1500,
                                         case_pack_size=1, qty_on_hand=10, vintage_year=2026)

    order = fx.create_cart_order(cust, channel="POS")
    fx.add_line(cust, order["id"], vw["id"], 6)
    fx.add_line(cust, order["id"], vg["id"], 4)
    submitted = fx.submit_order(cust, order["id"])

    assert submitted["discount_cents"] == 4500, \
        f"growler line must not change the 4500 wine-case discount, got {submitted['discount_cents']}"


def test_club_tier_silver_at_50000_boundary_with_points(api):
    """PRD §3.8: "otherwise if it is at least 50000 cents the tier becomes `SILVER` with a multiplier of 1.25"
    PRD §3.8: "The threshold boundary is pinned to be inclusive: a rolling spend of exactly 50000 cents qualifies as `SILVER`, and exactly 200000 cents qualifies as `GOLD`."
    PRD §3.8: "Points for the just-completed order are computed by taking the order's `settled_total_cents`, dividing by 100 and discarding any fractional remainder to get a base, then multiplying that base by the tier multiplier and rounding half up to a whole number of points; the result is added to the membership's `accrued_points`."

    Design: Corner/calculations/club_tier_silver_boundary_at_exactly_50000
    """
    fx.set_clock()
    cust = fx.create_verified_customer("ct1@x.com", ship_state_code="CA")
    membership = fx.create_membership(cust)
    _, vint, _ = fx.setup_released_vintage("CT-1", list_price_cents=3411, case_pack_size=6,
                                           qty_on_hand=20, vintage_year=2020)

    order = fx.build_ready_order(cust, vint["id"], 18, channel="POS")
    validate_success(api_client.complete_order(order["id"], ASSOCIATE))

    customer = get_success_data(api_client.get_customer(cust["id"], ASSOCIATE))
    assert customer["lifetime_spend_cents"] == 55972, \
        f"lifetime spend should be 55972, got {customer['lifetime_spend_cents']}"

    cm = get_success_data(api_client.get_membership(membership["id"], ASSOCIATE))
    assert cm["tier"] == "SILVER", f"tier should be SILVER, got {cm['tier']}"
    assert cm["accrued_points"] == 699, f"points should be 699, got {cm['accrued_points']}"


def test_lifetime_spend_excludes_refunded_order(api):
    """PRD §3.7: "The customer's **lifetime spend** is the sum of `settled_total_cents` over the customer's orders whose `payment_status` is `CAPTURED` and whose `fulfillment_status` is not `CANCELLED`; refunded orders are excluded."
    PRD §3.10: "A refund releases every line's reservation (`reservation_state → RELEASED`), credits `qty_reserved` back, restores `qty_on_hand` on the lot each line drew from, sets the order's `fulfillment_status` to `CANCELLED`, deactivates any compliance-window row for the order, and recomputes the customer's `lifetime_spend_cents` and `compliance_status`."

    Design: Corner/calculations/lifetime_spend_excludes_refunded_orders
    """
    fx.set_clock()
    cust = fx.create_verified_customer("ls1@x.com", ship_state_code="CA")
    _, vint, _ = fx.setup_released_vintage("LS-1", list_price_cents=3000, case_pack_size=6,
                                           qty_on_hand=10, vintage_year=2020)

    order = fx.build_captured_order(cust, vint["id"], 2, channel="POS")
    refunded = validate_success(api_client.refund_order(order["id"], COMPLIANCE))

    assert refunded["payment_status"] == "REFUNDED"
    assert refunded["fulfillment_status"] == "CANCELLED"
    customer = get_success_data(api_client.get_customer(cust["id"], ASSOCIATE))
    assert customer["lifetime_spend_cents"] == 0, \
        f"refunded order must be excluded; lifetime should be 0, got {customer['lifetime_spend_cents']}"
