"""Corner tests — §calculations (requisition sizing, record-cut utilization,
freight classification boundaries, waste tiers, COM credit recompute)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_line,
    api_client,
    confirm_order,
    create_approved_cut_plan,
    create_available_lot,
    create_cell,
    create_dealer,
    create_draft_cut_plan,
    create_lot,
    create_model,
    create_order,
    create_shipment_payload,
    create_spec,
    get_success_data,
    inspect_lot_pass,
    make_quality_inspector_headers,
    receive_lot,
    record_cut_on_plan,
    set_clock,
    setup_confirmed_order_with_plant_stock,
    setup_order_with_line,
    book_cell,
    start_and_complete_booking,
    validate_success,
)

SALES = TEST_USERS["sales_rep_headers"]
PLANNER = TEST_USERS["production_planner_headers"]
RECEIVER = TEST_USERS["material_receiver_headers"]
SHIP = TEST_USERS["shipping_coordinator_headers"]


def test_requisition_sizing_container_vs_domestic(api):
    """PRD §3.6: "A `CONTAINER` requisition rounds the requested quantity up to
    a multiple of the 50-unit minimum order quantity to produce its read-only
    `ordered_quantity`, prices it at a `unit_cost_cents` of 1200, and lands 45
    lead days out. A `DOMESTIC` requisition orders exactly the requested
    quantity at a `unit_cost_cents` of 2000 with a 7-day lead. In both cases
    the `extended_cost_cents` is the ordered quantity times the unit cost, and
    the read-only `available_date` is the ISO calendar date obtained by adding
    the lead days to the date of the order's `confirmed_at` on the logical
    clock."

    Design: Corner/calculations/requisition_sizing_container_vs_domestic
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP", required_component_codes=["FRAME"])
    spec = create_spec(fabric_code="FAB-A")
    dealer = create_dealer()
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-SZ",
                                        quantity=1)
    confirm_order(order["id"])

    req_c = get_success_data(api_client.create_supply_requisition({
        "order_line_id": line["id"], "component_code": "FRAME",
        "quantity": 120, "source_type": "CONTAINER",
    }, PLANNER))
    # ceil(120 / 50) × 50 = 150; unit 1200; 150 × 1200 = 180000;
    # confirmed 2026-05-10 + 45 days = 2026-06-24
    assert req_c["ordered_quantity"] == 150
    assert req_c["unit_cost_cents"] == 1200
    assert req_c["extended_cost_cents"] == 180000
    assert req_c["available_date"] == "2026-06-24"
    assert req_c["status"] == "OPEN"

    req_d = get_success_data(api_client.create_supply_requisition({
        "order_line_id": line["id"], "component_code": "LEGS",
        "quantity": 120, "source_type": "DOMESTIC",
    }, PLANNER))
    # 120 exact; 2000 unit; 240000; +7 days = 2026-05-17
    assert req_d["ordered_quantity"] == 120
    assert req_d["unit_cost_cents"] == 2000
    assert req_d["extended_cost_cents"] == 240000
    assert req_d["available_date"] == "2026-05-17"
    assert req_d["status"] == "OPEN"


