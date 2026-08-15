"""Composite setup helpers.

Every test starts against an empty database (the harness restarts the server
before each test), so these helpers build complete precondition chains out of
PRD-declared endpoints only. All setup calls use the lenient get_success_data
validator so a setup failure surfaces as a clear "Setup step failed" error.

Seal safety: sealing requires the recorded oxygen reading to sit at the room's
setpoint. Every seal helper first posts a reading exactly equal to the room's
o2_setpoint_pct (deviation zero passes the tolerance gate for any non-negative
tolerance), keeping fixtures independent of the PRD-unnamed tolerance value.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    atmosphere_reading_payload,
    close_pool_payload,
    complete_run_payload,
    create_allocation_payload,
    create_block_payload,
    create_ca_room_payload,
    create_grower_payload,
    create_inspection_payload,
    create_lot_payload,
    create_packing_run_payload,
    create_pool_payload,
    create_spec_payload,
    presize_payload,
    record_sale_payload,
    seal_payload,
    set_clock_payload,
)
from .test_users import TEST_USERS

ADMIN = TEST_USERS["admin_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
STORAGE = TEST_USERS["storage_operator_headers"]
SUPERVISOR = TEST_USERS["packing_supervisor_headers"]
POOL_MGR = TEST_USERS["pool_manager_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-resource creation
# ---------------------------------------------------------------------------

def set_logical_clock(to_iso8601):
    """Drive the logical clock forward (Admin-only, test-driving endpoint)."""
    return get_success_data(api_client.set_logical_clock(set_clock_payload(to_iso8601), ADMIN))


def create_grower(name="Grower One", grower_code="G1"):
    """Register a grower. Returns the grower."""
    return get_success_data(
        api_client.create_grower(create_grower_payload(name, grower_code), ADMIN))


def create_block(grower_id, variety=TEST_DEFAULTS["VARIETY"],
                 storage_life_days=TEST_DEFAULTS["STORAGE_LIFE_DAYS"],
                 orchard_name=TEST_DEFAULTS["ORCHARD_NAME"],
                 block_code=TEST_DEFAULTS["BLOCK_CODE"]):
    """Register an orchard block under a grower. Returns the block."""
    return get_success_data(api_client.create_block(
        grower_id,
        create_block_payload(orchard_name=orchard_name, block_code=block_code,
                             variety=variety, storage_life_days=storage_life_days),
        CLERK))


def create_grower_with_block(variety=TEST_DEFAULTS["VARIETY"],
                             storage_life_days=TEST_DEFAULTS["STORAGE_LIFE_DAYS"],
                             grower_name="Grower One", grower_code="G1",
                             orchard_name=TEST_DEFAULTS["ORCHARD_NAME"],
                             block_code=TEST_DEFAULTS["BLOCK_CODE"]):
    """Grower plus one orchard block. Returns (grower, block)."""
    grower = create_grower(grower_name, grower_code)
    block = create_block(grower["id"], variety=variety,
                         storage_life_days=storage_life_days,
                         orchard_name=orchard_name, block_code=block_code)
    return grower, block


def receive_lot(grower_id, block_id, received_bin_count=5, received_weight_lbs=4000,
                avg_color_pct=80):
    """Receive a lot (born RECEIVED, weight_balance_lbs == received weight)."""
    return get_success_data(api_client.create_lot(
        create_lot_payload(grower_id, block_id, received_bin_count,
                           received_weight_lbs, avg_color_pct),
        CLERK))


def presize_lot(lot_id, size_small_lbs=500, size_medium_lbs=2000,
                size_large_lbs=1000, presize_cull_lbs=500):
    """Run the presize line over a RECEIVED lot. Returns the PRESIZED lot."""
    return get_success_data(api_client.presize_lot(
        lot_id,
        presize_payload(size_small_lbs, size_medium_lbs, size_large_lbs,
                        presize_cull_lbs),
        CLERK))


def create_room(room_code=TEST_DEFAULTS["ROOM_CODE"],
                bin_capacity=TEST_DEFAULTS["BIN_CAPACITY"],
                o2_setpoint_pct=TEST_DEFAULTS["O2_SETPOINT_PCT"]):
    """Register a CA room (born AVAILABLE at ambient oxygen)."""
    return get_success_data(api_client.create_ca_room(
        create_ca_room_payload(room_code, bin_capacity, o2_setpoint_pct), STORAGE))


def allocate_bins(room_id, lot_id, bins=5):
    """Place bins of a lot into a room. Returns the ACTIVE allocation."""
    return get_success_data(api_client.create_allocation(
        room_id, create_allocation_payload(lot_id, bins), STORAGE))


def record_o2_reading(room_id, o2_pct):
    """Record an oxygen reading. Returns the updated room."""
    return get_success_data(api_client.create_atmosphere_reading(
        room_id, atmosphere_reading_payload(o2_pct), STORAGE))


def seal_room(room, planned_open_date=TEST_DEFAULTS["PLANNED_OPEN_DATE"]):
    """Pull oxygen to exactly the room's setpoint, then seal. Returns the room."""
    record_o2_reading(room["id"], room["o2_setpoint_pct"])
    return get_success_data(
        api_client.seal_ca_room(room["id"], seal_payload(planned_open_date), STORAGE))


