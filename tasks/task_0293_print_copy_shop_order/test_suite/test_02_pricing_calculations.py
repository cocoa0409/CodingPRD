"""Line pricing, order totals, tiered discounts, finishing, rush, and estimate-vs-locked."""
import pytest
from test_helpers import (
    api_client, get_success_data,
    validate_success,
    create_shop, create_customer, create_product, create_pricing_tier,
    create_finishing_option, create_order, add_line, upload_and_pass_preflight,
    add_pickup_fulfillment, add_ship_fulfillment, read_order_version, confirm_order,
    pin_clock, setup_priced_confirmable_order,
    TEST_USERS, make_customer_headers,
)

STAFF = TEST_USERS["shop_staff_headers"]


# ─── Calculation correctness ─────────────────────────────────────────────────
def test_rush_cutoff_hour_inclusive_boundary_slips_a_day(api):
    """PRD §3.6: "A `RUSH` line starts from that date plus the shop's
    `rush_turnaround_days` whole days, and then slips one further production day if the
    confirm happened at or after the shop's `rush_cutoff_hour_utc` — the comparison is
    inclusive, so a confirm landing exactly on the cutoff hour incurs the slip."

    Design: Corner/calculations/rush_cutoff_hour_inclusive_boundary_slips_a_day
    """
    pin_clock("2026-06-01T14:00:00Z")
    shop = create_shop(name="S16", rush_cutoff_hour_utc=14,
                       standard_turnaround_days=3, rush_turnaround_days=1)
    cust = create_customer(shop["id"], email="s16@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"], service_level="RUSH")
    upload_and_pass_preflight(line["id"], cust["id"])
    add_pickup_fulfillment(order["id"], cust["id"])
    v = read_order_version(order["id"], cust["id"])
    confirmed = validate_success(confirm_order(order["id"], cust["id"], v), 200)
    line_after = get_success_data(api.get_order_line(line["id"], make_customer_headers(cust["id"])))
    assert line_after["promised_ready_date"] == "2026-06-03"
    assert confirmed["promised_ready_date"] == "2026-06-03"


def test_flat_finishing_charged_once_not_per_unit(api):
    """PRD §3.2: "for each applied finishing option, a `PER_UNIT` option contributes its
    surcharge in cents multiplied by the quantity, while a `FLAT` option contributes its
    surcharge once for the whole line".

    Design: Corner/calculations/flat_finishing_charged_once_not_per_unit
    """
    shop = create_shop(name="S17")
    cust = create_customer(shop["id"], email="s17@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    create_finishing_option(prod["id"], "COIL_BIND", "FLAT", 300)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"], finishing_codes=["COIL_BIND"])
    assert line["estimate_line_cents"] == 5300, "base 500*10=5000 + FLAT 300 once"


def test_ship_fee_added_to_order_total_not_taxed(api):
    """PRD §3.6: "Finally the `total_cents` is the taxable base plus the `rush_fee_cents`
    plus the `tax_cents` plus the order's fulfillment shipping fee (which is 0 for a
    pickup)."

    Design: Corner/calculations/ship_fee_added_to_order_total
    """
    pin_clock("2026-06-01T09:00:00Z")
    shop = create_shop(name="S18", tax_rate_bps=0)
    cust = create_customer(shop["id"], email="s18@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=500, requires_proof=False, requires_press=False)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 10, cust["id"])
    upload_and_pass_preflight(line["id"], cust["id"])
    add_ship_fulfillment(order["id"], cust["id"], ship_fee_cents=1500)
    v = read_order_version(order["id"], cust["id"])
    confirmed = validate_success(confirm_order(order["id"], cust["id"], v), 200)
    assert confirmed["subtotal_cents"] == 5000
    assert confirmed["total_cents"] == 6500, "subtotal 5000 + ship 1500, no tax"


def test_tier_selection_picks_highest_qualifying_breakpoint(api):
    """PRD §3.2: "among the pricing tiers for the line's product, choose the one with the
    greatest `min_quantity` that is still less than or equal to the line's `quantity`".
    PRD §3.2: "The discounted unit price is the base unit price multiplied by the quantity
    ten-thousand-minus-the-tier-discount-basis-points divided by ten thousand, rounded
    half up to a whole cent **at this step only**."

    Design: Corner/calculations/tier_selection_picks_highest_qualifying_breakpoint
    """
    shop = create_shop(name="S19", daily_unit_capacity=100)
    cust = create_customer(shop["id"], email="s19@x.com")
    prod = create_product(shop["id"], name="P", category="COPIES",
                          base_unit_price_cents=1000, requires_proof=False, requires_press=False)
    create_pricing_tier(prod["id"], 10, 500)
    create_pricing_tier(prod["id"], 50, 2000)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 60, cust["id"])
    assert line["estimate_line_cents"] == 48000, "50-tier 20%: round(1000*0.8)=800 * 60"