def test_record_cut_utilization_and_waste(api):
    """PRD §3.5: "At record-cut, **all** of the line's ACTIVE allocations are
    consumed whole in `created_at` ascending order: each moves to `CONSUMED`
    with its `consumed_yards` set to its full reserved `yards`. The plan then
    records its cutting yield: `utilization_pct` is `required_yards_final`
    divided by the total consumed yards, expressed as a percentage and rounded
    half up to two decimal places, and `waste_yards` is the total consumed
    yards minus `required_yards_final`, kept at three decimals."

    Design: Corner/calculations/record_cut_utilization_and_waste
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(
        model_code="CAMDEN-SOFA", category="SOFA", base_fabric_yards=3.0,
        base_price_cents=100000, requires_pattern_match=True,
        option_rules=[{
            "fabric_grade": "A", "finish_code": "ESPRESSO",
            "allowed": True, "surcharge_pct": 0.0, "lead_time_adder_days": 0,
        }],
    )
    spec = create_spec(fabric_code="FAB-PEBBLE-A", origin="PLANT", grade="A",
                       nominal_width_inches=54.0, pattern_repeat_v_inches=9.0,
                       match_method="STRAIGHT", price_per_yard_cents=3000)
    dealer = create_dealer()
    lot = create_available_lot(spec["id"], yards=25.0, measured_width_inches=50.0)
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-UT",
                                        quantity=4)
    confirm_order(order["id"])

    cell = create_cell("C-CUT", "CUTTING", 1, [])
    b_cut = book_cell(cell["id"], line["id"], "CUT",
                      "2026-06-01T08:00:00Z", "2026-06-01T09:00:00Z")
    start_and_complete_booking(b_cut["id"])
    plan = create_approved_cut_plan(line, marker_length_yards=13.0)
    cut_plan = record_cut_on_plan(plan)

    assert cut_plan["status"] == "CUT"
    # utilization = 14.083 / 14.950 × 100 = 94.20
    assert cut_plan["utilization_pct"] == pytest.approx(94.20, abs=0.01)
    # waste = 14.950 − 14.083 = 0.867
    assert cut_plan["waste_yards"] == pytest.approx(0.867, abs=0.001)

    # Allocation is consumed whole (created_at ASC — only one here)
    allocs, _ = __import__("test_helpers").validate_paginated(
        api.list_material_allocations(PLANNER, params={"order_line_id": line["id"]})
    )
    assert len(allocs) == 1
    assert allocs[0]["status"] == "CONSUMED"
    assert allocs[0]["consumed_yards"] == pytest.approx(14.950, abs=0.001)

    lot_after = validate_success(api.get_material_lot(lot["id"], RECEIVER))
    assert lot_after["allocated_yards"] == pytest.approx(0.0, abs=0.001)
    assert lot_after["available_yards"] == pytest.approx(10.050, abs=0.001)
    assert lot_after["status"] == "AVAILABLE"  # not depleted

    line_after = validate_success(api.get_order_line(line["id"], SALES))
    assert line_after["status"] == "CUT"


def test_freight_classification_boundaries(api):
    """PRD §3.9: "The base `freight_class` is chosen by density lower bound:
    at least 22.5 earns `CLASS_65`; at least 15, `CLASS_70`; at least 12,
    `CLASS_85`; at least 9, `CLASS_92_5`; at least 8, `CLASS_100`..."
    PRD §3.9: "A declared-value override then applies: when
    `declared_value_cents` divided by `weight_lb` is strictly greater than
    3000 cents per pound, the class is bumped exactly one step toward
    `CLASS_400` along the class progression from 65 through 70, 85, 92.5, 100,
    110, 125, 150, 175, 200, 250, and 300 to 400."

    Design: Corner/calculations/freight_classification_boundaries
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-NP", category="CHAIR", base_fabric_yards=2.0,
                         option_rules=[{
                             "fabric_grade": "B", "finish_code": "ANY",
                             "allowed": True, "surcharge_pct": 0.0,
                             "lead_time_adder_days": 0,
                         }])
    spec = create_spec(fabric_code="FAB-B", origin="PLANT", grade="B",
                       nominal_width_inches=54.0, price_per_yard_cents=2000)
    dealer = create_dealer()

    ships = {}
    for name, weight, dims, declared, pieces in [
        ("over", 240.0, (60.0, 30.0, 36.0), 800000, 3),
        ("at", 180.0, (48.0, 30.0, 24.0), 0, 1),
        ("below", 179.9, (48.0, 30.0, 24.0), 0, 1),
    ]:
        order = create_order(f"ORD-F-{name}", dealer["id"])
        add_line(order["id"], model["id"], spec["id"], fabric_source="PLANT_STOCK",
                 finish_code="ESPRESSO", quantity=1)
        confirm_order(order["id"])
        ship = get_success_data(api_client.create_shipment(create_shipment_payload(
            order_id=order["id"], weight_lb=weight, length_in=dims[0],
            width_in=dims[1], height_in=dims[2], declared_value_cents=declared,
            piece_count=pieces,
        ), SHIP))
        ships[name] = ship

    # (a) Value override: 800000/240 = 3333.33 > 3000 → bump 125 → 150
    rated_over = validate_success(api.rate_shipment(ships["over"]["id"], SHIP))
    assert rated_over["freight_class"] == "CLASS_150"
    # base 240 × 155 = 37200; fuel 6696; total 43896
    assert rated_over["freight_charge_cents"] == 43896

    # (b) density 9.0 exactly — inclusive ≥ boundary → CLASS_92_5
    rated_at = validate_success(api.rate_shipment(ships["at"]["id"], SHIP))
    # 48 × 30 × 24 / 1728 = 20 cu ft; 180 / 20 = 9.0
    assert rated_at["density_lb_per_cuft"] == pytest.approx(9.0, abs=0.0001)
    assert rated_at["freight_class"] == "CLASS_92_5"
    # 180 × 80 = 14400; fuel 2592; total 16992
    assert rated_at["freight_charge_cents"] == 16992

    # (c) 179.9 / 20 = 8.995 < 9.0 → CLASS_100
    rated_below = validate_success(api.rate_shipment(ships["below"]["id"], SHIP))
    assert rated_below["density_lb_per_cuft"] == pytest.approx(8.995, abs=0.0001)
    assert rated_below["freight_class"] == "CLASS_100"
    # 179.9 × 95 = 17090.5 → 17091 wait, check exact: round_half_up(179.9 × 95)
    # 179.9 * 95 = 17090.5, half-up = 17091. fuel = round(17091 × 0.18) = round(3076.38) = 3076
    # Hmm — but the instance asserts 20167. Let me trust the design:
    # base = 17090.5 → 17091 (half up); fuel = round(17091 × 0.18) = round(3076.38) = 3076;
    # total = 17091 + 3076 = 20167
    assert rated_below["freight_charge_cents"] == 20167


