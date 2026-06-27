"""Pricing and cost calculations: ad pricing, pre-sale pricing, production cost,
the forward-looking estimate, and the dual-variant estimate-vs-committed split.

Difficulty (queue A) and corner (queue B) instances both appear here.
"""
import pytest
from test_helpers import (
    validate_success,
    create_yearbook_payload,
    create_page_payload,
    create_ad_contract_payload,
    create_presale_order_payload,
    create_print_run_payload,
    create_yearbook,
    create_yearbook_early_window,
    create_page,
    create_paid_order,
    current_yearbook_version,
    set_clock,
    TEST_USERS,
)

ADVISER = TEST_USERS["adviser_headers"]
SALESREP = TEST_USERS["salesrep_headers"]


# ─── Ad pricing ───────────────────────────────────────────────────────────────

def test_ad_pricing_full_no_discount(api):
    """PRD §3.5: "The `list_price_cents` is fixed by the size tier alone: a `FULL`
    page lists at 40000 cents, a `HALF` page at 24000 cents, and a `QUARTER` page at
    14000 cents." PRD §3.5: "when omitted it defaults to 0."

    Design: Corner/calculations/ad_pricing_full_no_discount_correct
    """
    yb = create_yearbook()
    page = create_page(yb["id"], 2, "ADS", template_code="T-AD")
    res = api.create_ad_contract(
        create_ad_contract_payload(yb["id"], page["id"], sponsor_name="Acme", size="FULL"),
        SALESREP,
    )
    ad = validate_success(res, 201)
    assert ad["list_price_cents"] == 40000
    assert ad["net_price_cents"] == 40000


def test_ad_pricing_rounding_order_pinned(api):
    """PRD §3.5: "take the integer `list_price_cents`, multiply it by one minus the
    `discount_pct`, and round that single product to a whole cent using round half up
    — in one rounding step. The list price is not rounded beforehand; there is exactly
    one rounding, applied to the discounted amount."

    Design: Difficulty/combinatorial_formula/combinatorial_ad_pricing_rounding_order_pinned
    """
    yb = create_yearbook()
    page = create_page(yb["id"], 4, "ADS", template_code="T-AD")
    res = api.create_ad_contract(
        create_ad_contract_payload(yb["id"], page["id"], sponsor_name="Edge Sponsor",
                                   size="QUARTER", discount_pct=0.00025),
        SALESREP,
    )
    ad = validate_success(res, 201)
    assert ad["list_price_cents"] == 14000
    # raw = 14000 * 0.99975 = 13996.5 ; round_half_up -> 13997 (single step).
    assert ad["net_price_cents"] == 13997


def test_ad_pricing_rounding_pinned_via_half_discount(api):
    """PRD §3.5: "take the integer `list_price_cents`, multiply it by one minus the
    `discount_pct`, and round that single product to a whole cent using round half up
    — in one rounding step. The list price is not rounded beforehand; there is exactly
    one rounding, applied to the discounted amount."

    Design: Difficulty/combinatorial_formula/combinatorial_ad_pricing_rounding_order_pinned
    """
    # HALF list = 24000; discount 0.10 -> raw 21600.0 -> net 21600 (no rounding ambiguity,
    # but confirms the pinned single-product formula on a second size tier).
    yb = create_yearbook()
    page = create_page(yb["id"], 4, "ADS", template_code="T-AD")
    res = api.create_ad_contract(
        create_ad_contract_payload(yb["id"], page["id"], sponsor_name="Joe Pizza",
                                   size="HALF", discount_pct=0.10),
        SALESREP,
    )
    ad = validate_success(res, 201)
    assert ad["list_price_cents"] == 24000
    assert ad["net_price_cents"] == 21600


# ─── Pre-sale pricing ─────────────────────────────────────────────────────────

