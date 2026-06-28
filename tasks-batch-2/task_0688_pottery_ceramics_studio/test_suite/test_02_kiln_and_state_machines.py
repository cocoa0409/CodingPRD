"""Kiln loading/firing state machine, the piece load/unload revision loop, the
class-series full/open cycle, capacity overflow, empty-kiln firing guard, the
state-before-capacity precedence pair, and conservation invariants.

Queue A (Difficulty): non_linear_state_machine, resource_temporal_overlap,
boundary_precision_check (empty kiln), priority_pair_validation_conflict
(state vs capacity), compensating_invariant.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_member, create_open_visit, add_piece, create_batch, create_item,
    create_series, load_piece, setup_full_capacity_batch, setup_full_series,
    setup_loaded_piece,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── non_linear_state_machine / bisque_piece_load_unload_cycle ──────────────

def test_piece_unload_returns_to_painted(api):
    """PRD §3.3: "A loaded piece that has not yet been fired may be un-loaded back
    to PAINTED: un-loading is permitted only while the piece is LOADED and its batch
    is still LOADING, and it clears the piece's kiln_batch_id."

    Design: Difficulty/non_linear_state_machine/bisque_piece_load_unload_cycle
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=3000, sku="PLATE-10", name="Plate")
    batch = create_batch(capacity_slots=4)
    load_piece(batch, piece["id"])

    unloaded = validate_success(api.unload_piece(piece["id"], STAFF), 200)
    assert unloaded["status"] == "PAINTED", unloaded["status"]
    assert unloaded["kiln_batch_id"] is None, unloaded["kiln_batch_id"]


