"""Site footprint propagation and the deterministic hull serial.

PRD.md section 3.7 makes a warehouse's posture a pure function of its rounded
utilisation, and makes a single store propagate that posture outward to the orders
merely targeting the site — then makes release-storage run the same propagation
backwards inside one request. PRD.md section 3.5 mints hull serials from the order's
own unit count, so an aborted cycle burns no sequence number.
"""

from test_helpers import (
    DEFAULT_ZONE_CODE,
    ApiErrorId,
    abort_payload,
    advance_unit_to_sellable,
    assert_at_most_scale,
    assert_footprint_summary_consistent,
    assert_hull_serial_format,
    assert_posture_for_utilization,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    dec,
    get_success_data,
    release_storage_payload,
    reserve_charge,
    run_cycle_to_demold,
    schedule_cycle,
    store_payload,
    store_unit,
    validate_error,
    validate_paginated,
    warehouse_version,
    zone,
)


def _p5_exact(actual, expected, places, label):
    """Assert a derived decimal is stored at its declared scale and exact value."""
    assert_at_most_scale(actual, places, label)
    assert dec(actual) == dec(expected), f"{label}: expected {expected}, got {actual!r}"


def _p5_charge_cycle(ctx, cycle, lot, **charge_overrides):
    """Attach one reserved charge to ``cycle`` and make it the context's cycle."""
    ctx["molding_cycle"] = cycle
    ctx["molding_cycle_id"] = cycle["id"]
    return reserve_charge(ctx, cycle, lot, **charge_overrides)


def _p5_zone_row(summary, zone_code):
    """Pick one zone row out of a footprint projection."""
    matches = [row for row in summary["zones"] if row["zone_code"] == zone_code]
    assert len(matches) == 1, (
        f"expected exactly one {zone_code} row, got {[r['zone_code'] for r in summary['zones']]}"
    )
    return matches[0]


def _p5_serials(api, headers, **filters):
    """Every hull serial matching a finished-unit filter, sorted for a stable compare.

    PRD.md section 3.5 does not pin the list's own ordering, so the serials are
    compared as a sorted sequence rather than in returned order.
    """
    rows, _meta = validate_paginated(api.list_finished_units(filters, headers))
    return sorted(row["hull_serial"] for row in rows)