def open_room(room_id):
    """Open a SEALED room. Returns the OPENED room."""
    return get_success_data(api_client.open_ca_room(room_id, STORAGE))


def release_allocation(allocation_id):
    """Manually release an ACTIVE allocation. Returns the RELEASED allocation."""
    return get_success_data(api_client.release_allocation(allocation_id, STORAGE))


def create_active_spec(color_min_pct=TEST_DEFAULTS["COLOR_MIN_PCT"],
                       customer_name=TEST_DEFAULTS["CUSTOMER_NAME"],
                       label_code=TEST_DEFAULTS["LABEL_CODE"],
                       grade_min=TEST_DEFAULTS["GRADE_MIN"],
                       size_class=TEST_DEFAULTS["SIZE_CLASS"],
                       pack_style=TEST_DEFAULTS["PACK_STYLE"]):
    """Create a packaging spec (born ACTIVE). Returns the spec."""
    return get_success_data(api_client.create_spec(
        create_spec_payload(customer_name=customer_name, label_code=label_code,
                            grade_min=grade_min, color_min_pct=color_min_pct,
                            size_class=size_class, pack_style=pack_style),
        POOL_MGR))


def create_open_pool(variety=TEST_DEFAULTS["VARIETY"],
                     grade_class=TEST_DEFAULTS["GRADE_CLASS"],
                     season=TEST_DEFAULTS["SEASON"]):
    """Open a marketing pool (born OPEN, totals zeroed). Returns the pool."""
    return get_success_data(
        api_client.create_pool(create_pool_payload(variety, grade_class, season),
                               POOL_MGR))


def record_sale(pool_id, cartons_sold=10, gross_revenue_cents=30000,
                deduction_cents=0):
    """Record a pooled sale. Returns the updated pool."""
    return get_success_data(api_client.record_pool_sale(
        pool_id, record_sale_payload(cartons_sold, gross_revenue_cents,
                                     deduction_cents),
        POOL_MGR))


# ---------------------------------------------------------------------------
# Tier 2: storage chain (grower -> block -> lot -> room -> allocation)
# ---------------------------------------------------------------------------

def setup_stored_lot(received_bin_count=5, received_weight_lbs=4000,
                     avg_color_pct=80, bins=None,
                     storage_life_days=TEST_DEFAULTS["STORAGE_LIFE_DAYS"],
                     variety=TEST_DEFAULTS["VARIETY"],
                     bin_capacity=TEST_DEFAULTS["BIN_CAPACITY"],
                     o2_setpoint_pct=TEST_DEFAULTS["O2_SETPOINT_PCT"]):
    """Grower + block + lot allocated into a room.

    Returns a ctx dict: lot IN_STORAGE, room FILLING, allocation ACTIVE.
    """
    grower, block = create_grower_with_block(
        variety=variety, storage_life_days=storage_life_days)
    lot = receive_lot(grower["id"], block["id"], received_bin_count,
                      received_weight_lbs, avg_color_pct)
    room = create_room(bin_capacity=bin_capacity, o2_setpoint_pct=o2_setpoint_pct)
    allocation = allocate_bins(room["id"], lot["id"],
                               bins if bins is not None else received_bin_count)
    return {"grower": grower, "block": block, "lot": lot, "room": room,
            "allocation": allocation}


def setup_sealed_storage(planned_open_date=TEST_DEFAULTS["PLANNED_OPEN_DATE"],
                         **kwargs):
    """Stored lot whose room is then SEALED. Returns the ctx dict."""
    ctx = setup_stored_lot(**kwargs)
    ctx["room"] = seal_room(ctx["room"], planned_open_date)
    return ctx


def setup_released_lot(planned_open_date=TEST_DEFAULTS["PLANNED_OPEN_DATE"],
                       **kwargs):
    """Full storage chain through release: lot RELEASED and packable.

    With a single allocation, the release empties the OPENED room back to
    AVAILABLE. Returns the ctx dict (room reflects its post-release state).
    """
    ctx = setup_sealed_storage(planned_open_date=planned_open_date, **kwargs)
    ctx["room"] = open_room(ctx["room"]["id"])
    ctx["allocation"] = release_allocation(ctx["allocation"]["id"])
    ctx["lot"] = get_success_data(api_client.get_lot(ctx["lot"]["id"], ADMIN))
    ctx["room"] = get_success_data(api_client.get_ca_room(ctx["room"]["id"], ADMIN))
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: packing-line chain (released lot + spec + pool + runs)
# ---------------------------------------------------------------------------

