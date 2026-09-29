"""Order cost roll-up: five ordered steps, per-component rounding, floored unit cost.

PRD.md section 3.3 builds the order cost in five numbered steps whose *order* is
part of the contract: material rounds per charge before summing, oven energy rounds
per cycle before summing, the overhead tier is chosen once from the pre-overhead
subtotal, overhead rounds half-up, and only then is the unit cost floored. The
computed read of PRD.md section 3.3 exposes every intermediate, so each step can be
observed rather than inferred.
"""

from test_helpers import (
    ADMIN_HEADERS,
    advance_unit_to_sellable,
    assert_money_equals,
    assert_resin_ledger_conserved,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    dec,
    get_success_data,
    mold_payload,
    product_model_payload,
    reserve_charge,
    run_cycle_to_demold,
    schedule_cycle,
)


def _p5_single_cavity_plant(*, nominal_charge_kg, station_overrides=None):
    """A plant whose only mould is single-cavity at the model's full nominal charge.

    PRD.md section 3.4 makes the tool's ``nominal_charge_kg`` the model's charge
    multiplied by ``cavity_count``, so a one-cavity tool at the same figure lets a
    test dial the consumed mass exactly.
    """
    return create_plant_baseline(
        model_overrides={"nominal_charge_kg": nominal_charge_kg},
        mold_overrides={"cavity_count": 1, "nominal_charge_kg": nominal_charge_kg},
        station_overrides=station_overrides,
    )


def _p5_demold_cycle(ctx, cycle, *, oven_start, oven_end, cooling_end):
    """Drive one already-charged cycle from SCHEDULED to DEMOLDED on explicit stamps."""
    ctx["molding_cycle"] = cycle
    ctx["molding_cycle_id"] = cycle["id"]
    return run_cycle_to_demold(
        ctx,
        actual_oven_start_at=oven_start,
        actual_oven_end_at=oven_end,
        actual_cooling_end_at=cooling_end,
    )


def _p5_unit_cost_absent(value):
    """True when a cost read reports "no unit cost yet".

    PRD.md section 3.3 says ``unit_cost_cents`` is "null otherwise", while the field
    catalogue of PRD.md section 2.8 lists it among money fields "all integers
    defaulting to 0". Both readings are honoured so neither faithful serialisation
    is punished.
    """
    return value is None or value == 0