def test_one_store_freezes_the_site_and_release_storage_reverses_the_propagation(
    api, admin_headers, planner_headers
):
    """A 10.0000 cube hull into a 10.0000 cube site reads 100.00 percent FROZEN, then 0.00 NORMAL.

    PRD.md section 3.7 derives the posture from the rounded utilisation only:
    "`utilization_pct` is recomputed as `committed_cube_m3` divided by
    `footprint_capacity_cube_m3` times 100, rounded to two decimals, and `posture` is
    re-derived from it", and "`posture` is `FROZEN` when `utilization_pct` is at or
    above `frozen_threshold_pct`, `RESTRICTED` when it is at or above
    `restricted_threshold_pct` but below the frozen threshold, and `NORMAL`
    otherwise."  The same section scopes the outward propagation: "a site that has
    reached `frozen_threshold_pct` sends its orders in `READY_TO_SCHEDULE` and
    `IN_PRODUCTION` that target it to `BLOCKED_WAREHOUSE` with `blocked_reason`
    `WAREHOUSE_FROZEN`" — so the COMPLETE order that produced the freezing hull is
    outside the swept set.  Opening the nest group is the expensive variant: "Opening a
    **new nest group** — no eligible zone anchors this model — charges the full
    `gross_cube_m3` and sets `is_zone_anchor` true."  The reversal is one request:
    release-storage's "(3) The site's `committed_cube_m3`, `utilization_pct` and
    `posture` are recomputed. (4) A site that has left `FROZEN` returns its orders in
    `BLOCKED_WAREHOUSE` to `READY_TO_SCHEDULE`, subject to those orders having at least
    one qualified lot."  PRD.md section 2.10 makes the projection a fixed point rather
    than a stepping stone: "Nothing is cached across requests."

    Design: Corner/calculations/calc_constraint_propagation_store_freezes_site_then_release_restores_it
    """
    ctx = create_plant_baseline(
        model_overrides={"gross_cube_m3": 10.0, "nest_factor": 0.5},
        warehouse_overrides={
            "footprint_capacity_cube_m3": 10.0,
            "zones": [zone(DEFAULT_ZONE_CODE, 10.0)],
        },
    )
    warehouse_id = ctx["warehouse_id"]
    lot = create_resin_lot()
    producing = create_production_order(ctx, ordered_qty=2)
    bystander = create_production_order(ctx, ordered_qty=1)
    assert bystander["status"] == "READY_TO_SCHEDULE", (
        f"the bystander order starts on the floor, got {bystander['status']}"
    )

    cycle = schedule_cycle(ctx, producing)
    _p5_charge_cycle(ctx, cycle, lot)
    run_cycle_to_demold(ctx)
    first, second = [advance_unit_to_sellable(ctx, hull) for hull in ctx["finished_units"]]

    complete = api.read_entity("get_production_order", producing["id"], admin_headers)
    assert complete["status"] == "COMPLETE", (
        f"both hulls passed, so the producing order is COMPLETE, got {complete['status']}"
    )

    stored = store_unit(ctx, first)
    _p5_exact(stored["stored_footprint_cube_m3"], "10.0000", 4, "anchor footprint")
    assert stored["is_zone_anchor"] is True, (
        "opening a new nest group charges the full gross cube, not the nested 5.0000, "
        f"got is_zone_anchor {stored['is_zone_anchor']!r}"
    )

    site = api.read_entity("get_warehouse", warehouse_id, planner_headers)
    _p5_exact(site["committed_cube_m3"], "10.0000", 4, "committed cube")
    # 10.0000 / 10.0000 * 100 = 100.00, and 100.00 >= the 95.00 frozen threshold.
    _p5_exact(site["utilization_pct"], "100.00", 2, "utilization")
    assert site["posture"] == "FROZEN", f"expected FROZEN, got {site['posture']}"
    assert_posture_for_utilization(
        site["posture"],
        site["utilization_pct"],
        site["restricted_threshold_pct"],
        site["frozen_threshold_pct"],
    )

    frozen_summary = api.read_footprint_summary(warehouse_id, planner_headers)
    again = api.read_footprint_summary(warehouse_id, planner_headers)
    assert frozen_summary == again, (
        "the projection is recomputed from scratch on each read and nothing is cached, "
        "so two consecutive reads of an unchanged site are identical"
    )
    assert_footprint_summary_consistent(frozen_summary)
    _p5_exact(frozen_summary["committed_cube_m3"], "10.0000", 4, "summary committed cube")
    _p5_exact(frozen_summary["utilization_pct"], "100.00", 2, "summary utilization")
    assert frozen_summary["posture"] == "FROZEN", (
        f"the projection reports the same posture, got {frozen_summary['posture']}"
    )
    frozen_zone = _p5_zone_row(frozen_summary, DEFAULT_ZONE_CODE)
    _p5_exact(frozen_zone["committed_cube_m3"], "10.0000", 4, "zone committed cube")
    _p5_exact(frozen_zone["remaining_cube_m3"], "0.0000", 4, "zone remaining cube")

    blocked = api.read_entity("get_production_order", bystander["id"], admin_headers)
    assert blocked["status"] == "BLOCKED_WAREHOUSE", (
        "an order that merely targets the site is swept by the freezing store, got "
        f"{blocked['status']}"
    )
    assert blocked["blocked_reason"] == "WAREHOUSE_FROZEN", (
        f"expected WAREHOUSE_FROZEN, got {blocked['blocked_reason']!r}"
    )
    untouched = api.read_entity("get_production_order", producing["id"], admin_headers)
    assert untouched["status"] == "COMPLETE", (
        "only READY_TO_SCHEDULE and IN_PRODUCTION orders are swept, so the order that "
        f"produced the freezing hull is untouched, got {untouched['status']}"
    )
    assert untouched["blocked_reason"] is None, (
        f"a COMPLETE order carries no blocked_reason, got {untouched['blocked_reason']!r}"
    )

    # The sibling would nest at round(10.0000 * 0.5000, 4) = 5.0000 and still not fit,
    # but the frozen-site gate is evaluated first and is the failure reported.
    validate_error(
        api.store_finished_unit(
            second["id"],
            store_payload(warehouse_version(warehouse_id)),
            planner_headers,
        ),
        ApiErrorId.WAREHOUSE_FROZEN,
    )

    released = get_success_data(
        api.release_storage(
            first["id"],
            release_storage_payload("site frozen in error, hull pulled back to the line"),
            planner_headers,
        )
    )
    assert released["logistics_status"] == "UNALLOCATED", (
        f"expected UNALLOCATED, got {released['logistics_status']}"
    )
    _p5_exact(released["stored_footprint_cube_m3"], "0.0000", 4, "released footprint")

    # The sibling was never admitted, so the group has no follower to promote and the
    # committed cube really does fall by the departing hull's full 10.0000.
    thawed_summary = api.read_footprint_summary(warehouse_id, planner_headers)
    assert_footprint_summary_consistent(thawed_summary)
    _p5_exact(thawed_summary["committed_cube_m3"], "0.0000", 4, "committed cube after release")
    _p5_exact(thawed_summary["utilization_pct"], "0.00", 2, "utilization after release")
    assert thawed_summary["posture"] == "NORMAL", (
        f"expected NORMAL, got {thawed_summary['posture']}"
    )
    thawed_zone = _p5_zone_row(thawed_summary, DEFAULT_ZONE_CODE)
    _p5_exact(thawed_zone["committed_cube_m3"], "0.0000", 4, "zone committed after release")
    _p5_exact(thawed_zone["remaining_cube_m3"], "10.0000", 4, "zone remaining after release")

    unblocked = api.read_entity("get_production_order", bystander["id"], admin_headers)
    assert unblocked["status"] == "READY_TO_SCHEDULE", (
        "the release ran the propagation backwards inside its own request, got "
        f"{unblocked['status']}"
    )
    assert unblocked["blocked_reason"] is None, (
        f"blocked_reason is cleared, got {unblocked['blocked_reason']!r}"
    )