# ─── Difficulty combinatorial_formula ────────────────────────────────────────
def test_line_price_nonlinear_tier_finishing_rush(api):
    """PRD §3.6: "At that lock, each line's `final_line_cents` is snapshotted using the
    very same tier-and-finishing arithmetic as the estimate". PRD §3.6: "for a `RUSH` line
    it is the locked `final_line_cents` multiplied by the shop's `rush_surcharge_bps`
    divided by ten thousand, rounded half up to a whole cent; for a `STANDARD` line it is
    0."

    Design: Difficulty/combinatorial_formula/line_price_nonlinear_tier_finishing_rush_inputs
    """
    ctx = setup_priced_confirmable_order(
        base_unit_price_cents=1000, quantity=100, tier=(50, 1000),
        finishing=("LAMINATE", "PER_UNIT", 50), service_level="RUSH",
        shop_overrides={"rush_surcharge_bps": 2000, "rush_cutoff_hour_utc": 23})
    validate_success(confirm_order(ctx["order"]["id"], ctx["customer"]["id"], ctx["version"]), 200)
    line = get_success_data(
        api.get_order_line(ctx["line"]["id"], make_customer_headers(ctx["customer"]["id"])))
    assert line["final_line_cents"] == 95000, "round(1000*0.9)=900*100 + PER_UNIT 50*100=5000"
    assert line["rush_surcharge_cents"] == 19000, "round(95000 * 2000bps)"


def test_line_price_rush_surcharge_zero_for_standard(api):
    """PRD §3.6: "for a `STANDARD` line it is 0. Note that `final_line_cents` itself
    excludes rush — the rush amount is carried separately and rolled into the order, not
    into the line's locked print price."

    Design: Difficulty/combinatorial_formula/line_price_nonlinear_tier_finishing_rush_inputs
    """
    ctx = setup_priced_confirmable_order(
        base_unit_price_cents=1000, quantity=100, tier=(50, 1000),
        finishing=("LAMINATE", "PER_UNIT", 50), service_level="STANDARD",
        shop_overrides={"rush_surcharge_bps": 2000, "rush_cutoff_hour_utc": 23})
    validate_success(confirm_order(ctx["order"]["id"], ctx["customer"]["id"], ctx["version"]), 200)
    line = get_success_data(
        api.get_order_line(ctx["line"]["id"], make_customer_headers(ctx["customer"]["id"])))
    assert line["final_line_cents"] == 95000
    assert line["rush_surcharge_cents"] == 0, "STANDARD line carries no rush surcharge"


def test_order_total_pinned_eval_discount_then_tax(api):
    """PRD §3.6: "a `SILVER` tier yields the subtotal times 500 basis points (5%)". PRD
    §3.6: "The taxable base is the `subtotal_cents` minus the `loyalty_discount_cents` —
    rush is deliberately not taxed. The `tax_cents` is that taxable base multiplied by the
    shop's `tax_rate_bps` divided by ten thousand, rounded half up to a whole cent".

    Design: Difficulty/combinatorial_formula/order_total_pinned_eval_order_discount_then_tax_then_rush
    """
    pin_clock("2026-06-01T09:00:00Z")
    shop = create_shop(name="Tax Shop", tax_rate_bps=825, rush_surcharge_bps=0,
                       rush_cutoff_hour_utc=23)
    cust = create_customer(shop["id"], email="d@x.com")
    get_success_data(api.inject_customer_loyalty(
        {"customer_id": cust["id"], "completed_order_count": 3, "lifetime_paid_cents": 40000,
         "loyalty_score": 3.0, "loyalty_tier": "SILVER"}, STAFF))
    prod = create_product(shop["id"], name="Color Copy", category="COPIES",
                          base_unit_price_cents=1000, requires_proof=False, requires_press=False)
    create_pricing_tier(prod["id"], 50, 1000)
    create_finishing_option(prod["id"], "LAMINATE", "PER_UNIT", 50)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 100, cust["id"],
                    finishing_codes=["LAMINATE"], service_level="STANDARD")
    upload_and_pass_preflight(line["id"], cust["id"])
    add_pickup_fulfillment(order["id"], cust["id"])
    v = read_order_version(order["id"], cust["id"])
    confirmed = validate_success(confirm_order(order["id"], cust["id"], v), 200)
    assert confirmed["subtotal_cents"] == 95000
    assert confirmed["loyalty_discount_cents"] == 4750, "round(95000 * 500bps)"
    assert confirmed["tax_cents"] == 7446, "round((95000-4750) * 825bps)"
    assert confirmed["total_cents"] == 97696, "taxable 90250 + rush 0 + tax 7446"


