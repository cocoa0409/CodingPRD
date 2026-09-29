"""
The three expected-parent-version guards of PRD §2.8 on the Salt Deicing Operations
API.

Scheduling a production run, raising a delivery order and reserving tonnage by hand
each carry the caller's last observed `version` of the parent mine, contract or lot.
Each test lets an unrelated write move the parent underneath the caller, shows the
412 refusal that follows and that nothing was persisted, and then repeats the very
same request with the freshly re-read version so that the token — and not any state
precondition — is proved to be the only defect (PRD §2.6 stage 10).
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_STALE_BID_CONTRACT_VERSION,
    ERR_STALE_MINE_VERSION,
    ERR_STALE_STOCKPILE_LOT_VERSION,
)
from test_helpers.constants import (
    ALLOCATION_RESERVED,
    HOIST_DERATED,
    LOT_AVAILABLE,
    LOT_QUARANTINED,
    ORDER_REQUESTED,
    ORIGIN_MANUAL,
    RUN_SCHEDULED,
)
from test_helpers.test_users import (
    LAB_LEAD,
    LOGISTICS,
    MINE_PLANNER,
)

# The standing baseline of this module: a 24,000 t/day mine whose 100,000 t panel at
# 50 % extraction, 96.00 % NaCl and 2.00 % insolubles carries 50,000.00 t of
# recoverable reserve, a 1,000 t run over a 24-hour hoist window, a 5,000 t covered
# Syracuse depot, a COARSE HIGHWAY_DEICING batch of 1,000 input tons at 0.00 %
# moisture yielding 940.00 t at 96.500 % NaCl, and a 1,000 t municipal contract whose
# 80 % minimum take needs 800.00 t of pre-season coverage the 940.00 t lot supplies.
_MINE = {"name": "Retsof Salt Mine", "state_code": "NY", "rated_hoist_tons_per_day": 24000}
_PANEL = {
    "panel_code": "P-1",
    "gross_tons_in_place": 100000,
    "extraction_ratio_pct": 50,
    "grade_pct_nacl": 96.00,
    "insolubles_pct": 2.00,
}
_RUN = {
    "planned_tons": 1000,
    "hoist_window_start": "2026-08-02T00:00:00Z",
    "hoist_window_end": "2026-08-03T00:00:00Z",
}
_DEPOT = {
    "name": "Syracuse Depot",
    "state_code": "NY",
    "covered_capacity_tons": 5000,
    "open_pad_capacity_tons": 5000,
    "loadout_rate_tons_per_hour": 500,
    "outbound_freight_rate_per_ton": 12.500,
}
_BATCH = {
    "anticaking_ppm": 20.00,
    "corrosion_inhibitor_pct": 0.50,
    "input_tons": 1000,
    "moisture_pct": 0.00,
}
_CONTRACT = {
    "committed_tons": 1000,
    "guaranteed_price_per_ton": 80.00,
    "min_take_pct": 80,
    "max_take_pct": 110,
    "failure_to_supply_penalty_per_ton": 30.00,
    "price_guarantee_cap_pct": 10,
}
_ORDER = {"requested_tons": 200, "required_by": "2026-12-01T00:00:00Z",
          "market_index_price_per_ton": 82.00}


def _contract_world(api):
    """
    The whole chain on the baseline geometry: mine, producing panel, hoisted run,
    Syracuse depot, treated batch, the 940.00 t lot it minted, and an ACTIVE 1,000 t
    contract whose pre-season coverage that lot satisfies.
    """
    return fx.standard_world(
        api,
        mine_kwargs=dict(_MINE),
        panel_kwargs=dict(_PANEL),
        depot_kwargs=dict(_DEPOT),
        run_kwargs=dict(_RUN),
        batch_kwargs=dict(_BATCH),
        contract_kwargs=dict(_CONTRACT),
        hoisted_tons=1000,
    )


def test_scheduling_a_run_on_a_version_read_before_a_hoist_derate_is_refused(api):
    """
    A planner reads the mine, a derate to one skip then moves the shaft dimension
    underneath it, and the run it schedules against that superseded read is refused;
    the identical window is accepted the moment the planner re-reads the mine, and it
    fits comfortably inside the derated 550.00 t/h ceiling.
    "If the supplied value does not equal the parent's current `version`, the write is
    rejected and nothing is persisted."
    "`POST /salt/production-runs` requires `expected_mine_version`, matching the
    target `Mine`'s current `version`. A mismatch is rejected with
    `ERR_STALE_MINE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/run_create_with_a_stale_mine_version_is_rejected
    """
    world = fx.mine_with_producing_panel(
        api, mine_kwargs=dict(_MINE), panel_kwargs=dict(_PANEL)
    )
    mine_id = world["mine"]["id"]
    panel_id = world["panel"]["id"]

    stale_version = fx.mine_version(api, mine_id)
    derated = fx.set_hoist_status(
        api, mine_id, HOIST_DERATED, note="one skip out of service"
    )
    fresh_version = derated["version"]
    assert fresh_version == stale_version + 1

    validate_error(
        api.create_run(
            f.run_payload(mine_id, panel_id, stale_version, **_RUN), MINE_PLANNER
        ),
        ERR_STALE_MINE_VERSION,
        412,
    )
    refused = fx.refresh_mine(api, mine_id)
    assert refused["version"] == fresh_version
    assertions.assert_tons(
        refused["scheduled_hoist_tons_open"], 0, "scheduled_hoist_tons_open"
    )
    assert fx.runs_of_mine(api, mine_id) == []

    run = validate_success(
        api.create_run(
            f.run_payload(mine_id, panel_id, fresh_version, **_RUN), MINE_PLANNER
        ),
        201,
    )
    assert run["status"] == RUN_SCHEDULED
    assertions.assert_rate_per_hour(run["planned_tons_per_hour"], 41.6667)

    scheduled = fx.refresh_mine(api, mine_id)
    assert scheduled["version"] == fresh_version + 1
    assertions.assert_tons(
        scheduled["scheduled_hoist_tons_open"], 1000.00, "scheduled_hoist_tons_open"
    )
    assertions.assert_hoist_capacity_view(
        fx.hoist_capacity(api, mine_id),
        rated=24000,
        hoist_factor=0.55,
        compliance_factor=1.00,
        effective=13200.00,
        scheduled_open=1000.00,
        scheduled_run_count=1,
    )


def test_raising_a_second_order_on_the_version_the_first_consumed_is_refused(api):
    """
    Two 200 t calls are placed back to back on one active contract: the first bumps the
    contract, so the second may not reuse the version it consumed, and the refusal
    arrives even though the take band still has 900.00 t of headroom.
    "`POST /salt/delivery-orders` requires `expected_bid_contract_version`, matching
    the target `BidContract`'s current `version`. A mismatch is rejected with
    `ERR_STALE_BID_CONTRACT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/order_create_with_a_stale_bid_contract_version_is_rejected
    """
    world = _contract_world(api)
    contract_id = world["contract"]["id"]
    depot_id = world["depot"]["id"]

    stale_version = world["contract"]["version"]
    fx.create_order(api, contract_id, depot_id, stale_version, **_ORDER)
    fresh_version = fx.contract_version(api, contract_id)
    assert fresh_version == stale_version + 1

    validate_error(
        api.create_order(
            f.order_payload(contract_id, depot_id, stale_version, **_ORDER), LOGISTICS
        ),
        ERR_STALE_BID_CONTRACT_VERSION,
        412,
    )
    refused = fx.refresh_contract(api, contract_id)
    assert refused["version"] == fresh_version
    _rows, meta = validate_paginated(
        api.list_orders(LOGISTICS, {"bid_contract_id": contract_id})
    )
    assertions.assert_page_meta(meta, total_count=1)

    second = validate_success(
        api.create_order(
            f.order_payload(contract_id, depot_id, fresh_version, **_ORDER), LOGISTICS
        ),
        201,
    )
    assert second["status"] == ORDER_REQUESTED
    _rows, meta = validate_paginated(
        api.list_orders(LOGISTICS, {"bid_contract_id": contract_id})
    )
    assertions.assert_page_meta(meta, total_count=2)
    assert fx.refresh_contract(api, contract_id)["version"] == fresh_version + 1

    ledger = fx.contract_ledger(api, contract_id)
    assertions.assert_tons(
        ledger["take_band_consumed_tons"], 400.00, "take_band_consumed_tons"
    )
    assertions.assert_tons(ledger["take_band_limit_tons"], 1100.00, "take_band_limit_tons")


def test_reserving_by_hand_on_a_lot_version_a_quarantine_round_trip_moved_is_refused(api):
    """
    A quarantine and its clearance leave the pile at 940.00 t and the lot back on
    AVAILABLE, but each change bumped the lot's `version`, so a manual reservation
    carrying the pre-quarantine token is refused before any tonnage check runs; the
    re-read token then reserves the 500 t cleanly.
    "`POST /salt/allocations` requires `expected_stockpile_lot_version`, matching the
    target `StockpileLot`'s current `version`. A mismatch is rejected with
    `ERR_STALE_STOCKPILE_LOT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/allocation_create_with_a_stale_stockpile_lot_version_is_rejected
    """
    world = _contract_world(api)
    lot_id = world["lot"]["id"]
    order = fx.create_order(
        api,
        world["contract"]["id"],
        world["depot"]["id"],
        requested_tons=500,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=82.00,
    )

    stale_version = world["lot"]["version"]
    held = validate_success(
        api.set_quarantine_state(
            lot_id,
            f.quarantine_payload(
                True, quarantine_reason="spot sample pulled for chloride assay"
            ),
            LAB_LEAD,
        ),
        200,
    )
    assert held["lot_state"] == LOT_QUARANTINED
    cleared = validate_success(
        api.set_quarantine_state(lot_id, f.quarantine_payload(False), LAB_LEAD), 200
    )
    assert cleared["lot_state"] == LOT_AVAILABLE
    fresh_version = cleared["version"]
    assert fresh_version == stale_version + 2

    validate_error(
        api.create_allocation(
            f.allocation_payload(order["id"], lot_id, 500, stale_version), LOGISTICS
        ),
        ERR_STALE_STOCKPILE_LOT_VERSION,
        412,
    )
    refused = fx.refresh_lot(api, lot_id)
    assert refused["version"] == fresh_version
    assertions.assert_lot_tonnage(refused, on_hand=940.00, reserved=0, available=940.00)
    _rows, meta = validate_paginated(
        api.list_allocations(LOGISTICS, {"delivery_order_id": order["id"]})
    )
    assertions.assert_page_meta(meta, total_count=0)

    allocation = validate_success(
        api.create_allocation(
            f.allocation_payload(order["id"], lot_id, 500, fresh_version), LOGISTICS
        ),
        201,
    )
    assert allocation["origin"] == ORIGIN_MANUAL
    assert allocation["rank_position"] == 1
    assert allocation["state"] == ALLOCATION_RESERVED
    assertions.assert_tons(allocation["tons"], 500.00, "tons")

    reserved = fx.refresh_lot(api, lot_id)
    assertions.assert_lot_tonnage(reserved, on_hand=940.00, reserved=500.00, available=440.00)
    assert reserved["version"] == fresh_version + 1
    assertions.assert_tons(
        fx.refresh_order(api, order["id"])["allocated_tons"], 500.00, "allocated_tons"
    )
