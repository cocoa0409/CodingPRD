"""Bottling: line scheduling geometry, the dry-goods waterfall and run completion."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    approve_release_order,
    assert_bottling_run,
    assert_dry_goods_item,
    client_units_invariant,
    create_bottling_run_payload,
    create_dry_goods_item_payload,
    execute_release_order,
    new_bottling_line,
    new_bottling_run,
    new_client,
    new_dry_goods_item,
    new_release_order,
    reserve_supplies,
    setup_active_contract,
    setup_contract_with_lot,
    setup_dry_goods_shelf,
    setup_housed_aging_lot,
    setup_scheduled_bottling_run,
    setup_supplies_reserved_run,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_run_hours_round_up_to_the_next_quarter_and_bake_in_the_changeover(
    api, cellar_supervisor_headers
):
    """PRD 3.7: "The run's `run_hours` is `cases_planned` divided by the line's
    `cases_per_hour`, rounded **up** to the next quarter hour, so a run needing
    two hours and one minute of line time occupies two and a quarter hours."
    PRD 3.7: "The run's `scheduled_end` is `scheduled_start` advanced by
    `run_hours` hours and then by the line's `changeover_minutes` minutes, so
    the changeover is already baked into the window."
    PRD 3.7: "The run's `gallons_consumed` is the wine the run will draw: the
    case count multiplied by the bottles in a case multiplied by
    `bottle_size_ml`, divided by 3785.411784 millilitres to the gallon, rounded
    half up to two decimal places."

    Design: Corner/calculations/corner_bottling_schedule_ceils_run_hours_to_next_quarter
    """
    scenario = setup_contract_with_lot(clock="2026-10-01T00:00:00Z", delivery_ticket="DT-K1")
    line = new_bottling_line()

    data = validate_success(
        api.create_bottling_run(
            create_bottling_run_payload(
                scenario["lot"]["id"],
                line["id"],
                scheduled_start="2026-10-05T10:00:00Z",
                cases_planned=190,
            ),
            cellar_supervisor_headers,
        ),
        201,
    )

    assert_bottling_run(data)
    assert data["run_hours"] == pytest.approx(1.25, abs=0.001), (
        f"190 / 180 is 1.0555 hours, which rounds up to 1.25; got {data['run_hours']}"
    )
    assert data["scheduled_end"] == "2026-10-05T12:00:00.000Z", (
        "10:00 plus 1 h 15 m of run time plus 45 changeover minutes"
    )
    assert data["gallons_consumed"] == pytest.approx(451.73, abs=0.01)
    assert data["status"] == "SCHEDULED"
    assert data["cases_actual"] is None


def test_scheduling_onto_a_line_in_maintenance_is_refused(api, cellar_supervisor_headers,
                                                          facility_admin_headers):
    """PRD 3.7: "The line must be `AVAILABLE`, or the request is refused with
    `ERR_LINE_UNAVAILABLE`."
    PRD 3.7: "A line opens `AVAILABLE`, and the same admin may take it out of
    service to `MAINTENANCE` and return it to `AVAILABLE` as often as the
    maintenance calendar requires, each move incrementing the line's `version`
    by 1."

    Design: Corner/errors/corner_bottling_run_on_maintenance_line_rejected
    """
    scenario = setup_contract_with_lot(clock="2026-10-01T00:00:00Z", delivery_ticket="DT-W1")
    line = new_bottling_line()
    down = validate_success(
        api.bottling_line_status(
            line["id"], {"action": "SET_MAINTENANCE"}, facility_admin_headers
        )
    )
    assert down["status"] == "MAINTENANCE"

    payload = create_bottling_run_payload(
        scenario["lot"]["id"], line["id"],
        scheduled_start="2026-10-05T10:00:00Z", cases_planned=100,
    )
    response = api.create_bottling_run(payload, cellar_supervisor_headers)
    validate_error(response, ApiErrorId.ERR_LINE_UNAVAILABLE.value, 409)

    validate_success(
        api.bottling_line_status(
            line["id"], {"action": "SET_AVAILABLE"}, facility_admin_headers
        )
    )
    run = validate_success(
        api.create_bottling_run(payload, cellar_supervisor_headers), 201
    )
    assert run["status"] == "SCHEDULED"
    assert run["run_hours"] == pytest.approx(0.75, abs=0.001)


def test_the_daily_capacity_budget_bites_across_non_overlapping_runs(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.7: "A second, aggregate ceiling then applies: total the `run_hours`
    of that line's runs in `SCHEDULED` or `SUPPLIES_RESERVED` whose
    `scheduled_start` falls on the same UTC calendar day as the new run, add the
    new run's own `run_hours`, and refuse the request with
    `ERR_LINE_DAILY_CAPACITY_EXCEEDED` when that total exceeds the line's
    `daily_capacity_hours`."

    Design: Corner/validations/corner_line_daily_capacity_exceeded_across_two_non_overlapping_runs
    """
    scenario = setup_contract_with_lot(clock="2026-10-01T00:00:00Z", delivery_ticket="DT-Q1")
    line = new_bottling_line(daily_capacity_hours=4.0)
    first = new_bottling_run(
        scenario["lot"]["id"], line["id"],
        scheduled_start="2026-10-05T10:00:00Z", cases_planned=500,
    )

    response = api.create_bottling_run(
        create_bottling_run_payload(
            scenario["lot"]["id"], line["id"],
            scheduled_start="2026-10-05T18:00:00Z", cases_planned=250,
        ),
        cellar_supervisor_headers,
    )
    validate_error(response, ApiErrorId.ERR_LINE_DAILY_CAPACITY_EXCEEDED.value, 409)

    next_day = validate_success(
        api.create_bottling_run(
            create_bottling_run_payload(
                scenario["lot"]["id"], line["id"],
                scheduled_start="2026-10-06T18:00:00Z", cases_planned=250,
            ),
            cellar_supervisor_headers,
        ),
        201,
    )
    assert next_day["status"] == "SCHEDULED", (
        "the budget is per UTC calendar day, so the next day is free"
    )

    rows, _ = validate_paginated(
        api.list_bottling_runs(facility_admin_headers, params={"line_id": line["id"]})
    )
    assert sorted(row["id"] for row in rows) == sorted([first["id"], next_day["id"]])


