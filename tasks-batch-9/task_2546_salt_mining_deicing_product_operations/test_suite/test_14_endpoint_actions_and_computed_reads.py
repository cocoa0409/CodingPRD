"""
Endpoint shapes of the Salt Deicing Operations API: partial revision of a depot's
capacities and rates, the loadout bay a cancelled shipment gives back, the explicit
close of a hoisted run that never carried a batch, the mine hoist-capacity
projection, the wholesale release of a delivery order's allocations, and the two
manual panel actions (suspend and abandon).

Every expected figure below is derived from PRD §2.10, §3.1, §3.2, §3.4, §3.6,
§3.7 and §3.9.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f, fixtures as fx
from test_helpers.api_errors import (
    ERR_LOADOUT_BAY_CONFLICT,
    ERR_PANEL_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_amount,
    assert_hoist_capacity_view,
    assert_lot_tonnage,
    assert_money,
    assert_page_meta,
    assert_rate_per_hour,
    assert_three_decimals,
    assert_timestamps_unchanged,
    assert_tons,
    assert_version_bumped,
    assert_version_unchanged,
    only,
)
from test_helpers.constants import (
    ALLOCATION_RELEASED,
    COVERED,
    DEPOT_OPEN,
    HELD_REASON_GROUND_CONTROL,
    HIGHWAY_DEICING,
    HOIST_DOWN,
    JURISDICTION_MUNICIPAL,
    LOT_AVAILABLE,
    METHOD_SEVERITY_WEIGHTED,
    MODE_RAIL,
    MODE_TRUCK,
    ORDER_ALLOCATED,
    ORDER_REQUESTED,
    ORIGIN_WATERFALL,
    PANEL_ABANDONED,
    PANEL_PRODUCING,
    PANEL_SUSPENDED,
    PENALTY_NONE,
    REQUIRED_GAP_MINUTES,
    RUN_CLOSED,
    RUN_HELD,
    RUN_HOISTED,
    RUN_VOIDED,
    SHIPMENT_CANCELLED,
    SHIPMENT_PLANNED,
)
from test_helpers.test_users import (
    GROUND_CONTROL,
    GROUND_CONTROL_USER_ID,
    LOGISTICS,
    MINE_PLANNER,
)

# The standing world these chains reuse: a 24,000 t/day mine, a 100,000 t panel at
# 50 % extraction assaying 96.00 % NaCl and 2.00 % insolubles (recoverable_tons
# 50,000.00 by PRD §3.2), a 1,000 t run over a 24 h window, and two NY depots.
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


def test_patch_depot_revises_only_the_named_rate_and_bumps_version(api):
    """
    A depot revision that carries only the outbound freight rate must leave the two
    storage capacities and the loadout rate exactly where creation set them, take the
    depot from version 1 to version 2, and keep `created_at` frozen while `updated_at`
    moves forward.

    "Capacities and rates can be revised in place by a `LogisticsPlanner`, or by the depot's own `DepotManager` under the ownership rule of §2.1, supplying any subset of `covered_capacity_tons`, `open_pad_capacity_tons`, `loadout_rate_tons_per_hour` and `outbound_freight_rate_per_ton`."

    Design: Corner/endpoints/patch_depot_updates_only_the_named_field_and_bumps_version
    """
    depot = fx.create_depot(api, **SYRACUSE)
    assert depot["version"] == 1

    patched = validate_success(
        api.patch_depot(
            depot["id"],
            f.depot_patch_payload(outbound_freight_rate_per_ton=9.750),
            LOGISTICS,
        ),
        200,
    )

    assert_three_decimals(
        patched["outbound_freight_rate_per_ton"], 9.750, "outbound_freight_rate_per_ton"
    )
    assert_version_bumped(patched, depot)
    assert patched["version"] == 2

    # The three omitted fields are untouched — a PATCH is not a replacement.
    assert_tons(patched["covered_capacity_tons"], 5000.00, "covered_capacity_tons")
    assert_tons(patched["open_pad_capacity_tons"], 5000.00, "open_pad_capacity_tons")
    assert_tons(
        patched["loadout_rate_tons_per_hour"], 500.00, "loadout_rate_tons_per_hour"
    )

    assert patched["created_at"] == depot["created_at"]
    assert patched["updated_at"] >= depot["created_at"]

    # An empty shed of 5,000 t covered capacity: utilization is 0.00 and posture OPEN.
    assert patched["depot_state"] == DEPOT_OPEN
    assert_amount(patched["covered_utilization_pct"], 0.00, 2, "covered_utilization_pct")
    assert_tons(patched["covered_stored_tons"], 0.00, "covered_stored_tons")

    refetched = validate_success(api.get_depot(depot["id"], LOGISTICS), 200)
    assert refetched == patched


def test_cancelling_a_planned_rail_move_frees_the_bay_for_the_blocked_truck(api):
    """
    A truck booking that grazes the 45-minute buffer around a planned rail move is
    refused for bay contention, and the identical payload is accepted once the rail
    move is cancelled — the peer set holds only planned and loaded shipments.

    "For each peer in that order, take the required gap as the **larger** of the new shipment's mode buffer and that peer's mode buffer."
    "Cancelling a `PLANNED` shipment moves no tonnage at all — nothing has left the origin pile yet — and its only effect is to free the bay window, since a `CANCELLED` shipment drops out of the peer set at step 1 above."

    Design: Corner/endpoints/cancelling_a_planned_shipment_frees_the_loadout_bay_for_the_blocked_one
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

    rail = fx.create_shipment(
        api,
        lot["id"],
        origin["id"],
        destination["id"],
        400,
        mode=MODE_RAIL,
        load_window_start="2026-08-05T08:00:00Z",
        load_window_end="2026-08-05T10:00:00Z",
        destination_storage_kind=COVERED,
    )
    assert rail["required_gap_minutes"] == REQUIRED_GAP_MINUTES[MODE_RAIL] == 45

    # The rail peer blocks 07:15-10:45, so a 10:30 truck start collides.
    truck_payload = f.shipment_payload(
        lot["id"],
        origin["id"],
        destination["id"],
        300,
        mode=MODE_TRUCK,
        load_window_start="2026-08-05T10:30:00Z",
        load_window_end="2026-08-05T11:00:00Z",
        destination_storage_kind=COVERED,
    )
    validate_error(
        api.create_shipment(truck_payload, LOGISTICS), ERR_LOADOUT_BAY_CONFLICT, 409
    )

    cancelled = validate_success(
        api.cancel_shipment(
            rail["id"],
            LOGISTICS,
            f.cancel_payload("railcars reassigned to a storm depot"),
        ),
        200,
    )
    assert cancelled["status"] == SHIPMENT_CANCELLED

    retried = validate_success(api.create_shipment(truck_payload, LOGISTICS), 201)
    assert retried["status"] == SHIPMENT_PLANNED
    assert retried["required_gap_minutes"] == REQUIRED_GAP_MINUTES[MODE_TRUCK] == 0

    # Neither the plan nor the cancellation moved a single ton.
    assert_lot_tonnage(fx.refresh_lot(api, lot["id"]), 940.00, 0.00, 940.00)

    rows, meta = validate_paginated(
        api.list_shipments(LOGISTICS, {"origin_depot_id": origin["id"], "limit": 100})
    )
    assert_page_meta(meta, total_count=2, has_more=False)
    assert sorted(row["status"] for row in rows) == [
        SHIPMENT_CANCELLED,
        SHIPMENT_PLANNED,
    ]


