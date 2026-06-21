"""Dual-variant pricing and loyalty calculations.

Queue A (Difficulty): dual_variant_calc, combinatorial_formula.
Queue B (Corner): calculations section.
"""
import pytest
from test_helpers import (
    api_client, validate_success, get_success_data,
    TEST_USERS,
    create_markdown_schedule_payload,
)
from test_helpers import (
    create_boutique, create_customer, create_style, create_variant,
    create_scheduled_markdown, create_active_markdown,
    open_order_with_line, create_authorized_order, create_captured_order,
    grant_store_credit, setup_basic_retail_scenario,
    push_customer_to_captured_spend,
)

MERCH = TEST_USERS["merchandiser_headers"]
ASSOCIATE = TEST_USERS["store_associate_headers"]
MANAGER = TEST_USERS["store_manager_headers"]


# ─── Queue A: dual_variant_calc ───────────────────────────────────────────

def test_markdown_projected_price_locked_at_scheduling(api):
    """PRD §3.5: "Scheduling a markdown (DRAFT -> SCHEDULED) computes its
    projected_price_cents, a provisional forward-looking preview, while
    un-scheduling it (SCHEDULED -> DRAFT) clears projected_price_cents back to null."
    PRD §3.5: "The provisional variant — projected_price_cents, computed at
    scheduling time — reads the style's current_price_cents as it stands at
    scheduling and does not write the style or re-read the clearance basis later."

    A CLEARANCE 40% scheduled while list price (10000) is live previews 6000 and
    does NOT write the style's current_price_cents.

    Design: Difficulty/dual_variant_calc/markdown_provisional_vs_final_price_diverges_on_style
    """
    bq = create_boutique(tax_rate_bps=875)
    style = create_style(bq["id"], list_price_cents=10000, category="OUTERWEAR", season="WINTER")
    create_variant(style["id"], size="M", color="Camel", on_hand=5)

    scheduled = create_scheduled_markdown(style["id"], style["version"],
                                          phase="CLEARANCE", markdown_pct=40, effective_date=0)
    assert scheduled["projected_price_cents"] == 6000
    assert scheduled["applied_price_cents"] is None, "applied not computed until activation"

    style_after = get_success_data(api.get_style(style["id"], MERCH))
    assert style_after["current_price_cents"] == 10000, "scheduling must not write the style price"


def test_tier_projection_includes_authorized_pending(api):
    """PRD §3.2: "the projected tier is computed against a projected_basis_cents
    equal to captured_spend_cents plus the sum of total_cents over every sales
    order of that customer currently in AUTHORIZED payment status (authorized but
    not yet captured)."
    PRD §3.2: "a customer ... reaches SILVER once it is at least 500 dollars
    (50,000 cents) but below the gold threshold".

    captured_spend 40000 -> actual STANDARD; one AUTHORIZED order (total 15438)
    lifts projected basis to 55438 >= 50000 -> projected SILVER.

    Design: Difficulty/dual_variant_calc/loyalty_tier_projected_vs_actual_diverges_on_customer
    """
    bq = create_boutique(tax_rate_bps=0)
    cu = create_customer(bq["id"])

    # Capture exactly 40000 net cash (tax 0, STANDARD so no discount).
    push_customer_to_captured_spend(bq["id"], cu["id"], 40000)

    # A second order authorized for 15438 but not captured.
    style_b = create_style(bq["id"], list_price_cents=15438, category="ACCESSORIES", season="SUMMER")
    variant_b = create_variant(style_b["id"], size="M", color="Black", on_hand=10)
    create_authorized_order(cu["id"], variant_b["id"], qty=1)

    proj = validate_success(api.get_tier_projection(cu["id"], ASSOCIATE), 200)
    assert proj["actual_tier"] == "STANDARD"
    assert proj["projected_tier"] == "SILVER"
    assert proj["projected_basis_cents"] == 55438

    customer_after = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_after["captured_spend_cents"] == 40000


