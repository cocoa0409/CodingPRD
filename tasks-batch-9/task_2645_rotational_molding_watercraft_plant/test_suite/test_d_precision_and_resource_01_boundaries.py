"""Exact-boundary behaviour on three different measurement axes.

Every threshold this module probes is stated in PRD.md with an explicit
comparison direction, so the value sitting exactly on the boundary and its
nearest representable neighbour are both pinned:

* the blended regrind ceiling of PRD.md section 3.2, a mass ratio at two
  decimals compared with strictly-greater;
* the frozen posture threshold of PRD.md section 3.7, a cube utilisation
  percentage at two decimals compared with at-or-above on the rounded value;
* the minimum inspection measurement count of PRD.md section 3.6, a
  collection cardinality compared with at-least.
"""

from decimal import Decimal

from test_helpers import (
    PASSING_WALL_THICKNESS_POINTS,
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    Q_WARPAGE,
    advance_unit_to_outfitted,
    api_client,
    assert_decimal_equals,
    assert_footprint_summary_consistent,
    assert_posture_for_utilization,
    assert_resin_ledger_conserved,
    assert_wall_statistics,
    get_success_data,
    resin_lot_version,
    schedule_cycle,
    setup_cycle_with_spare_order,
    setup_demolded_units,
    setup_scheduled_cycle,
    setup_sellable_units,
    store_unit,
    validate_error,
    zone,
)

# One single-cavity mould whose shot mass is the whole 24.000 kg charge, so a
# charge of exactly the default shot mass is inside tolerance and the order's
# overbuild allowance of one hull is never exceeded.
_P2_SINGLE_CAVITY = {
    "model_overrides": {"nominal_charge_kg": 24.0},
    "mold_overrides": {"cavity_count": 1},
    "order_overrides": {"ordered_qty": 1},
}

# A site sized so that one 2.0000 cube anchor hull lands on a raw utilisation of
# 94.99833... percent, which rounds half-up to exactly 95.00.
_P2_KNIFE_EDGE_CAPACITY = 2.1053


def _p2_site(frozen_threshold_pct: float) -> dict:
    """Warehouse overrides for the knife-edge site, varying only the threshold."""
    return {
        "footprint_capacity_cube_m3": _P2_KNIFE_EDGE_CAPACITY,
        "zones": [zone("Z-A", _P2_KNIFE_EDGE_CAPACITY)],
        "restricted_threshold_pct": 85.0,
        "frozen_threshold_pct": frozen_threshold_pct,
    }


def _p2_charge(ctx: dict, cycle: dict, lot: dict, regrind_kg: float):
    """POST one 24.000 kg charge carrying ``regrind_kg`` of regrind."""
    return api_client.create_resin_charge(
        {
            "molding_cycle_id": cycle["id"],
            "resin_lot_id": lot["id"],
            "charge_kg": 24.0,
            "regrind_kg": regrind_kg,
            "expected_resin_lot_version": resin_lot_version(lot["id"]),
        },
        ctx["resin_tech_headers"],
    )


def test_regrind_blend_exactly_at_the_model_ceiling_is_accepted():
    """A 30.00 percent blend against a 30.00 ceiling reserves normally.

    PRD.md section 3.2: "A percentage strictly greater than the model's
    `max_regrind_pct` is refused with `ERR_REGRIND_LIMIT_EXCEEDED` (HTTP 422);
    a blend landing at exactly the ceiling - 30.00 against a default ceiling of
    30.00 - is accepted, and 30.01 is not."

    PRD.md section 3.2 also fixes what the accepted row carries: "`virgin_kg` is
    `charge_kg` minus `regrind_kg` rounded to three decimals, and
    `charge_regrind_pct` is `regrind_kg` divided by `charge_kg` times 100
    rounded to two decimals."

    Design: Difficulty/boundary_precision_check/regrind_ceiling_exact_30_00_pct_accepted_vs_30_01_rejected
    """
    ctx = setup_scheduled_cycle(charge=False, **_P2_SINGLE_CAVITY)
    lot = ctx["resin_lot"]
    cycle = ctx["molding_cycle"]

    charge = get_success_data(_p2_charge(ctx, cycle, lot, 7.2))

    assert_decimal_equals(
        charge["charge_regrind_pct"], Decimal("30.00"), Q_PERCENT, "charge_regrind_pct"
    )
    assert_decimal_equals(charge["virgin_kg"], Decimal("16.800"), Q_MASS, "virgin_kg")
    assert charge["status"] == "RESERVED"

    refreshed = api_client.read_entity(
        "get_molding_cycle", cycle["id"], ctx["operator_headers"]
    )
    assert_decimal_equals(
        refreshed["cycle_regrind_pct"], Decimal("30.00"), Q_PERCENT, "cycle_regrind_pct"
    )
    assert_decimal_equals(
        refreshed["charged_mass_kg"], Decimal("24.000"), Q_MASS, "charged_mass_kg"
    )

    stored_lot = api_client.read_entity(
        "get_resin_lot", lot["id"], ctx["resin_tech_headers"]
    )
    assert_resin_ledger_conserved(stored_lot)
    assert_decimal_equals(
        stored_lot["reserved_kg"], Decimal("24.000"), Q_MASS, "reserved_kg"
    )
    assert stored_lot["status"] == "AVAILABLE"


