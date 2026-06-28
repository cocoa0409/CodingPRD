"""Transitive cascades (series cancel, visit void), cross-entity state gates
(piece load needs OPEN visit, enroll needs ACTIVE member), the
pieces-not-ready-before-insufficient-points precedence pair, and inventory
conservation on void.

Queue A (Difficulty): transitive_cascade, cross_entity_state_dependency,
priority_pair_validation_conflict (safety vs fiscal), compensating_invariant
(inventory conserved on void).
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    create_member, create_open_visit, add_piece, create_batch, create_item,
    create_series, create_member_with_lifetime, load_piece, setup_loaded_piece,
    TEST_USERS,
)

STAFF = TEST_USERS["staff_headers"]
MANAGER = TEST_USERS["manager_headers"]


# ─── transitive_cascade / series_cancel_refunds_and_reverses_points_depth3 ──

def test_series_cancel_refunds_enrollment(api):
    """PRD §3.11: "Cancellation cascades to every still-ENROLLED enrollment: each is
    moved to REFUNDED, and for each one the earned loyalty is reversed exactly as in
    a withdrawal."

    Design: Difficulty/transitive_cascade/series_cancel_refunds_and_reverses_points_depth3
    """
    member, series, enr = create_member_with_lifetime(price_cents=50000, session_count=8,
                                                      starts_at="2026-07-20T18:00:00Z")
    api.cancel_series(series["id"], MANAGER)
    enr_after = validate_success(api.get_enrollment(enr["id"], MANAGER), 200)
    assert enr_after["status"] == "REFUNDED", enr_after["status"]


def test_series_cancel_reverses_points_and_retiers(api):
    """PRD §3.11: "the member's point_balance and lifetime_points_earned are each
    decreased by that enrollment's points_earned, and a REVERSAL ledger entry with
    source_ref_type ENROLLMENT is appended. Every affected member's tier is
    recomputed." PRD §3.1: "below 500 the member is BRONZE."

    Design: Difficulty/transitive_cascade/series_cancel_refunds_and_reverses_points_depth3
    """
    member, series, _enr = create_member_with_lifetime(price_cents=50000, session_count=8,
                                                       starts_at="2026-07-20T18:00:00Z")
    assert member["tier"] == "SILVER"  # 550 lifetime before cancel
    api.cancel_series(series["id"], MANAGER)
    member_after = validate_success(api.get_member(member["id"], MANAGER), 200)
    assert member_after["point_balance"] == 0, member_after["point_balance"]
    assert member_after["lifetime_points_earned"] == 0, member_after["lifetime_points_earned"]
    assert member_after["tier"] == "BRONZE", member_after["tier"]


# ─── transitive_cascade / visit_void_unloads_piece_depth2 ───────────────────

def test_visit_void_voids_loaded_piece(api):
    """PRD §3.9: "The void cascades to every non-terminal piece on the visit — every
    piece that is PAINTED, LOADED, FIRING, or READY — moving each to VOIDED. For any
    piece that was sitting in a kiln (that is, LOADED, FIRING, or READY), the void
    also un-loads it from its batch... and the piece's kiln_batch_id is cleared."

    Design: Difficulty/transitive_cascade/visit_void_unloads_piece_depth2
    """
    visit, piece, batch_after = setup_loaded_piece(bisque_price_cents=5000)
    api.void_visit(visit["id"], MANAGER)
    piece_after = validate_success(api.get_piece(piece["id"], STAFF), 200)
    assert piece_after["status"] == "VOIDED", piece_after["status"]
    assert piece_after["kiln_batch_id"] is None, piece_after["kiln_batch_id"]


def test_visit_void_decrements_batch_occupied(api):
    """PRD §3.9: "the void also un-loads it from its batch: the batch's
    occupied_slots is decremented by one, the batch's updated_at is refreshed, the
    batch's version is incremented."

    Design: Difficulty/transitive_cascade/visit_void_unloads_piece_depth2
    """
    visit, piece, batch_after = setup_loaded_piece(bisque_price_cents=5000)
    # batch_after.version is 2 after the single load (created v1, load -> v2)
    api.void_visit(visit["id"], MANAGER)
    batch_now = validate_success(api.get_batch(batch_after["id"], STAFF), 200)
    assert batch_now["occupied_slots"] == 0, batch_now["occupied_slots"]
    assert batch_now["version"] == 3, batch_now["version"]


# ─── cross_entity_state_dependency / piece_load_requires_visit_open ─────────

def test_load_voided_piece_after_visit_void_rejected(api):
    """PRD §3.9: "The void cascades to every non-terminal piece on the visit... moving
    each to VOIDED." PRD §3.4: "the piece must be PAINTED" for a load to succeed; a
    non-PAINTED piece "yields ERR_INVALID_STATE."

    Design: Difficulty/cross_entity_state_dependency/piece_load_requires_visit_open
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=3000, sku="MUG-12OZ", name="Mug")
    batch = create_batch(capacity_slots=4)  # version 1
    fresh = validate_success(api.get_batch(batch["id"], STAFF), 200)
    api.void_visit(visit["id"], MANAGER)  # piece -> VOIDED

    res = api.load_piece(
        batch["id"],
        {"bisque_piece_id": piece["id"], "expected_kiln_batch_version": fresh["version"]},
        STAFF)
    validate_error(res, "ERR_INVALID_STATE")


