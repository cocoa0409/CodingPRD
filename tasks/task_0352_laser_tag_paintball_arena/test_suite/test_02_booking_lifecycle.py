"""Booking lifecycle: initial state, valid/invalid transitions, the
CONFIRMED→NO_SHOW branch, the referee-threshold boundary, and the
confirm→cancel headcount conservation invariant.

Queue A (Difficulty) — non_linear_state_machine, boundary_precision_check,
compensating_invariant.
Queue B (Corner) — state_machines, consistency_model.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_arena_payload, create_field_payload, create_booking_payload,
    create_party_package_payload, create_equipment_unit_payload,
    TEST_USERS,
    create_arena, create_field, setup_arena_and_field, create_held_booking,
    create_confirmed_booking, create_equipment,
)
from test_helpers.api_client import api_client

AM = TEST_USERS["arena_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["field_marshal_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — booking initial state & invalid transitions
# ─────────────────────────────────────────────────────────────────────────────
def test_booking_initial_state_is_held(api):
    """PRD §3.2: "The booking is created in `HELD` status, the field's
    `reserved_headcount` is recomputed, and the booking's `minors_present` and
    `referee_required` flags are computed from its (initially empty) waiver set and
    its field's game mode."

    Design: Corner/state_machines/booking_initial_state_is_held
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = validate_success(
        api.create_booking(create_booking_payload(arena["id"], field["id"]), FD), 201
    )
    assert booking["status"] == "HELD", f"new booking must be HELD, got {booking['status']}"


def test_confirm_already_confirmed_booking_returns_invalid_state(api):
    """PRD §3.3: "Confirming requires the booking to be `HELD`, the field to be
    `ACTIVE`, and the arena to be `OPEN`; a booking in any other state is rejected with
    `ERR_BOOKING_INVALID_STATE`."

    Design: Corner/state_machines/confirm_already_confirmed_booking_returns_invalid_state
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_confirmed_booking(arena, field)
    live_field = validate_success(api.get_field(field["id"], AM), 200)
    res = api.confirm_booking(booking["id"], {"expected_field_version": live_field["version"]}, FD)
    validate_error(res, "ERR_BOOKING_INVALID_STATE", expected_status=409)


def test_cancel_completed_booking_terminal_lockdown(api):
    """PRD §3.8: "Cancellation is the `FrontDesk` escape hatch and is permitted while
    the booking is `HELD` or `CONFIRMED`; a booking in any other state cannot be
    cancelled and is rejected with `ERR_BOOKING_INVALID_STATE`."

    Design: Corner/state_machines/cancel_completed_booking_terminal_lockdown
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_confirmed_booking(arena, field, party_size=4)
    validate_success(api.check_in_booking(booking["id"], {"checked_in_count": 4}, FM), 200)
    validate_success(api.complete_booking(booking["id"], FM), 200)
    res = api.cancel_booking(booking["id"], FD)
    validate_error(res, "ERR_BOOKING_INVALID_STATE", expected_status=409)


def test_restore_equipment_not_in_maintenance_invalid_state(api):
    """PRD §3.4: "restoring a unit that is not in `MAINTENANCE` is rejected with
    `ERR_EQUIPMENT_INVALID_STATE`."

    Design: Corner/state_machines/restore_equipment_not_in_maintenance_invalid_state
    """
    arena = create_arena(clock=None, marker_pool_total=1)
    unit = create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-b3", deposit_cents=2000)
    res = api.restore_equipment_unit(unit["id"], AM)
    validate_error(res, "ERR_EQUIPMENT_INVALID_STATE", expected_status=409)


def test_no_show_before_window_end_returns_invalid_state(api):
    """PRD §3.8: "No-show requires the booking to be `CONFIRMED` and the arena's current
    time to be at or after `window_end`; on success the booking transitions
    `CONFIRMED → NO_SHOW`, ..."

    Design: Corner/state_machines/no_show_before_window_end_returns_invalid_state
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:30:00Z")
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:30:00Z", window_end="2026-06-15T11:00:00Z",
    )
    # clock still inside [09:30, 11:00)
    res = api.no_show_booking(booking["id"], FM)
    validate_error(res, "ERR_BOOKING_INVALID_STATE", expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — non_linear_state_machine: CONFIRMED→NO_SHOW branch (two tests)
# ─────────────────────────────────────────────────────────────────────────────
def test_booking_no_show_branch_transitions_and_releases_headcount(api):
    """PRD §3.8: "A `FieldMarshal` marks a confirmed booking as a no-show once its
    window has passed. No-show requires the booking to be `CONFIRMED` and the arena's
    current time to be at or after `window_end`; on success the booking transitions
    `CONFIRMED → NO_SHOW`, every `HELD` rental for it is released (units back to
    `AVAILABLE`, `deposit_held_cents` decremented), every `QUOTED` add-on order is
    voided, any referee assignment is released and its referee freed, and
    `reserved_headcount` is recomputed."

    Design: Difficulty/non_linear_state_machine/booking_branch_checkin_vs_noshow
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 8}
    )
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    # advance clock past window_end
    validate_success(api.set_clock({"arena_id": arena["id"], "to_iso8601": "2026-06-15T10:30:00Z"}, AM), 200)
    res = api.no_show_booking(booking["id"], FM)
    updated = validate_success(res, 200)
    assert updated["status"] == "NO_SHOW", f"expected NO_SHOW, got {updated['status']}"
    field_after = validate_success(api.get_field(field["id"], AM), 200)
    assert field_after["reserved_headcount"] == 0, \
        f"reserved_headcount must drop to 0 after no-show, got {field_after['reserved_headcount']}"


