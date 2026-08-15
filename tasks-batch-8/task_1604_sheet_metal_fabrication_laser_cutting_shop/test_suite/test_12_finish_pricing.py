"""Finish pricing: POWDER in-house line-level cost, PLATING vendor
pass-through, and POWDER routing last."""
from test_helpers import (
    EST,
    accept_quote,
    create_customer,
    create_draft_quote,
    create_full_sheet,
    create_grade,
    create_machine,
    create_submitted_quote,
    create_vendor,
    get_order_lines,
    get_order_steps,
    validate_success,
)

CRS_GRADE = {
    "alloy_family": "CARBON_STEEL",
    "density_g_per_cm3": 7.85,
    "hardness_factor": 1.0,
    "base_cut_rate_cents_per_sec": 2.0,
    "material_cost_cents_per_cm2": 0.045,
    "scrap_rate_cents_per_cm2": 0.015,
}
CRS_TIERS = [{"max_thickness_mm": 1.0, "tier_index": 0},
             {"max_thickness_mm": 2.0, "tier_index": 1}]


def test_powder_finish_cost_and_routing_last(api):
    """PRD §3.3: "POWDER is an in-house finish whose line-level rows are
    computed per line with the quantity multiplied inside: the part area times
    0.040 cents per square centimeter, rounded half-up, times the line
    quantity." PRD §3.6: "The station sequence is the union of the lines'
    requirements in a fixed order: LASER always comes first, then BRAKE when
    any line has a positive `bend_count`, then WELD when any line has positive
    `weld_inches`, then OUTSIDE_VENDOR when any line's `finish` is PLATING or
    ANODIZING, then POWDER when any line's `finish` is POWDER — in-house
    powder always runs last."

    Design: Corner/calculations/powder_finish_cost_and_routing_last
    """
    grade = create_grade(tiers=CRS_TIERS, **CRS_GRADE)
    customer = create_customer()
    # 600x400 at 1.9mm (tier 1), 2 bends, POWDER, qty 2.
    line = {"thickness_mm": 1.9, "bbox_width_mm": 600, "bbox_height_mm": 400,
            "hole_count": 0, "corner_fillet_count": 0, "bend_count": 2,
            "weld_inches": 0, "finish": "POWDER", "qty": 2}
    quote = create_draft_quote(customer["id"], grade["id"],
                               line_overrides=line, qty=2)
    validate_success(api.price_quote(quote["id"], quote["version"], EST))

    priced_line = get_order_lines(quote["id"])[0]
    # finish: 2 * round_half_up(2400 * 0.040) = 192
    assert priced_line["finish_cost_cents"] == 192
    # cut: billed 100s * 2.0 * (1 + 0.20*1) * 1.0 = 240; bend: 2*(1+2+0)*150
    # = 900; finish 192; material round_half_up(2400*0.045) = 108; setup 900.
    assert priced_line["line_base_cents"] == 2340
    # qty 2 earns no discount; STANDARD multiplier is 1.00.
    assert priced_line["qty_discount_pct"] == 0
    assert priced_line["line_total_cents"] == 2340

    # Routing: in-house POWDER always runs last.
    create_full_sheet(grade["id"], thickness_mm=1.9)
    create_machine("LASER")
    create_machine("BRAKE")
    create_machine("POWDER")
    submitted = create_submitted_quote(customer["id"], grade["id"],
                                       line_overrides=line, qty=2)
    order = accept_quote(submitted["id"], customer["id"])
    stations = [s["station"] for s in get_order_steps(order["id"])]
    assert stations == ["LASER", "BRAKE", "POWDER"]
    assert [s["seq"] for s in get_order_steps(order["id"])] == [1, 2, 3]


def test_plating_finish_includes_vendor_pass_through(api):
    """PRD §3.3: "PLATING and ANODIZING are outside finishes: the same
    construction at 0.060 and 0.055 cents per square centimeter respectively,
    plus the assigned vendor's `base_cost_cents_per_part` multiplied by the
    line quantity on top."

    Design: Corner/calculations/plating_finish_includes_vendor_pass_through
    """
    grade = create_grade(**CRS_GRADE)
    create_vendor("PLATING", lead_time_days=5, base_cost_cents_per_part=350)
    customer = create_customer()
    quote = create_draft_quote(
        customer["id"], grade["id"],
        line_overrides={"bbox_width_mm": 100, "bbox_height_mm": 100,
                        "hole_count": 0, "corner_fillet_count": 0,
                        "bend_count": 0, "weld_inches": 0, "finish": "PLATING"},
        qty=2,
    )
    validate_success(api.price_quote(quote["id"], quote["version"], EST))

    line = get_order_lines(quote["id"])[0]
    # 2 * round_half_up(100 * 0.060) + 350 * 2 = 12 + 700.
    assert line["finish_cost_cents"] == 712