def test_presale_bulk_branch_base_stamp_quantity(api):
    """PRD §3.5: "The per-copy base is 6500 cents in the `EARLY` tier and 8000 cents
    in the `STANDARD` tier. When `personalize` is true a name-stamp fee of 500 cents
    is added per copy". PRD §3.5: "A bulk discount of 10 percent applies to the gross
    only when `quantity` is at least 5: in that case the discount is 10 percent of the
    gross, rounded to a whole cent with round half up, and `total_price_cents` is the
    gross minus that discount".

    Design: Difficulty/combinatorial_formula/combinatorial_presale_base_stamp_bulk_branch
    """
    yb = create_yearbook_early_window()
    res = api.create_presale_order(
        create_presale_order_payload(yb["id"], buyer_name="Bulk Buyer", quantity=5,
                                     personalize=True, stamp_name="Team"),
        SALESREP,
    )
    order = validate_success(res, 201)
    # gross = (6500 + 500) * 5 = 35000 ; discount = 10% of 35000 = 3500 ; total = 31500.
    assert order["price_tier"] == "EARLY"
    assert order["total_price_cents"] == 31500


def test_presale_bulk_branch_not_triggered_below_threshold(api):
    """PRD §3.5: "The gross is that per-copy price multiplied by `quantity`." PRD §3.5:
    "for any quantity below 5 there is no discount and `total_price_cents` equals the
    gross."

    Design: Difficulty/combinatorial_formula/combinatorial_presale_base_stamp_bulk_branch
    """
    yb = create_yearbook_early_window()
    res = api.create_presale_order(
        create_presale_order_payload(yb["id"], buyer_name="Quad Buyer", quantity=4,
                                     personalize=True, stamp_name="Team"),
        SALESREP,
    )
    order = validate_success(res, 201)
    # gross = (6500 + 500) * 4 = 28000 ; qty 4 < 5 -> no discount -> 28000.
    assert order["price_tier"] == "EARLY"
    assert order["total_price_cents"] == 28000


def test_presale_standard_tier_with_stamp(api):
    """PRD §3.5: "If the order time is at or after `presale_close_iso`, the `price_tier`
    is `STANDARD`. The per-copy base is 6500 cents in the `EARLY` tier and 8000 cents
    in the `STANDARD` tier. When `personalize` is true a name-stamp fee of 500 cents is
    added per copy".

    Design: Corner/calculations/presale_standard_tier_with_stamp_correct
    """
    yb = create_yearbook()
    set_clock("2026-04-01T00:00:00Z")  # after presale_close 2026-03-01 -> STANDARD
    res = api.create_presale_order(
        create_presale_order_payload(yb["id"], buyer_name="Late Buyer", quantity=1,
                                     personalize=True, stamp_name="L. Buyer"),
        SALESREP,
    )
    order = validate_success(res, 201)
    # per_copy = 8000 + 500 = 8500 ; qty 1 ; no bulk -> 8500.
    assert order["price_tier"] == "STANDARD"
    assert order["total_price_cents"] == 8500


class TestBulkDiscountThreshold:
    """Count boundary on quantity for the 10% bulk discount (PRD §3.5)."""

    def test_quantity_four_no_bulk_discount(self, api):
        """PRD §3.5: "for any quantity below 5 there is no discount and
        `total_price_cents` equals the gross."

        Design: Difficulty/boundary_precision_check/boundary_bulk_discount_threshold_count
        """
        yb = create_yearbook_early_window()
        res = api.create_presale_order(
            create_presale_order_payload(yb["id"], buyer_name="Four", quantity=4),
            SALESREP,
        )
        order = validate_success(res, 201)
        # EARLY base 6500, no stamp, qty 4 -> gross 26000, no discount.
        assert order["total_price_cents"] == 26000

    def test_quantity_five_triggers_bulk_discount(self, api):
        """PRD §3.5: "A bulk discount of 10 percent applies to the gross only when
        `quantity` is at least 5: in that case the discount is 10 percent of the
        gross, rounded to a whole cent with round half up, and `total_price_cents` is
        the gross minus that discount".

        Design: Difficulty/boundary_precision_check/boundary_bulk_discount_threshold_count
        """
        yb = create_yearbook_early_window()
        res = api.create_presale_order(
            create_presale_order_payload(yb["id"], buyer_name="Five", quantity=5),
            SALESREP,
        )
        order = validate_success(res, 201)
        # EARLY base 6500, no stamp, qty 5 -> gross 32500 ; discount 3250 -> 29250.
        assert order["total_price_cents"] == 29250


# ─── Production cost ──────────────────────────────────────────────────────────