def test_booking_no_show_terminal_status_persisted(api):
    """PRD §3.8: "on success the booking transitions `CONFIRMED → NO_SHOW`, every
    `HELD` rental for it is released (units back to `AVAILABLE`, `deposit_held_cents`
    decremented), every `QUOTED` add-on order is voided, any referee assignment is
    released and its referee freed, and `reserved_headcount` is recomputed."

    Design: Difficulty/non_linear_state_machine/booking_branch_checkin_vs_noshow
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    validate_success(api.set_clock({"arena_id": arena["id"], "to_iso8601": "2026-06-15T10:30:00Z"}, AM), 200)
    validate_success(api.no_show_booking(booking["id"], FM), 200)
    fetched = validate_success(api.get_booking(booking["id"], FM), 200)
    assert fetched["status"] == "NO_SHOW"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — boundary_precision_check: referee threshold party 11 vs 12 (two tests)
# ─────────────────────────────────────────────────────────────────────────────
def test_referee_required_false_below_threshold_party_11(api):
    """PRD §3.6: "a booking requires a referee when its `party_size` is at least 12, or
    when minors are present, or when the field's `game_mode` is `PAINTBALL`. Any one of
    these three conditions is sufficient."

    Design: Difficulty/boundary_precision_check/referee_threshold_party_11_vs_12_empty_vs_required
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z",
        field_overrides={"game_mode": "LASER_TAG", "capacity_max": 20},
    )
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=11,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    assert booking["referee_required"] is False, \
        "party_size 11 on LASER_TAG with no minors must not require a referee"


def test_referee_required_true_at_threshold_party_12(api):
    """PRD §3.6: "a booking requires a referee when its `party_size` is at least 12, or
    when minors are present, or when the field's `game_mode` is `PAINTBALL`. Any one of
    these three conditions is sufficient."

    Design: Difficulty/boundary_precision_check/referee_threshold_party_11_vs_12_empty_vs_required
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z",
        field_overrides={"game_mode": "LASER_TAG", "capacity_max": 20},
    )
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="RESERVATION", party_size=12,
        window_start="2026-06-15T10:30:00Z", window_end="2026-06-15T11:30:00Z",
    )
    assert booking["referee_required"] is True, \
        "party_size 12 (>= threshold) must require a referee"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — compensating_invariant: confirm raises then cancel restores headcount
# ─────────────────────────────────────────────────────────────────────────────
def test_field_headcount_restored_to_zero_after_confirm_then_cancel(api):
    """PRD §3.1: "The `reserved_headcount` is computed: it is the sum of `party_size`
    over all bookings on the field that currently hold a live slot — those in `HELD`,
    `CONFIRMED`, or `CHECKED_IN` whose window overlaps the current time — and it is
    recomputed on every booking transition."
    PRD §3.8: "any referee assignment for the booking is released and its referee
    returned to `AVAILABLE`; and finally the field's `reserved_headcount` is recomputed.
    The booking ends in `CANCELLED`."

    Design: Difficulty/compensating_invariant/field_headcount_conserved_on_confirm_then_cancel
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 10}
    )
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=7,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    field_confirmed = validate_success(api.get_field(field["id"], AM), 200)
    assert field_confirmed["reserved_headcount"] == 7, \
        f"confirm must raise reserved_headcount to 7, got {field_confirmed['reserved_headcount']}"

    cancelled = validate_success(api.cancel_booking(booking["id"], FD), 200)
    assert cancelled["status"] == "CANCELLED"
    field_after = validate_success(api.get_field(field["id"], AM), 200)
    assert field_after["reserved_headcount"] == 0, \
        f"cancel must restore reserved_headcount to 0, got {field_after['reserved_headcount']}"


def test_confirm_then_cancel_booking_ends_cancelled(api):
    """PRD §3.8: "Cancellation is the `FrontDesk` escape hatch and is permitted while
    the booking is `HELD` or `CONFIRMED`; a booking in any other state cannot be
    cancelled and is rejected with `ERR_BOOKING_INVALID_STATE`."

    Design: Difficulty/compensating_invariant/field_headcount_conserved_on_confirm_then_cancel
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 10}
    )
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=7,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    cancelled = validate_success(api.cancel_booking(booking["id"], FD), 200)
    assert cancelled["status"] == "CANCELLED", \
        f"cancelled booking must end CANCELLED, got {cancelled['status']}"


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — consistency_model: immediate visibility of confirm fee
# ─────────────────────────────────────────────────────────────────────────────
def test_immediate_visibility_of_confirm_fee_in_same_response(api):
    """PRD §3.3: "On success the booking transitions `HELD → CONFIRMED`, the field fee
    is computed and pinned onto the booking's `field_fee_cents`, the field's `version`
    is incremented by one, and `reserved_headcount` is recomputed."

    Design: Corner/consistency_model/immediate_visibility_of_confirm_fee_in_same_response
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 12}
    )
    pkg = validate_success(
        api.create_party_package(create_party_package_payload(
            arena["id"], name="Py1", included_players=10,
            extra_player_fee_cents=500, base_fee_cents=9000, active=True), AM), 201
    )
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=10,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
        package_id=pkg["id"],
    )
    live_field = validate_success(api.get_field(field["id"], AM), 200)
    confirmed = validate_success(
        api.confirm_booking(booking["id"], {"expected_field_version": live_field["version"]}, FD), 200
    )
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["field_fee_cents"] == 9000, \
        f"confirm response must reflect field_fee_cents 9000, got {confirmed['field_fee_cents']}"
