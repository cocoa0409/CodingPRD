"""Booking/rental validations and temporal-overlap rules: lead time, window
sanity, capacity, equipment availability, package active, damage fee, field-slot
and equipment-time conflicts, and a precedence pair.

Queue A (Difficulty) — resource_temporal_overlap, priority_pair_validation_conflict.
Queue B (Corner) — validations.
"""
import pytest
from test_helpers import (
    validate_success, validate_error,
    create_booking_payload, create_party_package_payload,
    create_equipment_unit_payload,
    TEST_USERS,
    create_arena, create_field, setup_arena_and_field, create_held_booking,
    create_confirmed_booking, create_package, create_equipment,
    reserve_rental, check_in_booking, create_referee,
)

AM = TEST_USERS["arena_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["field_marshal_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — resource_temporal_overlap (two instances, two tests each)
# ─────────────────────────────────────────────────────────────────────────────
def test_field_slot_overlap_with_turnaround_buffer_rejected(api):
    """PRD §3.2: "a new `HELD` or `CONFIRMED` booking whose window, extended by the
    field's `turnaround_minutes` buffer, collides with an existing live booking's window
    on the same field is rejected with `ERR_FIELD_SLOT_CONFLICT`. The buffer means two
    sessions on one field must be separated by at least `turnaround_minutes` of clear
    time between the end of one and the start of the next ..."

    Design: Difficulty/resource_temporal_overlap/field_slot_overlap_with_turnaround_buffer
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z",
        field_overrides={"capacity_max": 10, "turnaround_minutes": 15},
    )
    create_confirmed_booking(
        arena, field, booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T10:00:00Z", window_end="2026-06-15T11:00:00Z",
    )
    # new booking starts 11:10, only 10 min after the 11:00 end < 15-min buffer
    res = api.create_booking(create_booking_payload(
        arena["id"], field["id"], booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T11:10:00Z", window_end="2026-06-15T12:00:00Z"), FD)
    validate_error(res, "ERR_FIELD_SLOT_CONFLICT", expected_status=409)


def test_field_slot_outside_turnaround_buffer_allowed(api):
    """PRD §3.2: "The buffer means two sessions on one field must be separated by at
    least `turnaround_minutes` of clear time between the end of one and the start of the
    next; the slot-conflict check is applied both at booking creation and again at
    confirmation."

    Design: Difficulty/resource_temporal_overlap/field_slot_overlap_with_turnaround_buffer
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z",
        field_overrides={"capacity_max": 10, "turnaround_minutes": 15},
    )
    create_confirmed_booking(
        arena, field, booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T10:00:00Z", window_end="2026-06-15T11:00:00Z",
    )
    # start 11:15 = exactly 15 min clear after 11:00 end -> no conflict
    res = api.create_booking(create_booking_payload(
        arena["id"], field["id"], booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T11:15:00Z", window_end="2026-06-15T12:00:00Z"), FD)
    booking = validate_success(res, 201)
    assert booking["status"] == "HELD"


def test_equipment_overlap_closed_interval_rejected(api):
    """PRD §3.4: "reserving a unit that already has a live rental whose booking window
    overlaps the new booking's window is rejected with `ERR_EQUIPMENT_TIME_CONFLICT`.
    This equipment overlap is checked on closed intervals with no turnaround buffer —
    unlike the field-slot check, two rentals of the same unit collide whenever their
    windows touch at all."

    Design: Difficulty/resource_temporal_overlap/equipment_overlap_closed_interval_no_buffer
    """
    arena = create_arena(clock="2026-06-15T09:00:00Z", marker_pool_total=1)
    field_a = create_field(arena["id"], name="F16a", game_mode="LASER_TAG", capacity_max=10)
    field_b = create_field(arena["id"], name="F16b", game_mode="LASER_TAG", capacity_max=10)
    unit = create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-16", deposit_cents=3000)
    booking_a = create_held_booking(
        arena["id"], field_a["id"], booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T10:00:00Z", window_end="2026-06-15T11:00:00Z",
    )
    reserve_rental(arena["id"], booking_a["id"], unit["id"])
    booking_b = create_held_booking(
        arena["id"], field_b["id"], booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T10:30:00Z", window_end="2026-06-15T11:30:00Z",
    )
    from test_helpers import create_rental_payload
    res = api.create_rental(create_rental_payload(arena["id"], booking_b["id"], unit["id"]), FD)
    validate_error(res, "ERR_EQUIPMENT_TIME_CONFLICT", expected_status=409)


def test_equipment_reused_for_nonoverlapping_window_allowed(api):
    """PRD §3.4: "The system also guards against handing one physical unit to two
    overlapping sessions: reserving a unit that already has a live rental whose booking
    window overlaps the new booking's window is rejected with
    `ERR_EQUIPMENT_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/equipment_overlap_closed_interval_no_buffer
    """
    arena = create_arena(clock="2026-06-15T09:00:00Z", marker_pool_total=1)
    field_a = create_field(arena["id"], name="G16a", game_mode="LASER_TAG", capacity_max=10)
    field_b = create_field(arena["id"], name="G16b", game_mode="LASER_TAG", capacity_max=10)
    unit = create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-17", deposit_cents=3000)
    booking_a = create_held_booking(
        arena["id"], field_a["id"], booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T10:00:00Z", window_end="2026-06-15T11:00:00Z",
    )
    rental_a = reserve_rental(arena["id"], booking_a["id"], unit["id"])
    # release so the unit is free, then reserve for a disjoint window
    validate_success(api.release_rental(rental_a["id"], FD), 200)
    booking_b = create_held_booking(
        arena["id"], field_b["id"], booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T12:00:00Z", window_end="2026-06-15T13:00:00Z",
    )
    from test_helpers import create_rental_payload
    res = api.create_rental(create_rental_payload(arena["id"], booking_b["id"], unit["id"]), FD)
    rental_b = validate_success(res, 201)
    assert rental_b["status"] == "HELD"


# ─────────────────────────────────────────────────────────────────────────────
# Queue A — priority_pair_validation_conflict: capacity vs field-slot
#
# NOTE: a test asserting field-slot-conflict precedence over capacity when BOTH
# are violated was removed. The PRD contradicts itself on that precedence:
# §3.2's booking-create narrative checks capacity first and field-slot "Finally"
# (capacity → ERR_CAPACITY_EXCEEDED), while §5's precedence catalogue enumerates
# "the field-slot ... conflicts, ... the capacity ... constraints"
# (field-slot → ERR_FIELD_SLOT_CONFLICT). Two divergent PRD-faithful readings
# exist, so the outcome is not uniquely derivable. The capacity-alone case below
# is unambiguous and is retained.
# ─────────────────────────────────────────────────────────────────────────────
def test_capacity_alone_reported_when_no_slot_conflict(api):
    """PRD §3.2: "A booking's `party_size` may not exceed the field's `capacity_max`, or
    the create is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_slot_beats_fiscal_damage_distinct_pair
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z",
        field_overrides={"capacity_max": 5, "turnaround_minutes": 0},
    )
    # no existing booking -> only the capacity rule can fire
    res = api.create_booking(create_booking_payload(
        arena["id"], field["id"], booking_type="RESERVATION", party_size=9,
        window_start="2026-06-15T11:00:00Z", window_end="2026-06-15T13:00:00Z"), FD)
    validate_error(res, "ERR_CAPACITY_EXCEEDED", expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — validations
# ─────────────────────────────────────────────────────────────────────────────
def test_reservation_lead_time_too_soon_returns_lead_time_violation(api):
    """PRD §3.2: "A `RESERVATION` is a future booking whose `window_start` must be at
    least sixty minutes after the arena's current time; the boundary is inclusive, so a
    `window_start` exactly sixty minutes after `current_utc` satisfies the rule. A
    `WALK_IN` whose start is not the current instant, or a `RESERVATION` that starts
    sooner than the sixty-minute floor, is rejected with `ERR_LEAD_TIME_VIOLATION`."

    Design: Corner/validations/reservation_lead_time_too_soon_returns_lead_time_violation
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    res = api.create_booking(create_booking_payload(
        arena["id"], field["id"], booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z"), FD)
    validate_error(res, "ERR_LEAD_TIME_VIOLATION", expected_status=422)


def test_invalid_window_end_before_start_returns_invalid_window(api):
    """PRD §3.2: "Window sanity is enforced first: `window_end` must be strictly later
    than `window_start`, and a non-positive-length window is rejected with
    `ERR_INVALID_WINDOW`."

    Design: Corner/validations/invalid_window_end_before_start_returns_invalid_window
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    res = api.create_booking(create_booking_payload(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T09:00:00Z"), FD)
    validate_error(res, "ERR_INVALID_WINDOW", expected_status=422)


def test_party_size_exceeds_capacity_returns_capacity_exceeded(api):
    """PRD §3.2: "A booking's `party_size` may not exceed the field's `capacity_max`, or
    the create is rejected with `ERR_CAPACITY_EXCEEDED`."

    Design: Corner/validations/party_size_exceeds_capacity_returns_capacity_exceeded
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 5}
    )
    res = api.create_booking(create_booking_payload(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=9,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z"), FD)
    validate_error(res, "ERR_CAPACITY_EXCEEDED", expected_status=409)


def test_reserve_condition_c_unit_returns_equipment_unavailable(api):
    """PRD §3.4: "To reserve, the unit must currently be `AVAILABLE` and its
    `condition_grade` must be `A` or `B`; a unit that is not available, or a grade-`C`
    unit, is rejected with `ERR_EQUIPMENT_UNAVAILABLE`."

    Design: Corner/validations/reserve_condition_c_unit_returns_equipment_unavailable
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", arena_overrides={"marker_pool_total": 1}
    )
    unit = create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-v4",
                            deposit_cents=2000, condition_grade="C")
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    from test_helpers import create_rental_payload
    res = api.create_rental(create_rental_payload(arena["id"], booking["id"], unit["id"]), FD)
    validate_error(res, "ERR_EQUIPMENT_UNAVAILABLE", expected_status=409)


def test_attach_inactive_package_returns_package_inactive(api):
    """PRD §3.2: "If a `package_id` is supplied, the package must be active and must
    belong to the same arena; an inactive or cross-arena package is rejected with
    `ERR_PACKAGE_INACTIVE`."

    Design: Corner/validations/attach_inactive_package_returns_package_inactive
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", field_overrides={"capacity_max": 12}
    )
    pkg = create_package(
        arena["id"], name="Pinactive", included_players=8, extra_player_fee_cents=500,
        base_fee_cents=9000, active=False,
    )
    res = api.create_booking(create_booking_payload(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
        package_id=pkg["id"]), FD)
    validate_error(res, "ERR_PACKAGE_INACTIVE", expected_status=409)


def test_return_damage_exceeds_deposit_returns_damage_fee_error(api):
    """PRD §3.4: "that fee may not exceed the rental's `deposit_hold_cents` — a fee
    larger than the held deposit is rejected with `ERR_DAMAGE_FEE_EXCEEDS_DEPOSIT`."

    Design: Corner/validations/return_damage_exceeds_deposit_returns_damage_fee_error
    """
    arena = create_arena(clock="2026-06-15T09:00:00Z", marker_pool_total=1)
    field = create_field(arena["id"], name="Fv6", game_mode="LASER_TAG", capacity_max=8)
    unit = create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-v6", deposit_cents=2000)
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    rental = reserve_rental(arena["id"], booking["id"], unit["id"])
    check_in_booking(booking["id"], 4)
    res = api.return_rental(rental["id"], {"damage_fee_cents": 5000}, FM)
    validate_error(res, "ERR_DAMAGE_FEE_EXCEEDS_DEPOSIT", expected_status=422)


def test_walk_in_start_must_equal_clock(api):
    """PRD §3.2: "A `WALK_IN` must begin exactly at the arena's current time — its
    `window_start` must equal the arena's `current_utc` at create time."

    Design: Corner/validations/walk_in_start_must_equal_clock
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    res = api.create_booking(create_booking_payload(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:30:00Z", window_end="2026-06-15T10:00:00Z"), FD)
    validate_error(res, "ERR_LEAD_TIME_VIOLATION", expected_status=422)


def test_referee_not_certified_for_paintball_returns_not_eligible(api):
    """PRD §3.7: "assigning a referee who is not `certified_paintball` to a booking on a
    `PAINTBALL` field is rejected — both surface as `ERR_REFEREE_NOT_ELIGIBLE`."

    Design: Corner/validations/referee_not_certified_for_paintball_returns_not_eligible
    """
    arena = create_arena(clock="2026-06-15T09:00:00Z")
    field = create_field(arena["id"], name="PBv8", game_mode="PAINTBALL", capacity_max=6)
    referee = create_referee(arena["id"], name="NonCert", certified_paintball=False)
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    from test_helpers import create_referee_assignment_payload
    res = api.create_referee_assignment(
        create_referee_assignment_payload(arena["id"], booking["id"], referee["id"]), FM)
    validate_error(res, "ERR_REFEREE_NOT_ELIGIBLE", expected_status=409)


def test_create_booking_on_missing_field_returns_not_found(api):
    """PRD §2.5: "those identifiers are validated for existence in left-to-right order,
    arena first and then the more specific references. The first identifier that does not
    resolve causes the request to be rejected with the matching 404 error ... Existence
    is checked before any state or business rule ..."

    Design: Corner/validations/create_booking_on_missing_field_returns_not_found
    """
    arena = create_arena(clock="2026-06-15T09:00:00Z")
    res = api.create_booking(create_booking_payload(
        arena["id"], "00000000-0000-4000-8000-000000000abc",
        booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z"), FD)
    validate_error(res, "ERR_FIELD_NOT_FOUND", expected_status=404)