def test_cost_summary_counts_consumed_charges_and_demolded_cycles_only(api, admin_headers):
    """A scheduled-then-aborted second cycle leaves every cost figure bit-identical.

    PRD.md section 3.3 names both input sets: "over the order's charges in `status`
    `CONSUMED` — reached through the order's cycles — each charge contributes
    `charge_kg` multiplied by its lot's `cost_cents_per_kg`, **rounded half-up to
    whole cents per charge and only then summed** into `material_cost_cents`", and
    "over the order's cycles in `status` `DEMOLDED` only, each contributes
    `actual_oven_minutes` multiplied by its station's `energy_cents_per_min`, again
    rounded to whole cents per cycle before summation into `oven_energy_cost_cents`;
    cycles in `SCHEDULED`, `OVEN_RUNNING`, `COOLING` or `ABORTED` contribute
    nothing."  PRD.md section 3.5 fixes what the abort does to the ledger: charges
    "already `CONSUMED` are **not** restored: `consumed_kg` stays on the lot as a
    scrapped shot".

    Design: Corner/calculations/calc_input_set_filtering_order_cost_consumed_charges_and_demolded_cycles_only
    """
    ctx = _p5_single_cavity_plant(nominal_charge_kg=25.0)
    lot = create_resin_lot(cost_cents_per_kg=213, received_kg=200.0)
    order = create_production_order(ctx, ordered_qty=2)
    first = schedule_cycle(ctx, order)
    reserve_charge(ctx, first, lot, charge_kg=12.5, regrind_kg=1.25)
    reserve_charge(ctx, first, lot, charge_kg=12.5, regrind_kg=1.25)
    _p5_demold_cycle(
        ctx,
        first,
        oven_start="2026-08-01T09:00:00Z",
        oven_end="2026-08-01T10:00:00Z",
        cooling_end="2026-08-01T10:35:00Z",
    )
    advance_unit_to_sellable(ctx, ctx["finished_units"][0])

    second = schedule_cycle(
        ctx, order, oven_start_at="2026-08-01T11:00:00Z"
    )
    stray = reserve_charge(ctx, second, lot, charge_kg=12.5, regrind_kg=1.25)

    def _assert_costs(summary, label):
        assert summary["consumed_charge_count"] == 2, f"{label}: consumed_charge_count"
        # round_half_up(12.500 * 213) = round_half_up(2662.500) = 2663 per charge;
        # rounding the 5325.000 sum once instead gives 5325.
        assert_money_equals(summary["material_cost_cents"], 5326, f"{label}: material")
        assert summary["demolded_cycle_count"] == 1, f"{label}: demolded_cycle_count"
        assert_money_equals(summary["oven_energy_cost_cents"], 6000, f"{label}: oven energy")
        assert_money_equals(summary["pre_overhead_subtotal_cents"], 11326, f"{label}: subtotal")
        assert dec(summary["overhead_rate_pct"]) == dec("18.00"), f"{label}: overhead_rate_pct"
        # round_half_up(11326 * 18.00 / 100) = round_half_up(2038.68) = 2039.
        assert_money_equals(summary["overhead_cents"], 2039, f"{label}: overhead")
        assert_money_equals(summary["total_cost_cents"], 13365, f"{label}: total")
        assert summary["completed_qty"] == 1, f"{label}: completed_qty"
        assert_money_equals(summary["unit_cost_cents"], 13365, f"{label}: unit cost")

    _assert_costs(api.read_cost_summary(order["id"], admin_headers), "with the stray charge reserved")

    ledger = api.read_entity("get_resin_lot", lot["id"], admin_headers)
    assert dec(ledger["available_kg"]) == dec("162.500"), "the reserved shot leaves available_kg"
    assert dec(ledger["reserved_kg"]) == dec("12.500"), "the stray charge sits in reserved_kg"
    assert dec(ledger["consumed_kg"]) == dec("25.000"), "only the first cycle's shot is consumed"
    assert_resin_ledger_conserved(ledger)

    get_success_data(
        api.abort_molding_cycle(second["id"], {"abort_reason": "OPERATOR_ABORT"}, ctx["operator_headers"])
    )

    _assert_costs(api.read_cost_summary(order["id"], admin_headers), "after the abort")

    aborted = api.read_entity("get_molding_cycle", second["id"], ctx["operator_headers"])
    assert aborted["status"] == "ABORTED", f"expected ABORTED, got {aborted['status']}"
    released = api.read_entity("get_resin_charge", stray["id"], ctx["resin_tech_headers"])
    assert released["status"] == "RELEASED", f"expected RELEASED, got {released['status']}"
    assert released["released_reason"] == "CYCLE_ABORTED", (
        f"expected CYCLE_ABORTED, got {released['released_reason']!r}"
    )

    ledger = api.read_entity("get_resin_lot", lot["id"], admin_headers)
    assert dec(ledger["available_kg"]) == dec("175.000"), "the reserved shot returns to available_kg"
    assert dec(ledger["reserved_kg"]) == dec("0.000"), "nothing stays reserved after the abort"
    assert dec(ledger["consumed_kg"]) == dec("25.000"), "the CONSUMED bucket is never reversed"
    assert_resin_ledger_conserved(ledger)

    stored_order = api.read_entity("get_production_order", order["id"], admin_headers)
    assert stored_order["status"] == "IN_PRODUCTION", (
        f"an aborted cycle does not move the order, got {stored_order['status']}"
    )
    assert stored_order["completed_qty"] == 1, "completed_qty stays 1"
    assert stored_order["scrapped_qty"] == 0, "scrapped_qty stays 0"


