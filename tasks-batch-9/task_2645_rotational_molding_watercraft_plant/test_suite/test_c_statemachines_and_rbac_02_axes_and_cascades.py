"""Cyclic loops, parallel axes, guarded edges, roll-ups and cascades.

PRD.md section 3.1 lets a tool go round the service loop as often as it needs
to; PRD.md sections 3.6 and 3.7 give a hull two independent axes on one row;
PRD.md sections 3.3, 3.4, 3.5, 3.8 and 3.9 hang guards, roll-ups and cascades
off those machines. Each test below quotes the sentences it is checking.
"""

from test_helpers import (
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    assert_decimal_equals,
    assert_instant_equals,
    assert_money_equals,
    assert_null_fields,
    assert_resin_ledger_conserved,
    assert_warranty_reserve_conserved,
    complete_service_payload,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    create_shipment,
    demold_payload,
    enter_cooling_payload,
    get_success_data,
    inspect_payload,
    list_units_for_cycle,
    mark_down_payload,
    mold_payload,
    molding_cycle_payload,
    outfit_payload,
    production_order_version,
    release_storage_payload,
    remove_line_payload,
    reserve_charge,
    return_to_queue_payload,
    run_cycle_to_demold,
    scrap_payload,
    service_hold_payload,
    set_clock,
    setup_scheduled_cycle,
    setup_submitted_claim,
    shipment_line_payload,
    shipment_payload,
    shipment_version,
    start_oven_payload,
    storage_review_payload,
    store_payload,
    trim_payload,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
    waive_storage_finding_payload,
    warehouse_payload,
    warehouse_version,
    zone,
)

SINGLE_CAVITY_MODEL = {"nominal_charge_kg": 24.0}
SINGLE_CAVITY_MOLD = {"cavity_count": 1, "nominal_charge_kg": 24.0}