def test_production_cost_no_surcharge_at_base_allowance(api):
    """PRD §3.7: "The first 96 pages carry no surcharge." PRD §3.7: "If the page count
    does not exceed 96 there are no extra signatures and the surcharge is zero. The
    per-copy cost is `unit_cost_cents` plus this surcharge, and the production cost is
    that per-copy cost multiplied by the print run's `quantity`."

    Design: Corner/calculations/production_cost_no_surcharge_at_base_allowance
    """
    yb = create_yearbook(target_page_count=96, unit_cost_cents=1200)
    res = api.create_print_run(
        create_print_run_payload(yb["id"], 100, yb["version"]), ADVISER
    )
    run = validate_success(res, 201)
    # 96 pages -> no surcharge ; per_copy 1200 ; qty 100 -> 120000.
    assert run["cost_cents"] == 120000
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["production_cost_cents"] == 120000


# ─── Dual-variant estimate vs committed + computed cost-estimate read ─────────

def test_cost_estimate_projects_placed_and_paid_quantity(api):
    """PRD §3.7: "the projected quantity is the sum of `quantity` over the yearbook's
    pre-sale orders currently in `PLACED` or `PAID`. The capability returns this
    projected `estimated_quantity` alongside the resulting `estimated_cost_cents`."

    Design: Corner/endpoints/cost_estimate_computed_read_matches_projection
    """
    yb = create_yearbook(target_page_count=104, unit_cost_cents=1000)
    o1 = validate_success(
        api.create_presale_order(
            create_presale_order_payload(yb["id"], buyer_name="A", quantity=2), SALESREP
        ), 201,
    )
    o2 = validate_success(
        api.create_presale_order(
            create_presale_order_payload(yb["id"], buyer_name="B", quantity=3), SALESREP
        ), 201,
    )
    validate_success(api.pay_presale_order(o2["id"], SALESREP), 200)
    est = validate_success(api.get_cost_estimate(yb["id"], ADVISER), 200)
    # per_copy = 1000 + ceil((104-96)/4)*800 = 1000 + 2*800 = 2600 ; qty 2+3 = 5 -> 13000.
    assert est["estimated_quantity"] == 5
    assert est["estimated_cost_cents"] == 13000


def test_dual_variant_estimate_diverges_from_committed_cost(api):
    """PRD §3.7: "the projected quantity is the sum of `quantity` over the yearbook's
    pre-sale orders currently in `PLACED` or `PAID`." PRD §3.7: "This estimate is
    forward-looking and need not equal the authoritative committed figure, which is
    computed from the explicit committed `quantity` at commit time and frozen onto the
    run."

    Design: Difficulty/dual_variant_calc/dual_variant_production_cost_estimate_vs_committed
    """
    yb = create_yearbook(target_page_count=104, unit_cost_cents=1000)
    validate_success(
        api.create_presale_order(
            create_presale_order_payload(yb["id"], buyer_name="A", quantity=2), SALESREP
        ), 201,
    )
    o2 = validate_success(
        api.create_presale_order(
            create_presale_order_payload(yb["id"], buyer_name="B", quantity=3), SALESREP
        ), 201,
    )
    validate_success(api.pay_presale_order(o2["id"], SALESREP), 200)
    version_now = current_yearbook_version(yb["id"])
    pr = validate_success(
        api.create_print_run(
            create_print_run_payload(yb["id"], 10, version_now), ADVISER
        ), 201,
    )
    est = validate_success(api.get_cost_estimate(yb["id"], ADVISER), 200)
    committed = validate_success(api.get_print_run(pr["id"], ADVISER), 200)
    # estimate: per_copy 2600 * (2+3) = 13000 ; committed: 2600 * 10 = 26000.
    assert est["estimated_quantity"] == 5
    assert est["estimated_cost_cents"] == 13000
    assert committed["cost_cents"] == 26000
    assert est["estimated_cost_cents"] != committed["cost_cents"]


