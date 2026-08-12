"""Difficulty Rule 1 — dual_variant_calc (different entity domains)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_line,
    api_client,
    confirm_order,
    create_available_lot,
    create_dealer,
    create_model,
    create_order,
    create_shipment_payload,
    create_spec,
    get_success_data,
    set_clock,
    setup_basic_context,
    setup_order_with_line,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
SHIP = TEST_USERS["shipping_coordinator_headers"]


# ---------------------------------------------------------------------------
# Instance: fabric_requirement_provisional_vs_final
# ---------------------------------------------------------------------------

def _camden_fixture():
    """Pattern-match line qty 4 on a width-50 lot. Returns (order, line, lot, plan)."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(
        model_code="CAMDEN-SOFA",
        category="SOFA",
        base_fabric_yards=3.0,
        base_price_cents=100000,
        requires_pattern_match=True,
        option_rules=[{
            "fabric_grade": "A", "finish_code": "ESPRESSO",
            "allowed": True, "surcharge_pct": 0.0, "lead_time_adder_days": 0,
        }],
    )
    spec = create_spec(
        fabric_code="FAB-PEBBLE-A",
        origin="PLANT", grade="A", nominal_width_inches=54.0,
        pattern_repeat_v_inches=9.0, pattern_repeat_h_inches=0.0,
        match_method="STRAIGHT", price_per_yard_cents=3000,
    )
    dealer = create_dealer()
    lot = create_available_lot(spec["id"], yards=25.0, measured_width_inches=50.0)
    order = create_order("ORD-1001", dealer["id"])
    line = add_line(order["id"], model["id"], spec["id"],
                    fabric_source="PLANT_STOCK", finish_code="ESPRESSO", quantity=4)
    confirm_order(order["id"])
    return order, line, lot


def test_provisional_variant_uses_spec_sheet_width_and_pattern_ceil(api):
    """PRD §3.3: "The per-unit fabric need — the model's `base_fabric_yards`
    multiplied by the width factor — is then rounded up to a whole number of
    repeats, and the base requirement is that repeat count times the repeat
    length in yards times the line's `quantity`."
    PRD §3.3: "A tiered cutting-waste allowance then applies: fifteen percent
    for lines of five units or fewer..."

    Design: Difficulty/dual_variant_calc/fabric_requirement_provisional_vs_final
    """
    order, line, lot = _camden_fixture()
    line_now = validate_success(api.get_order_line(line["id"], SALES))
    # 3.0 × 54/52 = 3.1154 per unit; repeat 9.0/36 = 0.25; ceil(3.1154/0.25) = 13
    # base = 13 × 0.25 × 4 = 13.0; × 1.15 waste = 14.950
    assert line_now["required_yards_provisional"] == pytest.approx(14.950, abs=0.001)
    # Line was reserved fully by FEFO from the 25.0-yard lot
    assert line_now["allocated_yards"] == pytest.approx(14.950, abs=0.001)
    assert line_now["status"] == "ALLOCATED"


def test_final_variant_uses_marker_and_measured_width(api):
    """PRD §3.5: "the system computes the final requirement: it takes the
    narrowest `measured_width_inches` among the lots holding ACTIVE allocations
    for the line, then sets `required_yards_final` to `marker_length_yards`
    multiplied by 52 — the nominal 54-inch width less the 2-inch selvage trim —
    divided by that measured width less the same 2-inch trim, rounded half up
    to three decimal places."

    Design: Difficulty/dual_variant_calc/fabric_requirement_provisional_vs_final
    """
    order, line, lot = _camden_fixture()
    line_now = validate_success(api.get_order_line(line["id"], SALES))
    assert line_now["required_yards_provisional"] == pytest.approx(14.950, abs=0.001)

    plan_res = api.create_cut_plan(
        line["id"],
        {"expected_order_line_version": line_now["version"]},
        PLANNER,
    )
    plan = validate_success(plan_res, 201)
    approve_res = api.approve_cut_plan(plan["id"], {"marker_length_yards": 13.0}, PLANNER)
    plan_approved = validate_success(approve_res, 200)
    # 13.0 × 52 / (50 − 2) = 14.083 (3 decimals, half-up)
    assert plan_approved["required_yards_final"] == pytest.approx(14.083, abs=0.001)

    line_after = validate_success(api.get_order_line(line["id"], SALES))
    assert line_after["required_yards_final"] == pytest.approx(14.083, abs=0.001)
    # The two variants disagree on identical line data
    assert line_after["required_yards_final"] != pytest.approx(
        line_now["required_yards_provisional"], abs=0.001
    )