def test_mold_service_round_trip_repeats_and_resets_the_counter_each_lap(api):
    """AVAILABLE to MAINTENANCE and back is traversable repeatedly, resetting the counter.

    PRD.md section 3.1: "From `AVAILABLE`, a service hold moves the tool to
    `MAINTENANCE`; the request may carry a `hold_note`."
    PRD.md section 3.1: "Completing service requires `status` `MAINTENANCE`, may
    carry a `service_note`, resets `cycles_since_service` to zero — a full
    reset, never a decrement by the interval, so a serviced tool with a hundred
    lifetime demoulds reads 0 — and returns `status` to `AVAILABLE`, restoring
    the tool to the selection pool."
    PRD.md section 3.4: "The candidate pool is every tool whose
    `product_model_id` equals the order's, whose `status` is exactly
    `AVAILABLE` — `MAINTENANCE`, `IN_CYCLE` and `RETIRED` tools are excluded
    before ranking"
    PRD.md section 3.4: "otherwise — no available tool at all, or an
    `exclude_mold_ids` list that emptied the pool — it fails with
    `ERR_NO_ELIGIBLE_MOLD` (HTTP 409)."
    PRD.md section 3.5: "The tool moves `IN_CYCLE` to `AVAILABLE` and its
    `cycles_since_service` is incremented by 1 — only a completed demould wears
    a tool; an abort never does."
    PRD.md section 3.4: "The first ranked candidate is written to `mold_id` and
    returned in the response so the choice is observable."

    Design: Corner/state_machines/sm_cyclic_mold_service_round_trip_repeats_and_resets_the_counter_to_zero_each_lap
    """
    ctx = setup_scheduled_cycle(
        model_overrides=SINGLE_CAVITY_MODEL,
        mold_overrides=dict(SINGLE_CAVITY_MOLD, service_interval_cycles=5),
        order_overrides={"ordered_qty": 2},
        lot_overrides={"received_kg": 500.0},
        charge_overrides={"charge_kg": 24.0},
    )
    run_cycle_to_demold(ctx)
    mold_id = ctx["mold_id"]

    worn = api.read_entity("get_mold", mold_id, ctx["admin_headers"])
    assert worn["status"] == "AVAILABLE", "a demould with room left returns the tool"
    assert worn["cycles_since_service"] == 1, "one completed demould wore the tool once"
    assert worn["version"] == 3, (
        "one bump each for create, the oven lock and the demould; scheduling a "
        "cycle does not touch the tool"
    )

    held = validate_success(
        api.service_hold_mold(
            mold_id, service_hold_payload("first scheduled tool clean"), ctx["admin_headers"]
        )
    )
    assert held["status"] == "MAINTENANCE", "a service hold moves the tool to MAINTENANCE"
    assert held["cycles_since_service"] == 1, "a hold does not reset the counter"
    assert held["version"] == 4, "the hold is one more persisted mutation"

    booking = molding_cycle_payload(
        ctx["production_order_id"],
        ctx["oven_station_id"],
        ctx["cooling_bay_id"],
        production_order_version(ctx["production_order_id"]),
        arm_index=2,
        oven_start_at="2026-08-01T13:00:00Z",
    )
    validate_error(
        api.create_molding_cycle(booking, ctx["operator_headers"]),
        ApiErrorId.NO_ELIGIBLE_MOLD,
    )

    serviced = validate_success(
        api.complete_service_mold(
            mold_id,
            complete_service_payload("cavity polished, vents cleared"),
            ctx["admin_headers"],
        )
    )
    assert serviced["status"] == "AVAILABLE", "completing service restores the tool"
    assert serviced["cycles_since_service"] == 0, (
        "completing service is a full reset to zero, never a decrement"
    )
    assert serviced["version"] == 5, "the completion is one more persisted mutation"

    second = validate_success(
        api.create_molding_cycle(booking, ctx["operator_headers"]), 201
    )
    assert second["mold_id"] == mold_id, (
        "the identical payload refused a moment ago now selects the serviced tool"
    )
    reserve_charge(ctx, second, ctx["resin_lot"], charge_kg=24.0)

    set_clock("2026-08-01T13:00:00Z")
    get_success_data(
        api.start_oven(
            second["id"],
            {"actual_oven_start_at": "2026-08-01T13:00:00Z"},
            ctx["operator_headers"],
        )
    )
    set_clock("2026-08-01T14:00:00Z")
    get_success_data(
        api.enter_cooling(
            second["id"],
            enter_cooling_payload("2026-08-01T14:00:00Z"),
            ctx["operator_headers"],
        )
    )
    set_clock("2026-08-01T14:35:00Z")
    get_success_data(
        api.demold(
            second["id"],
            demold_payload("2026-08-01T14:35:00Z"),
            ctx["operator_headers"],
        )
    )

    relapped = api.read_entity("get_mold", mold_id, ctx["admin_headers"])
    assert relapped["status"] == "AVAILABLE", "the second demould also returns the tool"
    assert relapped["cycles_since_service"] == 1, (
        "the counter restarted from zero and counted exactly one new part"
    )
    assert relapped["version"] == 7, "one bump each for the second lock and demould"

    held_again = validate_success(
        api.service_hold_mold(
            mold_id,
            service_hold_payload("second scheduled tool clean"),
            ctx["admin_headers"],
        )
    )
    assert held_again["status"] == "MAINTENANCE", "the loop is entered a second time"
    assert held_again["version"] == 8, "the second hold is one more mutation"
    serviced_again = validate_success(
        api.complete_service_mold(
            mold_id, complete_service_payload("second service complete"), ctx["admin_headers"]
        )
    )
    assert serviced_again["status"] == "AVAILABLE", "and left a second time"
    assert serviced_again["cycles_since_service"] == 0, "with a second full reset"
    assert serviced_again["version"] == 9, "the second completion is one more mutation"

    order_row = api.read_entity(
        "get_production_order", ctx["production_order_id"], ctx["admin_headers"]
    )
    assert order_row["status"] == "IN_PRODUCTION", "both cycles were admitted"

    lot_row = api.read_entity("get_resin_lot", ctx["resin_lot_id"], ctx["admin_headers"])
    assert_decimal_equals(lot_row["available_kg"], "452.000", Q_MASS, "available_kg")
    assert_decimal_equals(lot_row["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
    assert_decimal_equals(lot_row["consumed_kg"], "48.000", Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(lot_row)


def test_unit_build_axis_advances_while_the_logistics_axis_holds_then_reverses(api):
    """The two hull axes move independently, and the logistics axis is reversible.

    PRD.md section 3.6: "A hull carries two independent state axes on one row:
    `build_status`, which the shop floor drives, and `logistics_status`, which
    the warehouse and trailer workflows drive."
    PRD.md section 3.6: "Both operations additionally require
    `logistics_status` `UNALLOCATED`; a hull that has been stored, loaded,
    shipped or delivered can no longer be trimmed, outfitted, re-inspected or
    scrapped, and the attempt is refused with `ERR_UNIT_NOT_REINSPECTABLE`
    (HTTP 409)."
    PRD.md section 3.7: "Storing writes `logistics_status` `STORED`, copies
    `warehouse_id` and `demand_bucket_id` from the producing order, stamps
    `stored_at` from the logical clock, and writes `storage_zone_code`,
    `stored_footprint_cube_m3` and `is_zone_anchor`"
    PRD.md section 3.7: "Loading moves a hull `STORED` to `LOADED` and —
    importantly — **does not move its warehouse footprint**: a loaded hull
    still occupies its zone until the trailer departs."
    PRD.md section 3.8: "Removing a line or cancelling a trailer moves the hull
    `LOADED` back to `STORED`, again with no footprint movement, because it
    never left the zone."
    PRD.md section 3.7: "**Releasing storage** requires `logistics_status`
    `STORED` and a `release_reason`, and is the head of **CASCADE-C**: (1) the
    hull moves `STORED` to `UNALLOCATED`, its `warehouse_id`,
    `storage_zone_code`, `stored_at` and `demand_bucket_id` are cleared,
    `stored_footprint_cube_m3` returns to 0.0000 and `is_zone_anchor` to false"

    Design: Corner/state_machines/sm_parallel_axes_unit_build_advances_while_logistics_holds_then_reverses
    """
    ctx = setup_scheduled_cycle(
        model_overrides=SINGLE_CAVITY_MODEL,
        mold_overrides=SINGLE_CAVITY_MOLD,
        warehouse_overrides={
            "footprint_capacity_cube_m3": 40.0,
            "zones": [zone("ZN-A", 40.0)],
        },
        order_overrides={"ordered_qty": 1},
        charge_overrides={"charge_kg": 24.0},
    )
    run_cycle_to_demold(ctx)
    unit_id = ctx["finished_unit_ids"][0]
    warehouse_id = ctx["warehouse_id"]

    trimmed = validate_success(
        api.trim_finished_unit(unit_id, trim_payload(0.5), ctx["assembly_headers"])
    )
    assert trimmed["build_status"] == "TRIMMED", "the build axis advanced"
    assert trimmed["logistics_status"] == "UNALLOCATED", (
        "the logistics axis is untouched by a build edge"
    )

    outfitted = validate_success(
        api.outfit_finished_unit(
            unit_id, outfit_payload("HK-PARALLEL-1"), ctx["assembly_headers"]
        )
    )
    assert outfitted["build_status"] == "OUTFITTED", "the build axis advanced again"
    assert outfitted["logistics_status"] == "UNALLOCATED", "still unallocated"
    assert outfitted["outfitted_by_technician_id"] == ctx["assembly_technician_id"], (
        "outfitting stamps the acting assembly technician"
    )

    inspected = validate_success(
        api.inspect_finished_unit(unit_id, inspect_payload(), ctx["inspector_headers"])
    )
    assert inspected["build_status"] == "SELLABLE", "a passing inspection makes it sellable"
    assert inspected["inspection_verdict"] == "PASS", "the verdict is PASS"
    assert inspected["logistics_status"] == "UNALLOCATED", (
        "three build edges have not moved the logistics axis once"
    )

    stored = validate_success(
        api.store_finished_unit(
            unit_id, store_payload(warehouse_version(warehouse_id)), ctx["planner_headers"]
        )
    )
    assert stored["logistics_status"] == "STORED", "now the logistics axis moves"
    assert stored["build_status"] == "SELLABLE", "and the build axis stands still"
    assert stored["warehouse_id"] == warehouse_id, "storing copies the producing warehouse"
    assert stored["storage_zone_code"] == "ZN-A", "the only zone is selected"
    assert_decimal_equals(
        stored["stored_footprint_cube_m3"], "2.0000", Q_CUBE, "stored_footprint_cube_m3"
    )
    assert stored["is_zone_anchor"] is True, "the first hull of its model opens the nest group"
    assert_instant_equals(stored["stored_at"], "2026-08-01T10:35:00Z", "stored_at")

    validate_error(
        api.inspect_finished_unit(unit_id, inspect_payload(), ctx["inspector_headers"]),
        ApiErrorId.UNIT_NOT_REINSPECTABLE,
    )

    shipment = create_shipment(
        ctx, trailer_cube_capacity_m3=3.0, trailer_max_payload_kg=100.0
    )
    line = validate_success(
        api.create_shipment_line(
            shipment_line_payload(
                shipment["id"], unit_id, shipment_version(shipment["id"])
            ),
            ctx["planner_headers"],
        ),
        201,
    )
    assert line["status"] == "LOADED", "a new line starts LOADED"
    assert line["nest_position"] == 1, "the only hull of its model takes position 1"
    assert_decimal_equals(line["line_gross_cube_m3"], "2.0000", Q_CUBE, "line_gross_cube_m3")
    assert_decimal_equals(
        line["line_nested_cube_m3"], "2.0000", Q_CUBE, "line_nested_cube_m3"
    )

    loaded_unit = api.read_entity("get_finished_unit", unit_id, ctx["admin_headers"])
    assert loaded_unit["logistics_status"] == "LOADED", "loading moved the logistics axis"
    assert loaded_unit["build_status"] == "SELLABLE", "the build axis is still SELLABLE"
    assert_decimal_equals(
        loaded_unit["stored_footprint_cube_m3"],
        "2.0000",
        Q_CUBE,
        "stored_footprint_cube_m3 after loading",
    )
    loading_shipment = api.read_entity("get_shipment", shipment["id"], ctx["admin_headers"])
    assert loading_shipment["status"] == "LOADING", (
        "the first accepted line moves the trailer from PLANNED to LOADING"
    )
    assert_decimal_equals(
        loading_shipment["cube_utilization_pct"], "66.67", Q_PERCENT, "cube_utilization_pct"
    )
    assert_decimal_equals(
        loading_shipment["loaded_weight_kg"], "24.000", Q_MASS, "loaded_weight_kg"
    )

    removed = validate_success(
        api.remove_shipment_line(line["id"], remove_line_payload(), ctx["planner_headers"])
    )
    assert removed["status"] == "REMOVED", "the line is retired"
    unloaded = api.read_entity("get_finished_unit", unit_id, ctx["admin_headers"])
    assert unloaded["logistics_status"] == "STORED", (
        "removing the line reverses the logistics axis back to STORED"
    )
    assert unloaded["build_status"] == "SELLABLE", "the build axis never moved"
    assert_decimal_equals(
        unloaded["stored_footprint_cube_m3"],
        "2.0000",
        Q_CUBE,
        "stored_footprint_cube_m3 after unloading",
    )
    emptied = api.read_entity("get_shipment", shipment["id"], ctx["admin_headers"])
    assert emptied["status"] == "PLANNED", (
        "removing the last LOADED line returns the trailer to PLANNED"
    )
    assert_decimal_equals(emptied["loaded_cube_m3"], "0.0000", Q_CUBE, "loaded_cube_m3")
    assert_decimal_equals(emptied["nested_cube_m3"], "0.0000", Q_CUBE, "nested_cube_m3")
    assert_decimal_equals(
        emptied["cube_utilization_pct"], "0.00", Q_PERCENT, "cube_utilization_pct"
    )
    assert emptied["version"] == 3, "one bump for the creation, the line and the removal"
    assert emptied["quoted_freight_cents"] is None, "an unsealed trailer is never priced"

    validate_error(
        api.remove_shipment_line(line["id"], remove_line_payload(), ctx["planner_headers"]),
        ApiErrorId.SHIPMENT_LINE_ALREADY_REMOVED,
    )

    released = validate_success(
        api.release_storage(unit_id, release_storage_payload(), ctx["planner_headers"])
    )
    assert released["logistics_status"] == "UNALLOCATED", (
        "releasing storage returns the logistics axis to its initial state"
    )
    assert released["build_status"] == "SELLABLE", (
        "a full logistics round trip leaves the build axis exactly where it was"
    )
    assert released["warehouse_id"] is None, "the warehouse pointer is cleared"
    assert released["storage_zone_code"] is None, "the zone is cleared"
    assert released["stored_at"] is None, "the storage stamp is cleared"
    assert_decimal_equals(
        released["stored_footprint_cube_m3"], "0.0000", Q_CUBE, "stored_footprint_cube_m3"
    )
    assert released["is_zone_anchor"] is False, "the anchor flag is cleared"

    reinspected = validate_success(
        api.inspect_finished_unit(unit_id, inspect_payload(), ctx["inspector_headers"])
    )
    assert reinspected["inspection_verdict"] == "PASS", (
        "the identical inspection refused while STORED is accepted once UNALLOCATED"
    )
    assert reinspected["build_status"] == "SELLABLE", "and keeps the hull sellable"
    assert reinspected["version"] == 9, (
        "trim, outfit, inspect, store, load, unload, release and re-inspect are "
        "eight persisted mutations after the demould cascade minted the row"
    )

    warehouse_row = api.read_entity("get_warehouse", warehouse_id, ctx["admin_headers"])
    assert_decimal_equals(
        warehouse_row["committed_cube_m3"],
        "0.0000",
        Q_CUBE,
        "committed_cube_m3",
    )
    assert_decimal_equals(
        warehouse_row["utilization_pct"], "0.00", Q_PERCENT, "utilization_pct"
    )
    assert warehouse_row["posture"] == "NORMAL", "an empty site is NORMAL"
    assert warehouse_row["version"] == 3, "one bump for the creation, the store and the release"


def test_cycle_create_and_enter_cooling_are_guarded_by_their_resource_pool(api):
    """Booking and entering cooling are blocked while the relevant pool is DOWN.

    PRD.md section 3.4: "The station's `status` must be `OPERATIONAL`, otherwise
    `ERR_OVEN_STATION_DOWN`; the bay's `status` must be `OPERATIONAL`, otherwise
    `ERR_COOLING_BAY_DOWN`."
    PRD.md section 3.4: "A refused booking writes nothing at all — no cycle row,
    no order version bump."
    PRD.md section 3.5: "**Entering cooling** supplies `actual_oven_end_at`,
    requires the bay's `status` to still be `OPERATIONAL`
    (`ERR_COOLING_BAY_DOWN`)"
    PRD.md section 3.5: "The cycle moves `OVEN_RUNNING` to `COOLING`,
    `actual_oven_end_at` is recorded from the logical clock, and
    `actual_oven_minutes` is recomputed as the floored whole minutes between
    `actual_oven_start_at` and `actual_oven_end_at`."
    PRD.md section 3.1: "Taking a cooling bay down works the same way and also
    requires a `down_reason`: `SCHEDULED` cycles booked into that bay become
    `ABORTED` with `abort_reason` `BAY_DOWN`, their `RESERVED` charges are
    released, revived lots unblock resin-blocked orders, and cycles already
    `OVEN_RUNNING` or `COOLING` are left alone."

    Design: Corner/state_machines/sm_guarded_cycle_create_and_enter_cooling_blocked_while_their_resource_pool_is_down
    """
    ctx = create_plant_baseline(
        model_overrides=SINGLE_CAVITY_MODEL, mold_overrides=SINGLE_CAVITY_MOLD
    )
    ctx["resin_lot"] = create_resin_lot()
    ctx["resin_lot_id"] = ctx["resin_lot"]["id"]
    order = create_production_order(ctx, ordered_qty=1)
    ctx["production_order"] = order
    ctx["production_order_id"] = order["id"]
    station_id = ctx["oven_station_id"]
    bay_id = ctx["cooling_bay_id"]

    validate_success(
        api.mark_down_oven_station(
            station_id, mark_down_payload("burner interlock fault"), ctx["admin_headers"]
        )
    )
    validate_success(
        api.mark_down_cooling_bay(
            bay_id, mark_down_payload("chiller pump seized"), ctx["admin_headers"]
        )
    )

    booking = molding_cycle_payload(
        order["id"], station_id, bay_id, production_order_version(order["id"])
    )
    validate_error(
        api.create_molding_cycle(booking, ctx["operator_headers"]),
        ApiErrorId.OVEN_STATION_DOWN,
    )

    validate_success(api.restore_oven_station(station_id, ctx["admin_headers"]))
    validate_error(
        api.create_molding_cycle(booking, ctx["operator_headers"]),
        ApiErrorId.COOLING_BAY_DOWN,
    )

    validate_success(api.restore_cooling_bay(bay_id, ctx["admin_headers"]))
    cycle = validate_success(
        api.create_molding_cycle(booking, ctx["operator_headers"]), 201
    )
    assert cycle["status"] == "SCHEDULED", "the booking is admitted once both pools are up"
    assert cycle["mold_id"] == ctx["mold_id"], "the only eligible tool is selected"

    reserve_charge(ctx, cycle, ctx["resin_lot"], charge_kg=24.0)
    set_clock("2026-08-01T09:00:00Z")
    validate_success(
        api.start_oven(
            cycle["id"], start_oven_payload("2026-08-01T09:00:00Z"), ctx["operator_headers"]
        )
    )

    validate_success(
        api.mark_down_cooling_bay(
            bay_id, mark_down_payload("chiller pump seized again"), ctx["admin_headers"]
        )
    )
    spared = api.read_entity("get_molding_cycle", cycle["id"], ctx["admin_headers"])
    assert spared["status"] == "OVEN_RUNNING", (
        "the bay cascade aborts only SCHEDULED cycles; the heat is already in the part"
    )
    assert spared["abort_reason"] is None, "so no abort reason is written"

    set_clock("2026-08-01T10:00:00Z")
    validate_error(
        api.enter_cooling(
            cycle["id"],
            enter_cooling_payload("2026-08-01T10:00:00Z"),
            ctx["operator_headers"],
        ),
        ApiErrorId.COOLING_BAY_DOWN,
    )
    blocked = api.read_entity("get_molding_cycle", cycle["id"], ctx["admin_headers"])
    assert blocked["status"] == "OVEN_RUNNING", "the refusal left the cycle in the oven"
    assert blocked["actual_oven_end_at"] is None, "and stamped nothing"

    validate_success(api.restore_cooling_bay(bay_id, ctx["admin_headers"]))
    cooled = validate_success(
        api.enter_cooling(
            cycle["id"],
            enter_cooling_payload("2026-08-01T10:00:00Z"),
            ctx["operator_headers"],
        )
    )
    assert cooled["status"] == "COOLING", "the same call is accepted once the bay is up"
    assert_instant_equals(
        cooled["actual_oven_end_at"], "2026-08-01T10:00:00Z", "actual_oven_end_at"
    )
    assert cooled["actual_oven_minutes"] == 60, "the floored whole minutes in the oven"
    assert cooled["version"] == 4, (
        "the booking, the charge rollup, the oven start and the cooling entry; the "
        "refused calls added nothing"
    )

    station_row = api.read_entity("get_oven_station", station_id, ctx["admin_headers"])
    assert station_row["status"] == "OPERATIONAL", "the station ended up restored"
    assert station_row["version"] == 3, "creation, one mark-down and one restore"
    bay_row = api.read_entity("get_cooling_bay", bay_id, ctx["admin_headers"])
    assert bay_row["status"] == "OPERATIONAL", "the bay ended up restored"
    assert bay_row["version"] == 5, "creation, two mark-downs and two restores"

    aborted, meta = validate_paginated(
        api.list_molding_cycles(
            {"cooling_bay_id": bay_id, "status": "ABORTED"}, ctx["admin_headers"]
        )
    )
    assert meta["total_count"] == 0, (
        "neither bay outage aborted anything, because no cycle was SCHEDULED on it "
        "while the bay was down"
    )
    assert aborted == [], "and the page is empty"


def test_a_shipment_line_requires_a_stored_hull_at_the_trailers_own_site(api):
    """The line guard checks the logistics axis first and the origin site second.

    PRD.md section 3.8: "The shipment must be in `PLANNED` or `LOADING`
    (`ERR_SHIPMENT_INVALID_STATE`), the hull's `build_status` must be `SELLABLE`
    (`ERR_UNIT_INVALID_BUILD_STATE`) and its `logistics_status` must be `STORED`
    (`ERR_UNIT_INVALID_LOGISTICS_STATE`), and the hull's `warehouse_id` must
    equal the shipment's `origin_warehouse_id`, otherwise
    `ERR_WAREHOUSE_MISMATCH` (HTTP 422) — a trailer cannot pick from two sites."
    PRD.md section 3.8: "The accepted line records `shipment_id`,
    `finished_unit_id`, `nest_position`, `line_gross_cube_m3`,
    `line_nested_cube_m3` and `line_freight_cents`, and starts in `LOADED`; the
    hull moves `STORED` to `LOADED` with no footprint movement."
    PRD.md section 3.5: "For each `cavity_index` from 1 to the tool's
    `cavity_count`, in ascending order, one hull is created with `hull_serial`
    formed as the order's `order_code`, a hyphen, `cavity_index` zero-padded to
    two digits, a hyphen, and `build_seq` plus `cavity_index` minus 1
    zero-padded to four digits."

    Design: Corner/state_machines/sm_guarded_shipment_line_requires_a_stored_hull_at_the_trailers_own_origin_site
    """
    ctx = setup_scheduled_cycle(order_overrides={"ordered_qty": 2})
    run_cycle_to_demold(ctx)
    units = list_units_for_cycle(ctx["molding_cycle_id"])
    assert [u["cavity_index"] for u in units] == [1, 2], (
        "one two-cavity tool demoulds one hull per cavity position"
    )
    order_code = ctx["production_order"]["order_code"]
    assert units[0]["hull_serial"] == f"{order_code}-01-0001", (
        "cavity 1 takes build_seq 1 + 1 - 1 == 1"
    )
    assert units[1]["hull_serial"] == f"{order_code}-02-0002", (
        "cavity 2 takes build_seq 1 + 2 - 1 == 2"
    )

    for unit in units:
        validate_success(
            api.trim_finished_unit(unit["id"], trim_payload(), ctx["assembly_headers"])
        )
        validate_success(
            api.outfit_finished_unit(unit["id"], outfit_payload(), ctx["assembly_headers"])
        )
        sellable = validate_success(
            api.inspect_finished_unit(
                unit["id"], inspect_payload(), ctx["inspector_headers"]
            )
        )
        assert sellable["build_status"] == "SELLABLE", "both hulls are sellable"

    warehouse_a = ctx["warehouse_id"]
    warehouse_b = get_success_data(
        api.create_warehouse(warehouse_payload(), ctx["admin_headers"]), 201
    )
    stored_unit = validate_success(
        api.store_finished_unit(
            units[0]["id"],
            store_payload(warehouse_version(warehouse_a)),
            ctx["planner_headers"],
        )
    )
    assert stored_unit["logistics_status"] == "STORED", "only the first hull is stored"
    assert stored_unit["warehouse_id"] == warehouse_a, "and it is stored at site A"

    shipment_a = get_success_data(
        api.create_shipment(shipment_payload(warehouse_a), ctx["planner_headers"]), 201
    )
    shipment_b = get_success_data(
        api.create_shipment(shipment_payload(warehouse_b["id"]), ctx["planner_headers"]),
        201,
    )

    validate_error(
        api.create_shipment_line(
            shipment_line_payload(
                shipment_b["id"], units[0]["id"], shipment_version(shipment_b["id"])
            ),
            ctx["planner_headers"],
        ),
        ApiErrorId.WAREHOUSE_MISMATCH,
    )
    validate_error(
        api.create_shipment_line(
            shipment_line_payload(
                shipment_b["id"], units[1]["id"], shipment_version(shipment_b["id"])
            ),
            ctx["planner_headers"],
        ),
        ApiErrorId.UNIT_INVALID_LOGISTICS_STATE,
    )

    line = validate_success(
        api.create_shipment_line(
            shipment_line_payload(
                shipment_a["id"], units[0]["id"], shipment_version(shipment_a["id"])
            ),
            ctx["planner_headers"],
        ),
        201,
    )
    assert line["status"] == "LOADED", "the line onto the hull's own site is admitted"
    assert line["nest_position"] == 1, "it is the first hull of its model on the trailer"
    assert_decimal_equals(line["line_gross_cube_m3"], "2.0000", Q_CUBE, "line_gross_cube_m3")
    assert_decimal_equals(
        line["line_nested_cube_m3"], "2.0000", Q_CUBE, "line_nested_cube_m3"
    )

    untouched = api.read_entity("get_shipment", shipment_b["id"], ctx["admin_headers"])
    assert untouched["status"] == "PLANNED", "two refusals left the wrong-site trailer alone"
    assert_decimal_equals(untouched["loaded_cube_m3"], "0.0000", Q_CUBE, "loaded_cube_m3")
    assert_decimal_equals(
        untouched["cube_utilization_pct"], "0.00", Q_PERCENT, "cube_utilization_pct"
    )
    assert untouched["version"] == 1, "a refused load bumps no version"

    loaded = api.read_entity("get_finished_unit", units[0]["id"], ctx["admin_headers"])
    assert loaded["logistics_status"] == "LOADED", "the stored hull is now loaded"
    assert loaded["build_status"] == "SELLABLE", "the build axis is untouched"
    assert loaded["warehouse_id"] == warehouse_a, "loading did not move it out of site A"
    assert_decimal_equals(
        loaded["stored_footprint_cube_m3"], "2.0000", Q_CUBE, "stored_footprint_cube_m3"
    )

    idle = api.read_entity("get_finished_unit", units[1]["id"], ctx["admin_headers"])
    assert idle["logistics_status"] == "UNALLOCATED", "the never-stored hull is unallocated"
    assert idle["warehouse_id"] is None, "with no site"
    assert_decimal_equals(
        idle["stored_footprint_cube_m3"], "0.0000", Q_CUBE, "stored_footprint_cube_m3"
    )
    assert idle["version"] == 4, (
        "the demould minted it, then trim, outfit and inspect; the refused load added nothing"
    )


TWO_CAVITY_MODEL = {"nominal_charge_kg": 24.0}
TWO_CAVITY_MOLD = {"cavity_count": 2, "nominal_charge_kg": 48.0}
FULL_CHARGE = {"charge_kg": 48.0, "regrind_kg": 4.8}


def _p4_two_sellable_children(api):
    """One order, one two-cavity cycle, both hulls demoulded, trimmed and outfitted."""
    ctx = setup_scheduled_cycle(
        model_overrides=TWO_CAVITY_MODEL,
        mold_overrides=TWO_CAVITY_MOLD,
        order_overrides={"ordered_qty": 2},
        charge_overrides=FULL_CHARGE,
    )
    run_cycle_to_demold(ctx)
    units = list_units_for_cycle(ctx["molding_cycle_id"])
    for unit in units:
        validate_success(
            api.trim_finished_unit(unit["id"], trim_payload(), ctx["assembly_headers"])
        )
        validate_success(
            api.outfit_finished_unit(unit["id"], outfit_payload(), ctx["assembly_headers"])
        )
    return ctx, units


def test_the_order_reaches_complete_only_on_the_last_sellable_child(api):
    """The parent flips to COMPLETE only when the roll-up reaches ordered_qty.

    PRD.md section 3.3: "Over all hulls reached through the order's cycles,
    `completed_qty` counts hulls whose `build_status` is `SELLABLE` **or** whose
    `logistics_status` is one of `STORED`, `LOADED`, `IN_TRANSIT` or
    `DELIVERED`"
    PRD.md section 3.3: "`scrapped_qty` counts hulls whose `build_status` is
    `SCRAPPED`. Hulls in `DEMOLDED`, `TRIMMED`, `OUTFITTED` or `REWORK` count
    toward neither figure."
    PRD.md section 3.6: "The order's `completed_qty` and `scrapped_qty` are
    recomputed, the order may move `IN_PRODUCTION` to `COMPLETE`, and the
    order's cost roll-up and `unit_cost_cents` are recomputed. Both the hull's
    and the order's `version` advance by 1."
    PRD.md section 3.3: "Fifth, `unit_cost_cents` is the **floor** of
    `total_cost_cents` divided by `completed_qty` when `completed_qty` is at
    least 1, and null otherwise"
    PRD.md section 3.3: "**Order cost** is recomputed at oven start (when
    charges become consumed), at demould, and on every inspection that changes
    `completed_qty`."

    Design: Corner/state_machines/sm_bubble_up_order_reaches_complete_only_on_the_last_sellable_child
    """
    ctx, units = _p4_two_sellable_children(api)
    order_id = ctx["production_order_id"]

    booked = api.read_entity("get_production_order", order_id, ctx["admin_headers"])
    assert booked["status"] == "IN_PRODUCTION", "the accepted cycle put the order in production"
    assert booked["completed_qty"] == 0, "an OUTFITTED hull counts toward neither figure"
    assert booked["scrapped_qty"] == 0, "and nothing is scrapped"
    assert booked["unit_cost_cents"] is None, (
        "with completed_qty 0 the recompute at demould left the unit cost null"
    )
    assert_money_equals(booked["material_cost_cents"], 10080, "material_cost_cents")
    assert_money_equals(booked["oven_energy_cost_cents"], 6000, "oven_energy_cost_cents")
    assert_money_equals(booked["overhead_cents"], 2894, "overhead_cents")
    assert_money_equals(booked["total_cost_cents"], 18974, "total_cost_cents")

    first = validate_success(
        api.inspect_finished_unit(units[0]["id"], inspect_payload(), ctx["inspector_headers"])
    )
    assert first["build_status"] == "SELLABLE", "a PASS moves OUTFITTED to SELLABLE"
    assert first["inspection_verdict"] == "PASS", "and writes the verdict"

    halfway = api.read_entity("get_production_order", order_id, ctx["admin_headers"])
    assert halfway["status"] == "IN_PRODUCTION", (
        "one terminal child out of two bubbles nothing up"
    )
    assert halfway["completed_qty"] == 1, "the roll-up counts the one sellable hull"
    assert_money_equals(halfway["unit_cost_cents"], 18974, "unit_cost_cents")
    assert_money_equals(halfway["total_cost_cents"], 18974, "total_cost_cents unchanged")

    second = validate_success(
        api.inspect_finished_unit(units[1]["id"], inspect_payload(), ctx["inspector_headers"])
    )
    assert second["build_status"] == "SELLABLE", "the second hull is sellable too"

    complete = api.read_entity("get_production_order", order_id, ctx["admin_headers"])
    assert complete["status"] == "COMPLETE", (
        "the last sellable child takes completed_qty to ordered_qty"
    )
    assert complete["completed_qty"] == 2, "both hulls now count"
    assert complete["scrapped_qty"] == 0, "and none was scrapped along the way"
    assert_money_equals(complete["unit_cost_cents"], 9487, "unit_cost_cents")
    assert_money_equals(complete["material_cost_cents"], 10080, "material_cost_cents")
    assert_money_equals(complete["oven_energy_cost_cents"], 6000, "oven_energy_cost_cents")
    assert_money_equals(complete["overhead_cents"], 2894, "overhead_cents")
    assert_money_equals(complete["total_cost_cents"], 18974, "total_cost_cents")
    assert complete["version"] == 5, (
        "creation, release, the cycle booking and one bump per inspection; neither "
        "the oven start nor the demould advances the order's version"
    )


def test_a_complete_order_is_re_derived_downward_when_a_child_is_scrapped(api):
    """COMPLETE is not a latch: scrapping a counted child demotes the parent.

    PRD.md section 3.6: "It sets `build_status` to `SCRAPPED` — terminal — and
    `inspection_verdict` to `SCRAP`, recomputes the order's `scrapped_qty` and
    `completed_qty`, returns a `COMPLETE` order to `IN_PRODUCTION` when
    `completed_qty` falls below `ordered_qty`, and advances both the hull's and
    the order's `version` by 1."
    PRD.md section 3.3: "While the order is `IN_PRODUCTION` the unit cost moves
    with every passing verdict; once `COMPLETE` it stabilises, and a demotion
    back to `IN_PRODUCTION` recomputes it *upward*, because the same total is
    divided by a smaller `completed_qty`."
    PRD.md section 3.6: "Scrapping is legal from `build_status` `OUTFITTED`,
    `SELLABLE` or `REWORK`, requires `logistics_status` `UNALLOCATED`, and is
    subject to the same segregation-of-duties constraint."
    PRD.md section 3.3: "`scrapped_qty` counts hulls whose `build_status` is
    `SCRAPPED`."
    PRD.md section 2.10: "No derived value in this service is an independently
    maintained counter that can drift. Each is defined as an aggregate over a
    named row set with a named status filter, and each is recomputed from that
    set inside every request that could change it."

    Design: Corner/state_machines/sm_compound_order_status_is_re_derived_downward_when_a_completed_child_is_scrapped
    """
    ctx, units = _p4_two_sellable_children(api)
    order_id = ctx["production_order_id"]
    for unit in units:
        validate_success(
            api.inspect_finished_unit(unit["id"], inspect_payload(), ctx["inspector_headers"])
        )

    complete = api.read_entity("get_production_order", order_id, ctx["admin_headers"])
    assert complete["status"] == "COMPLETE", "both children passed, so the order completed"
    assert complete["completed_qty"] == 2, "both hulls counted"
    assert complete["scrapped_qty"] == 0, "nothing was scrapped yet"
    assert_money_equals(complete["total_cost_cents"], 18974, "total_cost_cents")
    assert_money_equals(complete["unit_cost_cents"], 9487, "unit_cost_cents while COMPLETE")

    scrapped = validate_success(
        api.scrap_finished_unit(
            units[1]["id"],
            scrap_payload("delamination found on the hull-deck seam after the fact"),
            ctx["inspector_headers"],
        )
    )
    assert scrapped["build_status"] == "SCRAPPED", "the hull is scrapped outright"
    assert scrapped["inspection_verdict"] == "SCRAP", "and the verdict records it"

    demoted = api.read_entity("get_production_order", order_id, ctx["admin_headers"])
    assert demoted["status"] == "IN_PRODUCTION", (
        "the parent returns to IN_PRODUCTION, so COMPLETE was never a latch"
    )
    assert demoted["completed_qty"] == 1, "only the surviving hull still counts"
    assert demoted["scrapped_qty"] == 1, "and the scrapped hull is counted separately"
    assert_money_equals(demoted["total_cost_cents"], 18974, "total_cost_cents unchanged")
    assert_money_equals(
        demoted["unit_cost_cents"], 18974, "unit_cost_cents recomputed upward"
    )
    assert_money_equals(demoted["material_cost_cents"], 10080, "material_cost_cents")
    assert_money_equals(demoted["oven_energy_cost_cents"], 6000, "oven_energy_cost_cents")

    again = validate_success(
        api.inspect_finished_unit(units[0]["id"], inspect_payload(), ctx["inspector_headers"])
    )
    assert again["inspection_verdict"] == "PASS", "the surviving hull passes again"
    assert again["build_status"] == "SELLABLE", "and stays sellable"

    rederived = api.read_entity("get_production_order", order_id, ctx["admin_headers"])
    assert rederived["status"] == "IN_PRODUCTION", (
        "the order cannot return to COMPLETE: 1 is below ordered_qty 2 and SCRAPPED "
        "is terminal on the build axis"
    )
    assert rederived["completed_qty"] == 1, (
        "the roll-up is a pure function of the children, not an accumulator"
    )
    assert rederived["scrapped_qty"] == 1, "recomputing it a second time changes nothing"
    assert_money_equals(rederived["unit_cost_cents"], 18974, "unit_cost_cents")
    assert rederived["version"] == 7, (
        "creation, release, the cycle booking, two inspections, the scrap and the "
        "re-inspection"
    )


def test_marking_a_station_down_aborts_the_scheduled_cycle_and_spares_the_running_one(api):
    """CASCADE-E reaches only the SCHEDULED child, and restore never resurrects it.

    PRD.md section 3.1: "Taking a station down requires a `down_reason` and is
    the head of **CASCADE-E**, whose five links run in this order: (1) the
    station's `status` moves `OPERATIONAL` to `DOWN`; (2) every cycle on the
    station in `SCHEDULED` becomes `ABORTED` with `abort_reason` `STATION_DOWN`;
    (3) their `RESERVED` charges become `RELEASED` with `released_reason`
    `STATION_DOWN`; (4) lots that regain mass move `DEPLETED` to `AVAILABLE`;
    and (5) orders in `BLOCKED_RESIN` that those lots now qualify for move to
    `READY_TO_SCHEDULE`, except that an order whose target site posture is
    `FROZEN` moves to `BLOCKED_WAREHOUSE` instead."
    PRD.md section 3.1: "Cycles already `OVEN_RUNNING` or `COOLING` are
    deliberately untouched — the heat is already in the part."
    PRD.md section 3.1: "Restoring takes no body, moves `DOWN` to
    `OPERATIONAL`, and does not resurrect a single aborted cycle."
    PRD.md section 3.4: "Ranking is total and deterministic: ascending
    `cycles_since_service`, then ascending `mold_code`."
    PRD.md section 3.2: "The **charge roll-ups** on a cycle read only charges in
    `RESERVED` or `CONSUMED`; a `RELEASED` charge drops out the instant it is
    released, which is why every release path recomputes them."
    PRD.md section 3.4: "Occupancy is evaluated only against cycles in
    `SCHEDULED`, `OVEN_RUNNING` or `COOLING`; `DEMOLDED` and `ABORTED` cycles
    never block a tool."

    Design: Corner/state_machines/sm_cascade_down_station_mark_down_aborts_the_scheduled_cycle_and_spares_the_running_one
    """
    ctx = create_plant_baseline(
        model_overrides=SINGLE_CAVITY_MODEL,
        mold_overrides=dict(SINGLE_CAVITY_MOLD, mold_code="MLD-P4-CSD-A"),
    )
    mold_a_id = ctx["mold_id"]
    mold_b = get_success_data(
        api.create_mold(
            mold_payload(
                ctx["product_model_id"], mold_code="MLD-P4-CSD-B", **SINGLE_CAVITY_MOLD
            ),
            ctx["admin_headers"],
        ),
        201,
    )
    lot = create_resin_lot()
    ctx["resin_lot"] = lot
    ctx["resin_lot_id"] = lot["id"]
    order = create_production_order(ctx, ordered_qty=3)
    ctx["production_order"] = order
    ctx["production_order_id"] = order["id"]
    station_id = ctx["oven_station_id"]

    cycle_a = get_success_data(
        api.create_molding_cycle(
            molding_cycle_payload(
                order["id"],
                station_id,
                ctx["cooling_bay_id"],
                production_order_version(order["id"]),
                arm_index=1,
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    cycle_b = get_success_data(
        api.create_molding_cycle(
            molding_cycle_payload(
                order["id"],
                station_id,
                ctx["cooling_bay_id"],
                production_order_version(order["id"]),
                arm_index=2,
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    assert cycle_a["mold_id"] == mold_a_id, (
        "equal service counters, so ascending mold_code picks MLD-P4-CSD-A first"
    )
    assert cycle_b["mold_id"] == mold_b["id"], (
        "the first tool is occupied over the identical mould span, so the second is used"
    )

    charge_a = reserve_charge(ctx, cycle_a, lot, charge_kg=24.0)
    charge_b = reserve_charge(ctx, cycle_b, lot, charge_kg=24.0)
    set_clock("2026-08-01T09:00:00Z")
    validate_success(
        api.start_oven(
            cycle_a["id"], start_oven_payload("2026-08-01T09:00:00Z"), ctx["operator_headers"]
        )
    )
    before = api.read_entity("get_resin_lot", lot["id"], ctx["admin_headers"])
    assert_decimal_equals(before["available_kg"], "452.000", Q_MASS, "available_kg")
    assert_decimal_equals(before["reserved_kg"], "24.000", Q_MASS, "reserved_kg")
    assert_decimal_equals(before["consumed_kg"], "24.000", Q_MASS, "consumed_kg")

    downed = validate_success(
        api.mark_down_oven_station(
            station_id, mark_down_payload("arm 2 gearbox seized mid-shift"), ctx["admin_headers"]
        )
    )
    assert downed["status"] == "DOWN", "the station is out of service"
    assert downed["version"] == 2, "creation then the mark-down"

    aborted = api.read_entity("get_molding_cycle", cycle_b["id"], ctx["admin_headers"])
    assert aborted["status"] == "ABORTED", "the SCHEDULED cycle on that station is aborted"
    assert aborted["abort_reason"] == "STATION_DOWN", (
        "the reason names the originating cascade, not an operator decision"
    )
    assert_decimal_equals(aborted["charged_mass_kg"], "0.000", Q_MASS, "charged_mass_kg")
    assert aborted["version"] == 3, "the booking, the charge roll-up and the cascade abort"

    running = api.read_entity("get_molding_cycle", cycle_a["id"], ctx["admin_headers"])
    assert running["status"] == "OVEN_RUNNING", "the running cycle is deliberately untouched"
    assert running["abort_reason"] is None, "so no abort reason is written"
    assert_instant_equals(
        running["actual_oven_start_at"], "2026-08-01T09:00:00Z", "actual_oven_start_at"
    )
    assert_decimal_equals(running["charged_mass_kg"], "24.000", Q_MASS, "charged_mass_kg")
    assert running["version"] == 3, (
        "the booking, the charge roll-up and the oven start; the cascade did not touch it"
    )

    released = api.read_entity("get_resin_charge", charge_b["id"], ctx["admin_headers"])
    assert released["status"] == "RELEASED", "the aborted cycle's reservation is refunded"
    assert released["released_reason"] == "STATION_DOWN", "with the cascade's own reason"
    assert released["version"] == 2, "creation then the cascade release"
    consumed = api.read_entity("get_resin_charge", charge_a["id"], ctx["admin_headers"])
    assert consumed["status"] == "CONSUMED", "consumption is irreversible"
    assert consumed["released_reason"] is None, "a station outage does not undo it"
    assert consumed["version"] == 2, "creation then the consumption at oven start"

    lot_after = api.read_entity("get_resin_lot", lot["id"], ctx["admin_headers"])
    assert_decimal_equals(lot_after["available_kg"], "476.000", Q_MASS, "available_kg")
    assert_decimal_equals(lot_after["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
    assert_decimal_equals(lot_after["consumed_kg"], "24.000", Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(lot_after)
    assert lot_after["status"] == "AVAILABLE", (
        "available_kg never reached 0.000, so link 4 had no DEPLETED lot to revive"
    )

    order_after = api.read_entity(
        "get_production_order", order["id"], ctx["admin_headers"]
    )
    assert order_after["status"] == "IN_PRODUCTION", "the order was never BLOCKED_RESIN"
    assert order_after["blocked_reason"] is None, "so link 5 is inert too"
    assert order_after["version"] == 4, "creation, release and the two bookings"

    spare_tool = api.read_entity("get_mold", mold_b["id"], ctx["admin_headers"])
    assert spare_tool["status"] == "AVAILABLE", (
        "only an oven start locks a tool, so the aborted cycle's tool was never IN_CYCLE"
    )
    assert spare_tool["cycles_since_service"] == 0, "and it never completed a demould"
    assert spare_tool["version"] == 1, "the abort had no mould state to reverse"

    restored = validate_success(api.restore_oven_station(station_id, ctx["admin_headers"]))
    assert restored["status"] == "OPERATIONAL", "the station comes back up"
    assert restored["version"] == 3, "creation, mark-down and restore"
    still_aborted = api.read_entity("get_molding_cycle", cycle_b["id"], ctx["admin_headers"])
    assert still_aborted["status"] == "ABORTED", "restore resurrects no aborted cycle"
    assert still_aborted["abort_reason"] == "STATION_DOWN", "and rewrites no reason"
    assert still_aborted["version"] == 3, "and writes nothing to it at all"

    replacement = get_success_data(
        api.create_molding_cycle(
            molding_cycle_payload(
                order["id"],
                station_id,
                ctx["cooling_bay_id"],
                production_order_version(order["id"]),
                arm_index=2,
                oven_start_at="2026-08-01T12:00:00Z",
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    assert replacement["mold_id"] == mold_b["id"], (
        "the first tool is still IN_CYCLE from the oven start, while the second is "
        "AVAILABLE and free over the new half-open span"
    )
    assert production_order_version(order["id"]) == 5, (
        "the replacement booking is the order's fifth persisted mutation"
    )


def test_a_clock_advance_expires_a_lot_only_strictly_after_expires_on(api):
    """CASCADE-G is conditional on a strict date comparison and on child status.

    PRD.md section 3.2: "When `PlantAdmin` sets `current_utc`, the service (1)
    stores the new instant, then (2) moves every lot whose `expires_on` is
    *strictly before* the new clock's calendar date to `EXPIRED` — a lot whose
    `expires_on` equals the new date is *not* expired; (3) every `RESERVED`
    charge on those lots becomes `RELEASED` with `released_reason`
    `LOT_EXPIRED`, returning `charge_kg` to `available_kg`; (4) every
    `SCHEDULED` cycle holding one of those charges becomes `ABORTED` with
    `abort_reason` `LOT_EXPIRED`; and (5) every order left with no qualified lot
    moves to `BLOCKED_RESIN` with `blocked_reason` `NO_QUALIFIED_RESIN_LOT`."
    PRD.md section 3.2: "The response reports `current_utc`, the constant
    `default_utc` of `2026-08-01T00:00:00Z`, and the four sweep counters
    `expired_resin_lot_count`, `released_resin_charge_count`,
    `aborted_molding_cycle_count` and `blocked_production_order_count`."
    PRD.md section 3.2: "A lot in `EXPIRED` is terminal for qualification
    purposes: nothing returns it to `AVAILABLE`."
    PRD.md section 3.4: "The order's `status` must be `READY_TO_SCHEDULE` or
    `IN_PRODUCTION`; a `DRAFT`, `BLOCKED_RESIN`, `BLOCKED_WAREHOUSE`, `COMPLETE`
    or `CANCELLED` order cannot take a new cycle and is refused with
    `ERR_ORDER_NOT_SCHEDULABLE` (HTTP 409)."
    PRD.md section 2.5: "Dates supplied as `YYYY-MM-DD` — a resin lot's
    `expires_on`, a demand bucket's `window_start_on` and `window_end_on` — are
    compared against the calendar date of the logical clock in UTC, never
    against its time of day."

    Design: Corner/state_machines/sm_conditional_cascade_clock_advance_expires_a_lot_only_strictly_after_expires_on
    """
    ctx = create_plant_baseline(
        model_overrides=SINGLE_CAVITY_MODEL, mold_overrides=SINGLE_CAVITY_MOLD
    )
    lot = create_resin_lot(expires_on="2026-08-05")
    ctx["resin_lot"] = lot
    ctx["resin_lot_id"] = lot["id"]
    order = create_production_order(ctx, ordered_qty=3)
    ctx["production_order"] = order
    ctx["production_order_id"] = order["id"]

    cycle_a = get_success_data(
        api.create_molding_cycle(
            molding_cycle_payload(
                order["id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(order["id"]),
                arm_index=1,
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    cycle_b = get_success_data(
        api.create_molding_cycle(
            molding_cycle_payload(
                order["id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(order["id"]),
                arm_index=2,
                oven_start_at="2026-08-10T09:00:00Z",
            ),
            ctx["operator_headers"],
        ),
        201,
    )
    charge_a = reserve_charge(ctx, cycle_a, lot, charge_kg=24.0)
    charge_b = reserve_charge(ctx, cycle_b, lot, charge_kg=24.0)
    set_clock("2026-08-01T09:00:00Z")
    validate_success(
        api.start_oven(
            cycle_a["id"], start_oven_payload("2026-08-01T09:00:00Z"), ctx["operator_headers"]
        )
    )

    before = api.read_entity("get_resin_lot", lot["id"], ctx["admin_headers"])
    assert_decimal_equals(before["available_kg"], "452.000", Q_MASS, "available_kg")
    assert_decimal_equals(before["reserved_kg"], "24.000", Q_MASS, "reserved_kg")
    assert_decimal_equals(before["consumed_kg"], "24.000", Q_MASS, "consumed_kg")
    assert before["status"] == "AVAILABLE", "the lot is usable before the sweep"

    on_boundary = set_clock("2026-08-05T00:00:00Z")
    assert_instant_equals(on_boundary["current_utc"], "2026-08-05T00:00:00Z", "current_utc")
    assert_instant_equals(on_boundary["default_utc"], "2026-08-01T00:00:00Z", "default_utc")
    assert on_boundary["expired_resin_lot_count"] == 0, (
        "the clock date equals expires_on, and equality does not expire"
    )
    assert on_boundary["released_resin_charge_count"] == 0, "so no charge is refunded"
    assert on_boundary["aborted_molding_cycle_count"] == 0, "no cycle is aborted"
    assert on_boundary["blocked_production_order_count"] == 0, "and no order is blocked"
    unexpired = api.read_entity("get_resin_lot", lot["id"], ctx["admin_headers"])
    assert unexpired["status"] == "AVAILABLE", "the boundary is strict"
    waiting = api.read_entity("get_molding_cycle", cycle_b["id"], ctx["admin_headers"])
    assert waiting["status"] == "SCHEDULED", "so nothing downstream moved either"
    assert waiting["abort_reason"] is None, "and no reason was written"

    swept = set_clock("2026-08-06T00:00:00Z")
    assert swept["expired_resin_lot_count"] == 1, "one day past expires_on the lot expires"
    assert swept["released_resin_charge_count"] == 1, (
        "link 3 is conditional on RESERVED, so the CONSUMED charge is not a candidate"
    )
    assert swept["aborted_molding_cycle_count"] == 1, (
        "link 4 is conditional on SCHEDULED, so the OVEN_RUNNING cycle is out of scope"
    )
    assert swept["blocked_production_order_count"] == 1, (
        "the order is left with no qualified lot"
    )

    expired = api.read_entity("get_resin_lot", lot["id"], ctx["admin_headers"])
    assert expired["status"] == "EXPIRED", "the lot is swept out of qualification"
    assert_decimal_equals(expired["available_kg"], "476.000", Q_MASS, "available_kg")
    assert_decimal_equals(expired["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
    assert_decimal_equals(expired["consumed_kg"], "24.000", Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(expired)

    refunded = api.read_entity("get_resin_charge", charge_b["id"], ctx["admin_headers"])
    assert refunded["status"] == "RELEASED", "the reservation is refunded"
    assert refunded["released_reason"] == "LOT_EXPIRED", (
        "the reason names the originating cascade, and the charge is released before "
        "the cycle aborts"
    )
    kept = api.read_entity("get_resin_charge", charge_a["id"], ctx["admin_headers"])
    assert kept["status"] == "CONSUMED", "expiry never refunds mass already in a hull"
    assert kept["released_reason"] is None, "so no release reason is written"

    aborted = api.read_entity("get_molding_cycle", cycle_b["id"], ctx["admin_headers"])
    assert aborted["status"] == "ABORTED", "the scheduled cycle loses its resin and aborts"
    assert aborted["abort_reason"] == "LOT_EXPIRED", "with the cascade's own reason"
    assert_decimal_equals(aborted["charged_mass_kg"], "0.000", Q_MASS, "charged_mass_kg")
    unaffected = api.read_entity("get_molding_cycle", cycle_a["id"], ctx["admin_headers"])
    assert unaffected["status"] == "OVEN_RUNNING", (
        "a five-day clock jump neither advances nor cancels a physical run"
    )
    assert unaffected["abort_reason"] is None, "and writes no reason"
    assert_instant_equals(
        unaffected["actual_oven_start_at"], "2026-08-01T09:00:00Z", "actual_oven_start_at"
    )
    assert_decimal_equals(unaffected["charged_mass_kg"], "24.000", Q_MASS, "charged_mass_kg")

    blocked = api.read_entity("get_production_order", order["id"], ctx["admin_headers"])
    assert blocked["status"] == "BLOCKED_RESIN", "the order has no qualified lot left"
    assert blocked["blocked_reason"] == "NO_QUALIFIED_RESIN_LOT", "and says why"
    blocked_version = blocked["version"]

    validate_error(
        api.create_molding_cycle(
            molding_cycle_payload(
                order["id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                blocked_version,
                arm_index=2,
                oven_start_at="2026-08-20T09:00:00Z",
            ),
            ctx["operator_headers"],
        ),
        ApiErrorId.ORDER_NOT_SCHEDULABLE,
    )

    idle_sweep = set_clock("2026-08-07T00:00:00Z")
    assert idle_sweep["released_resin_charge_count"] == 0, (
        "no RESERVED charge is left on the lot, so nothing can be refunded twice"
    )
    assert idle_sweep["aborted_molding_cycle_count"] == 0, (
        "and no SCHEDULED cycle is left to abort"
    )
    unchanged = api.read_entity("get_production_order", order["id"], ctx["admin_headers"])
    assert unchanged["version"] == blocked_version, "a no-op cascade writes nothing"
    assert unchanged["status"] == "BLOCKED_RESIN", "and the block still stands"
    assert unchanged["blocked_reason"] == "NO_QUALIFIED_RESIN_LOT", "with the same reason"


def test_returning_a_claim_to_the_queue_revokes_the_waiver_and_re_ages_the_hull(api):
    """The review loop is traversable twice, and the second lap starts from scratch.

    PRD.md section 3.9: "**Returning a claim to the queue**, with a
    `return_note` recording why, is the documented backward edge and it resets
    both axes at once. `claim_status` moves `UNDER_REVIEW` back to `SUBMITTED`,
    and whichever of `GUIDANCE_VERIFIED`, `GUIDANCE_VIOLATED` or `WAIVED` the
    storage axis held returns to `NOT_STARTED`, revoking any administrative
    waiver. Both `months_in_service` and `storage_description` are cleared to
    null, so a second pass through review re-ages the claim against the clock as
    it then stands and must decide the storage axis afresh."
    PRD.md section 3.9: "It computes and freezes `months_in_service` as the
    number of **complete calendar months** from the hull's `delivered_at` to the
    logical clock, floored: a hull delivered twelve months and twenty-nine days
    ago reads 12, not 13."
    PRD.md section 3.9: "The axis must read `GUIDANCE_VIOLATED`, otherwise
    `ERR_STORAGE_FINDING_NOT_WAIVABLE` (HTTP 409), and the claim must be
    `UNDER_REVIEW`. The axis becomes `WAIVED`."
    PRD.md section 3.9: "Deciding the storage axis never moves the adjudication
    axis — the claim stays `UNDER_REVIEW` — and approval reads the storage axis
    as a precondition rather than driving it."
    PRD.md section 3.9: "The claim must be `UNDER_REVIEW`
    (`ERR_CLAIM_INVALID_STATE`) and the storage axis must still be
    `NOT_STARTED`, otherwise `ERR_STORAGE_REVIEW_ALREADY_DONE` (HTTP 409) — the
    axis is decided once per pass through review."

    Design: Corner/state_machines/sm_cyclic_claim_return_to_queue_revokes_the_waiver_and_remeasures_the_hull_age
    """
    ctx = setup_submitted_claim(claim_overrides={"claim_type": "HARDWARE"})
    claim_id = ctx["warranty_claim_id"]
    admin = ctx["admin_headers"]
    agent = ctx["agent_headers"]

    set_clock("2026-10-02T00:00:00Z")
    first_review = validate_success(api.start_claim_review(claim_id, agent))
    assert first_review["claim_status"] == "UNDER_REVIEW", "the claim enters review"
    assert first_review["months_in_service"] == 2, (
        "two complete calendar months from 2026-08-02T00:00:00Z to 2026-10-02T00:00:00Z"
    )

    violated = validate_success(
        api.submit_storage_review(
            claim_id,
            storage_review_payload(
                "VIOLATED", "hull stored on bare concrete without cradles"
            ),
            agent,
        )
    )
    assert violated["storage_review_status"] == "GUIDANCE_VIOLATED", "the axis is decided"
    assert violated["claim_status"] == "UNDER_REVIEW", "the two axes are independent"

    waived = validate_success(
        api.waive_storage_finding(
            claim_id,
            waive_storage_finding_payload("goodwill waiver for a first-season owner"),
            admin,
        )
    )
    assert waived["storage_review_status"] == "WAIVED", "the finding is waived"
    assert waived["claim_status"] == "UNDER_REVIEW", "and the adjudication axis holds"

    returned = validate_success(
        api.return_claim_to_queue(
            claim_id,
            return_to_queue_payload("hull photographs are illegible; re-open the file"),
            agent,
        )
    )
    assert returned["claim_status"] == "SUBMITTED", "the backward edge re-queues the claim"
    assert returned["storage_review_status"] == "NOT_STARTED", (
        "and resets the storage axis, revoking the administrative waiver"
    )
    assert returned["months_in_service"] is None, "the frozen age is cleared"
    assert returned["storage_description"] is None, "and so is the storage story"

    # The re-queued claim now breaks both waive preconditions at once, and
    # PRD.md section 3.9 does not order them: "The axis must read
    # `GUIDANCE_VIOLATED`, otherwise `ERR_STORAGE_FINDING_NOT_WAIVABLE`
    # (HTTP 409), and the claim must be `UNDER_REVIEW`" leaves the adjudication
    # rung without a code of its own or a position, so either refusal is
    # faithful.
    validate_error_is_one_of(
        api.waive_storage_finding(
            claim_id,
            waive_storage_finding_payload("attempt to re-use the revoked waiver"),
            admin,
        ),
        [ApiErrorId.STORAGE_FINDING_NOT_WAIVABLE, ApiErrorId.CLAIM_INVALID_STATE],
    )

    set_clock("2026-11-02T00:00:00Z")
    second_review = validate_success(api.start_claim_review(claim_id, agent))
    assert second_review["claim_status"] == "UNDER_REVIEW", "the loop is entered a second time"
    assert second_review["months_in_service"] == 3, (
        "the age is re-measured against the clock as it now stands, not restored"
    )

    verified = validate_success(
        api.submit_storage_review(
            claim_id,
            storage_review_payload("VERIFIED", "cradled under cover on the second review"),
            agent,
        )
    )
    assert verified["storage_review_status"] == "GUIDANCE_VERIFIED", (
        "the axis may be decided again only because the loop reset it"
    )

    final = api.read_entity("get_warranty_claim", claim_id, admin)
    assert final["claim_status"] == "UNDER_REVIEW", "the second pass is mid-review"
    assert final["storage_review_status"] == "GUIDANCE_VERIFIED", "with a fresh decision"
    assert final["months_in_service"] == 3, "and the re-measured age"
    assert final["storage_description"] == "cradled under cover on the second review", (
        "and the second description"
    )
    assert final["version"] == 7, (
        "creation, two start-reviews, two storage reviews, the waiver and the "
        "return-to-queue; the refused waiver added nothing"
    )
    assert_null_fields(
        final,
        [
            "payout_basis",
            "pre_fee_gross_cents",
            "storage_deduction_cents",
            "admin_fee_cents",
            "net_payout_cents",
            "denial_reason",
        ],
        "warranty claim money fields",
    )

    model = api.read_entity("get_product_model", ctx["product_model_id"], admin)
    assert_money_equals(model["warranty_reserve_cents"], 500000, "warranty_reserve_cents")
    assert_money_equals(model["warranty_paid_cents"], 0, "warranty_paid_cents")
    assert_warranty_reserve_conserved(model)
