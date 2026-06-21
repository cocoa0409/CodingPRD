"""Second, distinct-angle tests for each queue-A difficulty instance.

Each test here pairs with its primary in test_03/04/05/06, exercising the same
PRD rule from a different scenario or boundary point so every difficulty instance
carries at least two tests.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    confirm_pick_payload, release_wave_payload, add_order_to_wave_payload,
    submit_cycle_count_payload, create_replenishment_task_payload,
    create_location_payload, create_allocation_payload, set_clock_payload,
    make_inventory_controller_headers,
)
import test_helpers as th

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
PUTAWAY = TEST_USERS["putaway_operator_headers"]
PLANNER = TEST_USERS["wave_planner_headers"]
PICKER = TEST_USERS["picker_headers"]
IC = TEST_USERS["inventory_controller_headers"]


# ── dual_variant_calc ─────────────────────────────────────────────────────────

def test_crossdock_selector_prefers_most_open_lane(api):
    """PRD 3.3: "Among those eligible lanes it prefers the most open one: it ranks
    candidates by largest residual capacity first, with the residual measured to two
    decimal places, and breaks ties by oldest created_at first." PRD 3.3: "(Note the
    deliberate contrast with the putaway selector in Section 3.4, which prefers the
    tightest fit — the two slotting strategies rank residual capacity in opposite
    directions.)"

    Design: Difficulty/dual_variant_calc/slotting_strategy_diverges_by_abc_class
    """
    sku = th.create_sku(sku_code="SKU-XD-MO", abc_class="A", each_volume_cm3=10, min_qty=1, max_qty=100)
    tight = th.create_location(location_code="XD-TIGHT", zone="CROSS_DOCK", max_volume_cm3=60)
    roomy = th.create_location(location_code="XD-ROOMY", zone="CROSS_DOCK", max_volume_cm3=200)
    asn = th.create_asn(asn_number="ASN-XDMO", handling_mode="CROSS_DOCK")
    line = th.add_asn_line(asn["id"], sku["id"], 5)  # need = 50
    receipt = th.post_receipt(asn["id"], line["id"], 5)
    th.get_success_data(api.close_asn(asn["id"], CLERK))
    lpn = validate_success(api.get_license_plate(receipt["lpn_id"], CLERK))
    assert lpn["disposition"] == "STORED"
    assert lpn["location_id"] == roomy["id"]


def test_cycle_count_zero_variance_when_count_matches_snapshot(api):
    """PRD 3.10: "computes variance_qty as counted_qty minus the snapshot system_qty".
    PRD 3.10: "this snapshot is captured a single time and is not re-snapshotted on
    submit."

    Design: Difficulty/dual_variant_calc/cycle_count_variance_uses_open_snapshot_not_live
    """
    sku, loc, lpn, cc = th.setup_open_cycle_count(
        stored_qty=12,
        sku_overrides={"sku_code": "SKU-B-ZV", "abc_class": "B", "each_volume_cm3": 1, "min_qty": 1, "max_qty": 100})
    assert cc["system_qty"] == 12
    counter = make_inventory_controller_headers("ic-counter-zv")
    submitted = validate_success(api.submit_cycle_count(cc["id"], submit_cycle_count_payload(12), counter))
    assert submitted["system_qty"] == 12
    assert submitted["variance_qty"] == 0
    assert submitted["status"] == "COUNTED"


# ── combinatorial_formula ─────────────────────────────────────────────────────

def test_c_class_putaway_prefers_reserve(api):
    """PRD 3.4: "a B- or C-class SKU prefers a RESERVE location for deep storage."
    PRD 3.4: "a location is preferred when its zone matches the class preference —
    PICK_FACE for A-class, RESERVE otherwise — and a non-matching zone is
    deprioritized."

    Design: Difficulty/combinatorial_formula/putaway_rank_tuple_three_input_nonlinear
    """
    sku = th.create_sku(sku_code="SKU-C-RT", abc_class="C", each_volume_cm3=10, min_qty=1, max_qty=100)
    rs = th.create_location(location_code="RS-CRT", zone="RESERVE", max_volume_cm3=100)
    th.create_location(location_code="PF-CRT", zone="PICK_FACE", max_volume_cm3=200, pick_face_for_sku_id=sku["id"])
    asn, line, lpn = th.receive_one_lpn(sku["id"], 5)
    th.get_success_data(api.close_asn(asn["id"], CLERK))
    task = th.first_putaway_task_for_lpn(lpn["id"])
    data = validate_success(api.assign_putaway_task(task["id"], PUTAWAY))
    assert data["target_location_id"] == rs["id"]


def test_location_volume_single_plate_rounds_to_two_dp(api):
    """PRD 2.7: "This sum is computed in full first and then rounded once, half-up, to
    two decimal places". PRD 3.1: used_volume_cm3 is "the sum over the plates resting
    there ... of each plate's quantity times the SKU's per-each volume".

    Design: Difficulty/combinatorial_formula/location_volume_sum_then_round
    """
    sku = th.create_sku(sku_code="SKU-V2", abc_class="C", each_volume_cm3=3.33, min_qty=1, max_qty=100)
    rs = th.create_location(location_code="RS-V2", zone="RESERVE", max_volume_cm3=1000)
    asn, line, lpn = th.receive_one_lpn(sku["id"], 4)  # 4 * 3.33 = 13.32
    th.get_success_data(api.close_asn(asn["id"], CLERK))
    task = th.first_putaway_task_for_lpn(lpn["id"])
    th.get_success_data(api.assign_putaway_task(task["id"], PUTAWAY))
    th.get_success_data(api.complete_putaway_task(task["id"], PUTAWAY))
    loc = validate_success(api.get_location(rs["id"], ADMIN))
    assert loc["used_volume_cm3"] == pytest.approx(13.32, abs=0.001)


# ── non_linear_state_machine ──────────────────────────────────────────────────

def test_release_sets_allocated_without_touching_picking(api):
    """PRD 3.7: "A successful release advances release_status from PLANNING to
    RELEASED, runs the allocation waterfall (Section 3.8) to create RESERVED
    allocations, sets fulfillment_status from UNALLOCATED to ALLOCATED, drives every
    newly fully-reserved plate from STORED to ALLOCATED, recomputes available_qty for
    the affected SKUs, and increments the wave's version."

    Design: Difficulty/non_linear_state_machine/wave_parallel_release_and_fulfillment_axes
    """
    sku, loc, lpn, order, line, wave = th.setup_released_wave(
        sku_overrides={"sku_code": "SKU-W2", "abc_class": "A", "each_volume_cm3": 1}, ordered_qty=4, lpn_qty=4)
    assert wave["release_status"] == "RELEASED"
    assert wave["fulfillment_status"] == "ALLOCATED"


def test_partial_reservation_leaves_lpn_stored(api):
    """PRD 3.5: "a plate that is only partially reserved stays STORED." PRD 3.5: "a
    plate transitions STORED to ALLOCATED only when an allocation is created against
    it and the sum of its RESERVED and COMMITTED allocation quantities equals the
    plate's full qty".

    Design: Difficulty/non_linear_state_machine/lpn_cyclic_stored_allocated_revert
    """
    sku, loc, lpn = th.setup_stored_lpn(sku_overrides={"sku_code": "SKU-C2", "abc_class": "A", "each_volume_cm3": 1}, qty=10)
    order, line = th.create_order_with_line(sku["id"], 10)
    th.create_manual_allocation(line["id"], lpn["id"], 6)  # partial: 6 < 10
    lpn_now = validate_success(api.get_license_plate(lpn["id"], PLANNER))
    assert lpn_now["disposition"] == "STORED"


# ── transitive_cascade ────────────────────────────────────────────────────────

def test_pick_confirm_commits_allocation_and_stages_plate(api):
    """PRD 3.9: "drives the allocation from RESERVED to COMMITTED and recomputes the
    order line's picked_qty; drives the picked plate from ALLOCATED to PICKED_STAGED".

    Design: Difficulty/transitive_cascade/pick_confirm_cascade_depth4
    """
    sku, loc, lpn, order, line, wave, pick = th.setup_in_progress_pick(
        sku_overrides={"sku_code": "SKU-P1B", "abc_class": "A", "each_volume_cm3": 1}, ordered_qty=7, lpn_qty=7)
    th.get_success_data(api.confirm_pick_task(pick["id"], confirm_pick_payload(True), PICKER))
    alloc = validate_success(api.get_allocation(pick["allocation_id"], PLANNER))
    assert alloc["status"] == "COMMITTED"
    lpn_now = validate_success(api.get_license_plate(lpn["id"], PICKER))
    assert lpn_now["disposition"] == "PICKED_STAGED"
    line_now = validate_success(api.get_order_line(line["id"], PLANNER))
    assert line_now["picked_qty"] == 7


def test_asn_not_closed_until_last_putaway_task_completes(api):
    """PRD 3.3: "once every putaway task spawned from the ASN has reached COMPLETED or
    CANCELLED, with at least one COMPLETED, the system bubbles the ASN from PUT_AWAY
    to CLOSED."

    Design: Difficulty/transitive_cascade/putaway_complete_cascade_depth2_closes_asn
    """
    sku = th.create_sku(sku_code="SKU-P2B", abc_class="C", each_volume_cm3=1, min_qty=1, max_qty=100)
    th.create_location(location_code="RS-P2B", zone="RESERVE", max_volume_cm3=100000)
    asn = th.create_asn(asn_number="ASN-8B")
    line = th.add_asn_line(asn["id"], sku["id"], 8)
    rA = th.post_receipt(asn["id"], line["id"], 4)
    rB = th.post_receipt(asn["id"], line["id"], 4)
    th.get_success_data(api.close_asn(asn["id"], CLERK))
    task_a = th.first_putaway_task_for_lpn(rA["lpn_id"])
    task_b = th.first_putaway_task_for_lpn(rB["lpn_id"])
    th.get_success_data(api.assign_putaway_task(task_a["id"], PUTAWAY))
    th.get_success_data(api.complete_putaway_task(task_a["id"], PUTAWAY))
    asn_mid = validate_success(api.get_inbound_asn(asn["id"], CLERK))
    assert asn_mid["status"] == "PUT_AWAY"  # one task still open
    th.get_success_data(api.assign_putaway_task(task_b["id"], PUTAWAY))
    th.get_success_data(api.complete_putaway_task(task_b["id"], PUTAWAY))
    asn_done = validate_success(api.get_inbound_asn(asn["id"], CLERK))
    assert asn_done["status"] == "CLOSED"


# ── priority_pair_validation_conflict ─────────────────────────────────────────

def test_close_cancelled_asn_with_two_open_lines_invalid_state(api):
    """PRD 2.11: "fifth, the state-machine precondition that the target entity is in a
    state from which the requested transition is defined (ERR_INVALID_STATE)". PRD
    2.11: "an earlier check, when it fires, masks all later ones."

    Design: Difficulty/priority_pair_validation_conflict/asn_close_state_beats_lines_open
    """
    sku = th.create_sku(sku_code="SKU-X1B", abc_class="C", each_volume_cm3=1)
    asn = th.create_asn(asn_number="ASN-9B")
    th.add_asn_line(asn["id"], sku["id"], 5)
    th.add_asn_line(asn["id"], sku["id"], 3)
    th.get_success_data(api.cancel_asn(asn["id"], CLERK))
    resp = api.close_asn(asn["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    now = validate_success(api.get_inbound_asn(asn["id"], CLERK))
    assert now["status"] == "CANCELLED"


def test_stale_lpn_beats_insufficient_with_wider_margin(api):
    """PRD 2.11: "sixth, the OCC version check on the two guarded paths
    (ERR_STALE_WAVE_VERSION or ERR_STALE_LPN_VERSION); ... and thereafter the
    remaining domain-specific business constraints described in Section 3 ...
    availability ...". PRD 2.11: "an earlier check, when it fires, masks all later
    ones."

    Design: Difficulty/priority_pair_validation_conflict/allocation_stale_lpn_beats_insufficient_available
    """
    sku, loc, lpn = th.setup_stored_lpn(sku_overrides={"sku_code": "SKU-X2B", "abc_class": "A", "each_volume_cm3": 1}, qty=10)
    order, line = th.create_order_with_line(sku["id"], 30)
    stale = validate_success(api.get_license_plate(lpn["id"], PLANNER))["version"]
    th.get_success_data(api.create_allocation(create_allocation_payload(line["id"], lpn["id"], 5, stale), PLANNER))
    # Over-reserves by a wide margin (25 vs free 5) AND carries the stale version.
    resp = api.create_allocation(create_allocation_payload(line["id"], lpn["id"], 25, stale), PLANNER)
    validate_error(resp, ApiErrorId.ERR_STALE_LPN_VERSION.value, 412)


# ── boundary_precision_check ──────────────────────────────────────────────────

def test_replenishment_eligible_below_min(api):
    """PRD 3.11: "the pick-face on-hand — the sum of qty across the plates at the
    pick-face location for this SKU whose disposition is STORED or ALLOCATED — must be
    at most the SKU's min_qty (the boundary is inclusive of exactly min_qty)."
    PRD 3.11: "When eligible, replen_qty is computed as the SKU's max_qty minus the
    current pick-face on-hand — that is, the quantity needed to refill the face up to
    max_qty exactly."

    Design: Difficulty/boundary_precision_check/replen_eligibility_at_min_inclusive
    """
    sku, pf, _ = th.setup_replen_eligible(
        sku_overrides={"sku_code": "SKU-R1B", "abc_class": "A", "each_volume_cm3": 1, "min_qty": 20, "max_qty": 100},
        face_qty=0,
    )
    data = validate_success(api.create_replenishment_task(create_replenishment_task_payload(sku["id"]), IC), 201)
    assert data["replen_qty"] == 100  # max_qty - 0


def test_cycle_count_due_at_b_class_sixty_day_cadence(api):
    """PRD 3.10: "The cadence is 30 days for an A-class SKU, 60 days for a B-class
    SKU, and 90 days for a C-class SKU. The SKU is due when the elapsed whole days
    are at least the cadence — exactly the cadence number of days makes the SKU due".

    Design: Difficulty/boundary_precision_check/cycle_count_due_at_exact_cadence_day
    """
    sku, loc, lpn, cc = th.setup_reconciled_sku_at_clock(
        "2026-03-01T00:00:00Z",
        sku_overrides={"sku_code": "SKU-D2", "abc_class": "B", "each_volume_cm3": 1, "min_qty": 1, "max_qty": 100},
        stored_qty=5,
    )
    th.get_success_data(api.set_clock(set_clock_payload("2026-04-30T00:00:00Z"), ADMIN))  # exactly 60 days
    sku_now = validate_success(api.get_sku(sku["id"], IC))
    assert sku_now["cycle_count_due"] is True


# ── cross_entity_state_dependency ─────────────────────────────────────────────

def test_putaway_completes_after_target_unblocked(api):
    """PRD 3.4: "Completion requires that the task is ASSIGNED, that the target
    location's status is AVAILABLE". PRD 3.1: an InventoryController "may later return
    it to service with the reverse BLOCKED to AVAILABLE transition."

    Design: Difficulty/cross_entity_state_dependency/putaway_complete_requires_location_available
    """
    sku, loc, lpn, task = th.setup_open_putaway_task(
        sku_overrides={"sku_code": "SKU-CE2", "abc_class": "C", "each_volume_cm3": 1}, qty=4)
    assigned = th.get_success_data(api.assign_putaway_task(task["id"], PUTAWAY))
    target = assigned["target_location_id"]
    th.get_success_data(api.block_location(target, IC))
    blocked = api.complete_putaway_task(task["id"], PUTAWAY)
    validate_error(blocked, ApiErrorId.ERR_CROSS_ENTITY_STATE.value, 409)
    th.get_success_data(api.unblock_location(target, IC))
    done = validate_success(api.complete_putaway_task(task["id"], PUTAWAY))
    assert done["status"] == "COMPLETED"


def test_wave_with_order_releases_successfully(api):
    """PRD 3.7: "A successful release advances release_status from PLANNING to
    RELEASED, runs the allocation waterfall ... sets fulfillment_status from
    UNALLOCATED to ALLOCATED". PRD 3.7: "the wave must already hold at least one
    order".

    Design: Difficulty/cross_entity_state_dependency/wave_release_requires_at_least_one_order
    """
    sku, loc, lpn, order, line, wave = th.setup_released_wave(
        sku_overrides={"sku_code": "SKU-WO1", "abc_class": "A", "each_volume_cm3": 1}, ordered_qty=5, lpn_qty=5)
    assert wave["release_status"] == "RELEASED"
    assert wave["fulfillment_status"] == "ALLOCATED"


# ── resource_temporal_overlap ─────────────────────────────────────────────────

def test_putaway_complete_at_exact_capacity_fits(api):
    """PRD 2.10: "The check compares the location's existing consumed volume plus the
    incoming plate's volume against the ceiling; if the combined figure would exceed
    max_volume_cm3, the move is rejected with ERR_LOCATION_CAPACITY (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/location_volume_aggregate_capacity_overlap
    """
    sku = th.create_sku(sku_code="SKU-T1B", abc_class="C", each_volume_cm3=10, min_qty=1, max_qty=100)
    loc = th.create_location(location_code="RS-T1B", zone="RESERVE", max_volume_cm3=100)
    asn = th.create_asn(asn_number="ASN-15B")
    line = th.add_asn_line(asn["id"], sku["id"], 10)
    rA = th.post_receipt(asn["id"], line["id"], 6)  # 60 cm3
    rB = th.post_receipt(asn["id"], line["id"], 4)  # 40 cm3 -> 60+40 = 100 == ceiling, fits
    th.get_success_data(api.close_asn(asn["id"], CLERK))
    task_a = th.first_putaway_task_for_lpn(rA["lpn_id"])
    task_b = th.first_putaway_task_for_lpn(rB["lpn_id"])
    th.get_success_data(api.assign_putaway_task(task_a["id"], PUTAWAY))
    th.get_success_data(api.assign_putaway_task(task_b["id"], PUTAWAY))
    th.get_success_data(api.complete_putaway_task(task_a["id"], PUTAWAY))
    done = validate_success(api.complete_putaway_task(task_b["id"], PUTAWAY))
    assert done["status"] == "COMPLETED"
    loc_now = validate_success(api.get_location(loc["id"], ADMIN))
    assert loc_now["used_volume_cm3"] == pytest.approx(100, abs=0.001)


def test_pick_face_dedication_allowed_for_distinct_skus(api):
    """PRD 3.1: "A pick face may be claimed by at most one SKU: an attempt to create a
    location dedicating the same pick face to a second, different SKU is rejected with
    ERR_PICKFACE_TAKEN."

    Design: Difficulty/resource_temporal_overlap/pickface_exclusive_dedication_overlap
    """
    sku1 = th.create_sku(sku_code="SKU-PF-A", abc_class="A")
    sku2 = th.create_sku(sku_code="SKU-PF-B", abc_class="A")
    th.create_location(location_code="PF-DA", zone="PICK_FACE", max_volume_cm3=500, pick_face_for_sku_id=sku1["id"])
    # A distinct SKU may take its own, distinct pick-face location.
    resp = api.create_location(
        create_location_payload(location_code="PF-DB", zone="PICK_FACE", max_volume_cm3=500, pick_face_for_sku_id=sku2["id"]),
        ADMIN)
    data = validate_success(resp, 201)
    assert data["pick_face_for_sku_id"] == sku2["id"]


# ── compensating_invariant ────────────────────────────────────────────────────

def test_reservation_lowers_available_qty_before_cancel(api):
    """PRD 3.6: "On a successful create the line's allocated_qty and the SKU's
    available_qty are recomputed". PRD 3.1: "The available_qty is the SKU's
    on_hand_qty minus the sum of allocated_qty across that SKU's allocations that are
    RESERVED or COMMITTED".

    Design: Difficulty/compensating_invariant/allocate_then_cancel_conserves_available_qty
    """
    sku, loc, lpn = th.setup_stored_lpn(sku_overrides={"sku_code": "SKU-I1B", "abc_class": "A", "each_volume_cm3": 1}, qty=10)
    order, line = th.create_order_with_line(sku["id"], 10)
    th.create_manual_allocation(line["id"], lpn["id"], 10)
    sku_reserved = validate_success(api.get_sku(sku["id"], PLANNER))
    assert sku_reserved["on_hand_qty"] == 10
    assert sku_reserved["available_qty"] == 0


def test_replenishment_move_fills_pick_face_keeping_on_hand(api):
    """PRD 3.11: "while replen_qty eaches are added to the pick face by minting or
    merging into a PICK_FACE plate at pick_face_location_id (disposition STORED); the
    SKU's on_hand_qty is recomputed (the move is net-zero across the warehouse)".

    Design: Difficulty/compensating_invariant/replenish_move_conserves_on_hand_qty
    """
    sku, pf, reserve = th.setup_replen_eligible(
        sku_overrides={"sku_code": "SKU-I2B", "abc_class": "B", "each_volume_cm3": 1, "min_qty": 5, "max_qty": 30},
        face_qty=0, reserve_qty=30)
    task = th.get_success_data(api.create_replenishment_task(create_replenishment_task_payload(sku["id"]), IC))
    th.get_success_data(api.assign_replenishment_task(task["id"], IC))
    th.get_success_data(api.complete_replenishment_task(task["id"], PUTAWAY))
    # On-hand conserved at 30; the pick face now holds the moved stock.
    sku_now = validate_success(api.get_sku(sku["id"], IC))
    assert sku_now["on_hand_qty"] == 30
    face_lpns, meta = th._list(api.list_license_plates(
        IC, params={"sku_id": sku["id"], "location_id": pf["id"], "disposition": "STORED"}))
    face_total = sum(p["qty"] for p in face_lpns)
    assert face_total == 30