def test_actual_tier_excludes_authorized_pending(api):
    """PRD §3.2: "This actual tier is the value stored on loyalty_tier, and it is
    recomputed by the capture and refund side effects described later."
    PRD §3.2: "the actual tier is the stored tier just described, and the projected
    tier is computed against a projected_basis_cents equal to captured_spend_cents
    plus the sum of total_cents over every sales order of that customer currently in
    AUTHORIZED payment status".

    With captured_spend 40000 the stored loyalty_tier stays STANDARD even though an
    AUTHORIZED order pushes the projection to SILVER — actual excludes pending.

    Design: Difficulty/dual_variant_calc/loyalty_tier_projected_vs_actual_diverges_on_customer
    """
    bq = create_boutique(tax_rate_bps=0)
    cu = create_customer(bq["id"])
    push_customer_to_captured_spend(bq["id"], cu["id"], 40000)

    style_b = create_style(bq["id"], list_price_cents=15438, category="ACCESSORIES", season="SUMMER")
    variant_b = create_variant(style_b["id"], size="M", color="Black", on_hand=10)
    create_authorized_order(cu["id"], variant_b["id"], qty=1)

    customer_after = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_after["loyalty_tier"] == "STANDARD", "stored tier ignores AUTHORIZED pending"
    assert customer_after["captured_spend_cents"] == 40000


# ─── Queue A: combinatorial_formula ───────────────────────────────────────

def test_order_pricing_rounds_tax_once_over_summed_subtotal(api):
    """PRD §3.6: "subtotal_cents is the sum of those per-line integers."
    PRD §3.6: "Tax is then computed once over the discounted subtotal: tax_cents is
    the quantity (subtotal_cents minus loyalty_discount_cents) multiplied by the
    boutique's tax_rate_bps divided by 10,000, rounded half up to whole cents."

    Lines 7000x1 and 3000x2 sum to subtotal 13000; tax = 13000*875/10000 = 1137.5
    -> 1138 (rounded once over the summed base, not per line).

    Design: Difficulty/combinatorial_formula/order_pricing_round_per_line_then_sum_mode_b
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    style7 = create_style(bq["id"], list_price_cents=7000, category="TOPS", season="SPRING")
    sv7 = create_variant(style7["id"], size="S", color="Blue", on_hand=5)
    style3 = create_style(bq["id"], list_price_cents=3000, category="ACCESSORIES", season="SPRING")
    sv3 = create_variant(style3["id"], size="M", color="Red", on_hand=5)

    order = get_success_data(api.create_sales_order({"customer_id": cu["id"]}, ASSOCIATE))
    get_success_data(api.create_order_line(order["id"], {"sku_variant_id": sv7["id"], "qty": 1}, ASSOCIATE))
    get_success_data(api.create_order_line(order["id"], {"sku_variant_id": sv3["id"], "qty": 2}, ASSOCIATE))

    authorized = validate_success(api.authorize_order(order["id"], ASSOCIATE), 200)
    assert authorized["subtotal_cents"] == 13000
    assert authorized["tax_cents"] == 1138
    assert authorized["loyalty_discount_cents"] == 0, "STANDARD tier earns no discount"


def test_loyalty_accrual_evaluation_order_uses_net_cash_after_credit(api):
    """PRD §3.6: "the store credit actually applied, store_credit_applied_cents, is
    the smaller of the requested redeem_store_credit and the order's (subtotal_cents
    minus loyalty_discount_cents plus tax_cents), and the order's total_cents is
    finalized as subtotal_cents minus loyalty_discount_cents plus tax_cents minus
    store_credit_applied_cents."
    PRD §3.6: "The order's points_earned is the net-cash total divided by 100 and
    taken as the floor (the whole number of points, discarding any remainder), since
    one point is earned per 100 cents of net cash."

    Subtotal 13000 + tax 1138 = 14138 before credit; redeem 5000 -> total 9138;
    points = floor(9138/100) = 91 (NOT floor(14138/100)=141).

    Design: Difficulty/combinatorial_formula/loyalty_accrual_evaluation_order_breaks_cycle_mode_c
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    grant_store_credit(cu["id"], 5000)
    style7 = create_style(bq["id"], list_price_cents=7000, category="TOPS", season="SPRING")
    sv7 = create_variant(style7["id"], size="S", color="Blue", on_hand=5)
    style3 = create_style(bq["id"], list_price_cents=3000, category="ACCESSORIES", season="SPRING")
    sv3 = create_variant(style3["id"], size="M", color="Red", on_hand=5)

    order = get_success_data(api.create_sales_order({"customer_id": cu["id"]}, ASSOCIATE))
    get_success_data(api.create_order_line(order["id"], {"sku_variant_id": sv7["id"], "qty": 1}, ASSOCIATE))
    get_success_data(api.create_order_line(order["id"], {"sku_variant_id": sv3["id"], "qty": 2}, ASSOCIATE))
    get_success_data(api.authorize_order(order["id"], ASSOCIATE))

    captured = validate_success(
        api.capture_order(order["id"], ASSOCIATE, payload={"redeem_store_credit": 5000}), 200)
    assert captured["store_credit_applied_cents"] == 5000
    assert captured["total_cents"] == 9138
    assert captured["points_earned"] == 91

    customer_after = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_after["store_credit_cents"] == 0


