"""Production-order pricing: provisional vs final variants, the pinned
rounding order, tier multipliers, and amortization depletion.

Worked geometry (PRD §3.5 recipe on the default fixture): sheet board
footage 108*48*2/144 = 72.0; the 10x8 part nests to 52 parts per sheet;
provisional assumed yield is floor(52 * 0.70) = 36.
"""
from test_helpers import (
    SALES,
    assert_production_order,
    confirm_order,
    create_approved_spec,
    create_customer,
    create_locked_cnc_program,
    create_locked_die_program,
    create_material,
    create_quoted_order,
    get_tooling,
    validate_success,
)


def _die_setup():
    """Approved spec + LOCKED DIE program (52 parts/sheet) + IN_SERVICE die
    (die cost 250000 cents, amortization qty 1000)."""
    customer, material, spec = create_approved_spec()
    program, tooling = create_locked_die_program(spec["id"])
    return customer, material, spec, program, tooling


def test_provisional_pricing_uses_assumed_yield(api):
    """PRD §3.5: "The theoretical best nesting — the nesting study's
    `parts_per_sheet` computed from the specification's part dimensions
    against the material's sheet dimensions — is multiplied by 0.70 and
    rounded down to a whole number to give the effective parts per sheet."
    PRD §3.5: "Creation computes the provisional pricing fields
    `provisional_unit_price_cents` and `provisional_total_cents`; the final
    pricing fields `final_unit_price_cents` and `final_total_cents` stay null
    until confirmation, and `tooling_amort_cents` is determined at
    confirmation, zero for `CNC_ROUTE` work."

    Design: Difficulty/dual_variant_calc/production_order_provisional_vs_final_pricing
    """
    _c, _m, spec, program, _t = _die_setup()
    order = create_quoted_order(spec["id"], program["id"], 500)
    assert_production_order(order)
    # Provisional: effective 36/sheet -> 14 sheets; material 14*72*250/500 =
    # 504/part; cutting 25; amort ceil(250000/1000) = 250; (504+25+250)*1.15
    # = 895.85 -> 896.
    assert order["provisional_unit_price_cents"] == 896
    assert order["provisional_total_cents"] == 896 * 500 + 5000 == 453000
    assert order["final_unit_price_cents"] is None
    assert order["final_total_cents"] is None
    assert order["tooling_amort_cents"] is None
    assert order["fab_status"] == "QUOTED"
    assert order["order_kind"] == "CUSTOMER"


def test_final_pricing_uses_locked_actual_yield(api):
    """PRD §3.5: "Confirmation reprices with the locked program's actual
    `parts_per_sheet`, so a confirmed order's price generally differs from
    its quote even for identical quantity and material." PRD §3.5: "For
    `DIE_CUT`, confirmation also charges the die: the order's
    `tooling_amort_cents` is the smaller of the remaining unamortized cents
    and the per-part amortization component times the smaller of the order
    `qty` and `amortization_qty`, and the tooling's `amortized_cents`
    increases by the charged amount."

    Design: Difficulty/dual_variant_calc/production_order_provisional_vs_final_pricing
    """
    _c, _m, spec, program, tooling = _die_setup()
    order = create_quoted_order(spec["id"], program["id"], 500)
    confirmed = confirm_order(order["id"])
    # Final: locked 52/sheet -> 10 sheets; material 10*72*250/500 = 360/part;
    # cutting 25; amort 250; (360+25+250)*1.15 = 730.25 -> 730.
    assert confirmed["final_unit_price_cents"] == 730
    assert confirmed["final_total_cents"] == 730 * 500 + 5000 == 370000
    assert confirmed["tooling_amort_cents"] == 125000  # 250 * min(500, 1000)
    assert confirmed["provisional_unit_price_cents"] != confirmed["final_unit_price_cents"], (
        "identical qty/material/method price differently under the two variants"
    )
    assert get_tooling(tooling["id"])["amortized_cents"] == 125000