def test_regrind_blend_one_hundredth_above_the_ceiling_is_refused_and_writes_nothing():
    """A 30.01 percent blend is refused and leaves no trace on the lot.

    PRD.md section 3.2: "A percentage strictly greater than the model's
    `max_regrind_pct` is refused with `ERR_REGRIND_LIMIT_EXCEEDED` (HTTP 422);
    a blend landing at exactly the ceiling - 30.00 against a default ceiling of
    30.00 - is accepted, and 30.01 is not."

    PRD.md section 3.2 also states the write-nothing guarantee: "A refused
    charge writes nothing: no row, no mass movement, no version increment."

    Design: Difficulty/boundary_precision_check/regrind_ceiling_exact_30_00_pct_accepted_vs_30_01_rejected
    """
    ctx = setup_scheduled_cycle(charge=False, **_P2_SINGLE_CAVITY)
    lot = ctx["resin_lot"]
    cycle = ctx["molding_cycle"]
    version_before = resin_lot_version(lot["id"])

    # 7.202 / 24.000 * 100 == 30.00833..., which rounds half-up to 30.01.
    validate_error(
        _p2_charge(ctx, cycle, lot, 7.202),
        ApiErrorId.REGRIND_LIMIT_EXCEEDED,
        422,
    )

    stored_lot = api_client.read_entity(
        "get_resin_lot", lot["id"], ctx["resin_tech_headers"]
    )
    assert stored_lot["version"] == version_before, (
        "a refused charge must not advance the lot version"
    )
    assert_decimal_equals(
        stored_lot["available_kg"], Decimal("500.000"), Q_MASS, "available_kg"
    )
    assert_decimal_equals(
        stored_lot["reserved_kg"], Decimal("0.000"), Q_MASS, "reserved_kg"
    )
    assert_resin_ledger_conserved(stored_lot)

    rows = api_client.list_resin_charges(
        {"molding_cycle_id": cycle["id"], "limit": 100}, ctx["resin_tech_headers"]
    ).json()["data"]
    assert rows == [], "a refused charge must not write a row"

    refreshed = api_client.read_entity(
        "get_molding_cycle", cycle["id"], ctx["operator_headers"]
    )
    assert_decimal_equals(
        refreshed["charged_mass_kg"], Decimal("0.000"), Q_MASS, "charged_mass_kg"
    )