def test_piece_unload_decrements_occupied_slots(api):
    """PRD §3.3: "[un-loading]... decrements that batch's occupied_slots by one to
    compensate the earlier load, and increments the batch's version."

    Design: Difficulty/non_linear_state_machine/bisque_piece_load_unload_cycle
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=3000, sku="PLATE-11", name="Plate")
    batch = create_batch(capacity_slots=4)  # version 1
    load_piece(batch, piece["id"])  # version -> 2, occupied -> 1
    api.unload_piece(piece["id"], STAFF)  # version -> 3, occupied -> 0

    batch_after = validate_success(api.get_batch(batch["id"], STAFF), 200)
    assert batch_after["occupied_slots"] == 0, batch_after["occupied_slots"]
    assert batch_after["version"] == 3, batch_after["version"]


# ─── non_linear_state_machine / class_series_full_to_open_reopen_cycle ──────

def test_series_full_when_last_seat_taken(api):
    """PRD §3.10: "The series' enrolled_count is incremented by one, and if that
    increment brings the count up to the seat_capacity the series bubbles up from
    OPEN to FULL."

    Design: Difficulty/non_linear_state_machine/class_series_full_to_open_reopen_cycle
    """
    m1 = create_member()
    series = create_series(session_count=4, seat_capacity=1, price_cents=12000,
                           starts_at="2026-07-15T18:00:00Z")
    api.enroll(series["id"], {"member_id": m1["id"]}, STAFF)

    series_after = validate_success(api.get_series(series["id"], MANAGER), 200)
    assert series_after["status"] == "FULL", series_after["status"]
    assert series_after["enrolled_count"] == 1, series_after["enrolled_count"]


def test_series_reopens_on_withdraw(api):
    """PRD §3.11: "The series' enrolled_count is decremented by one, and if the
    series was FULL, dropping below seat_capacity bubbles it back up from FULL to
    OPEN because a seat has reopened."

    Design: Difficulty/non_linear_state_machine/class_series_full_to_open_reopen_cycle
    """
    m1 = create_member()
    series = create_series(session_count=4, seat_capacity=1, price_cents=12000,
                           starts_at="2026-07-15T18:00:00Z")
    enr = get_success_data(api.enroll(series["id"], {"member_id": m1["id"]}, STAFF))

    api.withdraw_enrollment(enr["id"], STAFF)
    series_after = validate_success(api.get_series(series["id"], MANAGER), 200)
    assert series_after["status"] == "OPEN", series_after["status"]
    assert series_after["enrolled_count"] == 0, series_after["enrolled_count"]


# ─── resource_temporal_overlap / kiln_capacity_aggregate_slot_overflow ──────

def test_load_into_full_kiln_rejected(api):
    """PRD §3.4: "the batch must have a free slot (its occupied_slots must be
    strictly less than its capacity_slots)." PRD §3.4: "A batch whose occupied_slots
    has reached its capacity_slots is reported as ERR_KILN_AT_CAPACITY."

    Design: Difficulty/resource_temporal_overlap/kiln_capacity_aggregate_slot_overflow
    """
    visit, batch_after, _loaded, spare = setup_full_capacity_batch(capacity_slots=1)
    res = api.load_piece(
        batch_after["id"],
        {"bisque_piece_id": spare["id"], "expected_kiln_batch_version": batch_after["version"]},
        STAFF)
    validate_error(res, "ERR_KILN_AT_CAPACITY")


def test_load_into_full_kiln_leaves_occupied_unchanged(api):
    """PRD §3.4: "A batch whose occupied_slots has reached its capacity_slots is
    reported as ERR_KILN_AT_CAPACITY." PRD §3.4: the failing load consumes no slot
    ("a stale expected_kiln_batch_version is reported as ERR_STALE_BATCH_VERSION
    (HTTP 412) on the stale-version check, before any slot is consumed").

    Design: Difficulty/resource_temporal_overlap/kiln_capacity_aggregate_slot_overflow
    """
    visit, batch_after, _loaded, spare = setup_full_capacity_batch(capacity_slots=1)
    api.load_piece(
        batch_after["id"],
        {"bisque_piece_id": spare["id"], "expected_kiln_batch_version": batch_after["version"]},
        STAFF)
    batch_now = validate_success(api.get_batch(batch_after["id"], STAFF), 200)
    assert batch_now["occupied_slots"] == 1, batch_now["occupied_slots"]


# ─── resource_temporal_overlap / class_seat_capacity_full_overflow ──────────

def test_enroll_into_full_series_rejected(api):
    """PRD §3.10: "a series whose enrolled_count has reached its seat_capacity is
    full and is rejected with ERR_SERIES_FULL."

    Design: Difficulty/resource_temporal_overlap/class_seat_capacity_full_overflow
    """
    series_after, _m1, m2 = setup_full_series()
    res = api.enroll(series_after["id"], {"member_id": m2["id"]}, STAFF)
    validate_error(res, "ERR_SERIES_FULL")


def test_enroll_into_full_series_leaves_count_unchanged(api):
    """PRD §3.10: "a series whose enrolled_count has reached its seat_capacity is
    full and is rejected with ERR_SERIES_FULL." PRD §3.10: enrolled_count tracks
    "the number of enrollments that are ENROLLED or ATTENDED."

    Design: Difficulty/resource_temporal_overlap/class_seat_capacity_full_overflow
    """
    series_after, _m1, m2 = setup_full_series()
    api.enroll(series_after["id"], {"member_id": m2["id"]}, STAFF)
    series_now = validate_success(api.get_series(series_after["id"], MANAGER), 200)
    assert series_now["enrolled_count"] == 1, series_now["enrolled_count"]
    assert series_now["status"] == "FULL", series_now["status"]


# ─── boundary_precision_check / fire_empty_kiln_zero_occupied_rejected ──────

def test_fire_empty_kiln_rejected(api):
    """PRD §3.5: "A batch may be started only while it is LOADING and only when it
    holds at least one piece — an empty kiln cannot be fired, so the batch's
    occupied_slots must be at least 1."

    Design: Difficulty/boundary_precision_check/fire_empty_kiln_zero_occupied_rejected
    """
    batch = create_batch(capacity_slots=4)  # occupied 0
    res = api.start_firing(batch["id"], STAFF)
    validate_error(res, "ERR_INVALID_STATE")


def test_fire_empty_kiln_leaves_loading(api):
    """PRD §3.5: "A batch may be started only while it is LOADING and only when it
    holds at least one piece... so the batch's occupied_slots must be at least 1."
    PRD §3.5: "On start, the batch's started_at is set to the current logical-clock
    instant" — a rejected start performs none of this.

    Design: Difficulty/boundary_precision_check/fire_empty_kiln_zero_occupied_rejected
    """
    batch = create_batch(capacity_slots=4)
    api.start_firing(batch["id"], STAFF)
    batch_after = validate_success(api.get_batch(batch["id"], STAFF), 200)
    assert batch_after["status"] == "LOADING", batch_after["status"]
    assert batch_after["started_at"] is None, batch_after["started_at"]


# ─── priority_pair_validation_conflict / state_before_capacity_on_load ──────

def test_already_loaded_piece_state_beats_capacity(api):
    """PRD §3.4: "After existence and the basic state check (a non-LOADING batch or
    a non-PAINTED piece yields ERR_INVALID_STATE), a temperature disagreement
    between the piece and the batch is reported as ERR_FIRING_TEMP_MISMATCH. A batch
    whose occupied_slots has reached its capacity_slots is reported as
    ERR_KILN_AT_CAPACITY."

    Design: Difficulty/priority_pair_validation_conflict/state_before_capacity_on_load
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=2000, sku="CUP-A", name="Cup A")
    batch = create_batch(capacity_slots=1)  # cap 1
    load_piece(batch, piece["id"])  # piece now LOADED; batch occupied 1 == capacity
    fresh = validate_success(api.get_batch(batch["id"], STAFF), 200)

    # re-load the already-LOADED piece into the now-full batch: state (non-PAINTED) wins
    res = api.load_piece(
        batch["id"],
        {"bisque_piece_id": piece["id"], "expected_kiln_batch_version": fresh["version"]},
        STAFF)
    validate_error(res, "ERR_INVALID_STATE")


