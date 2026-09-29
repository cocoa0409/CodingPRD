"""
Immediate consistency on the Salt Deicing Operations API (PRD §2.9).

The system carries no background sweep and no reconciliation endpoint, so the request
that changes a fact must already report every number derived from it. This module
takes the storm allocation waterfall — the write that touches an order, a lot and the
depot's storage posture at once — and checks that the reads which follow it add
nothing the write had not already published.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success

from test_helpers import assertions
from test_helpers import fixtures as fx
from test_helpers.constants import (
    ALLOCATION_RESERVED,
    ORDER_ALLOCATED,
    ORIGIN_WATERFALL,
    PENALTY_NONE,
)
from test_helpers.test_users import LOGISTICS

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


def test_the_allocate_response_already_reports_what_the_later_reads_report(api):
    """
    A 500 t routine call is filled from the single 940.00 t pile in the local shed, and
    the fill response itself carries the order's new status and tonnage; re-reading the
    order, the lot, the depot's storage posture and the allocation list afterwards adds
    nothing that the write had not already published.
    "When one request changes a fact, every number derived from that fact is brought up
    to date inside the same request, and every entity whose stored values changed has
    its `updated_at` refreshed and its `version` incremented by exactly 1."

    Design: Corner/consistency_model/allocate_response_already_carries_every_recomputed_field
    """
    world = fx.standard_world(
        api,
        mine_kwargs=dict(_MINE),
        panel_kwargs=dict(_PANEL),
        depot_kwargs=dict(_DEPOT),
        run_kwargs=dict(_RUN),
        batch_kwargs=dict(_BATCH),
        contract_kwargs=dict(_CONTRACT),
        hoisted_tons=1000,
    )
    lot_before = world["lot"]
    assertions.assert_lot_tonnage(
        lot_before, on_hand=940.00, reserved=0, available=940.00
    )
    order_before = fx.create_order(
        api,
        world["contract"]["id"],
        world["depot"]["id"],
        requested_tons=500,
        required_by="2026-12-01T00:00:00Z",
        market_index_price_per_ton=82.00,
    )

    written = validate_success(api.allocate_order(order_before["id"], LOGISTICS), 200)
    assert written["status"] == ORDER_ALLOCATED
    assertions.assert_tons(written["allocated_tons"], 500.00, "allocated_tons")
    assertions.assert_tons(written["shorted_tons"], 0, "shorted_tons")
    assert written["penalty_state"] == PENALTY_NONE
    assertions.assert_version_bumped(written, order_before)

    reread = fx.refresh_order(api, order_before["id"])
    assert reread["status"] == written["status"]
    assert reread["allocated_tons"] == written["allocated_tons"]
    assert reread["shorted_tons"] == written["shorted_tons"]
    assert reread["penalty_state"] == written["penalty_state"]
    assert reread["version"] == written["version"]
    assert reread["updated_at"] == written["updated_at"]

    lot_after = fx.refresh_lot(api, lot_before["id"])
    assertions.assert_lot_tonnage(
        lot_after, on_hand=940.00, reserved=500.00, available=440.00
    )
    assertions.assert_version_bumped(lot_after, lot_before)

    posture = fx.storage_posture(api, world["depot"]["id"])
    assertions.assert_tons(posture["reserved_tons"], 500.00, "reserved_tons")
    assertions.assert_tons(posture["covered_stored_tons"], 940.00, "covered_stored_tons")
    assertions.assert_amount(
        posture["covered_utilization_pct"], 18.80, 2, "covered_utilization_pct"
    )
    assertions.assert_posture_view_threshold(posture)

    rows, meta = validate_paginated(
        api.list_allocations(LOGISTICS, {"delivery_order_id": order_before["id"]})
    )
    assertions.assert_page_meta(meta, total_count=1, has_more=False)
    row = assertions.only(rows)
    assertions.assert_tons(row["tons"], 500.00, "tons")
    assert row["origin"] == ORIGIN_WATERFALL
    assert row["state"] == ALLOCATION_RESERVED
    assert row["rank_position"] == 1
    assert row["stockpile_lot_id"] == lot_before["id"]