def test_unit_cost_floors_the_same_total_as_completed_qty_rises(api, admin_headers):
    """The unit cost walks 13365, 26729 then 13364 — floored, never rounded.

    PRD.md section 3.3 pins the fifth step: "`unit_cost_cents` is the **floor** of
    `total_cost_cents` divided by `completed_qty` when `completed_qty` is at least 1,
    and null otherwise; because it is floored, the summed unit costs may fall below
    `total_cost_cents` and the remainder is deliberately not redistributed."  The same
    section makes the movement observable: "While the order is `IN_PRODUCTION` the unit
    cost moves with every passing verdict; once `COMPLETE` it stabilises".  PRD.md
    section 3.6 supplies the recomputation trigger: "The order's `completed_qty` and
    `scrapped_qty` are recomputed, the order may move `IN_PRODUCTION` to `COMPLETE`,
    and the order's cost roll-up and `unit_cost_cents` are recomputed."

    Design: Corner/calculations/calc_reconciliation_order_unit_cost_floor_from_in_flight_to_completion
    """
    ctx = _p5_single_cavity_plant(nominal_charge_kg=25.0)
    lot = create_resin_lot(cost_cents_per_kg=213, received_kg=200.0)
    order = create_production_order(ctx, ordered_qty=2)

    first = schedule_cycle(ctx, order)
    reserve_charge(ctx, first, lot, charge_kg=12.5, regrind_kg=1.25)
    reserve_charge(ctx, first, lot, charge_kg=12.5, regrind_kg=1.25)
    _p5_demold_cycle(
        ctx,
        first,
        oven_start="2026-08-01T09:00:00Z",
        oven_end="2026-08-01T10:00:00Z",
        cooling_end="2026-08-01T10:35:00Z",
    )
    advance_unit_to_sellable(ctx, ctx["finished_units"][0])

    after_one = api.read_cost_summary(order["id"], admin_headers)
    assert_money_equals(after_one["total_cost_cents"], 13365, "total after one hull")
    assert_money_equals(after_one["unit_cost_cents"], 13365, "unit cost after one hull")

    second = schedule_cycle(ctx, order, oven_start_at="2026-08-01T11:00:00Z")
    reserve_charge(ctx, second, lot, charge_kg=12.5, regrind_kg=1.25)
    reserve_charge(ctx, second, lot, charge_kg=12.5, regrind_kg=1.25)
    _p5_demold_cycle(
        ctx,
        second,
        oven_start="2026-08-01T11:00:00Z",
        oven_end="2026-08-01T12:00:00Z",
        cooling_end="2026-08-01T12:35:00Z",
    )
    second_hull = ctx["finished_units"][0]

    in_flight = api.read_cost_summary(order["id"], admin_headers)
    assert in_flight["consumed_charge_count"] == 4, "four charges are CONSUMED"
    assert_money_equals(in_flight["material_cost_cents"], 10652, "material for four charges")
    assert in_flight["demolded_cycle_count"] == 2, "two cycles are DEMOLDED"
    assert_money_equals(in_flight["oven_energy_cost_cents"], 12000, "oven energy for two cycles")
    assert_money_equals(in_flight["pre_overhead_subtotal_cents"], 22652, "in-flight subtotal")
    assert dec(in_flight["overhead_rate_pct"]) == dec("18.00"), "in-flight overhead rate"
    # round_half_up(22652 * 18.00 / 100) = round_half_up(4077.36) = 4077.
    assert_money_equals(in_flight["overhead_cents"], 4077, "in-flight overhead")
    assert_money_equals(in_flight["total_cost_cents"], 26729, "in-flight total")
    assert in_flight["completed_qty"] == 1, "the second hull is DEMOLDED, not yet countable"
    assert_money_equals(in_flight["unit_cost_cents"], 26729, "in-flight unit cost")

    advance_unit_to_sellable(ctx, second_hull)

    final = api.read_cost_summary(order["id"], admin_headers)
    assert_money_equals(final["total_cost_cents"], 26729, "total is unchanged by a verdict")
    assert final["completed_qty"] == 2, "both hulls now count"
    # floor(26729 / 2) = floor(13364.5) = 13364, not the rounded 13365.
    assert_money_equals(final["unit_cost_cents"], 13364, "final unit cost")
    assert 2 * final["unit_cost_cents"] == final["total_cost_cents"] - 1, (
        "one cent of the total is deliberately left unallocated"
    )

    stored_order = api.read_entity("get_production_order", order["id"], admin_headers)
    assert stored_order["status"] == "COMPLETE", f"expected COMPLETE, got {stored_order['status']}"
    assert stored_order["completed_qty"] == 2, "completed_qty"
    assert stored_order["scrapped_qty"] == 0, "scrapped_qty"

    finished = api.read_entity("get_finished_unit", second_hull["id"], admin_headers)
    assert finished["inspection_verdict"] == "PASS", "the second hull passes"
    assert finished["build_status"] == "SELLABLE", "a PASS moves OUTFITTED to SELLABLE"

    ledger = api.read_entity("get_resin_lot", lot["id"], admin_headers)
    assert dec(ledger["consumed_kg"]) == dec("50.000"), "four 12.500 kg shots are consumed"
    assert dec(ledger["reserved_kg"]) == dec("0.000"), "nothing stays reserved"
    assert dec(ledger["available_kg"]) == dec("150.000"), "the rest of the lot is untouched"
    assert_resin_ledger_conserved(ledger)