def test_dry_goods_item_defaults_to_an_empty_shelf(api, facility_admin_headers):
    """PRD 3.7: "An optional `initial_units` seeds the shelf and defaults to 0,
    so the item is created with `on_hand_units` equal to `initial_units`,
    `reserved_units` at 0 and `available_units` equal to `on_hand_units`."

    Design: Corner/entities/corner_dry_goods_item_defaults_on_hand_units_to_zero
    """
    client = new_client()

    data = validate_success(
        api.create_dry_goods_item(
            create_dry_goods_item_payload(client["id"]), facility_admin_headers
        ),
        201,
    )

    assert_dry_goods_item(data)
    assert data["on_hand_units"] == 0
    assert data["reserved_units"] == 0
    assert data["available_units"] == 0
    assert data["version"] == 1


def test_dry_goods_listing_is_partitioned_by_owning_client(api, facility_admin_headers):
    """PRD 3.7: "Dry goods are client-owned and never shared. A `FacilityAdmin`
    registers a **DryGoodsItem** against a `client_id` with its supplier `sku`,
    its `item_type` — one of `BOTTLE`, `CORK`, `CAPSULE`, `LABEL` or `CASE_BOX`
    — and the supplier pack size `units_per_case` (at least one), which is
    informational for receiving."
    PRD 2.3: "Beyond `limit` and `offset`, each list endpoint accepts optional
    equality filters drawn from the resource it returns, and any filter a caller
    omits simply does not narrow the result."

    Design: Corner/entities/corner_dry_goods_items_filtered_by_owning_client
    """
    client_a = new_client(name="Coombsville Cellars", ttb_permit_number="BW-CA-15001",
                          contact_email="a@x.example")
    client_b = new_client(name="Pritchard Hill Partners", ttb_permit_number="BW-CA-15002",
                          contact_email="b@x.example")
    bottle_a = new_dry_goods_item(client_a["id"], sku="BTL-750-ANT", item_type="BOTTLE",
                                  units_per_case=12, initial_units=1000)
    cork_a = new_dry_goods_item(client_a["id"], sku="CRK-44MM", item_type="CORK",
                                units_per_case=1000, initial_units=1000)
    bottle_b = new_dry_goods_item(client_b["id"], sku="BTL-750-BDX", item_type="BOTTLE",
                                  units_per_case=12, initial_units=500)

    rows, meta = validate_paginated(
        api.list_dry_goods_items(facility_admin_headers, params={"client_id": client_a["id"]})
    )
    ids = sorted(row["id"] for row in rows)
    assert ids == sorted([bottle_a["id"], cork_a["id"]])
    assert meta["total_count"] == 2
    assert bottle_b["id"] not in ids, "another client's SKU never appears"

    corks, _ = validate_paginated(
        api.list_dry_goods_items(
            facility_admin_headers,
            params={"client_id": client_a["id"], "item_type": "CORK"},
        )
    )
    assert [row["id"] for row in corks] == [cork_a["id"]]