def test_regrind_pct_is_rounded_half_up_to_two_decimals_before_the_ceiling_test():
    """7.201 kg of regrind in 24.000 kg rounds to 30.00 and is admitted.

    PRD.md section 3.2 fixes the scale the ceiling test reads: "the cycle's
    regrind percentage is then `total_regrind_kg` divided by `total_charge_kg`
    times 100, rounded to two decimals" and "`charge_regrind_pct` is
    `regrind_kg` divided by `charge_kg` times 100 rounded to two decimals".

    PRD.md section 2.4 fixes the mode: "Unless a calculation says otherwise,
    rounding is half-up at the stated number of decimal places, and every
    intermediate result that a later step reads is rounded before that step
    runs."

    So 7.201 / 24.000 * 100 == 30.0041666... becomes 30.00, which is not
    strictly greater than the 30.00 ceiling, and both charges reserve. PRD.md
    section 3.2: "The lot's `available_kg` falls and its `reserved_kg` rises by
    `charge_kg`, preserving the invariant that the rounded sum of
    `available_kg`, `reserved_kg` and `consumed_kg` equals `received_kg`".

    Design: Difficulty/boundary_precision_check/regrind_ceiling_exact_30_00_pct_accepted_vs_30_01_rejected
    """
    ctx = setup_cycle_with_spare_order(charge=False, **_P2_SINGLE_CAVITY)
    lot = ctx["resin_lot"]
    first = ctx["molding_cycle"]
    second = schedule_cycle(
        ctx,
        ctx["spare_production_order"],
        oven_start_at="2026-08-01T12:00:00Z",
    )

    charge_one = get_success_data(_p2_charge(ctx, first, lot, 7.201))
    assert_decimal_equals(
        charge_one["charge_regrind_pct"],
        Decimal("30.00"),
        Q_PERCENT,
        "charge_regrind_pct",
    )
    assert_decimal_equals(
        charge_one["virgin_kg"], Decimal("16.799"), Q_MASS, "virgin_kg"
    )

    charge_two = get_success_data(_p2_charge(ctx, second, lot, 7.2))
    assert_decimal_equals(
        charge_two["charge_regrind_pct"],
        Decimal("30.00"),
        Q_PERCENT,
        "charge_regrind_pct",
    )

    for cycle_id in (first["id"], second["id"]):
        refreshed = api_client.read_entity(
            "get_molding_cycle", cycle_id, ctx["operator_headers"]
        )
        assert_decimal_equals(
            refreshed["cycle_regrind_pct"],
            Decimal("30.00"),
            Q_PERCENT,
            "cycle_regrind_pct",
        )

    stored_lot = api_client.read_entity(
        "get_resin_lot", lot["id"], ctx["resin_tech_headers"]
    )
    assert_decimal_equals(
        stored_lot["available_kg"], Decimal("452.000"), Q_MASS, "available_kg"
    )
    assert_decimal_equals(
        stored_lot["reserved_kg"], Decimal("48.000"), Q_MASS, "reserved_kg"
    )
    assert_decimal_equals(
        stored_lot["consumed_kg"], Decimal("0.000"), Q_MASS, "consumed_kg"
    )
    assert stored_lot["status"] == "AVAILABLE"
    assert_resin_ledger_conserved(stored_lot)


def test_utilization_rounding_up_to_exactly_the_frozen_threshold_freezes_the_site():
    """A raw 94.998 percent rounds to 95.00 and the at-or-above test freezes.

    PRD.md section 3.7: "`posture` is `FROZEN` when `utilization_pct` is at or
    above `frozen_threshold_pct`, `RESTRICTED` when it is at or above
    `restricted_threshold_pct` but below the frozen threshold, and `NORMAL`
    otherwise. Both comparisons are at-or-above and both read the **rounded**
    `utilization_pct`, so at exactly 85.00 a default site is `RESTRICTED`, at
    exactly 95.00 it is `FROZEN`, 84.99 is `NORMAL`, 94.99 is `RESTRICTED`, and
    a raw utilisation of 94.995 rounds to 95.00 and freezes the site."

    PRD.md section 3.7 fixes the inputs too: the candidate footprint is "simply
    `gross_cube_m3` rounded to four decimals when none does" have an anchor, and
    CASCADE-H recomputes "`utilization_pct` ... as `committed_cube_m3` divided
    by `footprint_capacity_cube_m3` times 100, rounded to two decimals".

    Design: Difficulty/boundary_precision_check/warehouse_frozen_threshold_rounded_95_00_freezes_vs_95_01_threshold
    """
    ctx = setup_sellable_units(
        unit_count=1,
        warehouse_overrides=_p2_site(95.0),
        **_P2_SINGLE_CAVITY,
    )
    before = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], ctx["planner_headers"]
    )

    stored = store_unit(ctx, ctx["sellable_units"][0])

    assert_decimal_equals(
        stored["stored_footprint_cube_m3"],
        Decimal("2.0000"),
        Q_CUBE,
        "stored_footprint_cube_m3",
    )
    assert stored["is_zone_anchor"] is True
    assert stored["storage_zone_code"] == "Z-A"

    site = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], ctx["planner_headers"]
    )
    assert_decimal_equals(
        site["committed_cube_m3"], Decimal("2.0000"), Q_CUBE, "committed_cube_m3"
    )
    assert_decimal_equals(
        site["utilization_pct"], Decimal("95.00"), Q_PERCENT, "utilization_pct"
    )
    assert site["posture"] == "FROZEN"
    assert_posture_for_utilization(
        site["posture"],
        site["utilization_pct"],
        site["restricted_threshold_pct"],
        site["frozen_threshold_pct"],
    )
    assert site["version"] == before["version"] + 1

    summary = api_client.read_footprint_summary(
        ctx["warehouse_id"], ctx["planner_headers"]
    )
    assert_footprint_summary_consistent(summary)
    assert_decimal_equals(
        summary["remaining_cube_m3"], Decimal("0.1053"), Q_CUBE, "remaining_cube_m3"
    )
    assert_decimal_equals(
        summary["zones"][0]["remaining_cube_m3"],
        Decimal("0.1053"),
        Q_CUBE,
        "zone remaining_cube_m3",
    )
    assert summary["zones"][0]["stored_unit_count"] == 1
    # The producing order is already COMPLETE, so link 4 of the storage cascade
    # finds no READY_TO_SCHEDULE or IN_PRODUCTION order to block.
    assert summary["blocked_production_order_count"] == 0