def test_hull_serial_build_seq_counts_units_not_cycles_across_an_abort(
    api, admin_headers
):
    """Two demoulds astride one abort read 0001, 0002, then 0003 and 0004 — never 0005.

    PRD.md section 3.5: "**Hull serial assignment** is deterministic and uses no random
    value. `build_seq` is 1 plus the number of hulls already created for the producing
    order, counted across all of its cycles. For each `cavity_index` from 1 to the
    tool's `cavity_count`, in ascending order, one hull is created with `hull_serial`
    formed as the order's `order_code`, a hyphen, `cavity_index` zero-padded to two
    digits, a hyphen, and `build_seq` plus `cavity_index` minus 1 zero-padded to four
    digits."  Because the count is over hulls and not over cycles, the same section's
    abort rule burns no number: "No hull is ever created by an abort."  The same section
    also fixes the discovery channel: "Because there is no creation endpoint for hulls,
    the filtered hull list is their only discovery channel."

    Design: Corner/calculations/calc_chronological_hull_serial_build_seq_across_cycles
    """
    order_code = "PO-P5CVK"
    ctx = create_plant_baseline()
    lot = create_resin_lot()
    order = create_production_order(ctx, order_code=order_code, ordered_qty=6)
    assert order["order_code"] == order_code, (
        f"the serial is built from the order code, got {order['order_code']!r}"
    )

    first_cycle = schedule_cycle(ctx, order)
    _p5_charge_cycle(ctx, first_cycle, lot)
    run_cycle_to_demold(ctx)

    # build_seq = 1 + 0 already-created hulls, so cavity 1 takes 1 + 1 - 1 = 1 and
    # cavity 2 takes 1 + 2 - 1 = 2. The cavity index appears twice in each serial:
    # once padded to two digits and once folded into the four-digit sequence.
    first_batch = _p5_serials(api, admin_headers, molding_cycle_id=first_cycle["id"])
    assert first_batch == [f"{order_code}-01-0001", f"{order_code}-02-0002"], (
        f"expected the first two serials, got {first_batch}"
    )
    assert_hull_serial_format(first_batch[0], order_code, 1)
    assert_hull_serial_format(first_batch[1], order_code, 2)

    aborted_cycle = schedule_cycle(ctx, order, oven_start_at="2026-08-01T11:00:00Z")
    aborted_charge = _p5_charge_cycle(ctx, aborted_cycle, lot)
    aborted = get_success_data(
        api.abort_molding_cycle(
            aborted_cycle["id"], abort_payload("OPERATOR_ABORT"), ctx["operator_headers"]
        )
    )
    assert aborted["status"] == "ABORTED", f"expected ABORTED, got {aborted['status']}"
    released = api.read_entity("get_resin_charge", aborted_charge["id"], admin_headers)
    assert released["status"] == "RELEASED", (
        f"the aborted cycle's charge is released, got {released['status']}"
    )
    assert _p5_serials(api, admin_headers, molding_cycle_id=aborted_cycle["id"]) == [], (
        "an aborted cycle mints no hull, so it consumes no sequence number"
    )

    third_cycle = schedule_cycle(ctx, order, oven_start_at="2026-08-01T13:00:00Z")
    _p5_charge_cycle(ctx, third_cycle, lot)
    run_cycle_to_demold(
        ctx,
        actual_oven_start_at="2026-08-01T13:00:00Z",
        actual_oven_end_at="2026-08-01T14:00:00Z",
        actual_cooling_end_at="2026-08-01T14:35:00Z",
    )

    # Only two hulls exist for the order, so build_seq is 3 rather than 5: counting
    # attempted cycles, or advancing a stored counter on the abort, would emit
    # 0005 and 0006 here.
    third_batch = _p5_serials(api, admin_headers, molding_cycle_id=third_cycle["id"])
    assert third_batch == [f"{order_code}-01-0003", f"{order_code}-02-0004"], (
        f"expected 0003 and 0004 after the abort, got {third_batch}"
    )
    assert_hull_serial_format(third_batch[0], order_code, 1)
    assert_hull_serial_format(third_batch[1], order_code, 2)

    every = _p5_serials(api, admin_headers, product_model_id=ctx["product_model_id"])
    assert every == [
        f"{order_code}-01-0001",
        f"{order_code}-01-0003",
        f"{order_code}-02-0002",
        f"{order_code}-02-0004",
    ], f"the four serials run without duplicate or gap, got {every}"
    assert len(set(every)) == 4, f"every serial is globally unique, got {every}"
    for serial in every:
        assert ctx["product_model_id"] not in serial, (
            "no server identifier appears in a serial, so the four values are "
            f"reproducible by replaying the same three cycles, got {serial!r}"
        )