def test_a_dry_goods_receipt_raises_on_hand_and_recomputes_available(
    api, facility_admin_headers
):
    """PRD 3.7: "Later deliveries are received by the same role by supplying the
    `units` arriving; the receipt raises `on_hand_units` by that quantity,
    recomputes `available_units` as `on_hand_units` less `reserved_units`, and
    increments the item's `version`."

    Design: Corner/endpoints/corner_dry_goods_receipt_raises_on_hand_and_available
    """
    client = new_client()
    item = new_dry_goods_item(client["id"], initial_units=250)

    data = validate_success(
        api.receive_dry_goods(item["id"], {"units": 750}, facility_admin_headers)
    )

    assert_dry_goods_item(data)
    assert data["on_hand_units"] == 1000
    assert data["available_units"] == 1000
    assert data["reserved_units"] == 0
    assert data["version"] == 2


def test_the_supply_waterfall_drains_the_largest_shelf_first(api, facility_admin_headers):
    """PRD 3.7: "The eligible items are ranked by `available_units` descending
    and, where two items tie, by `created_at` ascending. The waterfall then
    drains the top-ranked item first, taking the smaller of that item's
    `available_units` and the units still outstanding, recording a reservation
    entry naming the `dry_goods_item_id`, the `item_type` and the
    `units_reserved`, and moving on to the next item until the requirement is
    met."
    PRD 3.7: "First the requirement is sized from the plan: the bottle count is
    `cases_planned` multiplied by the bottles in a case for the chosen format,
    and the run needs that many `BOTTLE` units, that many `CORK` units, that
    many `CAPSULE` units, twice that many `LABEL` units — every bottle carries a
    front and a back label — and `cases_planned` units of `CASE_BOX`."

    Design: Corner/calculations/corner_dry_goods_waterfall_drains_highest_available_first
    """
    scenario = setup_contract_with_lot(clock="2026-10-10T00:00:00Z", delivery_ticket="DT-J1")
    client_id = scenario["client"]["id"]
    line = new_bottling_line()
    low = new_dry_goods_item(client_id, sku="BTL-LO", item_type="BOTTLE",
                             units_per_case=12, initial_units=700)
    high = new_dry_goods_item(client_id, sku="BTL-HI", item_type="BOTTLE",
                              units_per_case=12, initial_units=800)
    cork = new_dry_goods_item(client_id, sku="CRK-44MM", item_type="CORK",
                              units_per_case=1000, initial_units=2000)
    capsule = new_dry_goods_item(client_id, sku="CAP-TIN", item_type="CAPSULE",
                                 units_per_case=1000, initial_units=2000)
    label = new_dry_goods_item(client_id, sku="LBL-EST", item_type="LABEL",
                               units_per_case=2400, initial_units=2400)
    case_box = new_dry_goods_item(client_id, sku="BOX-12", item_type="CASE_BOX",
                                  units_per_case=25, initial_units=100)
    run = new_bottling_run(scenario["lot"]["id"], line["id"], cases_planned=100)

    data = reserve_supplies(run["id"])
    assert data["status"] == "SUPPLIES_RESERVED"
    assert len(data["supply_reservations"]) == 6, (
        f"two bottle SKUs plus one each of the other four types, got "
        f"{data['supply_reservations']}"
    )

    def read(item):
        return validate_success(api.get_dry_goods_item(item["id"], facility_admin_headers))

    high_after = read(high)
    assert high_after["reserved_units"] == 800, (
        "the 800-unit SKU is ranked first by available_units descending"
    )
    assert high_after["available_units"] == 0

    low_after = read(low)
    assert low_after["reserved_units"] == 400, "only the outstanding 400 units are taken"
    assert low_after["available_units"] == 300

    assert read(label)["reserved_units"] == 2400, "two labels per bottle"
    assert read(case_box)["reserved_units"] == 100
    assert read(cork)["reserved_units"] == 1200
    assert read(capsule)["reserved_units"] == 1200