def test_utilization_one_hundredth_below_the_frozen_threshold_stops_at_restricted():
    """The same 95.00 utilisation against a 95.01 threshold only restricts.

    PRD.md section 3.7: "`posture` is `FROZEN` when `utilization_pct` is at or
    above `frozen_threshold_pct`, `RESTRICTED` when it is at or above
    `restricted_threshold_pct` but below the frozen threshold, and `NORMAL`
    otherwise."

    PRD.md section 2.8 declares the threshold's own scale - `frozen_threshold_pct`
    is "strictly greater than `restricted_threshold_pct` and at most 100.00, two
    decimals, default 95.00, compared with at-or-above" - so 95.01 is the
    smallest representable step above 95.00 and the site is left `RESTRICTED`.

    Design: Difficulty/boundary_precision_check/warehouse_frozen_threshold_rounded_95_00_freezes_vs_95_01_threshold
    """
    ctx = setup_sellable_units(
        unit_count=1,
        warehouse_overrides=_p2_site(95.01),
        **_P2_SINGLE_CAVITY,
    )
    before = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], ctx["planner_headers"]
    )

    stored = store_unit(ctx, ctx["sellable_units"][0])
    assert_decimal_equals(
        stored["stored_footprint_cube_m3"],
        Decimal("2.0000"),
        Q_CUBE,
        "stored_footprint_cube_m3",
    )
    assert stored["is_zone_anchor"] is True

    site = api_client.read_entity(
        "get_warehouse", ctx["warehouse_id"], ctx["planner_headers"]
    )
    assert_decimal_equals(
        site["committed_cube_m3"], Decimal("2.0000"), Q_CUBE, "committed_cube_m3"
    )
    assert_decimal_equals(
        site["utilization_pct"], Decimal("95.00"), Q_PERCENT, "utilization_pct"
    )
    assert site["posture"] == "RESTRICTED"
    assert site["version"] == before["version"] + 1

    summary = api_client.read_footprint_summary(
        ctx["warehouse_id"], ctx["planner_headers"]
    )
    assert summary["posture"] == "RESTRICTED"
    assert_footprint_summary_consistent(summary)


