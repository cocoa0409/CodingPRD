"""Difficulty Rule 2 — combinatorial_formula (modes a, b, c)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_line,
    api_client,
    confirm_order,
    create_dealer,
    create_model,
    create_order,
    create_shipment_payload,
    create_spec,
    get_success_data,
    set_clock,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
SHIP = TEST_USERS["shipping_coordinator_headers"]


# ---------------------------------------------------------------------------
# Instance: provisional_yardage_pattern_interaction (mode a — ≥3 inputs)
# ---------------------------------------------------------------------------

def _pattern_interaction_fixture():
    """Three lines on one order: pattern-match × STRAIGHT, no-match × STRAIGHT,
    pattern-match × DROP_HALF. Returns (order, line1, line2, line3)."""
    set_clock("2026-05-10T00:00:00Z")
    spec_s = create_spec(
        fabric_code="FAB-STRAIGHT", origin="PLANT", grade="A",
        nominal_width_inches=54.0, pattern_repeat_v_inches=9.0,
        match_method="STRAIGHT", price_per_yard_cents=3000,
    )
    spec_d = create_spec(
        fabric_code="FAB-DROP", origin="PLANT", grade="A",
        nominal_width_inches=54.0, pattern_repeat_v_inches=9.0,
        match_method="DROP_HALF", price_per_yard_cents=3000,
    )
    opt = [{"fabric_grade": "A", "finish_code": "ESPRESSO",
            "allowed": True, "surcharge_pct": 0.0, "lead_time_adder_days": 0}]
    model_pm = create_model(model_code="M-PM", category="SOFA", base_fabric_yards=3.0,
                            base_price_cents=50000, requires_pattern_match=True,
                            option_rules=opt)
    model_np = create_model(model_code="M-NP", category="SOFA", base_fabric_yards=3.0,
                            base_price_cents=40000, requires_pattern_match=False,
                            option_rules=opt)
    dealer = create_dealer()
    order = create_order("ORD-PM", dealer["id"])
    line1 = add_line(order["id"], model_pm["id"], spec_s["id"],
                     fabric_source="PLANT_STOCK", finish_code="ESPRESSO", quantity=4)
    line2 = add_line(order["id"], model_np["id"], spec_s["id"],
                     fabric_source="PLANT_STOCK", finish_code="ESPRESSO", quantity=4)
    line3 = add_line(order["id"], model_pm["id"], spec_d["id"],
                     fabric_source="PLANT_STOCK", finish_code="ESPRESSO", quantity=4)
    confirm_order(order["id"])
    return order, line1, line2, line3


def test_pattern_straight_vs_no_match_branch(api):
    """PRD §3.3: "When the model's `requires_pattern_match` is true and the
    spec declares a positive `pattern_repeat_v_inches`, the vertical repeat is
    converted to yards by dividing by 36, and a `match_method` of `DROP_HALF`
    inflates that repeat by half, multiplying it by 1.5; `STRAIGHT` and `NONE`
    leave it as-is. The per-unit fabric need — the model's `base_fabric_yards`
    multiplied by the width factor — is then rounded up to a whole number of
    repeats, and the base requirement is that repeat count times the repeat
    length in yards times the line's `quantity`. Where no pattern match
    applies, the base requirement is simply `base_fabric_yards` times the
    width factor times `quantity`."

    Design: Difficulty/combinatorial_formula/provisional_yardage_pattern_interaction
    """
    order, line1, line2, _ = _pattern_interaction_fixture()
    l1 = validate_success(api.get_order_line(line1["id"], SALES))
    l2 = validate_success(api.get_order_line(line2["id"], SALES))
    # L1: width factor 54/52; per-unit 3.0 × 54/52 = 3.1154; repeat 9.0/36 = 0.25;
    # ceil(3.1154/0.25) = 13; base 13 × 0.25 × 4 = 13.0; × 1.15 = 14.950
    assert l1["required_yards_provisional"] == pytest.approx(14.950, abs=0.001)
    # L2: no-match branch — 3.0 × 54/52 × 4 × 1.15 = 14.331
    assert l2["required_yards_provisional"] == pytest.approx(14.331, abs=0.001)
    # Same qty and spec width — pattern-match branch alone caused the difference
    assert l1["required_yards_provisional"] != l2["required_yards_provisional"]


def test_drop_half_inflates_repeat(api):
    """PRD §3.3: "a `match_method` of `DROP_HALF` inflates that repeat by half,
    multiplying it by 1.5; `STRAIGHT` and `NONE` leave it as-is."

    Design: Difficulty/combinatorial_formula/provisional_yardage_pattern_interaction
    """
    order, line1, _, line3 = _pattern_interaction_fixture()
    l1 = validate_success(api.get_order_line(line1["id"], SALES))
    l3 = validate_success(api.get_order_line(line3["id"], SALES))
    # L3: repeat 0.25 × 1.5 = 0.375; ceil(3.1154/0.375) = 9; base 9 × 0.375 × 4 = 13.5;
    # × 1.15 = 15.525
    assert l3["required_yards_provisional"] == pytest.approx(15.525, abs=0.001)
    assert l1["required_yards_provisional"] == pytest.approx(14.950, abs=0.001)
    # Order has no stock anywhere — all lines short, order on hold
    ord_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_now["status"] == "MATERIAL_HOLD"


# ---------------------------------------------------------------------------
# Instance: order_pricing_rounding_order (mode b — pinned rounding order)
# ---------------------------------------------------------------------------

def _price_fixture():
    """Model M-PRICE (base 10002, surcharge 0.13), one line qty 2 finish WALNUT."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(
        model_code="M-PRICE", category="CHAIR", base_fabric_yards=2.0,
        base_price_cents=10002, requires_pattern_match=False,
        flammability_standard="TB133",
        option_rules=[{
            "fabric_grade": "C", "finish_code": "WALNUT",
            "allowed": True, "surcharge_pct": 0.13, "lead_time_adder_days": 0,
        }],
    )
    spec = create_spec(fabric_code="FAB-C", origin="PLANT", grade="C",
                       nominal_width_inches=54.0, price_per_yard_cents=4000)
    dealer = create_dealer(credit_limit_cents=1000000)
    order = create_order("ORD-PRICE", dealer["id"], ship_to_state="VA")
    line = add_line(order["id"], model["id"], spec["id"],
                    fabric_source="PLANT_STOCK", finish_code="WALNUT", quantity=2)
    return order, line