def test_a_shortage_on_one_item_type_reserves_nothing_at_all(api, facility_admin_headers):
    """PRD 3.7: "The reservation is all-or-nothing across every required type.
    If any single type cannot be covered in full by the client's eligible pool,
    the entire reservation is refused with `ERR_DRY_GOODS_SHORTAGE` and no
    dry-goods item anywhere is touched — a run short only on capsules does not
    consume the bottles it could have had."

    Design: Corner/errors/corner_dry_goods_shortage_blocks_supply_reservation
    """
    scenario = setup_scheduled_bottling_run(
        delivery_ticket="DT-AB1",
        dry_goods={"BOTTLE": 1200, "CORK": 1200, "CAPSULE": 1200, "LABEL": 1000,
                   "CASE_BOX": 100},
    )

    response = api.bottling_run_transition(
        scenario["run"]["id"],
        {"action": "RESERVE_SUPPLIES"},
        TEST_USERS["cellar_supervisor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_DRY_GOODS_SHORTAGE.value, 409)

    run = validate_success(api.get_bottling_run(scenario["run"]["id"], facility_admin_headers))
    assert run["status"] == "SCHEDULED"
    assert run["supply_reservations"] == []

    items = scenario["dry_goods"]
    for item_type, item in items.items():
        stored = validate_success(
            api.get_dry_goods_item(item["id"], facility_admin_headers)
        )
        assert stored["reserved_units"] == 0, (
            f"{item_type} must be untouched by the refused reservation"
        )
    bottle = validate_success(
        api.get_dry_goods_item(items["BOTTLE"]["id"], facility_admin_headers)
    )
    assert bottle["available_units"] == 1200
    label = validate_success(
        api.get_dry_goods_item(items["LABEL"]["id"], facility_admin_headers)
    )
    assert label["available_units"] == 1000


def test_completing_a_draining_run_bottles_the_lot_and_frees_its_vessel(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.7: "Three hops then run against the wine: first, the lot's
    `volume_gallons` is reduced by the recomputed `gallons_consumed`, its
    `cases_bottled` is raised by `cases_actual`, and its `version` increments;
    second, a lot whose `volume_gallons` reached exactly zero in that first hop
    moves `AGING` to `BOTTLED`; third, a lot that just entered `BOTTLED` forces
    its `COMMITTED` allocation to `RELEASED`, which sets that allocation's
    vessel `condition` to `DIRTY` and stamps `last_released_at`, and recomputes
    the owning contract's `gallons_allocated` and `barrel_slots_used`."
    PRD 3.7: "On success each reserved item has both its `on_hand_units` and its
    `reserved_units` reduced by exactly its `units_reserved` — the glass has
    physically left the building — with `available_units` recomputed and
    `version` incremented."

    Design: Corner/cross_cutting_layers/corner_bottling_complete_cascades_lot_to_bottled_and_releases_allocation
    """
    scenario = setup_housed_aging_lot(
        clock="2026-10-10T00:00:00Z",
        delivery_ticket="DT-AL1",
        alloc_start="2026-10-10T00:00:00Z",
        alloc_end="2026-12-01T00:00:00Z",
    )
    line = new_bottling_line()
    order = new_release_order(
        scenario["lot"]["id"], scenario["rep_headers"], gallons=1946.23
    )
    approve_release_order(order["id"])
    executed = execute_release_order(order["id"])
    assert executed["excise_tax_cents"] == 13624
    drawn = validate_success(api.get_lot(scenario["lot"]["id"], facility_admin_headers))
    assert drawn["volume_gallons"] == pytest.approx(1188.77, abs=0.01)

    items = setup_dry_goods_shelf(scenario["client"]["id"])
    run = new_bottling_run(scenario["lot"]["id"], line["id"], cases_planned=500)
    assert run["gallons_consumed"] == pytest.approx(1188.77, abs=0.01)
    reserve_supplies(run["id"])

    data = validate_success(
        api.bottling_run_transition(
            run["id"], {"action": "COMPLETE", "cases_actual": 500}, cellar_supervisor_headers
        )
    )
    assert data["status"] == "COMPLETED"
    assert data["cases_actual"] == 500
    assert data["gallons_consumed"] == pytest.approx(1188.77, abs=0.01)

    lot = validate_success(api.get_lot(scenario["lot"]["id"], facility_admin_headers))
    assert lot["volume_gallons"] == pytest.approx(0.00, abs=0.01)
    assert lot["cases_bottled"] == 500
    assert lot["production_status"] == "BOTTLED"
    assert lot["bond_status"] == "IN_BOND", "bottling never writes the bond axis"

    allocation = validate_success(
        api.get_vessel_allocation(scenario["allocation"]["id"], facility_admin_headers)
    )
    assert allocation["status"] == "RELEASED"
    vessel = validate_success(api.get_vessel(scenario["vessel"]["id"], facility_admin_headers))
    assert vessel["condition"] == "DIRTY"
    contract = validate_success(
        api.get_contract(scenario["contract"]["id"], facility_admin_headers)
    )
    assert contract["gallons_allocated"] == pytest.approx(0.00, abs=0.01)

    for item_type, item in items.items():
        stored = validate_success(
            api.get_dry_goods_item(item["id"], facility_admin_headers)
        )
        assert stored["on_hand_units"] == 0, (
            f"{item_type} glass has physically left the building"
        )
        assert stored["reserved_units"] == 0
        assert stored["available_units"] == 0

    client = validate_success(
        api.get_client(scenario["client"]["id"], facility_admin_headers)
    )
    assert client["bond_gallons_in_bond"] == pytest.approx(0.00, abs=0.01)
    assert client["taxpaid_gallons_ytd"] == pytest.approx(1946.23, abs=0.01)


# ── Closed-interval line occupancy ──────────────────────────────────


def _setup_line_with_a_morning_run():
    """A 500-case run occupying 2026-10-05T10:00 through 13:45 on line L-1."""
    scenario = setup_contract_with_lot(clock="2026-10-01T00:00:00Z", delivery_ticket="DT-9201")
    line = new_bottling_line()
    scenario["line"] = line
    scenario["run"] = new_bottling_run(
        scenario["lot"]["id"], line["id"],
        scheduled_start="2026-10-05T10:00:00Z", cases_planned=500,
    )
    return scenario


def test_a_run_opening_on_the_incumbent_end_instant_collides(api, cellar_supervisor_headers):
    """PRD 3.7: "Line occupancy is a **closed** interval running from
    `scheduled_start` through `scheduled_end` inclusive, and two runs on the
    same line collide even when they merely touch at an endpoint — the
    changeover minutes are already inside the window, so back-to-back scheduling
    with no gap is a conflict rather than a convenience."
    PRD 3.7: "A collision with any other run on that line standing in
    `SCHEDULED` or `SUPPLIES_RESERVED` is refused with
    `ERR_LINE_SLOT_CONFLICT`; runs that have been cancelled or completed are
    ignored by the test."

    Design: Difficulty/resource_temporal_overlap/bottling_run_blocked_when_line_windows_touch_at_an_endpoint
    """
    scenario = _setup_line_with_a_morning_run()
    assert scenario["run"]["run_hours"] == pytest.approx(3.00, abs=0.001)
    assert scenario["run"]["scheduled_end"] == "2026-10-05T13:45:00.000Z"
    assert scenario["run"]["gallons_consumed"] == pytest.approx(1188.77, abs=0.01)

    response = api.create_bottling_run(
        create_bottling_run_payload(
            scenario["lot"]["id"], scenario["line"]["id"],
            scheduled_start="2026-10-05T13:45:00Z", cases_planned=250,
        ),
        cellar_supervisor_headers,
    )

    validate_error(response, ApiErrorId.ERR_LINE_SLOT_CONFLICT.value, 409)


def test_a_run_opening_after_the_incumbent_window_is_scheduled(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.7: "Line occupancy is a **closed** interval running from
    `scheduled_start` through `scheduled_end` inclusive, and two runs on the
    same line collide even when they merely touch at an endpoint — the
    changeover minutes are already inside the window, so back-to-back scheduling
    with no gap is a conflict rather than a convenience."
    PRD 3.7: "A new run is stored in `SCHEDULED` with `cases_actual` null and
    `supply_reservations` an empty array."

    Design: Difficulty/resource_temporal_overlap/bottling_run_blocked_when_line_windows_touch_at_an_endpoint
    """
    scenario = _setup_line_with_a_morning_run()

    data = validate_success(
        api.create_bottling_run(
            create_bottling_run_payload(
                scenario["lot"]["id"], scenario["line"]["id"],
                scheduled_start="2026-10-05T14:00:00Z", cases_planned=250,
            ),
            cellar_supervisor_headers,
        ),
        201,
    )

    assert_bottling_run(data)
    assert data["status"] == "SCHEDULED"
    assert data["run_hours"] == pytest.approx(1.50, abs=0.001), (
        f"250 / 180 is 1.3889 hours, rounded up to 1.50; got {data['run_hours']}"
    )
    assert data["scheduled_end"] == "2026-10-05T16:15:00.000Z"
    assert data["gallons_consumed"] == pytest.approx(594.39, abs=0.01)

    rows, _ = validate_paginated(
        api.list_bottling_runs(
            facility_admin_headers, params={"line_id": scenario["line"]["id"]}
        )
    )
    assert sorted(row["id"] for row in rows) == sorted(
        [scenario["run"]["id"], data["id"]]
    )


# ── Reserving and cancelling conserves the client's unit counts ──────


def _setup_reserved_run_on_a_modest_shelf():
    """A 100-case run at SUPPLIES_RESERVED against a shelf holding 11500 units."""
    return setup_supplies_reserved_run(
        delivery_ticket="DT-9401",
        dry_goods={"BOTTLE": 2000, "CORK": 2000, "CAPSULE": 2000, "LABEL": 5000,
                   "CASE_BOX": 500},
    )


def test_cancelling_a_reserved_run_returns_every_unit_without_touching_stock(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 3.7: "Cancelling from `SUPPLIES_RESERVED` is a compensation: every
    dry-goods item named in `supply_reservations` has its `reserved_units`
    reduced by exactly its `units_reserved` and its `available_units`
    recomputed, while `on_hand_units` is deliberately left untouched because no
    glass was consumed, and each such item's `version` increments."
    PRD 3.7: "The run's `supply_reservations` is then emptied to an empty array
    and the run moves to `CANCELLED`."

    Design: Difficulty/compensating_invariant/bottling_cancel_conserves_dry_goods_unit_counts
    """
    scenario = _setup_reserved_run_on_a_modest_shelf()
    items = scenario["dry_goods"]
    assert scenario["run"]["status"] == "SUPPLIES_RESERVED"
    assert scenario["run"]["run_hours"] == pytest.approx(0.75, abs=0.001)
    assert scenario["run"]["gallons_consumed"] == pytest.approx(237.75, abs=0.01)

    def read(item_type):
        return validate_success(
            api.get_dry_goods_item(items[item_type]["id"], facility_admin_headers)
        )

    bottle = read("BOTTLE")
    assert bottle["reserved_units"] == 1200 and bottle["available_units"] == 800
    label = read("LABEL")
    assert label["reserved_units"] == 2400 and label["available_units"] == 2600
    case_box = read("CASE_BOX")
    assert case_box["reserved_units"] == 100 and case_box["available_units"] == 400

    cancelled = validate_success(
        api.bottling_run_transition(
            scenario["run"]["id"], {"action": "CANCEL"}, cellar_supervisor_headers
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["supply_reservations"] == []

    expected_on_hand = {"BOTTLE": 2000, "CORK": 2000, "CAPSULE": 2000, "LABEL": 5000,
                        "CASE_BOX": 500}
    for item_type, on_hand in expected_on_hand.items():
        stored = read(item_type)
        assert stored["reserved_units"] == 0, f"{item_type} must be fully released"
        assert stored["available_units"] == on_hand
        assert stored["on_hand_units"] == on_hand, (
            f"{item_type} on_hand_units must be untouched — no glass was consumed"
        )


def test_available_plus_reserved_units_survive_the_reserve_and_the_cancel(
    api, cellar_supervisor_headers, facility_admin_headers
):
    """PRD 2.8: "Within a client, the total across its dry-goods items of
    `available_units` plus `reserved_units` is unchanged by reserving supplies
    and unchanged again by cancelling a reservation."
    PRD 3.7: "Both `COMPLETED` and `CANCELLED` are terminal, and the per-client
    unit conservation invariant of §2.8 holds across the reserve-and-cancel
    pair."

    Design: Difficulty/compensating_invariant/bottling_cancel_conserves_dry_goods_unit_counts
    """
    scenario = setup_scheduled_bottling_run(
        delivery_ticket="DT-9401",
        dry_goods={"BOTTLE": 2000, "CORK": 2000, "CAPSULE": 2000, "LABEL": 5000,
                   "CASE_BOX": 500},
    )
    client_id = scenario["client"]["id"]

    def invariant():
        rows, _ = validate_paginated(
            api.list_dry_goods_items(
                facility_admin_headers, params={"client_id": client_id, "limit": 100}
            )
        )
        return client_units_invariant(rows)

    before = invariant()
    assert before == 11500, f"2000 + 2000 + 2000 + 5000 + 500 units, got {before}"

    reserve_supplies(scenario["run"]["id"])
    during = invariant()
    assert during == 11500, (
        f"reserving moves units between the two counters only, got {during}"
    )

    validate_success(
        api.bottling_run_transition(
            scenario["run"]["id"], {"action": "CANCEL"}, cellar_supervisor_headers
        )
    )
    after = invariant()
    assert after == 11500, f"the compensation must leave zero drift, got {after}"

    lot = validate_success(api.get_lot(scenario["lot"]["id"], facility_admin_headers))
    assert lot["volume_gallons"] == pytest.approx(3135.00, abs=0.01), (
        "cancelling never consumes wine"
    )
    assert lot["cases_bottled"] == 0
