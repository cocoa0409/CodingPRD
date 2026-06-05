"""Inventory hygiene: ABC cycle counting (snapshot variance, reconcile adjustment,
cadence boundary, segregation of duties) and min/max replenishment (eligibility
boundary, not-needed, no-source, on-hand conservation). Plus the validation-priority
conflict where an invalid-state close masks an open-line business constraint, and
the existence-before-state ordering.

Covers queue-A difficulty instances (dual_variant_calc cycle snapshot,
boundary_precision_check replen + cadence, priority_pair asn close,
compensating_invariant on-hand) and queue-B corner instances under calculations,
validations, rbac (segregation).
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assert_cycle_count, assert_replenishment_task, assert_sku_invariants,
    submit_cycle_count_payload, create_cycle_count_payload,
    create_replenishment_task_payload, set_clock_payload,
    make_inventory_controller_headers,
    NON_EXISTENT_UUID,
)
import test_helpers as th

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK = TEST_USERS["receiving_clerk_headers"]
PUTAWAY = TEST_USERS["putaway_operator_headers"]
IC = TEST_USERS["inventory_controller_headers"]


# ── Cycle count variance & reconcile ──────────────────────────────────────────

def test_cycle_count_variance_uses_open_snapshot(api):
    """PRD 3.10: "Opening snapshots system_qty once, at open time ... this snapshot is
    captured a single time and is not re-snapshotted on submit." PRD 3.10: "computes
    variance_qty as counted_qty minus the snapshot system_qty (a signed value that
    may be negative)".

    Design: Difficulty/dual_variant_calc/cycle_count_variance_uses_open_snapshot_not_live
    """
    sku, loc, lpn, cc = th.setup_open_cycle_count(
        stored_qty=20, sku_overrides={"sku_code": "SKU-B1", "abc_class": "B", "each_volume_cm3": 1, "min_qty": 5, "max_qty": 40})
    assert cc["system_qty"] == 20
    counter = make_inventory_controller_headers("ic-counter-snap")
    submitted = validate_success(api.submit_cycle_count(cc["id"], submit_cycle_count_payload(18), counter))
    assert_cycle_count(submitted)
    assert submitted["system_qty"] == 20
    assert submitted["variance_qty"] == -2
    assert submitted["status"] == "COUNTED"


def test_cycle_count_positive_variance_increases_onhand(api):
    """PRD 3.10: "On approval, if variance_qty is non-zero, the STORED license-plate
    quantity at this location for this SKU is adjusted by the variance, filling plates
    in created_at ascending order, and the SKU's on_hand_qty and the location's
    used_volume_cm3 are recomputed".

    Design: Corner/calculations/cycle_count_positive_variance_increases_onhand
    """
    sku, loc, lpn, cc = th.setup_counted_cycle_count(
        stored_qty=20, counted_qty=25, counter_user_id="ic-counter-pos",
        sku_overrides={"sku_code": "SKU-CV1", "abc_class": "B", "each_volume_cm3": 1, "min_qty": 1, "max_qty": 100})
    assert cc["variance_qty"] == 5
    approver = make_inventory_controller_headers("ic-approver-pos")
    reconciled = validate_success(api.approve_cycle_count(cc["id"], approver))
    assert reconciled["status"] == "RECONCILED"
    sku_now = validate_success(api.get_sku(sku["id"], IC))
    assert sku_now["on_hand_qty"] == 25
    assert_sku_invariants(sku_now)


def test_cycle_count_self_approval_returns_segregation(api):
    """PRD 2.9: "The actor who approves or rejects a count must not be the actor who
    submitted that count (the X-User-ID recorded as counted_by_user_id), and — on
    approval specifically — must additionally not be a ReceivingClerk who received any
    ASN that fed inventory at the counted location (the X-User-ID recorded as
    received_by_user_id on such an ASN). A violation of either separation is rejected
    with ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    Design: Corner/rbac/cycle_count_self_approval_returns_segregation
    """
    sku, loc, lpn, cc = th.setup_counted_cycle_count(
        stored_qty=5, counted_qty=5, counter_user_id="ic-same",
        sku_overrides={"sku_code": "SKU-SD1", "abc_class": "B", "each_volume_cm3": 1, "min_qty": 1, "max_qty": 100})
    same = make_inventory_controller_headers("ic-same")
    resp = api.approve_cycle_count(cc["id"], same)
    validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value, 403)
    now = validate_success(api.get_cycle_count(cc["id"], IC))
    assert now["status"] == "COUNTED"


# ── Cadence boundary (queue A) ────────────────────────────────────────────────

def test_cycle_count_due_at_exact_cadence_day(api):
    """PRD 3.10: "The cadence is 30 days for an A-class SKU, 60 days for a B-class SKU,
    and 90 days for a C-class SKU." PRD 3.10: "The SKU is due when the elapsed whole
    days are at least the cadence — exactly the cadence number of days makes the SKU
    due (the boundary is inclusive)."

    Design: Difficulty/boundary_precision_check/cycle_count_due_at_exact_cadence_day
    """
    sku, loc, lpn, cc = th.setup_reconciled_sku_at_clock(
        "2026-01-01T00:00:00Z",
        sku_overrides={"sku_code": "SKU-D1", "abc_class": "A", "each_volume_cm3": 1, "min_qty": 1, "max_qty": 100},
        stored_qty=5,
    )
    th.get_success_data(api.set_clock(set_clock_payload("2026-01-31T00:00:00Z"), ADMIN))  # exactly 30 days
    sku_now = validate_success(api.get_sku(sku["id"], IC))
    assert sku_now["cycle_count_due"] is True


def test_cycle_count_due_false_one_day_before_cadence(api):
    """PRD 3.10: "The system measures the whole days (floored) between the current
    clock and the updated_at of the most recent RECONCILED count for that SKU."
    PRD 3.10: "The SKU is due when the elapsed whole days are at least the cadence —
    exactly the cadence number of days makes the SKU due (the boundary is inclusive)."

    Design: Corner/calculations/cycle_count_due_false_before_cadence
    """
    sku, loc, lpn, cc = th.setup_reconciled_sku_at_clock(
        "2026-01-01T00:00:00Z",
        sku_overrides={"sku_code": "SKU-DUE0", "abc_class": "A", "each_volume_cm3": 1, "min_qty": 1, "max_qty": 100},
        stored_qty=5,
    )
    th.get_success_data(api.set_clock(set_clock_payload("2026-01-30T00:00:00Z"), ADMIN))  # 29 days
    sku_now = validate_success(api.get_sku(sku["id"], IC))
    assert sku_now["cycle_count_due"] is False


# ── Replenishment (queue A + B) ───────────────────────────────────────────────

def test_replenishment_eligible_at_exactly_min_qty(api):
    """PRD 3.11: "the pick-face on-hand — the sum of qty across the plates at the
    pick-face location for this SKU whose disposition is STORED or ALLOCATED — must be
    at most the SKU's min_qty (the boundary is inclusive of exactly min_qty)."
    PRD 3.11: "When eligible, replen_qty is computed as the SKU's max_qty minus the
    current pick-face on-hand — that is, the quantity needed to refill the face up to
    max_qty exactly."

    Design: Difficulty/boundary_precision_check/replen_eligibility_at_min_inclusive
    """
    sku, pf, _ = th.setup_replen_eligible(
        sku_overrides={"sku_code": "SKU-R1", "abc_class": "A", "each_volume_cm3": 1, "min_qty": 20, "max_qty": 100},
        face_qty=20,
    )
    resp = api.create_replenishment_task(create_replenishment_task_payload(sku["id"]), IC)
    data = validate_success(resp, 201)
    assert_replenishment_task(data)
    assert data["replen_qty"] == 80
    assert data["status"] == "CREATED"


def test_replenishment_not_needed_above_min(api):
    """PRD 3.11: "If the pick-face on-hand is above min_qty, the create is rejected
    with ERR_REPLEN_NOT_NEEDED."

    Design: Corner/calculations/replen_not_needed_above_min
    """
    sku, pf, _ = th.setup_replen_eligible(
        sku_overrides={"sku_code": "SKU-RN1", "abc_class": "A", "each_volume_cm3": 1, "min_qty": 20, "max_qty": 100},
        face_qty=21,
    )
    resp = api.create_replenishment_task(create_replenishment_task_payload(sku["id"]), IC)
    validate_error(resp, ApiErrorId.ERR_REPLEN_NOT_NEEDED.value, 409)


def test_replenishment_assign_no_reserve_source_returns_error(api):
    """PRD 3.11: "If the whole pool's combined quantity is below replen_qty (or the
    pool is empty), the assign is rejected with ERR_NO_REPLEN_SOURCE".

    Design: Corner/errors/replen_assign_no_reserve_source_returns_no_replen_source
    """
    sku, pf, _ = th.setup_replen_eligible(
        sku_overrides={"sku_code": "SKU-NR1", "abc_class": "B", "each_volume_cm3": 1, "min_qty": 5, "max_qty": 30},
        face_qty=0, reserve_qty=0,
    )
    task = th.get_success_data(api.create_replenishment_task(create_replenishment_task_payload(sku["id"]), IC))
    resp = api.assign_replenishment_task(task["id"], IC)
    validate_error(resp, ApiErrorId.ERR_NO_REPLEN_SOURCE.value, 409)


def test_replenishment_move_conserves_on_hand(api):
    """PRD 3.11: "the SKU's on_hand_qty is recomputed (the move is net-zero across the
    warehouse)". PRD 3.1: "The on_hand_qty is the total eaches across every license
    plate of that SKU whose disposition is STORED, ALLOCATED, or PICKED_STAGED".

    Design: Difficulty/compensating_invariant/replenish_move_conserves_on_hand_qty
    """
    sku, pf, reserve = th.setup_replen_eligible(
        sku_overrides={"sku_code": "SKU-I2", "abc_class": "B", "each_volume_cm3": 1, "min_qty": 5, "max_qty": 30},
        face_qty=0, reserve_qty=30,
    )
    task = th.get_success_data(api.create_replenishment_task(create_replenishment_task_payload(sku["id"]), IC))
    assert task["replen_qty"] == 30
    th.get_success_data(api.assign_replenishment_task(task["id"], IC))
    th.get_success_data(api.complete_replenishment_task(task["id"], PUTAWAY))
    sku_now = validate_success(api.get_sku(sku["id"], IC))
    assert sku_now["on_hand_qty"] == 30
    assert_sku_invariants(sku_now)


# ── Validation priority & existence ordering ──────────────────────────────────

def test_close_cancelled_asn_with_open_line_reports_invalid_state(api):
    """PRD 2.11: "fifth, the state-machine precondition that the target entity is in a
    state from which the requested transition is defined (ERR_INVALID_STATE) ... and
    thereafter the remaining domain-specific business constraints described in
    Section 3 (uniqueness, capacity, pick-face dedication, replenishment eligibility,
    availability, open-line, ...)." PRD 2.11: "an earlier check, when it fires, masks
    all later ones."

    Design: Difficulty/priority_pair_validation_conflict/asn_close_state_beats_lines_open
    """
    sku = th.create_sku(sku_code="SKU-X1", abc_class="C", each_volume_cm3=1)
    asn = th.create_asn(asn_number="ASN-9")
    th.add_asn_line(asn["id"], sku["id"], 5)  # OPEN line, never received
    th.get_success_data(api.cancel_asn(asn["id"], CLERK))  # ANNOUNCED -> CANCELLED
    resp = api.close_asn(asn["id"], CLERK)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)


def test_complete_nonexistent_putaway_task_returns_not_found(api):
    """PRD 2.11: "third, existence of every referenced id, validated left-to-right in
    the path (ERR_NOT_FOUND); fourth, request-body well-formedness ... fifth, the
    state-machine precondition". PRD 2.5: "every referenced id must resolve to an
    existing entity of the expected type."

    Design: Corner/validations/existence_before_state_on_putaway_complete
    """
    resp = api.complete_putaway_task(NON_EXISTENT_UUID, PUTAWAY)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)