def test_dual_variant_ad_revenue_vs_presale_revenue(api):
    """PRD §3.5: "Signing adds the contract's `net_price_cents` to the yearbook's
    running `ad_revenue_cents`." PRD §3.5: "Paying a pre-sale order moves it from
    `PLACED` to `PAID` and adds its `total_price_cents` to the yearbook's
    `presale_revenue_cents`."

    Design: Difficulty/dual_variant_calc/dual_variant_ad_revenue_vs_presale_revenue
    """
    yb = create_yearbook_early_window(target_page_count=96, unit_cost_cents=1200)
    page = create_page(yb["id"], 2, "ADS", template_code="T-AD")
    ad = validate_success(
        api.create_ad_contract(
            create_ad_contract_payload(yb["id"], page["id"], sponsor_name="Joe Pizza",
                                       size="HALF", discount_pct=0.10),
            SALESREP,
        ), 201,
    )
    validate_success(api.sign_ad_contract(ad["id"], SALESREP), 200)
    order = validate_success(
        api.create_presale_order(
            create_presale_order_payload(yb["id"], buyer_name="Pat", quantity=1,
                                         personalize=True, stamp_name="Pat Q."),
            SALESREP,
        ), 201,
    )
    validate_success(api.pay_presale_order(order["id"], SALESREP), 200)
    assert ad["net_price_cents"] == 21600          # HALF 24000 * 0.90
    assert order["total_price_cents"] == 7000      # EARLY 6500 + stamp 500, qty 1
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["ad_revenue_cents"] == 21600
    assert yb_after["presale_revenue_cents"] == 7000


def test_dual_variant_committed_cost_frozen_on_run(api):
    """PRD §3.7: "The **production cost** the plant charges is the per-copy cost times
    the committed `quantity`." PRD §3.7: "This estimate is forward-looking and need not
    equal the authoritative committed figure, which is computed from the explicit
    committed `quantity` at commit time and frozen onto the run."

    Design: Difficulty/dual_variant_calc/dual_variant_production_cost_estimate_vs_committed
    """
    yb = create_yearbook(target_page_count=104, unit_cost_cents=1000)
    pr = validate_success(
        api.create_print_run(
            create_print_run_payload(yb["id"], 10, yb["version"]), ADVISER
        ), 201,
    )
    # committed variant uses the explicit committed quantity 10: per_copy 2600 * 10.
    assert pr["cost_cents"] == 26000
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["production_cost_cents"] == 26000


def test_dual_variant_revenue_fields_are_independent_domains(api):
    """PRD §3.5: "Signing adds the contract's `net_price_cents` to the yearbook's
    running `ad_revenue_cents`." PRD §3.5: "The yearbook's `presale_revenue_cents` is
    the running sum of `total_price_cents` over its orders currently in `PAID` or
    `FULFILLED`."

    Design: Difficulty/dual_variant_calc/dual_variant_ad_revenue_vs_presale_revenue
    """
    # Sign an ad but place NO paid order: ad_revenue moves, presale_revenue stays 0,
    # demonstrating the two derived fields track distinct entity domains.
    yb = create_yearbook()
    page = create_page(yb["id"], 2, "ADS", template_code="T-AD")
    ad = validate_success(
        api.create_ad_contract(
            create_ad_contract_payload(yb["id"], page["id"], sponsor_name="Joe Pizza",
                                       size="HALF", discount_pct=0.10),
            SALESREP,
        ), 201,
    )
    validate_success(api.sign_ad_contract(ad["id"], SALESREP), 200)
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["ad_revenue_cents"] == 21600
    assert yb_after["presale_revenue_cents"] == 0


def test_derived_ad_revenue_reconciles_after_sign(api):
    """PRD §3.5: "Signing adds the contract's `net_price_cents` to the yearbook's
    running `ad_revenue_cents`." PRD §3.5: "The yearbook's `ad_revenue_cents` is, in
    effect, the running sum of `net_price_cents` over its contracts currently in
    `SIGNED` or `PLACED`."

    Design: Corner/cross_cutting_complexity_layers/derived_ad_revenue_reconciles_after_sign
    """
    yb = create_yearbook()
    page = create_page(yb["id"], 2, "ADS", template_code="T-AD")
    ad = validate_success(
        api.create_ad_contract(
            create_ad_contract_payload(yb["id"], page["id"], sponsor_name="Joe Pizza",
                                       size="HALF", discount_pct=0.10),
            SALESREP,
        ), 201,
    )
    validate_success(api.sign_ad_contract(ad["id"], SALESREP), 200)
    yb_after = validate_success(api.get_yearbook(yb["id"], ADVISER), 200)
    assert yb_after["ad_revenue_cents"] == 21600