def test_a_hoisted_run_with_no_batches_is_closed_explicitly_by_the_planner(api):
    """
    A run whose salt was hoisted but never treated has nothing to close it
    automatically, so a mine planner closes it by hand; the close is accepted because
    the run carries no pending batch, and the closed run leaves nothing committed
    against the shaft.

    "A run with **zero** batches, on the other hand, never auto-closes, because the automatic path requires that at least one batch exist; such a run is closed explicitly by a `MinePlanner`, and the explicit close requires `open_batch_count` to already stand at 0."

    Design: Corner/endpoints/manual_close_of_a_hoisted_run_with_no_batches
    """
    world = fx.hoisted_run(
        api, MINE_KWARGS, PANEL_KWARGS, hoisted_tons=1000, **RUN_KWARGS
    )
    run = world["run"]
    assert run["status"] == RUN_HOISTED
    assert run["open_batch_count"] == 0
    assert_tons(run["hoisted_tons"], 1000.00, "hoisted_tons")

    closed = validate_success(api.close_run(run["id"], MINE_PLANNER), 200)

    assert closed["status"] == RUN_CLOSED
    assert closed["open_batch_count"] == 0
    assert_version_bumped(closed, run)

    # A CLOSED run no longer counts against the shaft's open commitment.
    mine_after = fx.refresh_mine(api, world["mine"]["id"])
    assert_tons(
        mine_after["scheduled_hoist_tons_open"], 0.00, "scheduled_hoist_tons_open"
    )
    view = fx.hoist_capacity(api, world["mine"]["id"])
    assert_hoist_capacity_view(view, 24000.00, 1.00, 1.00, 24000.00, 0.00, 0)


