"""Pricing and aggregation calculations: longarm dual-variant pricing, the combinatorial
longarm formula, special-order dual-variant pricing, and pinned kit rounding order."""
import pytest
from test_helpers import (
    validate_success, get_success_data,
    create_member, create_bolt,
    create_special_order, setup_in_progress_job,
    TEST_USERS,
)
from test_helpers import factories as f

CLERK = TEST_USERS["clerk_headers"]


# =========================================================================
# Difficulty/dual_variant_calc/longarm_estimate_vs_final_price
# =========================================================================
def test_longarm_estimate_price_at_intake(api):
    """PRD §3.4: "The estimate variant runs this formula over the quoted dimensions to
    produce estimated_price at intake." The base charge is area (60*80=4800) times the
    CUSTOM per-square-inch rate of $0.035 with no surcharge (area not above 7,500), no
    add-ons, no rush: 4800*0.035 = 168.00, above the $30 minimum.

    Design: Difficulty/dual_variant_calc/longarm_estimate_vs_final_price
    """
    member = create_member(api)
    resp = api.create_longarm_job(
        f.create_longarm_job_payload(member["id"], quoted_width_in=60, quoted_length_in=80,
                                     pattern_tier="CUSTOM"),
        CLERK)
    data = validate_success(resp, 201)
    assert data["estimated_price"] == 168.00, f"expected 168.00, got {data['estimated_price']}"
    assert data["status"] == "QUEUED"


def test_longarm_final_price_diverges_from_estimate(api):
    """PRD §3.4: "The final variant runs the identical formula over the measured dimensions
    to produce final_price at completion, and it diverges from the estimate whenever the
    measured dimensions differ from the quoted ones." Measured 60*82=4920 at CUSTOM $0.035
    gives 172.20, different from the 168.00 quoted at 60*80.

    Design: Difficulty/dual_variant_calc/longarm_estimate_vs_final_price
    """
    ctx = setup_in_progress_job(
        api, "2026-08-01T09:00:00Z", "2026-08-01T12:00:00Z",
        job_overrides={"quoted_width_in": 60, "quoted_length_in": 80, "pattern_tier": "CUSTOM"})
    resp = api.complete_longarm_job(
        ctx["job"]["id"], {"measured_width_in": 60, "measured_length_in": 82}, CLERK)
    data = validate_success(resp, 200)
    assert data["estimated_price"] == 168.00
    assert data["final_price"] == 172.20, f"expected 172.20, got {data['final_price']}"
    assert data["final_price"] != data["estimated_price"]
    assert data["status"] == "COMPLETED"


# =========================================================================
# Difficulty/combinatorial_formula/longarm_final_price_tiered_addons_rush
# =========================================================================
def test_longarm_price_surcharge_addons_and_rush_compose(api):
    """PRD §3.4: "If the area is strictly greater than 7,500 square inches, the base charge
    is then multiplied by a large-quilt surcharge factor of 1.1. ... a flat $25 batting fee
    is added when batting_addon is set, and a flat $12 specialty-thread fee is added when
    thread_addon is set. If rush is set, the resulting subtotal is then multiplied by 1.25."
    Area 100*80=8000 EDGE_TO_EDGE: 8000*0.02*1.1 = 176, +25+12 = 213, *1.25 = 266.25.

    Design: Difficulty/combinatorial_formula/longarm_final_price_tiered_addons_rush
    """
    member = create_member(api)
    resp = api.create_longarm_job(
        f.create_longarm_job_payload(member["id"], quoted_width_in=100, quoted_length_in=80,
                                     pattern_tier="EDGE_TO_EDGE",
                                     batting_addon=True, thread_addon=True, rush=True),
        CLERK)
    data = validate_success(resp, 201)
    assert data["estimated_price"] == 266.25, f"expected 266.25, got {data['estimated_price']}"
    assert data["status"] == "QUEUED"


def test_longarm_large_area_surcharge_without_addons(api):
    """PRD §3.4: "If the area is strictly greater than 7,500 square inches, the base charge is
    then multiplied by a large-quilt surcharge factor of 1.1." Isolating the surcharge: area
    100*80=8000 EDGE_TO_EDGE with no add-ons and no rush gives 8000*0.02*1.1 = 176.00, above
    the $30 minimum.

    Design: Difficulty/combinatorial_formula/longarm_final_price_tiered_addons_rush
    """
    member = create_member(api)
    resp = api.create_longarm_job(
        f.create_longarm_job_payload(member["id"], quoted_width_in=100, quoted_length_in=80,
                                     pattern_tier="EDGE_TO_EDGE"),
        CLERK)
    data = validate_success(resp, 201)
    assert data["estimated_price"] == 176.00, f"expected 176.00, got {data['estimated_price']}"


