"""Manual allocations: OCC on LPN version, availability ceiling, the cyclic
STORED<->ALLOCATED plate disposition, and the conserved-quantity invariant under
allocate-then-cancel.

Covers queue-A difficulty instances (non_linear_state_machine lpn cycle,
compensating_invariant available_qty, priority_pair stale-beats-insufficient) and
queue-B corner instances under state_machines (stale OCC) and validations
(insufficient available).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_inventory_allocation, assert_license_plate, assert_sku_invariants,
    create_allocation_payload,
)
import test_helpers as th

PLANNER = TEST_USERS["wave_planner_headers"]


def test_full_reservation_drives_lpn_allocated_then_cancel_reverts_stored(api):
    """PRD 3.5: "a plate transitions STORED to ALLOCATED only when an allocation is
    created against it and the sum of its RESERVED and COMMITTED allocation
    quantities equals the plate's full qty". PRD 3.6: "The release recomputes the
    line's allocated_qty and the SKU's available_qty, and if the plate is no longer
    fully reserved it reverts from ALLOCATED to STORED".

    Design: Difficulty/non_linear_state_machine/lpn_cyclic_stored_allocated_revert
    """
    sku, loc, lpn = th.setup_stored_lpn(sku_overrides={"sku_code": "SKU-C1", "abc_class": "A", "each_volume_cm3": 1}, qty=10)
    order, line = th.create_order_with_line(sku["id"], 10)
    alloc = th.create_manual_allocation(line["id"], lpn["id"], 10)
    lpn_alloc = validate_success(api.get_license_plate(lpn["id"], PLANNER))
    assert lpn_alloc["disposition"] == "ALLOCATED"
    cancelled = validate_success(api.cancel_allocation(alloc["id"], PLANNER))
    assert cancelled["status"] == "RELEASED"
    lpn_now = validate_success(api.get_license_plate(lpn["id"], PLANNER))
    assert_license_plate(lpn_now)
    assert lpn_now["disposition"] == "STORED"


def test_allocate_then_cancel_conserves_available_qty(api):
    """PRD 3.1: "The available_qty is the SKU's on_hand_qty minus the sum of
    allocated_qty across that SKU's allocations that are RESERVED or COMMITTED".
    PRD 3.6: "The release recomputes the line's allocated_qty and the SKU's
    available_qty".

    Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_available_qty
    """
    sku, loc, lpn = th.setup_stored_lpn(sku_overrides={"sku_code": "SKU-I1", "abc_class": "A", "each_volume_cm3": 1}, qty=10)
    order, line = th.create_order_with_line(sku["id"], 10)
    alloc = th.create_manual_allocation(line["id"], lpn["id"], 10)
    th.get_success_data(api.cancel_allocation(alloc["id"], PLANNER))
    sku_now = validate_success(api.get_sku(sku["id"], PLANNER))
    assert sku_now["on_hand_qty"] == 10
    assert sku_now["available_qty"] == 10
    assert_sku_invariants(sku_now)


def test_stale_lpn_version_on_manual_allocation_rejected(api):
    """PRD 2.8: "if the plate's version has advanced since the client read it — because
    another reservation, a pick confirm, or a replenishment drain already changed its
    quantity or disposition — the client's available-quantity view is out of date and
    the create is rejected with ERR_STALE_LPN_VERSION (HTTP 412)."

    Design: Corner/state_machines/stale_lpn_version_conflict_on_manual_allocation
    """
    sku, loc, lpn = th.setup_stored_lpn(sku_overrides={"sku_code": "SKU-OCC", "abc_class": "A", "each_volume_cm3": 1}, qty=10)
    order, line = th.create_order_with_line(sku["id"], 10)
    stale_version = validate_success(api.get_license_plate(lpn["id"], PLANNER))["version"]
    # First allocation of 4 succeeds and bumps the LPN version.
    th.get_success_data(api.create_allocation(
        create_allocation_payload(line["id"], lpn["id"], 4, stale_version), PLANNER))
    # Second allocation reuses the now-stale version.
    resp = api.create_allocation(
        create_allocation_payload(line["id"], lpn["id"], 3, stale_version), PLANNER)
    validate_error(resp, ApiErrorId.ERR_STALE_LPN_VERSION.value, 412)


def test_over_reserve_lpn_returns_insufficient_available(api):
    """PRD 3.6: "A reservation may not draw more than the plate's free quantity — the
    plate's qty minus the eaches already RESERVED or COMMITTED against that plate —
    and may not exceed the SKU's available_qty; a request that would breach either
    ceiling is rejected with ERR_INSUFFICIENT_AVAILABLE."

    Design: Corner/validations/over_reserve_lpn_returns_insufficient_available
    """
    sku, loc, lpn = th.setup_stored_lpn(sku_overrides={"sku_code": "SKU-IA1", "abc_class": "A", "each_volume_cm3": 1}, qty=10)
    order, line = th.create_order_with_line(sku["id"], 20)
    current_version = validate_success(api.get_license_plate(lpn["id"], PLANNER))["version"]
    resp = api.create_allocation(
        create_allocation_payload(line["id"], lpn["id"], 12, current_version), PLANNER)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE.value, 409)


def test_stale_lpn_version_beats_insufficient_available(api):
    """PRD 2.11: "sixth, the OCC version check on the two guarded paths
    (ERR_STALE_WAVE_VERSION or ERR_STALE_LPN_VERSION); ... and thereafter the
    remaining domain-specific business constraints described in Section 3
    (uniqueness, capacity, pick-face dedication, replenishment eligibility,
    availability, open-line, selector-emptiness, and pick-to-light checks)."
    PRD 2.11: "an earlier check, when it fires, masks all later ones."

    Design: Difficulty/priority_pair_validation_conflict/allocation_stale_lpn_beats_insufficient_available
    """
    sku, loc, lpn = th.setup_stored_lpn(sku_overrides={"sku_code": "SKU-X2", "abc_class": "A", "each_volume_cm3": 1}, qty=10)
    order, line = th.create_order_with_line(sku["id"], 20)
    stale_version = validate_success(api.get_license_plate(lpn["id"], PLANNER))["version"]
    # An allocation of 8 succeeds and bumps the LPN version, so stale_version is now behind.
    th.get_success_data(api.create_allocation(
        create_allocation_payload(line["id"], lpn["id"], 8, stale_version), PLANNER))
    # This request BOTH carries the stale version AND over-reserves (5 > free 2):
    # the OCC check fires first.
    resp = api.create_allocation(
        create_allocation_payload(line["id"], lpn["id"], 5, stale_version), PLANNER)
    validate_error(resp, ApiErrorId.ERR_STALE_LPN_VERSION.value, 412)