def test_pinned_rounding_rounds_unit_before_multiplying(api):
    """PRD §3.5: "First, the raw unit amount is rounded half-up to whole
    cents, producing the unit price. Second, the order total is that rounded
    unit price multiplied by the quantity. Third — for production orders
    only — the setup fee is added to that total afterward: 5,000 cents for
    `DIE_CUT` work and 15,000 cents for `CNC_ROUTE` work."

    Design: Difficulty/combinatorial_formula/order_total_unit_rounding_then_multiply
    """
    _c, _m, spec, program, _t = _die_setup()
    order = create_quoted_order(spec["id"], program["id"], 500)
    confirmed = confirm_order(order["id"])
    # unit_raw is 730.25; the pinned order rounds the unit FIRST (730), then
    # multiplies (365000), then adds the 5000-cent die setup fee.
    assert confirmed["final_unit_price_cents"] == 730
    assert confirmed["final_total_cents"] == 730 * 500 + 5000 == 370000


def test_pinned_rounding_rejects_sum_then_round_alternative(api):
    """PRD §3.5: "The setup fee is never tier-multiplied, and the alternative
    of summing raw unrounded amounts and rounding once at the end must not be
    used, because it yields different cents."

    Design: Difficulty/combinatorial_formula/order_total_unit_rounding_then_multiply
    """
    _c, _m, spec, program, _t = _die_setup()
    order = create_quoted_order(spec["id"], program["id"], 500)
    confirmed = confirm_order(order["id"])
    # Sum-then-round would give round(730.25 * 500) + 5000 = 370125.
    assert confirmed["final_total_cents"] != 370125
    # The setup fee is added after the unit*qty multiplication, unmultiplied:
    # 370000 - 730*500 == 5000 exactly.
    assert (
        confirmed["final_total_cents"]
        - confirmed["final_unit_price_cents"] * confirmed["qty"]
        == 5000
    )
    quoted = validate_success(api.get_production_order(order["id"], SALES))
    assert quoted["provisional_total_cents"] - 896 * 500 == 5000