def test_inspection_with_five_measurement_points_is_refused_and_writes_nothing():
    """Five wall readings fall one short of the minimum cardinality.

    PRD.md section 3.6: "Inspection requires `build_status` `OUTFITTED` (a first
    inspection) or `SELLABLE` (a re-inspection), requires `logistics_status`
    `UNALLOCATED`, requires both the `WALL_GAUGE` and `IMPACT_RIG`
    certifications, and requires at least six numeric measurements each strictly
    greater than 0.000 in `wall_thickness_points`, otherwise
    `ERR_INSUFFICIENT_MEASUREMENTS` (HTTP 422)."

    Because the hull carries "`inspection_verdict` (default `PENDING`, ...)" and
    "`build_status` (default `DEMOLDED`, ...)" per PRD.md section 2.8, a refused
    inspection must leave both axes and the version exactly where they were.

    Design: Difficulty/boundary_precision_check/inspection_measurement_count_six_accepted_vs_five_rejected
    """
    ctx = setup_demolded_units(**_P2_SINGLE_CAVITY)
    unit = advance_unit_to_outfitted(ctx, ctx["finished_units"][0])
    assert unit["build_status"] == "OUTFITTED"
    version_before = unit["version"]

    validate_error(
        api_client.inspect_finished_unit(
            unit["id"],
            {
                "wall_thickness_points": [5.9, 6.0, 6.1, 5.95, 6.05],
                "impact_test_joules": 120.0,
                "cosmetic_defect_grade": "A",
            },
            ctx["inspector_headers"],
        ),
        ApiErrorId.INSUFFICIENT_MEASUREMENTS,
        422,
    )

    after = api_client.read_entity(
        "get_finished_unit", unit["id"], ctx["inspector_headers"]
    )
    assert after["version"] == version_before, (
        "a refused inspection must not advance the hull version"
    )
    assert after["build_status"] == "OUTFITTED"
    assert after["inspection_verdict"] == "PENDING"
    assert after["mean_wall_thickness_mm"] is None
    assert after["wall_sd_mm"] is None
    assert after["wall_cv_pct"] is None
    assert after["min_wall_thickness_mm"] is None


def test_inspection_with_exactly_six_measurement_points_is_accepted_and_passes():
    """Six wall readings meet the minimum exactly and drive the verdict ladder.

    PRD.md section 3.6: "requires at least six numeric measurements each strictly
    greater than 0.000 in `wall_thickness_points`, otherwise
    `ERR_INSUFFICIENT_MEASUREMENTS` (HTTP 422)" - so six is admitted.

    PRD.md section 3.6 then fixes the statistics: "`mean_wall_thickness_mm` is
    the sum of the points divided by `n`, rounded to three decimals and stored.
    `wall_sd_mm` is then the population standard deviation taken **about that
    already-rounded mean** ... `wall_cv_pct` is then `wall_sd_mm` divided by
    `mean_wall_thickness_mm` times 100, rounded to two decimals, computed from
    the two already-rounded values ... `min_wall_thickness_mm` is the smallest
    supplied point rounded to three decimals."

    Every clause of the ladder in PRD.md section 3.6 fails to match, so
    "(8) Otherwise the verdict is `PASS`", and PRD.md section 3.3 rolls the
    order up: "When the completion roll-up finds `completed_qty` at or above
    `ordered_qty` while the order is `IN_PRODUCTION`, the order moves to
    `COMPLETE`".

    Design: Difficulty/boundary_precision_check/inspection_measurement_count_six_accepted_vs_five_rejected
    """
    ctx = setup_demolded_units(**_P2_SINGLE_CAVITY)
    unit = advance_unit_to_outfitted(ctx, ctx["finished_units"][0])
    points = list(PASSING_WALL_THICKNESS_POINTS)
    assert len(points) == 6

    inspected = get_success_data(
        api_client.inspect_finished_unit(
            unit["id"],
            {
                "wall_thickness_points": points,
                "impact_test_joules": 120.0,
                "cosmetic_defect_grade": "A",
            },
            ctx["inspector_headers"],
        )
    )

    assert_wall_statistics(inspected, points)
    assert_decimal_equals(
        inspected["mean_wall_thickness_mm"],
        Decimal("6.000"),
        Q_MASS,
        "mean_wall_thickness_mm",
    )
    assert_decimal_equals(
        inspected["wall_sd_mm"], Decimal("0.065"), Q_MASS, "wall_sd_mm"
    )
    assert_decimal_equals(
        inspected["wall_cv_pct"], Decimal("1.08"), Q_PERCENT, "wall_cv_pct"
    )
    assert_decimal_equals(
        inspected["min_wall_thickness_mm"],
        Decimal("5.900"),
        Q_MASS,
        "min_wall_thickness_mm",
    )
    assert_decimal_equals(
        inspected["final_warpage_index"],
        Decimal("0.000"),
        Q_WARPAGE,
        "final_warpage_index",
    )
    assert inspected["inspection_verdict"] == "PASS"
    assert inspected["build_status"] == "SELLABLE"
    assert inspected["logistics_status"] == "UNALLOCATED"

    order = api_client.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["planner_headers"]
    )
    assert order["completed_qty"] == 1
    assert order["status"] == "COMPLETE"
