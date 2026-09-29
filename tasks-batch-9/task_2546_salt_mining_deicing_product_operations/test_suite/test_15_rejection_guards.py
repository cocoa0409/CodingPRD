"""
Refusals of the Salt Deicing Operations API: per-entity not-found codes, the two
product-line spec guards on a treatment batch, the panel reserve and panel state
guards on run scheduling, the lot and shipment guards that protect stored tonnage,
the quarantine guard on a drained lot, the order and allocation state guards, the
pre-season coverage floor on contract activation, and the shaft-availability guard.

Every refusal here is expected to leave the system exactly as it was, per the
precedence and no-side-effect rules of PRD §2.6 and the status table of PRD §5.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import (
    ERR_ADDITIVE_DOSE_OUT_OF_SPEC,
    ERR_ALLOCATION_NOT_FOUND,
    ERR_ALLOCATION_NOT_RESERVED,
    ERR_BATCH_NOT_FOUND,
    ERR_BATCH_QC_ALREADY_DECIDED,
    ERR_CONTRACT_NOT_FOUND,
    ERR_DEPOT_NOT_FOUND,
    ERR_FORECAST_NOT_FOUND,
    ERR_HOIST_UNAVAILABLE,
    ERR_INSPECTION_NOT_FOUND,
    ERR_INSUFFICIENT_LOT_TONS,
    ERR_LOT_NOT_FOUND,
    ERR_LOT_QUARANTINED,
    ERR_LOT_STATE_INVALID,
    ERR_ORDER_INVALID_STATE,
    ERR_ORDER_NOT_FOUND,
    ERR_PANEL_INVALID_STATE,
    ERR_PANEL_RESERVE_EXCEEDED,
    ERR_PRESEASON_COVERAGE_SHORT,
    ERR_RUN_NOT_FOUND,
    ERR_SCREEN_SPEC_NOT_ALLOWED,
    ERR_SHIPMENT_INVALID_STATE,
    ERR_SHIPMENT_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_lot_tonnage,
    assert_money,
    assert_page_meta,
    assert_purity,
    assert_rate_per_hour,
    assert_tons,
    assert_version_bumped,
    assert_version_unchanged,
    only,
)
from test_helpers.constants import (
    ALLOCATION_RELEASED,
    ALLOCATION_RESERVED,
    COARSE,
    CONTRACT_AWARDED,
    COVERED,
    DECISION_FAIL,
    FOOD_GRADE,
    HIGHWAY_DEICING,
    HOIST_DERATED,
    HOIST_DOWN,
    JURISDICTION_MUNICIPAL,
    LOT_AVAILABLE,
    LOT_DEPLETED,
    LOT_QUARANTINED,
    METHOD_SEVERITY_WEIGHTED,
    MODE_TRUCK,
    ORDER_REQUESTED,
    ORIGIN_MANUAL,
    PANEL_PRODUCING,
    QC_PASSED,
    RUN_HOISTED,
    RUN_SCHEDULED,
    SHIPMENT_LOADED,
    SHIPMENT_PLANNED,
    SHIPMENT_RECEIVED,
    WATER_CONDITIONING,
)
from test_helpers.test_users import (
    CONTRACT_ADMIN,
    LAB_LEAD,
    LAB_TECH,
    LOGISTICS,
    MINE_PLANNER,
    make_depot_manager_headers,
)

# The standing world these refusals are staged in: a 24,000 t/day mine, a 100,000 t
# panel at 50 % extraction assaying 96.00 % NaCl and 2.00 % insolubles (50,000.00 t
# recoverable), a 1,000 t run over a 24 h window, and two NY depots.
MINE_KWARGS = {
    "name": "Retsof Salt Mine",
    "state_code": "NY",
    "rated_hoist_tons_per_day": 24000,
}
PANEL_KWARGS = {
    "panel_code": "P-1",
    "gross_tons_in_place": 100000,
    "extraction_ratio_pct": 50,
    "grade_pct_nacl": 96.00,
    "insolubles_pct": 2.00,
}
RUN_KWARGS = {
    "planned_tons": 1000,
    "hoist_window_start": "2026-08-02T00:00:00Z",
    "hoist_window_end": "2026-08-03T00:00:00Z",
}
SYRACUSE = {
    "name": "Syracuse Depot",
    "state_code": "NY",
    "covered_capacity_tons": 5000,
    "open_pad_capacity_tons": 5000,
    "loadout_rate_tons_per_hour": 500,
    "outbound_freight_rate_per_ton": 12.500,
}
ROCHESTER = {
    "name": "Rochester Depot",
    "state_code": "NY",
    "covered_capacity_tons": 5000,
    "open_pad_capacity_tons": 5000,
    "loadout_rate_tons_per_hour": 400,
    "outbound_freight_rate_per_ton": 8.000,
}
FORECAST_KWARGS = {
    "season_code": "2026-27",
    "region_code": "NY-CENTRAL",
    "normal_season_tons": 20000,
    "severity_index": 60,
    "prior_season_1_actual_tons": 21000,
    "prior_season_2_actual_tons": 19000,
    "prior_season_3_actual_tons": 18000,
    "method": METHOD_SEVERITY_WEIGHTED,
    "preseason_lock_date": "2026-10-15T00:00:00Z",
}
CONTRACT_KWARGS = {
    "customer_name": "City of Syracuse",
    "jurisdiction_level": JURISDICTION_MUNICIPAL,
    "state_code": "NY",
    "product_line": HIGHWAY_DEICING,
    "committed_tons": 1000,
    "guaranteed_price_per_ton": 80.00,
    "min_take_pct": 80,
    "max_take_pct": 110,
    "failure_to_supply_penalty_per_ton": 30.00,
    "price_guarantee_cap_pct": 10,
}
ORDER_KWARGS = {
    "requested_tons": 500,
    "required_by": "2026-12-01T00:00:00Z",
    "market_index_price_per_ton": 82.00,
}


def test_each_collection_returns_its_own_not_found_code(api):
    """
    Ten reads of ten different collections, each addressing a well-formed identifier
    that belongs to nothing, must each answer with the not-found code of that
    collection's own entity — never one shared code for the whole API.

    "**Path resource existence** — each identifier in the URL path is resolved left to right, and the first one that does not resolve yields that entity's own 404: `ERR_MINE_NOT_FOUND`, `ERR_PANEL_NOT_FOUND`, `ERR_RUN_NOT_FOUND`, `ERR_BATCH_NOT_FOUND`, `ERR_DEPOT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_SHIPMENT_NOT_FOUND`, `ERR_FORECAST_NOT_FOUND`, `ERR_CONTRACT_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_ALLOCATION_NOT_FOUND` or `ERR_INSPECTION_NOT_FOUND` (all 404). Applies to every endpoint with a path parameter."

    Design: Corner/errors/unknown_path_ids_return_entity_scoped_not_found_errors
    """
    probes = [
        (api.get_run(NON_EXISTENT_UUID, LOGISTICS), ERR_RUN_NOT_FOUND),
        (api.get_batch(NON_EXISTENT_UUID, LOGISTICS), ERR_BATCH_NOT_FOUND),
        (api.get_depot(NON_EXISTENT_UUID, LOGISTICS), ERR_DEPOT_NOT_FOUND),
        (api.get_lot(NON_EXISTENT_UUID, LOGISTICS), ERR_LOT_NOT_FOUND),
        (api.get_shipment(NON_EXISTENT_UUID, LOGISTICS), ERR_SHIPMENT_NOT_FOUND),
        (api.get_forecast(NON_EXISTENT_UUID, LOGISTICS), ERR_FORECAST_NOT_FOUND),
        (api.get_contract(NON_EXISTENT_UUID, LOGISTICS), ERR_CONTRACT_NOT_FOUND),
        (api.get_order(NON_EXISTENT_UUID, LOGISTICS), ERR_ORDER_NOT_FOUND),
        (api.get_allocation(NON_EXISTENT_UUID, LOGISTICS), ERR_ALLOCATION_NOT_FOUND),
        (api.get_inspection(NON_EXISTENT_UUID, LOGISTICS), ERR_INSPECTION_NOT_FOUND),
    ]

    for response, expected_error_id in probes:
        validate_error(response, expected_error_id, 404)

    assert len({expected_error_id for _response, expected_error_id in probes}) == 10


def test_batch_spec_guards_refuse_a_bad_screen_cut_and_a_bad_additive_dose(api):
    """
    Two batches are opened against the same hoisted run: a food-grade batch asking for
    the coarse cut its line does not permit, and a water-conditioning batch carrying an
    anticaking dose its line does not permit at all. Each is refused for its own reason
    and neither batch comes into existence.

    "Batch creation is screened against the product-line register of §2.11 twice: an impermissible screen cut is refused with `ERR_SCREEN_SPEC_NOT_ALLOWED`, and a dose outside the line's inclusive window is refused with `ERR_ADDITIVE_DOSE_OUT_OF_SPEC`."

    Design: Corner/errors/treatment_batch_spec_guards_reject_a_bad_screen_and_a_bad_additive_dose
    """
    world = fx.hoisted_run(
        api, MINE_KWARGS, PANEL_KWARGS, hoisted_tons=1000, **RUN_KWARGS
    )
    run = world["run"]
    depot = fx.create_depot(api, **SYRACUSE)

    # FOOD_GRADE is a FINE-cut line only, and its additive window is satisfied here.
    bad_screen = api.create_batch(
        f.batch_payload(
            run["id"],
            depot["id"],
            product_line=FOOD_GRADE,
            screen_spec=COARSE,
            anticaking_ppm=8.00,
            corrosion_inhibitor_pct=0.00,
            input_tons=500,
            moisture_pct=0.00,
            storage_kind=COVERED,
        ),
        LAB_TECH,
    )
    validate_error(bad_screen, ERR_SCREEN_SPEC_NOT_ALLOWED, 422)

    # WATER_CONDITIONING permits the COARSE cut but no anticaking agent whatsoever.
    bad_dose = api.create_batch(
        f.batch_payload(
            run["id"],
            depot["id"],
            product_line=WATER_CONDITIONING,
            screen_spec=COARSE,
            anticaking_ppm=5.00,
            corrosion_inhibitor_pct=0.00,
            input_tons=500,
            moisture_pct=0.00,
            storage_kind=COVERED,
        ),
        LAB_TECH,
    )
    validate_error(bad_dose, ERR_ADDITIVE_DOSE_OUT_OF_SPEC, 422)

    # Neither refusal opened a batch, so the run still has nothing pending on it.
    _rows, meta = validate_paginated(
        api.list_batches(LAB_TECH, {"production_run_id": run["id"], "limit": 100})
    )
    assert_page_meta(meta, total_count=0, has_more=False)
    run_after = fx.refresh_run(api, run["id"])
    assert run_after["status"] == RUN_HOISTED
    assert run_after["open_batch_count"] == 0
    assert_version_unchanged(run_after, run)
    assert len(fx.lots_at_depot(api, depot["id"])) == 0


def test_panel_reserve_and_panel_state_guards_refuse_an_oversized_run_and_a_second_develop(api):
    """
    A panel with 50,000.00 t of recoverable reserve will not carry a run planned for one
    ton more, and a panel already in production cannot be developed a second time; the
    same run at exactly the reserve is accepted.

    "Sum the `planned_tons` of every run already on the target panel whose `status` is `SCHEDULED`, `HELD`, `HOISTED` or `CLOSED`, add the new run's `planned_tons`, and refuse with `ERR_PANEL_RESERVE_EXCEEDED` when that total would exceed the panel's `recoverable_tons`."
    "**Panel state** — `ERR_PANEL_INVALID_STATE` (409). Applies to `POST /salt/panels/{id}/develop` (needs `PLANNED`), `POST /salt/panels/{id}/start-production` (needs `DEVELOPED` or `SUSPENDED`), `POST /salt/panels/{id}/suspend` (needs `PRODUCING`), `POST /salt/panels/{id}/deplete` (needs `PRODUCING` or `SUSPENDED`), `POST /salt/panels/{id}/abandon` (needs `PLANNED`, `DEVELOPED`, `PRODUCING` or `SUSPENDED`) and `POST /salt/production-runs` (needs the target panel `PRODUCING`)."

    Design: Corner/errors/panel_reserve_and_panel_state_guards_reject_an_oversized_run_and_a_repeat_develop
    """
    world = fx.mine_with_producing_panel(api, MINE_KWARGS, PANEL_KWARGS)
    mine, panel = world["mine"], world["panel"]
    assert panel["status"] == PANEL_PRODUCING
    assert_tons(panel["recoverable_tons"], 50000.00, "recoverable_tons")
    mine_version = mine["version"]

    # 50,001 t over 72 h is 694.4583 t/h, well inside the 1,000.00 t/h shaft, so only
    # the geology objects.
    oversized = api.create_run(
        f.run_payload(
            mine["id"],
            panel["id"],
            mine_version,
            planned_tons=50001,
            hoist_window_start="2026-08-02T00:00:00Z",
            hoist_window_end="2026-08-05T00:00:00Z",
        ),
        MINE_PLANNER,
    )
    validate_error(oversized, ERR_PANEL_RESERVE_EXCEEDED, 409)

    validate_error(
        api.develop_panel(panel["id"], MINE_PLANNER), ERR_PANEL_INVALID_STATE, 409
    )

    # Neither refusal touched the panel, the mine or the (empty) run list.
    panel_after_refusals = fx.refresh_panel(api, panel["id"])
    assert_version_unchanged(panel_after_refusals, panel)
    assert panel_after_refusals["status"] == PANEL_PRODUCING
    mine_after_refusals = fx.refresh_mine(api, mine["id"])
    assert_version_unchanged(mine_after_refusals, mine)
    assert_tons(
        mine_after_refusals["scheduled_hoist_tons_open"],
        0.00,
        "scheduled_hoist_tons_open",
    )
    assert len(fx.runs_of_mine(api, mine["id"])) == 0

    # Exactly the reserve is not more than the reserve, so this one stands.
    accepted = validate_success(
        api.create_run(
            f.run_payload(
                mine["id"],
                panel["id"],
                mine_version,
                planned_tons=50000,
                hoist_window_start="2026-08-02T00:00:00Z",
                hoist_window_end="2026-08-05T00:00:00Z",
            ),
            MINE_PLANNER,
        ),
        201,
    )
    assert accepted["status"] == RUN_SCHEDULED
    assert_rate_per_hour(accepted["planned_tons_per_hour"], 694.4444)
    assert_tons(
        fx.refresh_mine(api, mine["id"])["scheduled_hoist_tons_open"],
        50000.00,
        "scheduled_hoist_tons_open",
    )


def test_lot_and_shipment_guards_refuse_an_oversized_move_an_early_receive_and_a_quarantined_move(api):
    """
    Three separate guards fire against the same 940.00 t covered pile: a truck booked
    for one ton more than the pile holds, a receive on a shipment that never left the
    origin, and a booking against the pile after the lab quarantines it.

    "Booking is refused if the origin depot is `CLOSED` or the destination depot is `CLOSED`, both with `ERR_DEPOT_CLOSED`; if the source lot is not `AVAILABLE`, with `ERR_LOT_STATE_INVALID` (or `ERR_LOT_QUARANTINED` where the lot is specifically quarantined); if the lot's `tons_available` is less than the `tons` requested, with `ERR_INSUFFICIENT_LOT_TONS`; and if the declared `destination_storage_kind` is `OPEN_PAD` while the lot's `product_line` is `FOOD_GRADE` or `WATER_CONDITIONING`, with `ERR_UNCOVERED_STORAGE_NOT_ALLOWED`."
    "**Shipment state** — `ERR_SHIPMENT_INVALID_STATE` (409). Applies to `POST /salt/shipments/{id}/load` (needs `PLANNED`), `POST /salt/shipments/{id}/receive` (needs `LOADED`) and `POST /salt/shipments/{id}/cancel` (needs `PLANNED` or `LOADED`)."

    Design: Corner/errors/lot_and_shipment_guards_reject_five_distinct_illegal_moves
    """
    world = fx.lot_at_depot(
        api,
        mine_kwargs=MINE_KWARGS,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE,
        run_kwargs=RUN_KWARGS,
        hoisted_tons=1000,
        input_tons=1000,
        moisture_pct=0.00,
    )
    origin, lot = world["depot"], world["lot"]
    destination = fx.create_depot(api, **ROCHESTER)
    assert_lot_tonnage(lot, 940.00, 0.00, 940.00)

    # One ton more than the pile holds.
    validate_error(
        api.create_shipment(
            f.shipment_payload(
                lot["id"],
                origin["id"],
                destination["id"],
                941,
                mode=MODE_TRUCK,
                load_window_start="2026-08-05T08:00:00Z",
                load_window_end="2026-08-05T09:00:00Z",
                destination_storage_kind=COVERED,
            ),
            LOGISTICS,
        ),
        ERR_INSUFFICIENT_LOT_TONS,
        409,
    )

    shipment = validate_success(
        api.create_shipment(
            f.shipment_payload(
                lot["id"],
                origin["id"],
                destination["id"],
                400,
                mode=MODE_TRUCK,
                load_window_start="2026-08-05T08:00:00Z",
                load_window_end="2026-08-05T09:00:00Z",
                destination_storage_kind=COVERED,
            ),
            LOGISTICS,
        ),
        201,
    )
    assert shipment["status"] == SHIPMENT_PLANNED

    # Receiving salt that was never loaded out.
    validate_error(
        api.receive_shipment(
            shipment["id"], make_depot_manager_headers(destination["id"])
        ),
        ERR_SHIPMENT_INVALID_STATE,
        409,
    )

    quarantined = validate_success(
        api.set_quarantine_state(
            lot["id"],
            f.quarantine_payload(
                True, "suspected clay contamination in the north face"
            ),
            LAB_LEAD,
        ),
        200,
    )
    assert quarantined["lot_state"] == LOT_QUARANTINED
    assert_lot_tonnage(quarantined, 940.00, 0.00, 940.00)

    # A window a day clear of the planned bay block, so only the quarantine can refuse it.
    validate_error(
        api.create_shipment(
            f.shipment_payload(
                lot["id"],
                origin["id"],
                destination["id"],
                100,
                mode=MODE_TRUCK,
                load_window_start="2026-08-06T08:00:00Z",
                load_window_end="2026-08-06T09:00:00Z",
                destination_storage_kind=COVERED,
            ),
            LOGISTICS,
        ),
        ERR_LOT_QUARANTINED,
        409,
    )

    # None of the refused calls moved tonnage, and only the one accepted booking exists.
    assert_lot_tonnage(fx.refresh_lot(api, lot["id"]), 940.00, 0.00, 940.00)
    rows, meta = validate_paginated(
        api.list_shipments(LOGISTICS, {"origin_depot_id": origin["id"], "limit": 100})
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert only(rows)["id"] == shipment["id"]


def test_a_batch_already_passed_refuses_a_second_quality_decision(api):
    """
    Quality control is decided once and only once: a batch that has already passed
    refuses a later fail, and the pile it minted is untouched by the attempt.

    "A batch that has already landed on `PASSED` or `FAILED` refuses any further decision — including a verbatim repeat of the decision already recorded — with `ERR_BATCH_QC_ALREADY_DECIDED`; the operation is deliberately not idempotent."

    Design: Corner/errors/lot_and_shipment_guards_reject_five_distinct_illegal_moves
    """
    world = fx.lot_at_depot(
        api,
        mine_kwargs=MINE_KWARGS,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE,
        run_kwargs=RUN_KWARGS,
        hoisted_tons=1000,
        input_tons=1000,
        moisture_pct=0.00,
    )
    batch, lot, depot = world["batch"], world["lot"], world["depot"]
    assert batch["qc_state"] == QC_PASSED

    validate_error(
        api.qc_decision(batch["id"], f.qc_decision_payload(DECISION_FAIL), LAB_LEAD),
        ERR_BATCH_QC_ALREADY_DECIDED,
        409,
    )

    batch_after = fx.refresh_batch(api, batch["id"])
    assert batch_after["qc_state"] == QC_PASSED
    assert_version_unchanged(batch_after, batch)

    lot_after = fx.refresh_lot(api, lot["id"])
    assert_lot_tonnage(lot_after, 940.00, 0.00, 940.00)
    assert lot_after["lot_state"] == LOT_AVAILABLE
    assert_purity(lot_after["purity_pct_nacl"], 96.500)
    assert len(fx.lots_at_depot(api, depot["id"])) == 1
    assert_tons(
        fx.refresh_depot(api, depot["id"])["covered_stored_tons"],
        940.00,
        "covered_stored_tons",
    )


def test_a_lot_drained_to_zero_cannot_change_its_quarantine_state(api):
    """
    Shipping a pile out in its entirety drains it to nothing and closes it for good, so
    the lab can no longer put an audit hold on it — the refusal is about the pile's
    state, not its tonnage.

    "`DEPLETED` is reached in exactly one way: a shipment load drains the lot's `tons_on_hand` to exactly 0 while its `tons_reserved` also stands at 0."
    "Because a depleted lot's available tonnage is 0, a reservation against it is refused for insufficient tonnage rather than for its state; a *quarantine-state change* against it, however, is refused with `ERR_LOT_STATE_INVALID`."

    Design: Corner/errors/depleted_lot_cannot_change_its_quarantine_state
    """
    world = fx.lot_at_depot(
        api,
        mine_kwargs=MINE_KWARGS,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE,
        run_kwargs=RUN_KWARGS,
        hoisted_tons=1000,
        input_tons=1000,
        moisture_pct=0.00,
    )
    origin, lot = world["depot"], world["lot"]
    destination = fx.create_depot(api, **ROCHESTER)

    shipment = fx.create_shipment(
        api,
        lot["id"],
        origin["id"],
        destination["id"],
        940,
        mode=MODE_TRUCK,
        load_window_start="2026-08-05T08:00:00Z",
        load_window_end="2026-08-05T09:00:00Z",
        destination_storage_kind=COVERED,
    )

    loaded = validate_success(
        api.load_shipment(shipment["id"], make_depot_manager_headers(origin["id"])), 200
    )
    assert loaded["status"] == SHIPMENT_LOADED

    drained = fx.refresh_lot(api, lot["id"])
    assert_lot_tonnage(drained, 0.00, 0.00, 0.00)
    assert drained["lot_state"] == LOT_DEPLETED

    validate_error(
        api.set_quarantine_state(
            lot["id"],
            f.quarantine_payload(True, "audit hold requested on a drained pile"),
            LAB_LEAD,
        ),
        ERR_LOT_STATE_INVALID,
        409,
    )

    still_depleted = fx.refresh_lot(api, lot["id"])
    assert still_depleted["lot_state"] == LOT_DEPLETED
    assert still_depleted["quarantine_reason"] is None
    assert_version_unchanged(still_depleted, drained)

    # The tonnage itself is intact at the far end once the movement is received.
    received = validate_success(
        api.receive_shipment(
            shipment["id"], make_depot_manager_headers(destination["id"])
        ),
        200,
    )
    assert received["status"] == SHIPMENT_RECEIVED
    new_lot = fx.refresh_lot(api, received["received_lot_id"])
    assert_lot_tonnage(new_lot, 940.00, 0.00, 940.00)
    assert new_lot["lot_state"] == LOT_AVAILABLE
    assert new_lot["product_line"] == HIGHWAY_DEICING
    assert_purity(new_lot["purity_pct_nacl"], 96.500)
    assert_tons(
        fx.refresh_depot(api, origin["id"])["covered_stored_tons"],
        0.00,
        "covered_stored_tons",
    )
    assert_tons(
        fx.refresh_depot(api, destination["id"])["covered_stored_tons"],
        940.00,
        "covered_stored_tons",
    )


def test_an_order_still_awaiting_salt_cannot_be_delivered(api):
    """
    Delivery is only available to an order that has salt behind it, so a delivery order
    that has never been allocated is refused, and the attempt leaves it untouched.

    "**Order state** — `ERR_ORDER_INVALID_STATE` (409). Applies to `POST /salt/delivery-orders/{id}/allocate` (needs `REQUESTED`), `POST /salt/delivery-orders/{id}/release-allocations` (needs `ALLOCATED` or `SHORTED`), `POST /salt/delivery-orders/{id}/deliver` (needs `ALLOCATED` or `SHORTED`) and `POST /salt/delivery-orders/{id}/waive-penalty` (needs `SHORTED`)."

    Design: Corner/errors/order_and_allocation_state_guards_reject_an_early_deliver_and_a_double_release
    """
    world = fx.requested_order(
        api,
        order_kwargs=ORDER_KWARGS,
        mine_kwargs=MINE_KWARGS,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE,
        run_kwargs=RUN_KWARGS,
        batch_kwargs={"input_tons": 1000, "moisture_pct": 0.00},
        forecast_kwargs=FORECAST_KWARGS,
        contract_kwargs=CONTRACT_KWARGS,
        hoisted_tons=1000,
    )
    order, lot = world["order"], world["lot"]
    assert order["status"] == ORDER_REQUESTED
    assert_tons(order["allocated_tons"], 0.00, "allocated_tons")

    validate_error(
        api.deliver_order(order["id"], LOGISTICS), ERR_ORDER_INVALID_STATE, 409
    )

    order_after = fx.refresh_order(api, order["id"])
    assert order_after["status"] == ORDER_REQUESTED
    assert order_after["delivered_at"] is None
    assert_version_unchanged(order_after, order)
    assert len(fx.allocations_of_order(api, order["id"])) == 0
    assert_lot_tonnage(fx.refresh_lot(api, lot["id"]), 940.00, 0.00, 940.00)


def test_an_allocation_already_released_cannot_be_released_again(api):
    """
    A hand-written reservation is released once and then kept as a record; releasing the
    same line a second time is refused and returns nothing further to the pile.

    "A single allocation is released by a `LogisticsPlanner` with an optional `reason`, moving it `RESERVED → RELEASED`; it must be `RESERVED`, else `ERR_ALLOCATION_NOT_RESERVED`."

    Design: Corner/errors/order_and_allocation_state_guards_reject_an_early_deliver_and_a_double_release
    """
    world = fx.requested_order(
        api,
        order_kwargs=ORDER_KWARGS,
        mine_kwargs=MINE_KWARGS,
        panel_kwargs=PANEL_KWARGS,
        depot_kwargs=SYRACUSE,
        run_kwargs=RUN_KWARGS,
        batch_kwargs={"input_tons": 1000, "moisture_pct": 0.00},
        forecast_kwargs=FORECAST_KWARGS,
        contract_kwargs=CONTRACT_KWARGS,
        hoisted_tons=1000,
    )
    order, lot = world["order"], world["lot"]

    reserved = validate_success(
        api.create_allocation(
            f.allocation_payload(
                order["id"], lot["id"], 500, fx.lot_version(api, lot["id"])
            ),
            LOGISTICS,
        ),
        201,
    )
    assert reserved["state"] == ALLOCATION_RESERVED
    assert reserved["origin"] == ORIGIN_MANUAL
    assert reserved["rank_position"] == 1
    assert_lot_tonnage(fx.refresh_lot(api, lot["id"]), 940.00, 500.00, 440.00)

    released = validate_success(
        api.release_allocation(
            reserved["id"], LOGISTICS, f.release_payload("load cancelled by the city")
        ),
        200,
    )
    assert released["state"] == ALLOCATION_RELEASED
    assert_version_bumped(released, reserved)
    assert_lot_tonnage(fx.refresh_lot(api, lot["id"]), 940.00, 0.00, 940.00)

    validate_error(
        api.release_allocation(
            reserved["id"],
            LOGISTICS,
            f.release_payload("duplicate cancellation from the depot terminal"),
        ),
        ERR_ALLOCATION_NOT_RESERVED,
        409,
    )

    # The refused second release changed neither the row, the pile nor the order.
    row_after = fx.refresh_allocation(api, reserved["id"])
    assert row_after["state"] == ALLOCATION_RELEASED
    assert_version_unchanged(row_after, released)
    assert_lot_tonnage(fx.refresh_lot(api, lot["id"]), 940.00, 0.00, 940.00)
    order_after = fx.refresh_order(api, order["id"])
    assert_tons(order_after["allocated_tons"], 0.00, "allocated_tons")
    assert_money(order_after["shortfall_penalty_usd"], 0.00, "shortfall_penalty_usd")


def test_activation_with_no_salt_on_the_ground_is_refused_for_coverage(api):
    """
    A contract committing 1,000 t at an 80 % minimum take needs 800.00 t already stored
    in its own state and product line before it may go live; with an empty yard the
    activation is refused and the contract stays awarded.

    "Activation is refused with `ERR_PRESEASON_COVERAGE_SHORT` when that coverage is strictly less than `committed_tons` multiplied by `min_take_pct` divided by 100."

    Design: Corner/errors/activation_with_no_stockpile_returns_preseason_coverage_short
    """
    world = fx.awarded_contract(api, FORECAST_KWARGS, CONTRACT_KWARGS)
    contract = world["contract"]
    assert contract["status"] == CONTRACT_AWARDED

    validate_error(
        api.activate_contract(contract["id"], CONTRACT_ADMIN),
        ERR_PRESEASON_COVERAGE_SHORT,
        409,
    )

    ledger = fx.contract_ledger(api, contract["id"])
    assert_tons(ledger["preseason_coverage_tons"], 0.00, "preseason_coverage_tons")
    assert_tons(
        ledger["preseason_coverage_required_tons"],
        800.00,
        "preseason_coverage_required_tons",
    )

    contract_after = fx.refresh_contract(api, contract["id"])
    assert contract_after["status"] == CONTRACT_AWARDED
    assert_version_unchanged(contract_after, contract)


def test_scheduling_a_run_while_the_shaft_is_down_is_refused(api):
    """
    A mine whose shaft is out of service can hoist nothing, so no run may be scheduled
    against it; once the shaft comes back partly derated, the same run is accepted.

    "**Shaft availability** — `ERR_HOIST_UNAVAILABLE` (409) when the mine's `hoist_state` is `HOIST_DOWN`. Applies to `POST /salt/production-runs`, `POST /salt/production-runs/{id}/hoist` and `POST /salt/production-runs/{id}/reinstate`."
    "Each contributes a factor: the shaft contributes 1.00 while available, 0.55 while derated and 0.00 while down; compliance contributes 1.00 while compliant, 0.80 while cited and 0.00 under a withdrawal order."

    Design: Corner/errors/run_scheduling_while_the_shaft_is_down_returns_hoist_unavailable
    """
    world = fx.mine_with_producing_panel(api, MINE_KWARGS, PANEL_KWARGS)
    mine, panel = world["mine"], world["panel"]

    downed = fx.set_hoist_status(
        api, mine["id"], HOIST_DOWN, note="skip rope replacement on the production shaft"
    )
    assert downed["hoist_state"] == HOIST_DOWN
    assert_tons(
        downed["effective_hoist_tons_per_day"], 0.00, "effective_hoist_tons_per_day"
    )

    validate_error(
        api.create_run(
            f.run_payload(mine["id"], panel["id"], downed["version"], **RUN_KWARGS),
            MINE_PLANNER,
        ),
        ERR_HOIST_UNAVAILABLE,
        409,
    )

    _rows, meta = validate_paginated(
        api.list_runs(MINE_PLANNER, {"mine_id": mine["id"], "limit": 100})
    )
    assert_page_meta(meta, total_count=0, has_more=False)
    mine_after_refusal = fx.refresh_mine(api, mine["id"])
    assert_version_unchanged(mine_after_refusal, downed)
    assert_tons(
        mine_after_refusal["scheduled_hoist_tons_open"],
        0.00,
        "scheduled_hoist_tons_open",
    )

    # A derated shaft still hoists 24000 x 0.55 = 13,200.00 t/day, so the run is allowed.
    derated = fx.set_hoist_status(
        api, mine["id"], HOIST_DERATED, note="one skip back in service"
    )
    assert_tons(
        derated["effective_hoist_tons_per_day"],
        13200.00,
        "effective_hoist_tons_per_day",
    )

    accepted = validate_success(
        api.create_run(
            f.run_payload(mine["id"], panel["id"], derated["version"], **RUN_KWARGS),
            MINE_PLANNER,
        ),
        201,
    )
    assert accepted["status"] == RUN_SCHEDULED
    assert_rate_per_hour(accepted["planned_tons_per_hour"], 41.6667)
    assert_tons(
        fx.refresh_mine(api, mine["id"])["scheduled_hoist_tons_open"],
        1000.00,
        "scheduled_hoist_tons_open",
    )