def test_load_voided_piece_leaves_batch_empty(api):
    """PRD §3.9: voiding moves the piece to VOIDED. PRD §3.4: a successful load
    increments occupied_slots; a state-rejected load consumes no slot.

    Design: Difficulty/cross_entity_state_dependency/piece_load_requires_visit_open
    """
    visit = create_open_visit()
    piece = add_piece(visit["id"], bisque_price_cents=3000, sku="MUG-13OZ", name="Mug")
    batch = create_batch(capacity_slots=4)
    fresh = validate_success(api.get_batch(batch["id"], STAFF), 200)
    api.void_visit(visit["id"], MANAGER)
    api.load_piece(
        batch["id"],
        {"bisque_piece_id": piece["id"], "expected_kiln_batch_version": fresh["version"]},
        STAFF)
    batch_now = validate_success(api.get_batch(batch["id"], STAFF), 200)
    assert batch_now["occupied_slots"] == 0, batch_now["occupied_slots"]


# ─── cross_entity_state_dependency / enroll_requires_member_active ──────────

def test_suspended_member_enroll_rejected(api):
    """PRD §3.10: "a suspended member is rejected with ERR_MEMBER_SUSPENDED." PRD
    §3.1: "a SUSPENDED member may neither enroll in a class nor redeem points."

    Design: Difficulty/cross_entity_state_dependency/enroll_requires_member_active
    """
    member = create_member()
    api.suspend_member(member["id"], MANAGER)
    series = create_series(session_count=4, seat_capacity=5, price_cents=12000,
                           starts_at="2026-08-01T18:00:00Z")
    res = api.enroll(series["id"], {"member_id": member["id"]}, STAFF)
    validate_error(res, "ERR_MEMBER_SUSPENDED")


def test_suspended_member_enroll_leaves_count_unchanged(api):
    """PRD §3.10: "a suspended member is rejected with ERR_MEMBER_SUSPENDED." PRD
    §3.10: "A series opens in OPEN status with enrolled_count at 0" — a rejected
    enroll does not increment it.

    Design: Difficulty/cross_entity_state_dependency/enroll_requires_member_active
    """
    member = create_member()
    api.suspend_member(member["id"], MANAGER)
    series = create_series(session_count=4, seat_capacity=5, price_cents=12000,
                           starts_at="2026-08-01T18:00:00Z")
    api.enroll(series["id"], {"member_id": member["id"]}, STAFF)
    series_after = validate_success(api.get_series(series["id"], MANAGER), 200)
    assert series_after["enrolled_count"] == 0, series_after["enrolled_count"]