def test_hoist_capacity_view_reports_the_scheduled_commitment_without_mutating(api):
    """
    The mine's hoist-capacity read must show the rated tonnage, both derate factors,
    the effective daily tonnage, the hourly capacity behind it, and the one scheduled
    run's open tonnage — and leave every stored `version` exactly where it was.

    "A mine's hoist-capacity view reports `rated_hoist_tons_per_day`, `hoist_factor`, `compliance_factor`, `effective_hoist_tons_per_day`, `mine_hourly_capacity`, `scheduled_hoist_tons_open` and `scheduled_run_count`."
    "None of the three mutates anything or moves a `version`."

    Design: Corner/endpoints/hoist_capacity_read_derives_every_field_without_mutating
    """
    world = fx.scheduled_run(api, MINE_KWARGS, PANEL_KWARGS, **RUN_KWARGS)
    mine, run = world["mine"], world["run"]
    mine_before = fx.refresh_mine(api, mine["id"])
    run_before = fx.refresh_run(api, run["id"])
    assert_rate_per_hour(run_before["planned_tons_per_hour"], 41.6667)

    view = validate_success(api.get_hoist_capacity(mine["id"], MINE_PLANNER), 200)

    # An available shaft at a compliant mine: 24000 x 1.00 x 1.00, 1000.00/h.
    assert_hoist_capacity_view(view, 24000.00, 1.00, 1.00, 24000.00, 1000.00, 1)
    assert_amount(view["mine_hourly_capacity"], 1000.00, 2, "mine_hourly_capacity")

    assert_version_unchanged(fx.refresh_mine(api, mine["id"]), mine_before)
    assert_timestamps_unchanged(fx.refresh_mine(api, mine["id"]), mine_before)
    assert_version_unchanged(fx.refresh_run(api, run["id"]), run_before)

    repeated = validate_success(api.get_hoist_capacity(mine["id"], MINE_PLANNER), 200)
    assert repeated == view