# =========================================================================
# Difficulty/dual_variant_calc/special_order_quote_vs_final_total
# =========================================================================
def test_special_order_quote_excludes_shipping_at_creation(api):
    """PRD §3.6: "The estimate variant, used at creation and on every re-quote, sets
    quoted_price to the estimated unit cost times the quantity times a special-order markup
    of 1.5, rounded half-up to two decimal places; it excludes shipping." est 10.00 * qty 3
    * 1.5 = 45.00.

    Design: Difficulty/dual_variant_calc/special_order_quote_vs_final_total
    """
    order, _ = create_special_order(api, quantity=3, est_unit_cost=10.00, description="Ruler set")
    assert order["quoted_price"] == 45.00, f"expected 45.00, got {order['quoted_price']}"
    assert order["status"] == "QUOTED"


def test_special_order_final_total_uses_actual_and_shipping(api):
    """PRD §3.6: "The final variant, used at fulfillment, sets final_total to the actual unit
    cost times the quantity times that same 1.5 markup, plus the shipping cost, rounded
    half-up to two decimal places ... and diverges from the quoted price whenever the actual
    unit cost differs from the estimate or any shipping is charged." actual 12.00 * qty 3 *
    1.5 + 5.00 = 59.00, different from the 45.00 quote.

    Design: Difficulty/dual_variant_calc/special_order_quote_vs_final_total
    """
    order, _ = create_special_order(api, quantity=3, est_unit_cost=10.00, description="Ruler set")
    resp = api.fulfill_special_order(order["id"], {"actual_unit_cost": 12.00, "shipping_cost": 5.00}, CLERK)
    data = validate_success(resp, 200)
    assert data["quoted_price"] == 45.00
    assert data["final_total"] == 59.00, f"expected 59.00, got {data['final_total']}"
    assert data["final_total"] != data["quoted_price"]
    assert data["status"] == "FULFILLED"


# =========================================================================
# Difficulty/combinatorial_formula/kit_price_round_per_component_then_sum
# =========================================================================
def test_kit_price_rounds_each_line_before_summing(api):
    """PRD §3.3: "for each component the system takes its yards_per_kit times the referenced
    bolt's current price_per_yard, rounds that line to two decimal places, multiplies the
    rounded line by the component's quantity, and adds the result into the running materials
    cost. This per-line rounding happens before the components are summed — the rounding
    order is pinned as round-then-sum, not sum-then-round. The kit_price is then the finished
    materials_cost multiplied by a kit markup of 1.4, rounded half-up to two decimal places."
    Two components of 1.5yd @ $3.33: round(4.995,2)=5.00 each, sum 10.00 (sum-then-round would
    give 9.99); kit_price = round(10.00*1.4,2) = 14.00.

    Design: Difficulty/combinatorial_formula/kit_price_round_per_component_then_sum
    """
    bolt = create_bolt(api, price_per_yard=3.33, original_yards=50)
    components = [
        {"bolt_id": bolt["id"], "yards_per_kit": 1.5, "quantity": 1},
        {"bolt_id": bolt["id"], "yards_per_kit": 1.5, "quantity": 1},
    ]
    resp = api.create_kit(f.create_kit_payload(components, name="Sunwash BOM", kit_type="BOM"), CLERK)
    data = validate_success(resp, 201)
    assert data["materials_cost"] == 10.00, f"expected 10.00, got {data['materials_cost']}"
    assert data["kit_price"] == 14.00, f"expected 14.00, got {data['kit_price']}"


def test_kit_price_rounded_line_multiplied_by_quantity(api):
    """PRD §3.3: "for each component the system takes its yards_per_kit times the referenced
    bolt's current price_per_yard, rounds that line to two decimal places, multiplies the
    rounded line by the component's quantity, and adds the result into the running materials
    cost." One component 1.5yd @ $3.33 with quantity 2: the line rounds to round(4.995,2)=5.00
    and is then multiplied by quantity 2 = 10.00; kit_price = round(10.00*1.4,2) = 14.00.

    Design: Difficulty/combinatorial_formula/kit_price_round_per_component_then_sum
    """
    bolt = create_bolt(api, price_per_yard=3.33, original_yards=50)
    components = [{"bolt_id": bolt["id"], "yards_per_kit": 1.5, "quantity": 2}]
    resp = api.create_kit(f.create_kit_payload(components, name="Sunwash Kit", kit_type="KIT"), CLERK)
    data = validate_success(resp, 201)
    assert data["materials_cost"] == 10.00, f"expected 10.00, got {data['materials_cost']}"
    assert data["kit_price"] == 14.00, f"expected 14.00, got {data['kit_price']}"