def test_overhead_tier_is_selected_once_at_each_ceiling_boundary(api, admin_headers):
    """Subtotals of 500000, 500001 and 2000001 cents pick 18.00, 14.50 and 11.00 percent.

    PRD.md section 3.3: "the overhead rate is the rate of the *first* tier whose
    ceiling is at or above that subtotal — 18.00 percent up to 500000 cents, 14.50
    percent up to 2000000 cents, and 11.00 percent above that. The tier is chosen once
    from the pre-overhead subtotal and is **never re-selected** after overhead is
    added, even when `total_cost_cents` lands in a different band."  Because the rate
    applies to the whole subtotal rather than marginally, one extra cent of subtotal
    can lower the total: 500001 cents at 14.50 percent totals 572501, below the
    500000-cent order's 590000.

    Design: Corner/calculations/calc_tiered_pricing_overhead_tier_boundaries_selected_once
    """
    ctx = _p5_single_cavity_plant(
        nominal_charge_kg=25.0, station_overrides={"energy_cents_per_min": 1}
    )
    heavy_model = get_success_data(
        api.create_product_model(
            product_model_payload(hull_type="CANOE", nominal_charge_kg=100.0), ADMIN_HEADERS
        )
    )
    get_success_data(
        api.create_mold(
            mold_payload(heavy_model["id"], cavity_count=1, nominal_charge_kg=100.0),
            ADMIN_HEADERS,
        )
    )
    heavy_ctx = dict(ctx, product_model_id=heavy_model["id"])
    lot = create_resin_lot(cost_cents_per_kg=19997, received_kg=500.0)

    at_ceiling = create_production_order(ctx, ordered_qty=1)
    one_cent_over = create_production_order(ctx, ordered_qty=1)
    top_band = create_production_order(heavy_ctx, ordered_qty=1)

    cycle_at_ceiling = schedule_cycle(ctx, at_ceiling, scheduled_oven_minutes=74)
    reserve_charge(ctx, cycle_at_ceiling, lot, charge_kg=12.5, regrind_kg=1.25)
    reserve_charge(ctx, cycle_at_ceiling, lot, charge_kg=12.5, regrind_kg=1.25)
    _p5_demold_cycle(
        ctx,
        cycle_at_ceiling,
        oven_start="2026-08-01T09:00:00Z",
        oven_end="2026-08-01T10:14:00Z",
        cooling_end="2026-08-01T10:44:00Z",
    )

    cycle_over = schedule_cycle(
        ctx, one_cent_over, oven_start_at="2026-08-01T11:00:00Z", scheduled_oven_minutes=75
    )
    reserve_charge(ctx, cycle_over, lot, charge_kg=12.5, regrind_kg=1.25)
    reserve_charge(ctx, cycle_over, lot, charge_kg=12.5, regrind_kg=1.25)
    _p5_demold_cycle(
        ctx,
        cycle_over,
        oven_start="2026-08-01T11:00:00Z",
        oven_end="2026-08-01T12:15:00Z",
        cooling_end="2026-08-01T12:45:00Z",
    )

    cycle_top = schedule_cycle(
        heavy_ctx,
        top_band,
        arm_index=2,
        oven_start_at="2026-08-01T13:00:00Z",
        scheduled_oven_minutes=301,
    )
    reserve_charge(heavy_ctx, cycle_top, lot, charge_kg=50.0, regrind_kg=5.0)
    reserve_charge(heavy_ctx, cycle_top, lot, charge_kg=50.0, regrind_kg=5.0)
    _p5_demold_cycle(
        heavy_ctx,
        cycle_top,
        oven_start="2026-08-01T13:00:00Z",
        oven_end="2026-08-01T18:01:00Z",
        cooling_end="2026-08-01T18:31:00Z",
    )

    # round_half_up(12.500 * 19997) = round_half_up(249962.500) = 249963 per charge, so
    # 499926 for two; rounding the 499925.000 sum once instead gives 499925.
    first_tier = api.read_cost_summary(at_ceiling["id"], admin_headers)
    assert_money_equals(first_tier["material_cost_cents"], 499926, "material at the ceiling")
    assert_money_equals(first_tier["oven_energy_cost_cents"], 74, "oven energy at the ceiling")
    assert_money_equals(first_tier["pre_overhead_subtotal_cents"], 500000, "subtotal at the ceiling")
    assert dec(first_tier["overhead_rate_pct"]) == dec("18.00"), (
        "a subtotal of exactly 500000 is at-or-below the first tier's ceiling"
    )
    assert_money_equals(first_tier["overhead_cents"], 90000, "overhead at the ceiling")
    assert_money_equals(first_tier["total_cost_cents"], 590000, "total at the ceiling")

    second_tier = api.read_cost_summary(one_cent_over["id"], admin_headers)
    assert_money_equals(second_tier["material_cost_cents"], 499926, "material one cent over")
    assert_money_equals(second_tier["oven_energy_cost_cents"], 75, "oven energy one cent over")
    assert_money_equals(second_tier["pre_overhead_subtotal_cents"], 500001, "subtotal one cent over")
    assert dec(second_tier["overhead_rate_pct"]) == dec("14.50"), "the second tier's rate"
    # round_half_up(500001 * 14.50 / 100) = round_half_up(72500.145) = 72500.
    assert_money_equals(second_tier["overhead_cents"], 72500, "overhead one cent over")
    assert_money_equals(second_tier["total_cost_cents"], 572501, "total one cent over")
    assert second_tier["total_cost_cents"] < first_tier["total_cost_cents"], (
        "one more cent of subtotal lowers the total, because the chosen rate applies to "
        "the whole subtotal and is not applied marginally per tier"
    )

    top_tier = api.read_cost_summary(top_band["id"], admin_headers)
    # round_half_up(50.000 * 19997) = 999850 exactly, twice.
    assert_money_equals(top_tier["material_cost_cents"], 1999700, "material in the top band")
    assert_money_equals(top_tier["oven_energy_cost_cents"], 301, "oven energy in the top band")
    assert_money_equals(top_tier["pre_overhead_subtotal_cents"], 2000001, "subtotal in the top band")
    assert dec(top_tier["overhead_rate_pct"]) == dec("11.00"), "the top rate"
    # round_half_up(2000001 * 11.00 / 100) = round_half_up(220000.11) = 220000.
    assert_money_equals(top_tier["overhead_cents"], 220000, "overhead in the top band")
    assert_money_equals(top_tier["total_cost_cents"], 2220001, "total in the top band")

    for label, summary in (
        ("at the ceiling", first_tier),
        ("one cent over", second_tier),
        ("in the top band", top_tier),
    ):
        assert summary["completed_qty"] == 0, f"{label}: no hull has been inspected"
        assert _p5_unit_cost_absent(summary["unit_cost_cents"]), (
            f"{label}: with completed_qty 0 there is no unit cost, got "
            f"{summary['unit_cost_cents']!r}"
        )
