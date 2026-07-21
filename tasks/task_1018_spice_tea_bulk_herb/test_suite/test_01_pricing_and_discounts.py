"""Provisional vs final line pricing, per-line rounding order, and volume discount tiers."""
from test_helpers import (
    validate_success,
    setup_confirmed_order, new_product, new_account, new_order, new_line, do_price,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
PROD = TEST_USERS["production_headers"]
SALES = TEST_USERS["sales_headers"]


# ---- dual_variant_calc / order_line_provisional_vs_final ----

def test_provisional_line_priced_from_requested_grams(api):
    """PRD §3.6: "On each line, `provisional_line_cents` is the line's `requested_grams`
    multiplied by its product's `unit_price_cents_per_gram`, rounded half-up to whole cents."

    Design: Difficulty/dual_variant_calc/order_line_provisional_vs_final
    """
    ctx = setup_confirmed_order(api, unit_price_cents_per_gram=2.5, requested_grams=100,
                                lot_grams=500, allergen_ack=False)
    measurements = [{"line_id": ctx["line"]["id"], "gross_grams": 121, "tare_grams": 10}]
    validate_success(api.pack_order(ctx["order"]["id"], {"line_measurements": measurements}, PROD))
    line = validate_success(api.get_order_line(ctx["line"]["id"], ADMIN))
    assert line["provisional_line_cents"] == 250, \
        f"provisional should be 100*2.5=250, got {line['provisional_line_cents']}"


def test_final_line_priced_from_measured_net_grams(api):
    """PRD §3.7: "On each line, `final_line_cents` is its `net_grams` multiplied by the
    product's `unit_price_cents_per_gram`, rounded half-up to whole cents; this diverges
    from the provisional amount whenever measured net differs from requested grams."

    Design: Difficulty/dual_variant_calc/order_line_provisional_vs_final
    """
    ctx = setup_confirmed_order(api, unit_price_cents_per_gram=2.5, requested_grams=100,
                                lot_grams=500, allergen_ack=False)
    measurements = [{"line_id": ctx["line"]["id"], "gross_grams": 121, "tare_grams": 10}]
    validate_success(api.pack_order(ctx["order"]["id"], {"line_measurements": measurements}, PROD))
    line = validate_success(api.get_order_line(ctx["line"]["id"], ADMIN))
    # net = 121 - 10 = 111; 111 * 2.5 = 277.5 -> round-half-up -> 278.
    assert line["final_line_cents"] == 278, \
        f"final should be 111*2.5=277.5->278, got {line['final_line_cents']}"
    assert line["final_line_cents"] != line["provisional_line_cents"], \
        "final must diverge from provisional when measured net != requested"


# ---- combinatorial_formula / order_subtotal_rounding_order ----

def _two_line_order(api):
    ceylon = new_product(api, name="Ceylon Cinnamon", category="SPICE",
                         unit_price_cents_per_gram=3.5, tare_default_grams=10)
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api, credit_limit_cents=100000)
    order = new_order(api, account["id"])
    line_c = new_line(api, order["id"], ceylon["id"], 111)
    line_ch = new_line(api, order["id"], cham["id"], 45)
    return order, line_c, line_ch


def test_per_line_amounts_rounded_before_summing(api):
    """PRD §2.6: "Rounding is always applied at the per-line level before any summation
    — never after — a pinned ordering detailed in §3.7."

    Design: Difficulty/combinatorial_formula/order_subtotal_rounding_order
    """
    order, line_c, line_ch = _two_line_order(api)
    validate_success(api.price_order(order["id"], SALES))
    lc = validate_success(api.get_order_line(line_c["id"], ADMIN))
    lch = validate_success(api.get_order_line(line_ch["id"], ADMIN))
    # 111*3.5 = 388.5 -> 389 ; 45*2.5 = 112.5 -> 113 (each rounded first).
    assert lc["provisional_line_cents"] == 389, lc["provisional_line_cents"]
    assert lch["provisional_line_cents"] == 113, lch["provisional_line_cents"]


def test_order_subtotal_sums_rounded_lines_not_raw_products(api):
    """PRD §3.6: "The order's provisional subtotal is the sum of the already-rounded
    per-line provisional amounts — each line rounded to whole cents first, then summed."

    Design: Difficulty/combinatorial_formula/order_subtotal_rounding_order
    """
    order, _line_c, _line_ch = _two_line_order(api)
    priced = validate_success(api.price_order(order["id"], SALES))
    assert priced["total_net_grams"] == 156, priced["total_net_grams"]
    # round-each-then-sum = 389 + 113 = 502 (below 500g -> no discount... 156g so 0%).
    assert priced["provisional_total_cents"] == 502, priced["provisional_total_cents"]


# ---- combinatorial_formula / order_discount_tier_selection ----

def test_discount_tier_selected_from_total_net_grams(api):
    """PRD §3.6: "A volume discount then applies based on `total_net_grams`: below 500
    grams the rate is zero; from 500 grams up to but not including 2000 grams the rate is
    five percent; at 2000 grams and above the rate is twelve percent."

    Design: Difficulty/combinatorial_formula/order_discount_tier_selection
    """
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api, credit_limit_cents=100000)
    order = new_order(api, account["id"])
    new_line(api, order["id"], cham["id"], 600)
    priced = validate_success(api.price_order(order["id"], SALES))
    assert priced["total_net_grams"] == 600, priced["total_net_grams"]


def test_order_total_is_subtotal_minus_discount(api):
    """PRD §3.6: "The discount is the subtotal multiplied by that rate, rounded half-up
    to whole cents, and the `provisional_total_cents` stamped on the order is the subtotal
    minus that discount."

    Design: Difficulty/combinatorial_formula/order_discount_tier_selection
    """
    cham = new_product(api, name="Chamomile", category="HERB", unit_price_cents_per_gram=2.5)
    account = new_account(api, credit_limit_cents=100000)
    order = new_order(api, account["id"])
    new_line(api, order["id"], cham["id"], 600)
    priced = validate_success(api.price_order(order["id"], SALES))
    # subtotal 600*2.5=1500 ; 600g in [500,2000) -> 5% ; discount round(75)=75 ; total 1425.
    assert priced["provisional_total_cents"] == 1425, priced["provisional_total_cents"]
