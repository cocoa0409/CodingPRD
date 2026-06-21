"""Provisioning and CRUD: arena/field/waiver creation, validation, defaults,
computed fields, not-found, and listing envelope.

Queue B (Corner) — sections: entities.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error, validate_paginated,
    assert_arena, assert_field, assert_waiver_profile,
    create_arena_payload, set_clock_payload, create_field_payload,
    create_booking_payload, create_waiver_profile_payload,
    TEST_USERS, NON_EXISTENT_UUID,
    create_arena, setup_arena_and_field, create_held_booking,
)

AM = TEST_USERS["arena_manager_headers"]
FD = TEST_USERS["front_desk_headers"]


def test_create_arena_returns_201_with_system_fields(api):
    """PRD §3.1: "A new arena opens in `OPEN` status with its equipment available
    counts at zero — no units exist yet — and its deposit ledger at zero."
    PRD §2.4: "an integer `version` that begins at its creation value and increments
    by one on every mutation."

    Design: Corner/entities/create_arena_returns_201_with_system_fields
    """
    res = api.create_arena(create_arena_payload(name="Corner Arena",
                                                marker_pool_total=0, vest_pool_total=0), AM)
    arena = validate_success(res, 201)
    assert_arena(arena)
    assert arena["status"] == "OPEN", f"new arena must be OPEN, got {arena['status']}"
    assert arena["version"] == 1, f"version must begin at 1, got {arena['version']}"
    assert arena["marker_available_count"] == 0
    assert arena["deposit_held_cents"] == 0


def test_create_field_missing_game_mode_returns_validation(api):
    """PRD §2.5: "a write request that omits a required input field, supplies a field
    of the wrong type, or supplies an enum value outside the declared domain (for example
    a `game_mode`, `unit_type`, `booking_type`, or `condition_grade` not among its
    allowed strings) is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_field_missing_game_mode_returns_validation
    """
    arena = create_arena()
    payload = {"arena_id": arena["id"], "name": "NoMode", "capacity_max": 8}
    res = api.create_field(payload, AM)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_create_field_invalid_game_mode_enum_returns_validation(api):
    """PRD §2.5: "a write request that omits a required input field, supplies a field
    of the wrong type, or supplies an enum value outside the declared domain (for example
    a `game_mode`, `unit_type`, `booking_type`, or `condition_grade` not among its
    allowed strings) is rejected with `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/create_field_invalid_game_mode_enum_returns_validation
    """
    arena = create_arena()
    payload = create_field_payload(arena["id"], name="BadMode", game_mode="AIRSOFT", capacity_max=8)
    res = api.create_field(payload, AM)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_turnaround_minutes_defaults_to_zero_when_omitted(api):
    """PRD §3.1: "an optional `turnaround_minutes` buffer (defaulting to 0, never
    negative)."

    Design: Corner/entities/turnaround_minutes_defaults_to_zero_when_omitted
    """
    arena = create_arena()
    payload = {"arena_id": arena["id"], "name": "DefBuf", "game_mode": "LASER_TAG", "capacity_max": 8}
    field = validate_success(api.create_field(payload, AM), 201)
    assert field["turnaround_minutes"] == 0, \
        f"omitted turnaround_minutes must default to 0, got {field['turnaround_minutes']}"


def test_waiver_age_and_is_minor_computed_from_clock(api):
    """PRD §3.6: "At creation the profile's `age_years` is computed as the full years
    between `date_of_birth` and the arena's `current_utc`, and `is_minor` is set true
    when `age_years` is below 18."

    Design: Corner/entities/waiver_age_and_is_minor_computed_from_clock
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_held_booking(arena["id"], field["id"])
    payload = create_waiver_profile_payload(
        arena["id"], booking["id"], participant_name="Teen",
        date_of_birth="2010-01-01T00:00:00Z", guardian_name="Parent",
    )
    waiver = validate_success(api.create_waiver_profile(payload, FD), 201)
    assert_waiver_profile(waiver)
    assert waiver["age_years"] == 16, f"age_years must be 16, got {waiver['age_years']}"
    assert waiver["is_minor"] is True


def test_get_arena_nonexistent_returns_not_found(api):
    """PRD §2.5: "The first identifier that does not resolve causes the request to be
    rejected with the matching 404 error: `ERR_ARENA_NOT_FOUND`, `ERR_FIELD_NOT_FOUND`,
    `ERR_PACKAGE_NOT_FOUND`, `ERR_BOOKING_NOT_FOUND`, ..."

    Design: Corner/entities/get_arena_nonexistent_returns_not_found
    """
    res = api.get_arena(NON_EXISTENT_UUID, AM)
    validate_error(res, "ERR_ARENA_NOT_FOUND", expected_status=404)


def test_list_bookings_paginated_envelope(api):
    """PRD §2.3: "List responses always carry `limit`, `offset`, `total_count`, and
    `has_more` inside the `meta` object of the envelope."

    Design: Corner/entities/list_bookings_paginated_envelope
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    create_held_booking(arena["id"], field["id"])
    data, meta = validate_paginated(api.list_bookings(FD))
    assert isinstance(data, list)
    assert meta["total_count"] >= 1, f"total_count must be >= 1, got {meta['total_count']}"
    assert "has_more" in meta