def test_order_total_no_discount_for_none_tier(api):
    """PRD §3.6: "a `NONE` tier yields no discount". PRD §3.6: "The `subtotal_cents` is the
    sum of the locked `final_line_cents` across all the order's lines; because each line
    figure is already a whole-cent integer, this sum is exact and is not re-rounded."

    Design: Difficulty/combinatorial_formula/order_total_pinned_eval_order_discount_then_tax_then_rush
    """
    pin_clock("2026-06-01T09:00:00Z")
    shop = create_shop(name="Tax Shop2", tax_rate_bps=825, rush_surcharge_bps=0,
                       rush_cutoff_hour_utc=23)
    cust = create_customer(shop["id"], email="d2@x.com")
    prod = create_product(shop["id"], name="Color Copy", category="COPIES",
                          base_unit_price_cents=1000, requires_proof=False, requires_press=False)
    create_pricing_tier(prod["id"], 50, 1000)
    create_finishing_option(prod["id"], "LAMINATE", "PER_UNIT", 50)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 100, cust["id"],
                    finishing_codes=["LAMINATE"], service_level="STANDARD")
    upload_and_pass_preflight(line["id"], cust["id"])
    add_pickup_fulfillment(order["id"], cust["id"])
    v = read_order_version(order["id"], cust["id"])
    confirmed = validate_success(confirm_order(order["id"], cust["id"], v), 200)
    assert confirmed["subtotal_cents"] == 95000
    assert confirmed["loyalty_discount_cents"] == 0, "NONE tier yields no discount"
    assert confirmed["tax_cents"] == 7838, "round(95000 * 825bps)"


# ─── Difficulty dual_variant_calc (estimate vs locked) ───────────────────────
def test_estimate_frozen_after_preflight_locked_differs_on_catalog_edit(api):
    """PRD §2.8: "The `estimate_line_cents` field is **provisional and forward-looking**:
    it is recomputed from the catalog rates *in force right now* every time the line is
    created or edited". PRD §3.1: "a staff member may later edit a product's
    `base_unit_price_cents` ... doing so recomputes `estimate_line_cents` on every
    still-`OPEN` line that references the product, but ... never disturbs a
    `final_line_cents` already frozen on a locked line."

    Design: Difficulty/dual_variant_calc/line_estimate_vs_locked_final_diverge_on_catalog_edit
    """
    pin_clock("2026-06-01T09:00:00Z")
    shop = create_shop(name="Lock Shop", tax_rate_bps=825, rush_surcharge_bps=2000,
                       rush_cutoff_hour_utc=14)
    cust = create_customer(shop["id"], email="a@x.com")
    prod = create_product(shop["id"], name="Color Copy", category="COPIES",
                          base_unit_price_cents=1000, unit_size=1,
                          requires_proof=False, requires_press=False, active=True)
    create_pricing_tier(prod["id"], 50, 1000)
    create_finishing_option(prod["id"], "LAMINATE", "PER_UNIT", 50)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 100, cust["id"],
                    finishing_codes=["LAMINATE"], service_level="STANDARD")
    # Now PREFLIGHT_OK (no longer OPEN), so the catalog edit will not move the estimate.
    upload_and_pass_preflight(line["id"], cust["id"])
    get_success_data(api.patch_product(prod["id"], {"base_unit_price_cents": 1200}, STAFF))
    add_pickup_fulfillment(order["id"], cust["id"])
    v = read_order_version(order["id"], cust["id"])
    validate_success(confirm_order(order["id"], cust["id"], v), 200)
    line_after = get_success_data(
        api.get_order_line(line["id"], make_customer_headers(cust["id"])))
    assert line_after["estimate_line_cents"] == 95000, "frozen at PREFLIGHT_OK rates"
    assert line_after["final_line_cents"] == 113000, "locked at 1200 base: 1080*100 + 5000"
    assert line_after["final_line_cents"] != line_after["estimate_line_cents"]


def test_estimate_recomputed_on_open_line_after_catalog_edit(api):
    """PRD §3.1: "doing so recomputes `estimate_line_cents` on every still-`OPEN` line that
    references the product". PRD §2.8: "it is recomputed from the catalog rates *in force
    right now* every time the line is created or edited, so it tracks the latest published
    prices."

    Design: Difficulty/dual_variant_calc/line_estimate_vs_locked_final_diverge_on_catalog_edit
    """
    shop = create_shop(name="Edit Shop")
    cust = create_customer(shop["id"], email="ae@x.com")
    prod = create_product(shop["id"], name="Color Copy", category="COPIES",
                          base_unit_price_cents=1000, requires_proof=False, requires_press=False)
    create_pricing_tier(prod["id"], 50, 1000)
    create_finishing_option(prod["id"], "LAMINATE", "PER_UNIT", 50)
    order = create_order(shop["id"], cust["id"])
    line = add_line(order["id"], prod["id"], 100, cust["id"], finishing_codes=["LAMINATE"])
    assert line["estimate_line_cents"] == 95000, "round(1000*0.9)=900*100 + 5000"
    # Line is still OPEN; a base-price edit recomputes the estimate.
    get_success_data(api.patch_product(prod["id"], {"base_unit_price_cents": 1200}, STAFF))
    line_after = get_success_data(
        api.get_order_line(line["id"], make_customer_headers(cust["id"])))
    assert line_after["estimate_line_cents"] == 113000, "round(1200*0.9)=1080*100 + 5000"