# ---------------------------------------------------------------------------
# Instance: freight_charge_ltl_vs_white_glove
# ---------------------------------------------------------------------------

def _ltl_and_wg_shipments():
    """Two orders (LTL_FREIGHT and WHITE_GLOVE), each with one DRAFT shipment
    carrying identical weights/dims/pieces. Returns (ship_ltl, ship_wg)."""
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(
        model_code="M-LOUNGE",
        category="CHAIR",
        base_fabric_yards=2.0,
        base_price_cents=50000,
        requires_pattern_match=False,
        option_rules=[{
            "fabric_grade": "B", "finish_code": "ANY",
            "allowed": True, "surcharge_pct": 0.0, "lead_time_adder_days": 0,
        }],
    )
    spec = create_spec(fabric_code="FAB-B", origin="PLANT", grade="B",
                       nominal_width_inches=54.0, price_per_yard_cents=2000)
    dealer = create_dealer()

    order_ltl = create_order("ORD-LTL", dealer["id"], delivery_method="LTL_FREIGHT")
    add_line(order_ltl["id"], model["id"], spec["id"], fabric_source="PLANT_STOCK",
             finish_code="ESPRESSO", quantity=1)
    confirm_order(order_ltl["id"])

    order_wg = create_order("ORD-WG", dealer["id"], delivery_method="WHITE_GLOVE")
    add_line(order_wg["id"], model["id"], spec["id"], fabric_source="PLANT_STOCK",
             finish_code="ESPRESSO", quantity=1)
    confirm_order(order_wg["id"])

    ship_ltl = get_success_data(api_client.create_shipment(
        create_shipment_payload(
            order_id=order_ltl["id"], weight_lb=240.0, length_in=60.0,
            width_in=30.0, height_in=36.0, declared_value_cents=0, piece_count=3,
        ), SHIP))
    ship_wg = get_success_data(api_client.create_shipment(
        create_shipment_payload(
            order_id=order_wg["id"], weight_lb=240.0, length_in=60.0,
            width_in=30.0, height_in=36.0, declared_value_cents=0, piece_count=3,
        ), SHIP))
    return ship_ltl, ship_wg


def test_ltl_variant_rates_by_class_and_fuel(api):
    """PRD §3.9: "For an `LTL_FREIGHT` order the build order is pinned: the base
    is `weight_lb` times the class's per-pound rate ... rounded half up to a
    whole cent; the fuel surcharge is eighteen percent of that base, again
    rounded half up to a whole cent, assessed on the base only; and the
    `freight_charge_cents` is the base plus the fuel surcharge."

    Design: Difficulty/dual_variant_calc/freight_charge_ltl_vs_white_glove
    """
    ship_ltl, _ = _ltl_and_wg_shipments()
    rated = validate_success(api.rate_shipment(ship_ltl["id"], SHIP))
    # density 240 / 37.5 = 6.4 ≥ 6 → CLASS_125 (rate 130 cents/lb)
    assert rated["method"] == "LTL"
    assert rated["freight_class"] == "CLASS_125"
    # base 240 × 130 = 31200; fuel = round_half_up(31200 × 0.18) = 5616
    assert rated["freight_charge_cents"] == 36816


def test_white_glove_variant_flat_rated(api):
    """PRD §3.9: "For a `WHITE_GLOVE` order the charge is flat-rated: the greater
    of a 15000-cent minimum and 8500 cents per piece in `piece_count`, plus a
    fixed 4500-cent inside-delivery surcharge — the same packaged goods price
    differently under the two methods, and density and class are still computed
    and stored on a white-glove shipment even though the charge ignores them."

    Design: Difficulty/dual_variant_calc/freight_charge_ltl_vs_white_glove
    """
    ship_ltl, ship_wg = _ltl_and_wg_shipments()
    rated_wg = validate_success(api.rate_shipment(ship_wg["id"], SHIP))
    # max(15000, 3 × 8500) + 4500 = 25500 + 4500 = 30000
    assert rated_wg["method"] == "WHITE_GLOVE"
    assert rated_wg["freight_charge_cents"] == 30000

    rated_ltl = validate_success(api.rate_shipment(ship_ltl["id"], SHIP))
    # Identical packaged inputs, different charge — variants diverge
    assert rated_ltl["freight_charge_cents"] == 36816
    assert rated_ltl["freight_charge_cents"] != rated_wg["freight_charge_cents"]
