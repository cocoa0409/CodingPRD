"""Waves and picking: the two parallel status axes, the deterministic allocation
waterfall, OCC on release, the empty-wave guard, the depth-4 pick-confirm cascade,
pick-to-light, short-pick compensation, shipment, and terminal lockdown.

Covers queue-A difficulty instances (non_linear_state_machine wave axes,
transitive_cascade depth-4, cross_entity_state_dependency empty wave) and queue-B
corner instances under state_machines, calculations, errors, and the cross-cutting
layers (stale wave, derived volume reconciliation after ship).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_wave, assert_pick_task, assert_outbound_order,
    confirm_pick_payload, release_wave_payload, add_order_to_wave_payload,
    create_order_line_payload,
)
import test_helpers as th

ADMIN = TEST_USERS["platform_admin_headers"]
PLANNER = TEST_USERS["wave_planner_headers"]
PICKER = TEST_USERS["picker_headers"]
PUTAWAY = TEST_USERS["putaway_operator_headers"]


# ── Parallel axes (queue A) ───────────────────────────────────────────────────

def test_wave_release_and_start_picking_advance_independent_axes(api):
    """PRD 3.7: "A successful release advances release_status from PLANNING to
    RELEASED, runs the allocation waterfall (Section 3.8) to create RESERVED
    allocations, sets fulfillment_status from UNALLOCATED to ALLOCATED, drives every
    newly fully-reserved plate from STORED to ALLOCATED, recomputes available_qty for
    the affected SKUs, and increments the wave's version." PRD 3.7: "it advances
    fulfillment_status from ALLOCATED to PICKING, spawns one PickTask (in status
    PENDING) per allocation of the wave, drives each WAVED order of the wave to
    PICKING, and increments the wave's version; release_status stays RELEASED."

    Design: Difficulty/non_linear_state_machine/wave_parallel_release_and_fulfillment_axes
    """
    sku, loc, lpn, order, line, wave = th.setup_released_wave(
        sku_overrides={"sku_code": "SKU-W1", "abc_class": "A", "each_volume_cm3": 1}, ordered_qty=10, lpn_qty=10)
    assert wave["release_status"] == "RELEASED"
    assert wave["fulfillment_status"] == "ALLOCATED"
    after = validate_success(api.start_picking_wave(wave["id"], PLANNER))
    assert_wave(after)
    assert after["release_status"] == "RELEASED"
    assert after["fulfillment_status"] == "PICKING"


def test_wave_release_requires_at_least_one_order(api):
    """PRD 3.7: "the wave must already hold at least one order — a release of an
    order-less wave is rejected with ERR_CROSS_ENTITY_STATE."

    Design: Difficulty/cross_entity_state_dependency/wave_release_requires_at_least_one_order
    """
    wave = th.create_planning_wave(wave_label="WAVE-EMPTY")
    resp = api.release_wave(wave["id"], release_wave_payload(wave["version"]), PLANNER)
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE.value, 409)
    now = validate_success(api.get_wave(wave["id"], PLANNER))
    assert now["release_status"] == "PLANNING"


def test_pick_confirm_cascade_picks_order_and_closes_wave(api):
    """PRD 3.9: "If every line of the order is now fully picked ... the order bubbles
    from PICKING to PICKED. If no pick task of the wave remains PENDING or
    IN_PROGRESS, the wave's fulfillment_status bubbles from PICKING to PICKED (and,
    as noted, the release_status closes)." PRD 3.7: "the system bubbles
    fulfillment_status from PICKING to PICKED and, in the same step, bubbles
    release_status from RELEASED to CLOSED."

    Design: Difficulty/transitive_cascade/pick_confirm_cascade_depth4
    """
    sku, loc, lpn, order, line, wave, pick = th.setup_in_progress_pick(
        sku_overrides={"sku_code": "SKU-P1", "abc_class": "A", "each_volume_cm3": 1}, ordered_qty=10, lpn_qty=10)
    done = validate_success(api.confirm_pick_task(pick["id"], confirm_pick_payload(True), PICKER))
    assert done["status"] == "PICKED"
    order_now = validate_success(api.get_outbound_order(order["id"], PLANNER))
    assert order_now["status"] == "PICKED"
    wave_now = validate_success(api.get_wave(wave["id"], PLANNER))
    assert wave_now["fulfillment_status"] == "PICKED"
    assert wave_now["release_status"] == "CLOSED"


# ── Allocation waterfall (queue B) ────────────────────────────────────────────

def test_wave_release_allocates_oldest_lpn_first(api):
    """PRD 3.8: "Supply is drawn from the STORED license plates of the line's SKU that
    still have free quantity, sorted oldest-received first by created_at ascending".
    PRD 3.1: "The available_qty is the SKU's on_hand_qty minus the sum of
    allocated_qty across that SKU's allocations that are RESERVED or COMMITTED".

    Design: Corner/calculations/wave_allocation_waterfall_oldest_lpn_first
    """
    sku = th.create_sku(sku_code="SKU-WA1", abc_class="A", each_volume_cm3=1, min_qty=1, max_qty=100)
    th.create_location(location_code="RS-WA1", zone="RESERVE", max_volume_cm3=10000)
    asn = th.create_asn(asn_number="ASN-WA1")
    line = th.add_asn_line(asn["id"], sku["id"], 14)
    rA = th.post_receipt(asn["id"], line["id"], 6)  # older
    rB = th.post_receipt(asn["id"], line["id"], 8)  # newer
    th.get_success_data(api.close_asn(asn["id"], th.CLERK))
    for receipt in (rA, rB):
        task = th.first_putaway_task_for_lpn(receipt["lpn_id"])
        th.get_success_data(api.assign_putaway_task(task["id"], PUTAWAY))
        th.get_success_data(api.complete_putaway_task(task["id"], PUTAWAY))
    order, oline = th.create_order_with_line(sku["id"], 10)
    wave = th.create_planning_wave(wave_label="WAVE-WA1")
    th.get_success_data(api.add_order_to_wave(wave["id"], add_order_to_wave_payload(order["id"]), PLANNER))
    wave = validate_success(api.get_wave(wave["id"], PLANNER))
    th.get_success_data(api.release_wave(wave["id"], release_wave_payload(wave["version"]), PLANNER))
    oline_now = validate_success(api.get_order_line(oline["id"], PLANNER))
    assert oline_now["allocated_qty"] == 10
    sku_now = validate_success(api.get_sku(sku["id"], PLANNER))
    assert sku_now["on_hand_qty"] == 14
    assert sku_now["available_qty"] == 4


# ── Pick-to-light, short pick, ship (queue B) ─────────────────────────────────

def test_pick_confirm_without_light_returns_light_required(api):
    """PRD 3.9: "a confirm submitted with light_confirmed not true (the operator did
    not press the bin light) is rejected with ERR_VALIDATION_LIGHT_REQUIRED."

    Design: Corner/errors/pick_confirm_without_light_returns_light_required
    """
    sku, loc, lpn, order, line, wave, pick = th.setup_in_progress_pick(
        sku_overrides={"sku_code": "SKU-LT1", "abc_class": "A", "each_volume_cm3": 1}, ordered_qty=5, lpn_qty=5)
    resp = api.confirm_pick_task(pick["id"], confirm_pick_payload(False), PICKER)
    validate_error(resp, ApiErrorId.ERR_VALIDATION_LIGHT_REQUIRED.value, 409)
    now = validate_success(api.get_pick_task(pick["id"], PICKER))
    assert now["status"] == "IN_PROGRESS"


def test_short_pick_releases_allocation_and_reverts_lpn(api):
    """PRD 3.9: "A short pick is the compensation path: rather than committing, it
    drives the task's allocation from RESERVED to RELEASED, recomputes the order
    line's allocated_qty and the SKU's available_qty, and — if the plate is no longer
    fully reserved — reverts the plate from ALLOCATED to STORED".

    Design: Corner/state_machines/short_pick_releases_allocation_reverts_lpn
    """
    sku, loc, lpn, order, line, wave, pick = th.setup_in_progress_pick(
        sku_overrides={"sku_code": "SKU-SH1", "abc_class": "A", "each_volume_cm3": 1}, ordered_qty=5, lpn_qty=5)
    done = validate_success(api.short_pick_task(pick["id"], PICKER))
    assert done["status"] == "SHORT"
    lpn_now = validate_success(api.get_license_plate(lpn["id"], PICKER))
    assert lpn_now["disposition"] == "STORED"
    line_now = validate_success(api.get_order_line(line["id"], PLANNER))
    assert line_now["allocated_qty"] == 0


def test_cancel_shipped_order_returns_invalid_state(api):
    """PRD 3.6: "An order that is still OPEN, not yet waved, may be cancelled, moving
    it from OPEN to CANCELLED." PRD 3.9: "The order's terminal states are SHIPPED and
    CANCELLED."

    Design: Corner/state_machines/terminal_shipped_order_cannot_cancel
    """
    sku, loc, lpn, order, line, wave, pick = th.setup_in_progress_pick(
        sku_overrides={"sku_code": "SKU-TL1", "abc_class": "A", "each_volume_cm3": 1}, ordered_qty=4, lpn_qty=4)
    th.get_success_data(api.confirm_pick_task(pick["id"], confirm_pick_payload(True), PICKER))
    th.get_success_data(api.ship_order(order["id"], PICKER))
    resp = api.cancel_order(order["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    now = validate_success(api.get_outbound_order(order["id"], PLANNER))
    assert now["status"] == "SHIPPED"


def test_used_volume_reconciles_to_zero_after_ship(api):
    """PRD 3.9: "Shipment drives each PICKED_STAGED plate behind the order's COMMITTED
    allocations to SHIPPED, setting each plate's qty to zero and recomputing the
    SKU's on_hand_qty". PRD 3.1: used_volume_cm3 "is recomputed on every plate move
    in or out, as the sum over the plates resting there".

    Design: Corner/cross_cutting_complexity_layers/derived_used_volume_reconciles_after_ship
    """
    sku, loc, lpn, order, line, wave, pick = th.setup_in_progress_pick(
        sku_overrides={"sku_code": "SKU-DR1", "abc_class": "A", "each_volume_cm3": 1}, ordered_qty=5, lpn_qty=5)
    th.get_success_data(api.confirm_pick_task(pick["id"], confirm_pick_payload(True), PICKER))
    shipped = validate_success(api.ship_order(order["id"], PICKER))
    assert shipped["status"] == "SHIPPED"
    lpn_now = validate_success(api.get_license_plate(lpn["id"], PICKER))
    assert lpn_now["disposition"] == "SHIPPED"
    loc_now = validate_success(api.get_location(loc["id"], PUTAWAY))
    assert loc_now["used_volume_cm3"] == pytest.approx(0, abs=0.001)


def test_stale_wave_version_release_rejected(api):
    """PRD 2.8: "If expected_wave_version does not match the wave's current version,
    the release is rejected with ERR_STALE_WAVE_VERSION (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/stale_wave_version_release_conflict
    """
    sku, loc, lpn = th.setup_stored_lpn(sku_overrides={"sku_code": "SKU-SW1", "abc_class": "A", "each_volume_cm3": 1}, qty=5)
    order, oline = th.create_order_with_line(sku["id"], 5)
    wave = th.create_planning_wave(wave_label="WAVE-SW1")
    added = th.get_success_data(api.add_order_to_wave(wave["id"], add_order_to_wave_payload(order["id"]), PLANNER))
    current_version = validate_success(api.get_wave(wave["id"], PLANNER))["version"]
    resp = api.release_wave(wave["id"], release_wave_payload(current_version - 1), PLANNER)
    validate_error(resp, ApiErrorId.ERR_STALE_WAVE_VERSION.value, 412)
    now = validate_success(api.get_wave(wave["id"], PLANNER))
    assert now["release_status"] == "PLANNING"