def test_order_subtotal_sums_exact_line_products(api):
    """PRD §3.6: "on creation the line snapshots the style's current_price_cents into its
    own unit_price_cents and computes line_total_cents as unit_price_cents times qty."
    PRD §3.6: "each line's line_total_cents is the exact integer product of its
    unit_price_cents and qty, and subtotal_cents is the sum of those per-line integers."

    Line products 7000x1=7000 and 3000x2=6000 are exact integers; the order's
    subtotal_cents is their sum 13000 — the per-line-then-sum ordering at the line step.

    Design: Difficulty/combinatorial_formula/order_pricing_round_per_line_then_sum_mode_b
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    style7 = create_style(bq["id"], list_price_cents=7000, category="TOPS", season="SPRING")
    sv7 = create_variant(style7["id"], size="S", color="Blue", on_hand=5)
    style3 = create_style(bq["id"], list_price_cents=3000, category="ACCESSORIES", season="SPRING")
    sv3 = create_variant(style3["id"], size="M", color="Red", on_hand=5)

    order = get_success_data(api.create_sales_order({"customer_id": cu["id"]}, ASSOCIATE))
    line1 = get_success_data(api.create_order_line(order["id"], {"sku_variant_id": sv7["id"], "qty": 1}, ASSOCIATE))
    line2 = get_success_data(api.create_order_line(order["id"], {"sku_variant_id": sv3["id"], "qty": 2}, ASSOCIATE))
    assert line1["line_total_cents"] == 7000
    assert line2["line_total_cents"] == 6000

    authorized = validate_success(api.authorize_order(order["id"], ASSOCIATE), 200)
    assert authorized["subtotal_cents"] == 13000


def test_loyalty_points_basis_is_net_cash_not_pre_credit_total(api):
    """PRD §3.6: "The accrual basis is the net cash actually paid, namely the finalized
    total_cents; store-credit-funded cents earn nothing."
    PRD §3.6: "Capture increments the customer's loyalty_points by points_earned".

    With 5000 store credit applied the net cash total is 9138, so the customer's
    loyalty_points lands at 91 — store-credit-funded cents minted nothing.

    Design: Difficulty/combinatorial_formula/loyalty_accrual_evaluation_order_breaks_cycle_mode_c
    """
    bq = create_boutique(tax_rate_bps=875)
    cu = create_customer(bq["id"])
    grant_store_credit(cu["id"], 5000)
    style7 = create_style(bq["id"], list_price_cents=7000, category="TOPS", season="SPRING")
    sv7 = create_variant(style7["id"], size="S", color="Blue", on_hand=5)
    style3 = create_style(bq["id"], list_price_cents=3000, category="ACCESSORIES", season="SPRING")
    sv3 = create_variant(style3["id"], size="M", color="Red", on_hand=5)

    order = get_success_data(api.create_sales_order({"customer_id": cu["id"]}, ASSOCIATE))
    get_success_data(api.create_order_line(order["id"], {"sku_variant_id": sv7["id"], "qty": 1}, ASSOCIATE))
    get_success_data(api.create_order_line(order["id"], {"sku_variant_id": sv3["id"], "qty": 2}, ASSOCIATE))
    get_success_data(api.authorize_order(order["id"], ASSOCIATE))
    get_success_data(api.capture_order(order["id"], ASSOCIATE, payload={"redeem_store_credit": 5000}))

    customer_after = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert customer_after["loyalty_points"] == 91


# ─── Queue B: calculations ────────────────────────────────────────────────

def test_seasonal_markdown_writes_rounded_price_on_activate(api):
    """PRD §3.5: "For a SEASONAL schedule the price is the style's list_price_cents
    multiplied by the quantity (100 minus markdown_pct) divided by 100, rounded half
    up to whole cents at that single multiplication step."
    PRD §3.5: "Activation computes the schedule's applied_price_cents, writes it onto
    the style's current_price_cents".

    Activating a SEASONAL 25%-off schedule on a list_price 8000 style writes
    current_price_cents = round_half_up(8000*0.75) = 6000.

    Design: Corner/calculations/seasonal_markdown_correct_result_on_activate
    """
    bq = create_boutique(tax_rate_bps=875)
    style = create_style(bq["id"], list_price_cents=8000, category="DRESSES", season="SUMMER")

    active = create_active_markdown(style["id"], style["version"],
                                    phase="SEASONAL", markdown_pct=25, effective_date=0)
    assert active["applied_price_cents"] == 6000

    style_after = get_success_data(api.get_style(style["id"], MERCH))
    assert style_after["current_price_cents"] == 6000


def test_silver_tier_discount_applied_at_authorize(api):
    """PRD §3.6: "SILVER earns 5% (500 basis points)".
    PRD §3.6: "loyalty_discount_cents is subtotal_cents multiplied by the tier's
    basis-point rate divided by 10,000, rounded half up to whole cents."

    A SILVER customer (captured_spend 50000) on a 10000 subtotal order at tax 0
    yields loyalty_discount_cents = 500 and total_cents = 9500.

    Design: Corner/calculations/silver_loyalty_discount_applied_at_authorize
    """
    bq = create_boutique(tax_rate_bps=0)
    cu = create_customer(bq["id"])
    # Drive to SILVER with one captured 50000 order.
    push_customer_to_captured_spend(bq["id"], cu["id"], 50000)
    cust = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert cust["loyalty_tier"] == "SILVER"

    style_m = create_style(bq["id"], list_price_cents=10000, category="TOPS", season="SPRING")
    sv_m = create_variant(style_m["id"], size="M", color="White", on_hand=5)
    authorized, _ = create_authorized_order(cu["id"], sv_m["id"], qty=1)
    assert authorized["loyalty_discount_cents"] == 500
    assert authorized["total_cents"] == 9500


def test_silver_tier_inclusive_boundary_at_50000(api):
    """PRD §3.2: "a customer reaches `GOLD` once their captured spend is at least 1,500
    dollars (150,000 cents), and reaches `SILVER` once it is at least 500 dollars
    (50,000 cents) but below the gold threshold; otherwise they remain `STANDARD`."
    PRD §3.2: "one at exactly the silver threshold is `SILVER`."

    captured_spend_cents exactly 50000 yields loyalty_tier SILVER (inclusive >=).

    Design: Corner/calculations/tier_threshold_exact_boundary_silver
    """
    bq = create_boutique(tax_rate_bps=0)
    cu = create_customer(bq["id"])
    push_customer_to_captured_spend(bq["id"], cu["id"], 50000)

    cust = get_success_data(api.get_customer(cu["id"], ASSOCIATE))
    assert cust["captured_spend_cents"] == 50000
    assert cust["loyalty_tier"] == "SILVER"