def test_amortization_component_depletes_across_confirmed_orders(api):
    """PRD §3.5: "The amortization component per part exists only for
    `DIE_CUT`: it is the tooling's remaining unamortized cents —
    `die_cost_cents` minus the tooling's `amortized_cents` at pricing time —
    divided by the tooling's `amortization_qty`, rounded up; for `CNC_ROUTE`
    the component is zero."

    Design: Difficulty/combinatorial_formula/quote_pricing_tiered_amortization_interaction
    """
    _c, _m, spec, program, _t = _die_setup()
    o1 = create_quoted_order(spec["id"], program["id"], 500)
    o1 = confirm_order(o1["id"], "DIE-1",
                       "2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
    o2 = create_quoted_order(spec["id"], program["id"], 500)
    o2 = confirm_order(o2["id"], "DIE-1",
                       "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")

    # First order: amort component ceil(250000/1000) = 250/part.
    assert o1["final_unit_price_cents"] == 730  # (360+25+250)*1.15 = 730.25
    assert o1["tooling_amort_cents"] == 125000
    # Second order: component ceil(125000/1000) = 125/part on the remainder.
    assert o2["final_unit_price_cents"] == 587  # (360+25+125)*1.15 = 586.5
    assert o2["tooling_amort_cents"] == 62500  # 125 * min(500, 1000)


def test_amortization_accumulates_on_tooling_without_exceeding_die_cost(api):
    """PRD §3.5: "For `DIE_CUT`, confirmation also charges the die: the
    order's `tooling_amort_cents` is the smaller of the remaining unamortized
    cents and the per-part amortization component times the smaller of the
    order `qty` and `amortization_qty`, and the tooling's `amortized_cents`
    increases by the charged amount."

    Design: Difficulty/combinatorial_formula/quote_pricing_tiered_amortization_interaction
    """
    _c, _m, spec, program, tooling = _die_setup()
    windows = [
        ("2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z"),
        ("2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z"),
        ("2026-08-03T10:00:00Z", "2026-08-03T11:00:00Z"),
    ]
    orders = []
    for start, end in windows:
        order = create_quoted_order(spec["id"], program["id"], 500)
        orders.append(confirm_order(order["id"], "DIE-1", start, end))

    # Third order: component ceil(62500/1000) = 63/part on remaining 62500.
    assert orders[2]["final_unit_price_cents"] == 515  # (360+25+63)*1.15
    assert orders[2]["tooling_amort_cents"] == 31500  # 63 * 500

    tooling_after = get_tooling(tooling["id"])
    assert tooling_after["amortized_cents"] == 125000 + 62500 + 31500 == 219000
    assert tooling_after["amortized_cents"] <= tooling_after["die_cost_cents"]


def _cnc_setup():
    """Approved spec + LOCKED CNC program (machine_seconds_per_part 40)."""
    customer, material, spec = create_approved_spec()
    program = create_locked_cnc_program(spec["id"], machine_seconds_per_part=40)
    return customer, material, spec, program


def test_qty_999_takes_mid_run_multiplier(api):
    """PRD §3.5: "A tier multiplier then scales with quantity: 1.35 when
    `qty` is 99 or fewer, 1.15 when `qty` is from 100 through 999, and 1.00
    when `qty` is 1,000 or more."

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_at_1000
    """
    _c, _m, spec, program = _cnc_setup()
    order = create_quoted_order(spec["id"], program["id"], 999)
    confirmed = confirm_order(order["id"], "CNC-1",
                              "2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
    # 999 -> 20 sheets; material 20*72*250/999 = 360.360.../part; cutting
    # 40*3 = 120; (480.360...)*1.15 = 552.414... -> 552.
    assert confirmed["final_unit_price_cents"] == 552
    assert confirmed["final_total_cents"] == 552 * 999 + 15000 == 566448
    assert confirmed["tooling_amort_cents"] == 0, (
        "CNC_ROUTE work carries no die amortization"
    )


def test_qty_1000_takes_volume_multiplier(api):
    """PRD §3.5: "A tier multiplier then scales with quantity: 1.35 when
    `qty` is 99 or fewer, 1.15 when `qty` is from 100 through 999, and 1.00
    when `qty` is 1,000 or more."

    Design: Difficulty/boundary_precision_check/volume_tier_boundary_at_1000
    """
    _c, _m, spec, program = _cnc_setup()
    order = create_quoted_order(spec["id"], program["id"], 1000)
    confirmed = confirm_order(order["id"], "CNC-1",
                              "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
    # 1000 -> 20 sheets; material 360/part; cutting 120; (480)*1.00 = 480.
    assert confirmed["final_unit_price_cents"] == 480
    assert confirmed["final_total_cents"] == 480 * 1000 + 15000 == 495000


def test_created_entities_reflect_computed_fields_immediately(api):
    """PRD §3.2: "At creation the system computes the specification's
    `required_ild_lb`, the minimum acceptable material ILD, from a
    drop-height banding." PRD §3.5: "Creation computes the provisional
    pricing fields `provisional_unit_price_cents` and
    `provisional_total_cents`; the final pricing fields
    `final_unit_price_cents` and `final_total_cents` stay null until
    confirmation, and `tooling_amort_cents` is determined at confirmation,
    zero for `CNC_ROUTE` work."

    Design: Corner/consistency_model/created_entities_reflect_computed_fields_immediately
    """
    customer = create_customer()
    material = create_material()
    create_resp = api.create_package_spec(
        {
            "customer_id": customer["id"],
            "material_id": material["id"],
            "part_name": "Widget Tray",
            "part_length_in": 10,
            "part_width_in": 8,
            "product_weight_lb": 5,
            "required_drop_height_in": 30,
            "max_fragility_g": 60,
        },
        SALES,
    )
    spec = validate_success(create_resp, 201)
    assert spec["required_ild_lb"] == 50, (
        "the create response itself carries the computed required ILD"
    )

    _c, _m, spec, program = _cnc_setup()
    order = create_quoted_order(spec["id"], program["id"], 100)
    # Provisional yield floor(52*0.70) = 36 -> 3 sheets; material
    # 3*72*250/100 = 540/part; cutting 120; (660)*1.15 = 759.0.
    assert order["provisional_unit_price_cents"] == 759
    assert order["provisional_total_cents"] == 759 * 100 + 15000 == 90900