def test_state_before_capacity_leaves_occupied_unchanged(api):
    """PRD §3.4: "a non-LOADING batch or a non-PAINTED piece yields
    ERR_INVALID_STATE." PRD §3.4: a successful load increments occupied_slots, so a
    state-rejected load must not.

    Design: Difficulty/priority_pair_validation_conflict/state_before_capacity_on_load
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=2000, sku="CUP-B", name="Cup B")
    batch = create_batch(capacity_slots=1)
    load_piece(batch, piece["id"])
    fresh = validate_success(api.get_batch(batch["id"], STAFF), 200)
    api.load_piece(
        batch["id"],
        {"bisque_piece_id": piece["id"], "expected_kiln_batch_version": fresh["version"]},
        STAFF)
    batch_now = validate_success(api.get_batch(batch["id"], STAFF), 200)
    assert batch_now["occupied_slots"] == 1, batch_now["occupied_slots"]


# ─── compensating_invariant / kiln_slots_conserved_on_cancel ────────────────

def test_cancel_batch_conserves_slots_to_zero(api):
    """PRD §3.5: "A batch may instead be cancelled by a manager while it is still
    LOADING. Cancellation returns every LOADED piece on the batch to PAINTED with
    its kiln_batch_id cleared, sets the batch's occupied_slots to 0, and moves the
    batch to CANCELLED."

    Design: Difficulty/compensating_invariant/kiln_slots_conserved_on_cancel
    """
    visit = create_open_visit()
    p1 = add_piece(visit["id"], bisque_price_cents=2000, sku="Q1", name="Q1")
    p2 = add_piece(visit["id"], bisque_price_cents=2000, sku="Q2", name="Q2")
    batch = create_batch(capacity_slots=4)
    load_piece(batch, p1["id"])
    load_piece(batch, p2["id"])

    cancelled = validate_success(api.cancel_batch(batch["id"], MANAGER), 200)
    assert cancelled["occupied_slots"] == 0, cancelled["occupied_slots"]
    assert cancelled["status"] == "CANCELLED", cancelled["status"]


def test_cancel_batch_returns_pieces_to_painted(api):
    """PRD §3.5: "Cancellation returns every LOADED piece on the batch to PAINTED
    with its kiln_batch_id cleared."

    Design: Difficulty/compensating_invariant/kiln_slots_conserved_on_cancel
    """
    visit = create_open_visit()
    p1 = add_piece(visit["id"], bisque_price_cents=2000, sku="Q3", name="Q3")
    p2 = add_piece(visit["id"], bisque_price_cents=2000, sku="Q4", name="Q4")
    batch = create_batch(capacity_slots=4)
    load_piece(batch, p1["id"])
    load_piece(batch, p2["id"])
    api.cancel_batch(batch["id"], MANAGER)

    p1_after = validate_success(api.get_piece(p1["id"], STAFF), 200)
    p2_after = validate_success(api.get_piece(p2["id"], STAFF), 200)
    assert p1_after["status"] == "PAINTED" and p1_after["kiln_batch_id"] is None
    assert p2_after["status"] == "PAINTED" and p2_after["kiln_batch_id"] is None
