"""Pricing engine: estimate vs invoice, rush tiers, volume discounts, deposit (queues A + B)."""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_customer_headers,
    make_staff_headers,
    fixtures,
    factories,
)

STAFF = make_staff_headers()


# ─── Dual-variant: ESTIMATE omits promo, INVOICE redeems it ───
def test_order_pricing_estimate_vs_invoice_diverge_on_promo(api):
    """PRD §3.4: "In the **estimate** pass the promo is deliberately *not* applied even
    when a `promo_code_id` is present: `estimate_subtotal_cents` is set to the order
    subtotal, `estimate_total_cents` is set to the pre-promo amount, and the promo's
    `uses_count` is left untouched."
    PRD §3.4: "The **invoice** pass runs at confirmation and uses identical subtotal and
    rush arithmetic, but the promo *is* applied and redeemed: `invoice_subtotal_cents` is
    set to the subtotal, `invoice_total_cents` is set to the promo-adjusted grand total,
    and the promo's `uses_count` increases by 1."

    Design: Difficulty/dual_variant_calc/order_pricing_estimate_vs_invoice_diverge_on_promo
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    promo = fixtures.create_promo(code="SAVE10", kind="PERCENT", percent_off=0.10,
                                  min_subtotal_cents=100000)
    component = fixtures.create_component(on_hand_qty=100)
    product = fixtures.create_product(
        component["id"], sku="ASA-1", name="Acrylic Star Award", product_type="ACRYLIC",
        base_price_cents=5000, engraving_price_per_char_cents=50, logo_setup_fee_cents=2000,
        standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer, service_level="EXPEDITED",
                                  due_date="2026-06-18T00:00:00Z", promo_code_id=promo["id"])
    line = fixtures.add_line(order, customer, product["id"], quantity=30,
                             engraving_text="CHAMPION 2026", include_logo=True)
    fixtures.add_approved_proof(line, customer, content_ref="CHAMPION 2026")
    priced = fixtures.price(order, customer)
    assert priced["estimate_total_cents"] == 203781
    assert priced["estimate_subtotal_cents"] == 163025
    cust = make_customer_headers(customer["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    assert confirmed["invoice_total_cents"] == 187479
    assert confirmed["invoice_subtotal_cents"] == 163025
    assert priced["estimate_total_cents"] - confirmed["invoice_total_cents"] == 16302


def test_invoice_total_below_estimate_when_valid_promo(api):
    """PRD §3.4: "Because the invoice applies a discount the estimate omits, the invoice
    total is at most the estimate total whenever a valid promo exists."

    Design: Difficulty/dual_variant_calc/order_pricing_estimate_vs_invoice_diverge_on_promo
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    promo = fixtures.create_promo(code="SAVE10C", kind="PERCENT", percent_off=0.10,
                                  min_subtotal_cents=100000)
    component = fixtures.create_component(on_hand_qty=100)
    product = fixtures.create_product(
        component["id"], sku="ASA-1C", product_type="ACRYLIC",
        base_price_cents=5000, engraving_price_per_char_cents=50, logo_setup_fee_cents=2000,
        standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer, service_level="EXPEDITED",
                                  due_date="2026-06-18T00:00:00Z", promo_code_id=promo["id"])
    line = fixtures.add_line(order, customer, product["id"], quantity=30,
                             engraving_text="CHAMPION 2026", include_logo=True)
    fixtures.add_approved_proof(line, customer, content_ref="CHAMPION 2026")
    priced = fixtures.price(order, customer)
    cust = make_customer_headers(customer["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    assert confirmed["invoice_total_cents"] <= priced["estimate_total_cents"]


# ─── Combinatorial: invoice as non-linear function of >=3 inputs ───
def test_order_pricing_three_input_nonlinear_subtotal_rush_promo(api):
    """PRD §3.4: "First, the order subtotal is the exact integer sum, over every line
    regardless of its status, of each line's `line_subtotal_cents` minus its
    `volume_discount_cents`. Second, the rush amount is that subtotal multiplied by the
    resolved tier's surcharge fraction, floored to whole cents; the pre-promo amount is the
    subtotal plus the rush amount."
    PRD §3.4: "a `PERCENT` promo's discount is the subtotal (not the pre-promo amount)
    multiplied by `percent_off`, floored to whole cents".

    Design: Difficulty/combinatorial_formula/order_pricing_three_input_nonlinear_subtotal_rush_promo
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    promo = fixtures.create_promo(code="SAVE10B", kind="PERCENT", percent_off=0.10,
                                  min_subtotal_cents=100000)
    component = fixtures.create_component(on_hand_qty=100)
    product = fixtures.create_product(
        component["id"], sku="ASA-3", product_type="ACRYLIC",
        base_price_cents=5000, engraving_price_per_char_cents=50, logo_setup_fee_cents=2000,
        standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer, service_level="EXPEDITED",
                                  due_date="2026-06-18T00:00:00Z", promo_code_id=promo["id"])
    line = fixtures.add_line(order, customer, product["id"], quantity=30,
                             engraving_text="CHAMPION 2026", include_logo=True)
    fixtures.add_approved_proof(line, customer, content_ref="CHAMPION 2026")
    priced = fixtures.price(order, customer)
    cust = make_customer_headers(customer["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    line_reread = validate_success(api.get_order_line(line["id"], cust))
    assert line_reread["line_subtotal_cents"] == 171500
    assert line_reread["volume_discount_cents"] == 8475
    assert confirmed["invoice_subtotal_cents"] == 163025
    assert confirmed["invoice_total_cents"] == 187479


def test_order_pricing_rounding_order_sum_then_floor(api):
    """PRD §3.4: "First, the order subtotal is the exact integer sum, over every line
    regardless of its status, of each line's `line_subtotal_cents` minus its
    `volume_discount_cents`. Second, the rush amount is that subtotal multiplied by the
    resolved tier's surcharge fraction, floored to whole cents".
    PRD §3.4: "The discount applies only to the engraved goods, excluding the one-time logo
    fee: take the line's `line_subtotal_cents`, subtract the `logo_setup_fee_cents` if
    `include_logo` is set, multiply that goods amount by the tier rate, floor it to whole
    cents, and store the result as `volume_discount_cents`."

    Design: Difficulty/combinatorial_formula/order_pricing_rounding_order_sum_then_floor
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=200)
    product = fixtures.create_product(
        component["id"], sku="ASA-4", product_type="CRYSTAL",
        base_price_cents=3001, engraving_price_per_char_cents=1, logo_setup_fee_cents=0,
        standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer, service_level="EXPEDITED",
                                  due_date="2026-06-18T00:00:00Z")
    line1 = fixtures.add_line(order, customer, product["id"], quantity=33, engraving_text="AB")
    line2 = fixtures.add_line(order, customer, product["id"], quantity=27, engraving_text="AB")
    fixtures.add_approved_proof(line1, customer, content_ref="AB")
    fixtures.add_approved_proof(line2, customer, content_ref="AB")
    priced = fixtures.price(order, customer)
    cust = make_customer_headers(customer["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    l1 = validate_success(api.get_order_line(line1["id"], cust))
    l2 = validate_success(api.get_order_line(line2["id"], cust))
    assert l1["line_subtotal_cents"] == 99099
    assert l1["volume_discount_cents"] == 4954
    assert l2["line_subtotal_cents"] == 81081
    assert l2["volume_discount_cents"] == 4054
    assert confirmed["invoice_subtotal_cents"] == 171172
    assert confirmed["invoice_total_cents"] == 213965


# ─── Boundary: volume tier inclusive at 25 ───
def test_volume_tier_boundary_qty25_inclusive(api):
    """PRD §3.4: "a quantity of 25 or more but fewer than 50 sets `TIER1` at 5 percent; and
    any quantity below 25 sets `NONE` at 0 percent. These breakpoints are inclusive at the
    lower edge — a quantity of exactly 25 is `TIER1`, while a quantity of 24 is `NONE`."

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_qty25_inclusive
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=100)
    product = fixtures.create_product(
        component["id"], sku="ASA-11", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer)
    line25 = fixtures.add_line(order, customer, product["id"], quantity=25)
    line24 = fixtures.add_line(order, customer, product["id"], quantity=24)
    priced = fixtures.price(order, customer)
    cust = make_customer_headers(customer["id"])
    l25 = validate_success(api.get_order_line(line25["id"], cust))
    l24 = validate_success(api.get_order_line(line24["id"], cust))
    assert l25["volume_tier"] == "TIER1"
    assert l25["volume_discount_cents"] == 5000
    assert l24["volume_tier"] == "NONE"
    assert l24["volume_discount_cents"] == 0


def test_price_order_with_zero_lines_rejected(api):
    """PRD §3.4: "Pricing requires the order to be in `DRAFT`, to have at least one line
    (`line_count` of 1 or more), and to have exactly one active rush policy in place."

    Design: Difficulty/boundary_precision_check/price_order_with_zero_lines_rejected
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer)
    resp = api.price_order(order["id"], STAFF)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
    cust = make_customer_headers(customer["id"])
    reread = validate_success(api.get_order(order["id"], cust))
    assert reread["line_count"] == 0
    assert reread["production_status"] == "DRAFT"


def test_volume_tier_boundary_qty24_excluded(api):
    """PRD §3.4: "These breakpoints are inclusive at the lower edge — a quantity of exactly
    25 is `TIER1`, while a quantity of 24 is `NONE`."
    PRD §3.4: "any quantity below 25 sets `NONE` at 0 percent."

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_qty25_inclusive
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=100)
    product = fixtures.create_product(
        component["id"], sku="ASA-11B", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer)
    line24 = fixtures.add_line(order, customer, product["id"], quantity=24)
    fixtures.price(order, customer)
    cust = make_customer_headers(customer["id"])
    l24 = validate_success(api.get_order_line(line24["id"], cust))
    assert l24["volume_tier"] == "NONE"
    assert l24["volume_discount_cents"] == 0


def test_price_zero_line_order_unchanged_and_repeatably_rejected(api):
    """PRD §3.4: "Pricing requires the order to be in `DRAFT`, to have at least one line
    (`line_count` of 1 or more), and to have exactly one active rush policy in place."

    Design: Difficulty/boundary_precision_check/price_order_with_zero_lines_rejected
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer)
    cust = make_customer_headers(customer["id"])
    # First price attempt fails; order remains DRAFT with line_count 0.
    validate_error(api.price_order(order["id"], STAFF), ApiErrorId.ERR_INVALID_STATE.value)
    mid = validate_success(api.get_order(order["id"], cust))
    assert mid["line_count"] == 0
    assert mid["estimate_total_cents"] == 0
    # A repeat attempt is still rejected — no estimate was ever produced.
    validate_error(api.price_order(order["id"], STAFF), ApiErrorId.ERR_INVALID_STATE.value)


def test_order_pricing_three_input_volume_discount_excludes_logo_fee(api):
    """PRD §3.4: "The discount applies only to the engraved goods, excluding the one-time
    logo fee: take the line's `line_subtotal_cents`, subtract the `logo_setup_fee_cents` if
    `include_logo` is set, multiply that goods amount by the tier rate, floor it to whole
    cents, and store the result as `volume_discount_cents`."

    Design: Difficulty/combinatorial_formula/order_pricing_three_input_nonlinear_subtotal_rush_promo
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    promo = fixtures.create_promo(code="SAVE10D", kind="PERCENT", percent_off=0.10,
                                  min_subtotal_cents=100000)
    component = fixtures.create_component(on_hand_qty=100)
    product = fixtures.create_product(
        component["id"], sku="ASA-3D", product_type="ACRYLIC",
        base_price_cents=5000, engraving_price_per_char_cents=50, logo_setup_fee_cents=2000,
        standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer, service_level="EXPEDITED",
                                  due_date="2026-06-18T00:00:00Z", promo_code_id=promo["id"])
    line = fixtures.add_line(order, customer, product["id"], quantity=30,
                             engraving_text="CHAMPION 2026", include_logo=True)
    fixtures.add_approved_proof(line, customer, content_ref="CHAMPION 2026")
    priced = fixtures.price(order, customer)
    cust = make_customer_headers(customer["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    line_reread = validate_success(api.get_order_line(line["id"], cust))
    # goods = 171500 - 2000(logo) = 169500; 5% floored = 8475 (logo excluded from discount).
    assert line_reread["volume_discount_cents"] == 8475
    assert confirmed["invoice_total_cents"] == 187479


def test_order_pricing_per_line_volume_discount_floors_independently(api):
    """PRD §3.4: "First, the order subtotal is the exact integer sum, over every line
    regardless of its status, of each line's `line_subtotal_cents` minus its
    `volume_discount_cents`."

    Design: Difficulty/combinatorial_formula/order_pricing_rounding_order_sum_then_floor
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=200)
    product = fixtures.create_product(
        component["id"], sku="ASA-4B", product_type="CRYSTAL",
        base_price_cents=3001, engraving_price_per_char_cents=1, logo_setup_fee_cents=0,
        standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer, service_level="EXPEDITED",
                                  due_date="2026-06-18T00:00:00Z")
    line1 = fixtures.add_line(order, customer, product["id"], quantity=33, engraving_text="AB")
    line2 = fixtures.add_line(order, customer, product["id"], quantity=27, engraving_text="AB")
    fixtures.add_approved_proof(line1, customer, content_ref="AB")
    fixtures.add_approved_proof(line2, customer, content_ref="AB")
    priced = fixtures.price(order, customer)
    cust = make_customer_headers(customer["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    l1 = validate_success(api.get_order_line(line1["id"], cust))
    l2 = validate_success(api.get_order_line(line2["id"], cust))
    # Each line's discount floors independently: 4954 and 4054 (not equal despite same tier).
    assert l1["volume_discount_cents"] == 4954
    assert l2["volume_discount_cents"] == 4054
    assert confirmed["invoice_subtotal_cents"] == 171172


# ─── Corner: rush tier boundaries and char-count line subtotal ───
def test_rush_tier_boundary_expedited_at_business_days_3(api):
    """PRD §3.4: "if the count is 3 or more but still fewer than the largest
    `standard_lead_days` among the products on the order's lines, the `rush_tier` is
    `EXPEDITED` and the surcharge is the policy's `expedited_surcharge_pct`".
    PRD §3.4: "The threshold at 3 business days is strict: a job due in exactly 3 business
    days is `EXPEDITED`, while a job due in 2 business days is `RUSH`."

    Design: Corner/calculations/rush_tier_boundary_expedited_at_business_days_3
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="EP-17", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer, service_level="EXPEDITED",
                                  due_date="2026-06-18T00:00:00Z")
    fixtures.add_line(order, customer, product["id"], quantity=1)
    priced = fixtures.price(order, customer)
    assert priced["rush_tier"] == "EXPEDITED"
    assert priced["production_status"] == "PRICED"
    assert priced["estimate_subtotal_cents"] == 4000
    assert priced["estimate_total_cents"] == 5000


def test_rush_tier_boundary_rush_at_business_days_2(api):
    """PRD §3.4: "if the business-day count is fewer than 3, the `rush_tier` is `RUSH` and
    the surcharge is the policy's `rush_surcharge_pct`".
    PRD §3.4: "The threshold at 3 business days is strict: a job due in exactly 3 business
    days is `EXPEDITED`, while a job due in 2 business days is `RUSH`."

    Design: Corner/calculations/rush_tier_boundary_rush_at_business_days_2
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="EP-18", base_price_cents=4000,
        engraving_price_per_char_cents=0, standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer, service_level="RUSH",
                                  due_date="2026-06-17T00:00:00Z")
    fixtures.add_line(order, customer, product["id"], quantity=1)
    priced = fixtures.price(order, customer)
    assert priced["rush_tier"] == "RUSH"
    assert priced["estimate_subtotal_cents"] == 4000
    assert priced["estimate_total_cents"] == 6000


def test_char_count_drives_line_subtotal_per_char(api):
    """PRD §3.4: "A line's character count, `char_count`, is the length of its
    `engraving_text` with whitespace counted (an empty string yields 0). The per-unit price
    is the product's `base_price_cents` plus `char_count` multiplied by the product's
    `engraving_price_per_char_cents`. The line's `line_subtotal_cents` is the `quantity`
    multiplied by that per-unit price, plus the product's `logo_setup_fee_cents` once if
    `include_logo` is set (the logo fee is charged a single time per line, never per unit)."

    Design: Corner/calculations/char_count_drives_line_subtotal_per_char
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=10)
    product = fixtures.create_product(
        component["id"], sku="EP-22", product_type="MEDAL", base_price_cents=1000,
        engraving_price_per_char_cents=50, standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer)
    line = fixtures.add_line(order, customer, product["id"], quantity=2, engraving_text="AB C")
    fixtures.price(order, customer)
    cust = make_customer_headers(customer["id"])
    reread = validate_success(api.get_order_line(line["id"], cust))
    assert reread["char_count"] == 4
    assert reread["line_subtotal_cents"] == 2400


def test_rush_deposit_is_full_invoice(api):
    """PRD §3.5: "The deposit is then computed: `deposit_due_cents` is the invoice total
    multiplied by one half, rounded up to the next whole cent — except that a `RUSH`-tier
    order requires full prepayment, so for a `RUSH` order the `deposit_due_cents` equals the
    full `invoice_total_cents`."

    Design: Corner/calculations/rush_deposit_is_full_invoice
    """
    fixtures.set_clock()
    fixtures.create_active_rush_policy()
    component = fixtures.create_component(on_hand_qty=20)
    product = fixtures.create_product(
        component["id"], sku="EP-19", product_type="CRYSTAL", base_price_cents=5000,
        engraving_price_per_char_cents=50, standard_lead_days=5,
    )
    customer = fixtures.register_customer()
    order = fixtures.create_order(customer, service_level="RUSH",
                                  due_date="2026-06-17T00:00:00Z")
    line = fixtures.add_line(order, customer, product["id"], quantity=10, engraving_text="GOLD")
    fixtures.add_approved_proof(line, customer, content_ref="GOLD")
    priced = fixtures.price(order, customer)
    cust = make_customer_headers(customer["id"])
    confirmed = validate_success(
        api.confirm_order(order["id"], {"expected_order_version": priced["version"]}, cust)
    )
    assert confirmed["invoice_total_cents"] == 78000
    assert confirmed["deposit_due_cents"] == 78000