def test_unit_price_rounded_per_unit_before_multiplying(api):
    """PRD §3.3: "each line's `unit_price_cents` is the model's
    `base_price_cents` multiplied by one plus the line's `matched_surcharge_pct`,
    rounded half up to a whole cent per unit — before any multiplication by
    quantity; the line's `line_total_cents` is then that unit price multiplied
    exactly by `quantity`."

    Design: Difficulty/combinatorial_formula/order_pricing_rounding_order
    """
    order, line = _price_fixture()
    confirm_order(order["id"])
    line_now = validate_success(api.get_order_line(line["id"], SALES))
    # round_half_up(10002 × 1.13) = 11302 per unit BEFORE quantity
    assert line_now["unit_price_cents"] == 11302
    # 11302 × 2 = 22604 (NOT 22605 from sum-then-round)
    assert line_now["line_total_cents"] == 22604


def test_order_subtotal_and_total_derived(api):
    """PRD §3.3: "The order's `subtotal_cents` is the sum of the line totals."
    PRD §3.3: "`total_cents` is derived only by subtracting `com_credit_cents`
    from `subtotal_cents` — it is never recomputed directly."

    Design: Difficulty/combinatorial_formula/order_pricing_rounding_order
    """
    order, line = _price_fixture()
    confirm_order(order["id"])
    ord_now = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_now["subtotal_cents"] == 22604
    assert ord_now["com_credit_cents"] == 0
    # total derived by subtraction only
    assert ord_now["total_cents"] == 22604


# ---------------------------------------------------------------------------
# Instance: freight_fuel_evaluation_order (mode c — pinned base→fuel order)
# ---------------------------------------------------------------------------

def _fuel_fixture():
    """DRAFT shipment 240 lb 60x30x36 in, declared 0, 3 pieces on an LTL order."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-LOUNGE", category="CHAIR",
                         base_fabric_yards=2.0, base_price_cents=50000,
                         option_rules=[{
                             "fabric_grade": "B", "finish_code": "ANY",
                             "allowed": True, "surcharge_pct": 0.0,
                             "lead_time_adder_days": 0,
                         }])
    spec = create_spec(fabric_code="FAB-B", origin="PLANT", grade="B",
                       nominal_width_inches=54.0, price_per_yard_cents=2000)
    dealer = create_dealer()
    order = create_order("ORD-FUEL", dealer["id"])
    add_line(order["id"], model["id"], spec["id"], fabric_source="PLANT_STOCK",
             finish_code="ESPRESSO", quantity=1)
    confirm_order(order["id"])
    ship = get_success_data(api_client.create_shipment(
        create_shipment_payload(
            order_id=order["id"], weight_lb=240.0, length_in=60.0,
            width_in=30.0, height_in=36.0, declared_value_cents=0, piece_count=3,
        ), SHIP))
    return ship


def test_fuel_computed_on_base_only(api):
    """PRD §3.9: "the fuel surcharge is eighteen percent of that base, again
    rounded half up to a whole cent, assessed on the base only; and the
    `freight_charge_cents` is the base plus the fuel surcharge."

    Design: Difficulty/combinatorial_formula/freight_fuel_evaluation_order
    """
    ship = _fuel_fixture()
    rated = validate_success(api.rate_shipment(ship["id"], SHIP))
    # density 6.4 → CLASS_125 → base 240 × 130 = 31200
    # fuel = round_half_up(31200 × 0.18) = 5616 (on base only, NOT on total)
    assert rated["freight_charge_cents"] == 36816


def test_freight_class_matches_density(api):
    """PRD §3.9: "The packaged volume in cubic feet is `length_in` times
    `width_in` times `height_in` divided by 1728, and the
    `density_lb_per_cuft` is `weight_lb` divided by that volume, carried at
    four decimal places with half-up rounding. The base `freight_class` is
    chosen by density lower bound: ... at least 6, `CLASS_125`..."

    Design: Difficulty/combinatorial_formula/freight_fuel_evaluation_order
    """
    ship = _fuel_fixture()
    rated = validate_success(api.rate_shipment(ship["id"], SHIP))
    # volume 60 × 30 × 36 / 1728 = 37.5 cu ft; density = 240 / 37.5 = 6.4
    assert rated["density_lb_per_cuft"] == pytest.approx(6.4, abs=0.0001)
    assert rated["freight_class"] == "CLASS_125"
