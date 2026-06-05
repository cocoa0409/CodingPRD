"""Putaway: ABC-class slotting selector, the contrasting cross-dock slotting
direction, volume sum-then-round, capacity and cross-entity guards, and the
putaway task lifecycle.

Covers queue-A difficulty instances (dual_variant_calc, combinatorial_formula,
cross_entity_state_dependency, resource_temporal_overlap, transitive_cascade) and
queue-B corner instances under state_machines, validations, errors, consistency.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_putaway_task, assert_location,
    create_location_payload,
)
import test_helpers as th

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
PUTAWAY = TEST_USERS["putaway_operator_headers"]
IC = TEST_USERS["inventory_controller_headers"]


# ── Slotting selector (queue A) ───────────────────────────────────────────────

def test_a_class_putaway_prefers_pick_face(api):
    """PRD 3.4: "an A-class (high-velocity) SKU prefers a PICK_FACE location for
    forward velocity, while a B- or C-class SKU prefers a RESERVE location for deep
    storage." PRD 3.4: "a location is preferred when its zone matches the class
    preference — PICK_FACE for A-class, RESERVE otherwise".

    Design: Difficulty/dual_variant_calc/slotting_strategy_diverges_by_abc_class
    """
    sku = th.create_sku(sku_code="SKU-A1", abc_class="A", each_volume_cm3=10, min_qty=5, max_qty=50)
    pf = th.create_location(location_code="PF-01", zone="PICK_FACE", max_volume_cm3=60, pick_face_for_sku_id=sku["id"])
    th.create_location(location_code="RS-01", zone="RESERVE", max_volume_cm3=100)
    asn, line, lpn = th.receive_one_lpn(sku["id"], 5)
    th.get_success_data(api.close_asn(asn["id"], CLERK))
    task = th.first_putaway_task_for_lpn(lpn["id"])
    data = validate_success(api.assign_putaway_task(task["id"], PUTAWAY))
    assert_putaway_task(data)
    assert data["target_location_id"] == pf["id"]
    assert data["status"] == "ASSIGNED"


def test_b_class_putaway_prefers_reserve_over_pick_face(api):
    """PRD 3.4: "a B- or C-class SKU prefers a RESERVE location for deep storage."
    PRD 3.4: "a location is preferred when its zone matches the class preference —
    PICK_FACE for A-class, RESERVE otherwise — and a non-matching zone is
    deprioritized."

    Design: Difficulty/combinatorial_formula/putaway_rank_tuple_three_input_nonlinear
    """
    sku = th.create_sku(sku_code="SKU-B2", abc_class="B", each_volume_cm3=10, min_qty=5, max_qty=50)
    rs = th.create_location(location_code="RS-20", zone="RESERVE", max_volume_cm3=100)
    th.create_location(location_code="PF-20", zone="PICK_FACE", max_volume_cm3=80, pick_face_for_sku_id=sku["id"])
    asn, line, lpn = th.receive_one_lpn(sku["id"], 5)
    th.get_success_data(api.close_asn(asn["id"], CLERK))
    task = th.first_putaway_task_for_lpn(lpn["id"])
    data = validate_success(api.assign_putaway_task(task["id"], PUTAWAY))
    assert data["target_location_id"] == rs["id"]
    assert data["status"] == "ASSIGNED"


def test_location_used_volume_is_sum_then_rounded(api):
    """PRD 2.7: "This sum is computed in full first and then rounded once, half-up, to
    two decimal places — the rounding is applied a single time to the completed sum,
    never per line."

    Design: Difficulty/combinatorial_formula/location_volume_sum_then_round
    """
    sku = th.create_sku(sku_code="SKU-V1", abc_class="C", each_volume_cm3=3.33, min_qty=1, max_qty=100)
    rs = th.create_location(location_code="RS-30", zone="RESERVE", max_volume_cm3=1000)
    asn = th.create_asn(asn_number="ASN-4")
    line = th.add_asn_line(asn["id"], sku["id"], 5)
    r1 = th.post_receipt(asn["id"], line["id"], 3)
    r2 = th.post_receipt(asn["id"], line["id"], 2)
    th.get_success_data(api.close_asn(asn["id"], CLERK))
    task_a = th.first_putaway_task_for_lpn(r1["lpn_id"])
    th.get_success_data(api.assign_putaway_task(task_a["id"], PUTAWAY))
    th.get_success_data(api.complete_putaway_task(task_a["id"], PUTAWAY))
    task_b = th.first_putaway_task_for_lpn(r2["lpn_id"])
    th.get_success_data(api.assign_putaway_task(task_b["id"], PUTAWAY))
    th.get_success_data(api.complete_putaway_task(task_b["id"], PUTAWAY))
    loc = validate_success(api.get_location(rs["id"], ADMIN))
    assert loc["used_volume_cm3"] == pytest.approx(16.65, abs=0.001)


# ── Putaway lifecycle, errors, cross-entity (queue A + B) ─────────────────────

def test_putaway_assign_no_eligible_location_returns_error(api):
    """PRD 3.4: "if the selector returns an empty candidate set, the assign is
    rejected with ERR_NO_PUTAWAY_LOCATION and the task stays CREATED."

    Design: Corner/errors/putaway_assign_no_eligible_location_returns_no_putaway_location
    """
    sku = th.create_sku(sku_code="SKU-NP1", abc_class="C", each_volume_cm3=10, min_qty=1, max_qty=100)
    th.create_location(location_code="RS-NP1", zone="RESERVE", max_volume_cm3=10)  # need=50 > 10
    asn, line, lpn = th.receive_one_lpn(sku["id"], 5)
    th.get_success_data(api.close_asn(asn["id"], CLERK))
    task = th.first_putaway_task_for_lpn(lpn["id"])
    resp = api.assign_putaway_task(task["id"], PUTAWAY)
    validate_error(resp, ApiErrorId.ERR_NO_PUTAWAY_LOCATION.value, 409)


def test_assign_completed_putaway_task_returns_invalid_state(api):
    """PRD 2.11: "fifth, the state-machine precondition that the target entity is in a
    state from which the requested transition is defined (ERR_INVALID_STATE)."
    PRD 3.4: "A PutawayOperator first assigns the task, advancing it from CREATED to
    ASSIGNED."

    Design: Corner/state_machines/putaway_assign_from_completed_returns_invalid_state
    """
    sku, loc, lpn, task = th.setup_open_putaway_task(sku_overrides={"sku_code": "SKU-SM1", "abc_class": "C"}, qty=3)
    th.get_success_data(api.assign_putaway_task(task["id"], PUTAWAY))
    th.get_success_data(api.complete_putaway_task(task["id"], PUTAWAY))
    resp = api.assign_putaway_task(task["id"], PUTAWAY)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    now = validate_success(api.get_putaway_task(task["id"], PUTAWAY))
    assert now["status"] == "COMPLETED"


def test_putaway_complete_into_blocked_location_returns_cross_entity_state(api):
    """PRD 3.4: "A target that has become BLOCKED since assignment ... blocks
    completion: a blocked target raises ERR_CROSS_ENTITY_STATE". PRD 2.10: "A
    location whose status is BLOCKED rejects all inbound moves regardless of capacity."

    Design: Difficulty/cross_entity_state_dependency/putaway_complete_requires_location_available
    """
    sku, loc, lpn, task = th.setup_open_putaway_task(
        sku_overrides={"sku_code": "SKU-CE1", "abc_class": "C", "each_volume_cm3": 1},
        qty=4,
    )
    assigned = th.get_success_data(api.assign_putaway_task(task["id"], PUTAWAY))
    th.get_success_data(api.block_location(assigned["target_location_id"], IC))
    resp = api.complete_putaway_task(task["id"], PUTAWAY)
    validate_error(resp, ApiErrorId.ERR_CROSS_ENTITY_STATE.value, 409)
    now = validate_success(api.get_putaway_task(task["id"], PUTAWAY))
    assert now["status"] == "ASSIGNED"


def test_putaway_complete_over_capacity_returns_location_capacity(api):
    """PRD 2.10: "if the combined figure would exceed max_volume_cm3, the move is
    rejected with ERR_LOCATION_CAPACITY". PRD 3.4: "Completion requires ... that the
    target's residual capacity is still at least the plate's volume."

    Design: Difficulty/resource_temporal_overlap/location_volume_aggregate_capacity_overlap
    """
    sku = th.create_sku(sku_code="SKU-T1", abc_class="C", each_volume_cm3=10, min_qty=1, max_qty=100)
    loc = th.create_location(location_code="RS-T1", zone="RESERVE", max_volume_cm3=100)
    asn = th.create_asn(asn_number="ASN-15")
    line = th.add_asn_line(asn["id"], sku["id"], 12)
    rA = th.post_receipt(asn["id"], line["id"], 6)  # 60 cm3
    rB = th.post_receipt(asn["id"], line["id"], 6)  # 60 cm3
    th.get_success_data(api.close_asn(asn["id"], CLERK))
    task_a = th.first_putaway_task_for_lpn(rA["lpn_id"])
    task_b = th.first_putaway_task_for_lpn(rB["lpn_id"])
    th.get_success_data(api.assign_putaway_task(task_a["id"], PUTAWAY))
    th.get_success_data(api.assign_putaway_task(task_b["id"], PUTAWAY))
    th.get_success_data(api.complete_putaway_task(task_a["id"], PUTAWAY))  # bin used = 60
    resp = api.complete_putaway_task(task_b["id"], PUTAWAY)  # 60 + 60 = 120 > 100
    validate_error(resp, ApiErrorId.ERR_LOCATION_CAPACITY.value, 409)
    loc_now = validate_success(api.get_location(loc["id"], ADMIN))
    assert loc_now["used_volume_cm3"] == pytest.approx(60, abs=0.001)
    task_b_now = validate_success(api.get_putaway_task(task_b["id"], PUTAWAY))
    assert task_b_now["status"] == "ASSIGNED"


def test_putaway_complete_cascade_closes_asn(api):
    """PRD 3.4: "If this completion makes every putaway task of the source ASN
    terminal (all COMPLETED or CANCELLED, at least one COMPLETED), the ASN bubbles
    from PUT_AWAY to CLOSED." PRD 3.4: "On completion the plate is driven from
    PUTAWAY_PENDING to STORED".

    Design: Difficulty/transitive_cascade/putaway_complete_cascade_depth2_closes_asn
    """
    sku, loc, lpn, task = th.setup_open_putaway_task(
        sku_overrides={"sku_code": "SKU-P2", "abc_class": "C", "each_volume_cm3": 1},
        qty=4,
    )
    th.get_success_data(api.assign_putaway_task(task["id"], PUTAWAY))
    done = validate_success(api.complete_putaway_task(task["id"], PUTAWAY))
    assert done["status"] == "COMPLETED"
    lpn_now = validate_success(api.get_license_plate(lpn["id"], PUTAWAY))
    assert lpn_now["disposition"] == "STORED"
    asn_now = validate_success(api.get_inbound_asn(lpn_now["source_asn_id"], CLERK))
    assert asn_now["status"] == "CLOSED"


def test_putaway_task_version_increments_per_mutation(api):
    """PRD 2.4: "version, an integer that begins at its initial value on creation and
    is incremented by exactly one on every mutation that changes the resource."

    Design: Corner/state_machines/version_increments_on_putaway_complete
    """
    sku, loc, lpn, task = th.setup_open_putaway_task(sku_overrides={"sku_code": "SKU-VER", "abc_class": "C", "each_volume_cm3": 1}, qty=3)
    assert task["version"] == 1
    th.get_success_data(api.assign_putaway_task(task["id"], PUTAWAY))
    done = validate_success(api.complete_putaway_task(task["id"], PUTAWAY))
    assert done["version"] == 3


def test_onhand_immediately_visible_after_putaway_complete(api):
    """PRD 2.6: "the recomputed values are reflected immediately — the system uses an
    immediate-consistency model, so a read always observes the fully reconciled
    state." PRD 3.4: "the SKU's on_hand_qty is recomputed".

    Design: Corner/consistency_model/immediate_onhand_visible_in_putaway_response_chain
    """
    sku, loc, lpn, task = th.setup_open_putaway_task(sku_overrides={"sku_code": "SKU-IM1", "abc_class": "C", "each_volume_cm3": 1}, qty=8)
    th.get_success_data(api.assign_putaway_task(task["id"], PUTAWAY))
    th.get_success_data(api.complete_putaway_task(task["id"], PUTAWAY))
    sku_now = validate_success(api.get_sku(sku["id"], IC))
    assert sku_now["on_hand_qty"] == 8


def test_second_pick_face_for_same_sku_returns_pickface_taken(api):
    """PRD 3.1: "A pick face may be claimed by at most one SKU: an attempt to create a
    location dedicating the same pick face to a second, different SKU is rejected with
    ERR_PICKFACE_TAKEN."

    Design: Difficulty/resource_temporal_overlap/pickface_exclusive_dedication_overlap
    """
    sku = th.create_sku(sku_code="SKU-T2", abc_class="A")
    th.create_location(location_code="PF-T1", zone="PICK_FACE", max_volume_cm3=500, pick_face_for_sku_id=sku["id"])
    resp = api.create_location(
        create_location_payload(location_code="PF-T2", zone="PICK_FACE", max_volume_cm3=500, pick_face_for_sku_id=sku["id"]),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_PICKFACE_TAKEN.value, 409)