# ── priority_pair / pieces_not_ready_before_insufficient_points_on_checkout ─

def test_pieces_not_ready_beats_insufficient_points(api):
    """PRD §3.8: "a critical safety gate applies first: every piece on the visit must
    already be in READY, PICKED_UP, or VOIDED. If any piece is still PAINTED,
    LOADED, or FIRING — that is, still somewhere in the kiln pipeline — the checkout
    is blocked with ERR_PIECES_NOT_READY."

    Design: Difficulty/priority_pair_validation_conflict/pieces_not_ready_before_insufficient_points_on_checkout
    """
    member = create_member()  # balance 0
    visit = create_open_visit(member_id=member["id"])
    add_piece(visit["id"], bisque_price_cents=3000, sku="MUG-12OZ", name="Mug")  # PAINTED

    res = api.checkout_visit(visit["id"], {"points_redeemed": 100}, STAFF)
    validate_error(res, "ERR_PIECES_NOT_READY")


def test_pieces_not_ready_leaves_visit_open(api):
    """PRD §3.8: "the checkout is blocked with ERR_PIECES_NOT_READY, because a guest
    cannot settle and walk away while their pottery is still in the kiln." PRD §3.8:
    "Only a visit that is OPEN may be checked out."

    Design: Difficulty/priority_pair_validation_conflict/pieces_not_ready_before_insufficient_points_on_checkout
    """
    member = create_member()
    visit = create_open_visit(member_id=member["id"])
    add_piece(visit["id"], bisque_price_cents=3000, sku="MUG-14OZ", name="Mug")
    api.checkout_visit(visit["id"], {"points_redeemed": 100}, STAFF)

    visit_after = validate_success(api.get_visit(visit["id"], STAFF), 200)
    assert visit_after["status"] == "OPEN", visit_after["status"]
    member_after = validate_success(api.get_member(member["id"], MANAGER), 200)
    assert member_after["point_balance"] == 0, member_after["point_balance"]


# ─── compensating_invariant / inventory_conserved_on_visit_void ─────────────

def test_inventory_restored_on_void(api):
    """PRD §3.7: "When a visit is voided, every supply line on it is treated as a
    compensating restore: the line's quantity is added back to the originating
    item's on_hand_qty." PRD §3.9: "Every paint-bar item consumed on the visit is
    compensated by restoring its consumed quantity to the item's on_hand_qty."

    Design: Difficulty/compensating_invariant/inventory_conserved_on_visit_void
    """
    item = create_item(unit_price_cents=400, on_hand=50, sku="GLZ-C", name="Glaze C")
    visit = create_open_visit()
    api.consume_supply(visit["id"], {"paint_bar_item_id": item["id"], "qty": 4}, STAFF)
    item_mid = validate_success(api.get_paint_bar_item(item["id"], STAFF), 200)
    assert item_mid["on_hand_qty"] == 46, item_mid["on_hand_qty"]

    api.void_visit(visit["id"], MANAGER)
    item_after = validate_success(api.get_paint_bar_item(item["id"], STAFF), 200)
    assert item_after["on_hand_qty"] == 50, item_after["on_hand_qty"]


def test_void_sets_visit_voided_after_inventory_restore(api):
    """PRD §3.9: "The visit's settled_total_cents stays at 0 and the visit moves from
    OPEN to VOIDED, which is terminal."

    Design: Difficulty/compensating_invariant/inventory_conserved_on_visit_void
    """
    item = create_item(unit_price_cents=400, on_hand=50, sku="GLZ-C2", name="Glaze C2")
    visit = create_open_visit()
    api.consume_supply(visit["id"], {"paint_bar_item_id": item["id"], "qty": 4}, STAFF)
    voided = validate_success(api.void_visit(visit["id"], MANAGER), 200)
    assert voided["status"] == "VOIDED", voided["status"]
    assert voided["settled_total_cents"] == 0, voided["settled_total_cents"]