def test_waste_tier_mid_quantity(api):
    """PRD §3.3: "A tiered cutting-waste allowance then applies: fifteen
    percent for lines of five units or fewer, ten percent for lines of six to
    twenty units, and seven percent for lines of more than twenty units."

    Design: Corner/calculations/waste_tier_mid_quantity
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-PM", category="SOFA", base_fabric_yards=3.0,
                         base_price_cents=50000, requires_pattern_match=True,
                         option_rules=[{
                             "fabric_grade": "A", "finish_code": "ESPRESSO",
                             "allowed": True, "surcharge_pct": 0.0,
                             "lead_time_adder_days": 0,
                         }])
    spec = create_spec(fabric_code="FAB-STRAIGHT", origin="PLANT", grade="A",
                       nominal_width_inches=54.0, pattern_repeat_v_inches=9.0,
                       match_method="STRAIGHT", price_per_yard_cents=3000)
    dealer = create_dealer()
    order = create_order("ORD-T6", dealer["id"])
    line = add_line(order["id"], model["id"], spec["id"], fabric_source="PLANT_STOCK",
                    finish_code="ESPRESSO", quantity=6)
    confirm_order(order["id"])

    line_now = validate_success(api.get_order_line(line["id"], SALES))
    # per-unit 3.1154; repeat 0.25; ceil = 13; base 13 × 0.25 × 6 = 19.5;
    # qty 6 falls in mid tier → × 1.10 = 21.450
    assert line_now["required_yards_provisional"] == pytest.approx(21.450, abs=0.001)
    # No lots → line short
    assert line_now["status"] == "MATERIAL_SHORTFALL"


def test_com_credit_updates_on_allocation_events(api):
    """PRD §3.3: "While confirm supplies the initial subtotal, the COM credit
    is recomputed on every allocation creation, release, or consumption
    thereafter."
    PRD §3.3: "the line credit is the line's allocated COM yards — the summed
    `yards` of that line's allocations in `ACTIVE` or `CONSUMED` status against
    lots whose `ownership` is `CUSTOMER` — multiplied by the fabric's
    `com_credit_per_yard_cents`, rounded half up to a whole cent per line."

    Design: Corner/calculations/com_credit_updates_on_allocation_events
    """
    set_clock("2026-05-10T00:00:00Z")
    model = create_model(model_code="M-COM", category="SOFA", base_fabric_yards=3.0,
                         base_price_cents=50000, requires_pattern_match=False,
                         option_rules=[{
                             "fabric_grade": "COM", "finish_code": "ANY",
                             "allowed": True, "surcharge_pct": 0.0,
                             "lead_time_adder_days": 0,
                         }])
    spec = create_spec(fabric_code="FAB-COM-CR", origin="CUSTOMER", grade="COM",
                       nominal_width_inches=54.0, com_credit_per_yard_cents=250)
    dealer = create_dealer()
    order, line = setup_order_with_line(model, spec, dealer, order_number="ORD-CR2",
                                        quantity=4, fabric_source="COM")
    confirm_order(order["id"])

    lot = create_lot(spec["id"], expected_yards=10.5, order_line_id=line["id"])
    receive_lot(lot["id"], received_yards=10.5)
    inspect_lot_pass(lot["id"], usable_yards=10.5, measured_width_inches=54.0)

    # After inspect: credit = round_half_up(10.5 × 250) = 2625
    ord_mid = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_mid["subtotal_cents"] == 200000
    assert ord_mid["com_credit_cents"] == 2625
    assert ord_mid["total_cents"] == 197375

    line_mid = validate_success(api.get_order_line(line["id"], SALES))
    assert line_mid["allocated_yards"] == pytest.approx(10.5, abs=0.001)
    assert line_mid["status"] == "MATERIAL_SHORTFALL"

    # Find the auto-created allocation and release it
    from test_helpers import validate_paginated
    allocs, _ = validate_paginated(api.list_material_allocations(
        PLANNER, params={"lot_id": lot["id"]}))
    assert len(allocs) == 1
    validate_success(api.release_allocation(allocs[0]["id"], PLANNER), 200)

    ord_end = validate_success(api.get_customer_order(order["id"], SALES))
    assert ord_end["com_credit_cents"] == 0
    assert ord_end["total_cents"] == 200000

    line_end = validate_success(api.get_order_line(line["id"], SALES))
    assert line_end["allocated_yards"] == pytest.approx(0.0, abs=0.001)
    assert line_end["shortfall_yards"] == pytest.approx(14.331, abs=0.001)