def test_release_allocations_returns_both_lots_and_resets_the_order(api):
    """
    An order filled from two sheds — the local pile first, then the cheaper remote one
    — is unwound in a single wholesale release: both reserved rows go to RELEASED,
    each lot gets its own tonnage back, and the order is a clean REQUESTED order again.

    "Releasing an order's allocations wholesale, again by a `LogisticsPlanner` with an optional `reason`, moves every one of the order's `RESERVED` rows to `RELEASED`, returns each row's tonnage to its own lot, and walks the order back to `REQUESTED` — `ALLOCATED → REQUESTED` or `SHORTED → REQUESTED`."
    "It resets the order's `allocated_tons` and `shorted_tons` to 0, returns its `penalty_state` to `NONE` and its `shortfall_penalty_usd` to 0, and recomputes the contract's `penalty_accrued_usd`, `supply_reliability_score` and `breach_watch` from the ledger that remains."

    Design: Corner/endpoints/release_allocations_releases_every_line_across_two_lots_at_once
    """
    world = fx.hoisted_run(
        api,
        MINE_KWARGS,
        PANEL_KWARGS,
        hoisted_tons=1300,
        planned_tons=1300,
        hoist_window_start="2026-08-02T00:00:00Z",
        hoist_window_end="2026-08-03T00:00:00Z",
    )
    depot_a = fx.create_depot(api, **SYRACUSE)
    depot_b = fx.create_depot(api, **ROCHESTER)

    # 300 t and 1,000 t of feed at a COARSE cut and no moisture: 282.00 t and 940.00 t.
    lot_a = fx.mint_lot(
        api, world["run"]["id"], depot_a["id"], input_tons=300, moisture_pct=0.00
    )["lot"]
    lot_b = fx.mint_lot(
        api, world["run"]["id"], depot_b["id"], input_tons=1000, moisture_pct=0.00
    )["lot"]
    assert_lot_tonnage(lot_a, 282.00, 0.00, 282.00)
    assert_lot_tonnage(lot_b, 940.00, 0.00, 940.00)

    contract = fx.active_contract(api, FORECAST_KWARGS, CONTRACT_KWARGS)["contract"]
    order = fx.create_order(
        api,
        contract["id"],
        depot_a["id"],
        requested_tons=500,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=82.00,
    )

    allocated = validate_success(api.allocate_order(order["id"], LOGISTICS), 200)
    assert allocated["status"] == ORDER_ALLOCATED
    assert_tons(allocated["allocated_tons"], 500.00, "allocated_tons")

    # Rank 1 is the lot in the order's own shed; rank 2 covers the remaining 218.00 t.
    reserved_rows = fx.allocations_of_order(api, order["id"])
    assert len(reserved_rows) == 2
    by_rank = sorted(reserved_rows, key=lambda row: row["rank_position"])
    assert [row["rank_position"] for row in by_rank] == [1, 2]
    assert by_rank[0]["stockpile_lot_id"] == lot_a["id"]
    assert by_rank[1]["stockpile_lot_id"] == lot_b["id"]
    assert_tons(by_rank[0]["tons"], 282.00, "tons")
    assert_tons(by_rank[1]["tons"], 218.00, "tons")
    assert all(row["origin"] == ORIGIN_WATERFALL for row in reserved_rows)

    released_order = validate_success(
        api.release_order_allocations(
            order["id"], LOGISTICS, f.release_payload("customer deferred the load")
        ),
        200,
    )

    assert released_order["status"] == ORDER_REQUESTED
    assert_tons(released_order["allocated_tons"], 0.00, "allocated_tons")
    assert_tons(released_order["shorted_tons"], 0.00, "shorted_tons")
    assert released_order["penalty_state"] == PENALTY_NONE
    assert_money(released_order["shortfall_penalty_usd"], 0.00, "shortfall_penalty_usd")
    assert_version_bumped(released_order, allocated)

    released_rows = fx.allocations_of_order(api, order["id"])
    assert len(released_rows) == 2
    assert all(row["state"] == ALLOCATION_RELEASED for row in released_rows)

    # Each lot got back exactly its own row's tonnage; nothing left either pile.
    lot_a_after = fx.refresh_lot(api, lot_a["id"])
    lot_b_after = fx.refresh_lot(api, lot_b["id"])
    assert_lot_tonnage(lot_a_after, 282.00, 0.00, 282.00)
    assert_lot_tonnage(lot_b_after, 940.00, 0.00, 940.00)
    assert lot_a_after["lot_state"] == LOT_AVAILABLE
    assert lot_b_after["lot_state"] == LOT_AVAILABLE

    ledger = fx.contract_ledger(api, contract["id"])
    assert_money(ledger["penalty_accrued_usd"], 0.00, "penalty_accrued_usd")
    assert ledger["breach_watch"] is False