def setup_packable_lot(color_min_pct=TEST_DEFAULTS["COLOR_MIN_PCT"], **kwargs):
    """Released lot plus an ACTIVE spec and an OPEN pool.

    Returns ctx dict with keys: grower, block, lot, room, allocation, spec, pool.
    """
    ctx = setup_released_lot(**kwargs)
    ctx["spec"] = create_active_spec(color_min_pct=color_min_pct)
    ctx["pool"] = create_open_pool()
    return ctx


def schedule_run(ctx, input_weight_lbs=500,
                 scheduled_start=TEST_DEFAULTS["RUN_START"],
                 scheduled_end=TEST_DEFAULTS["RUN_END"],
                 line_code=TEST_DEFAULTS["LINE_CODE"]):
    """Schedule a packing run against the ctx's lot/spec/pool. Returns the run."""
    return get_success_data(api_client.create_packing_run(
        create_packing_run_payload(
            ctx["lot"]["id"], ctx["spec"]["id"], ctx["pool"]["id"],
            line_code=line_code, scheduled_start=scheduled_start,
            scheduled_end=scheduled_end, input_weight_lbs=input_weight_lbs),
        SUPERVISOR))


def complete_run(run_id, cartons_produced=20, packed_weight_lbs=3400,
                 cull_weight_lbs=400, juice_weight_lbs=200):
    """Complete a SCHEDULED run. Returns the COMPLETED run."""
    return get_success_data(api_client.complete_packing_run(
        run_id,
        complete_run_payload(cartons_produced, packed_weight_lbs,
                             cull_weight_lbs, juice_weight_lbs),
        SUPERVISOR))


def setup_completed_run(input_weight_lbs=4000, cartons_produced=20,
                        packed_weight_lbs=3400, cull_weight_lbs=400,
                        juice_weight_lbs=200, **kwargs):
    """Packable lot plus one COMPLETED run (settlement auto-created).

    Returns ctx dict with keys: ..., spec, pool, run, settlement.
    """
    ctx = setup_packable_lot(**kwargs)
    ctx["run"] = schedule_run(ctx, input_weight_lbs=input_weight_lbs)
    ctx["run"] = complete_run(ctx["run"]["id"], cartons_produced,
                              packed_weight_lbs, cull_weight_lbs, juice_weight_lbs)
    ctx["lot"] = get_success_data(api_client.get_lot(ctx["lot"]["id"], ADMIN))
    ctx["settlement"] = get_pool_settlement(ctx["pool"]["id"], ctx["grower"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: pool close / settlement helpers
# ---------------------------------------------------------------------------

def get_pool_settlement(pool_id, grower_id=None):
    """Fetch the (single) settlement for a pool, optionally pinned by grower."""
    params = {"pool_id": pool_id}
    if grower_id is not None:
        params["grower_id"] = grower_id
    data, _meta = validate_paginated(api_client.list_settlements(ADMIN, params=params))
    assert len(data) >= 1, f"Setup failed: no settlement found for pool {pool_id}"
    return data[0]


def get_pool_version(pool_id):
    """Read the pool and return its current version (OCC echo)."""
    return get_success_data(api_client.get_pool(pool_id, ADMIN))["version"]


def close_pool_fresh(pool_id):
    """Close a pool with a freshly read version. Returns the CLOSED pool."""
    return get_success_data(api_client.close_pool(
        pool_id, close_pool_payload(get_pool_version(pool_id)), POOL_MGR))


def refresh_pool(pool_id):
    return get_success_data(api_client.get_pool(pool_id, ADMIN))


def refresh_lot(lot_id):
    return get_success_data(api_client.get_lot(lot_id, ADMIN))


def refresh_room(room_id):
    return get_success_data(api_client.get_ca_room(room_id, ADMIN))


def refresh_allocation(allocation_id):
    return get_success_data(api_client.get_allocation(allocation_id, ADMIN))


def refresh_settlement(settlement_id):
    return get_success_data(api_client.get_settlement(settlement_id, ADMIN))


def record_inspection(room_id, scald_pct=4.0, bitter_pit_pct=3.0, decay_pct=4.9):
    """Record a storage-disorder inspection. Returns the inspection event."""
    return get_success_data(api_client.create_inspection(
        room_id,
        create_inspection_payload(scald_pct, bitter_pit_pct, decay_pct),
        STORAGE))