def test_manual_suspend_then_abandon_holds_the_run_and_voids_it(api):
    """
    A ground-control engineer pulls a producing panel out by hand, which holds its
    scheduled run and takes the shaft down; a planner then abandons the panel, which
    voids the held run and freezes the panel's reserve for good.

    "This manual `PRODUCING → SUSPENDED` edge sets `suspended_by_user_id` to the caller's `X-User-ID`, drops the mine's `producing_panel_count`, and fires hops 2 through 4 exactly as the defect path does — the shaft tightens, runs are held for `GROUND_CONTROL` and `CAPACITY` respectively, and `scheduled_hoist_tons_open` is recomputed."
    "The one difference is decisive: a manual suspension does **not** set `open_defect`, because only a defect inspection does that."

    Design: Corner/endpoints/manual_panel_suspend_then_abandon_action_endpoints
    """
    world = fx.scheduled_run(api, MINE_KWARGS, PANEL_KWARGS, **RUN_KWARGS)
    mine, panel, run = world["mine"], world["panel"], world["run"]
    assert panel["status"] == PANEL_PRODUCING
    assert_tons(panel["recoverable_tons"], 50000.00, "recoverable_tons")

    suspended = validate_success(
        api.suspend_panel(
            panel["id"],
            f.suspend_payload("convergence above the trigger on the north face"),
            GROUND_CONTROL,
        ),
        200,
    )

    assert suspended["status"] == PANEL_SUSPENDED
    assert suspended["suspended_by_user_id"] == GROUND_CONTROL_USER_ID
    assert suspended["open_defect"] is False
    assert suspended["ground_control_defect_count"] == 0
    assert_version_bumped(suspended, panel)

    held = only(fx.runs_of_mine(api, mine["id"], panel_id=panel["id"]))
    assert held["status"] == RUN_HELD
    assert held["held_reason"] == HELD_REASON_GROUND_CONTROL

    # The last producing panel left production, so the shaft is down and nothing
    # remains committed against it.
    mine_after_suspension = fx.refresh_mine(api, mine["id"])
    assert mine_after_suspension["producing_panel_count"] == 0
    assert mine_after_suspension["hoist_state"] == HOIST_DOWN
    assert_tons(
        mine_after_suspension["effective_hoist_tons_per_day"],
        0.00,
        "effective_hoist_tons_per_day",
    )
    assert_tons(
        mine_after_suspension["scheduled_hoist_tons_open"],
        0.00,
        "scheduled_hoist_tons_open",
    )

    abandoned = validate_success(
        api.abandon_panel(
            panel["id"],
            f.abandon_payload("roof conditions uneconomic to rehabilitate"),
            MINE_PLANNER,
        ),
        200,
    )
    assert abandoned["status"] == PANEL_ABANDONED
    assert_tons(abandoned["recoverable_tons"], 50000.00, "recoverable_tons")

    voided = only(fx.runs_of_mine(api, mine["id"], panel_id=panel["id"]))
    assert voided["status"] == RUN_VOIDED
    assert voided["id"] == run["id"]

    # Abandonment is terminal: a second attempt is refused and changes nothing.
    validate_error(
        api.abandon_panel(
            panel["id"], f.abandon_payload("duplicate abandonment"), MINE_PLANNER
        ),
        ERR_PANEL_INVALID_STATE,
        409,
    )
    assert_version_unchanged(fx.refresh_panel(api, panel["id"]), abandoned)

    rows, meta = validate_paginated(
        api.list_panels(
            MINE_PLANNER,
            {"mine_id": mine["id"], "status": PANEL_ABANDONED, "limit": 100},
        )
    )
    assert_page_meta(meta, total_count=1, has_more=False)
    assert only(rows)["id"] == panel["id"]
