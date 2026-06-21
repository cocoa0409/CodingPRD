"""RBAC denials, not-found / invalid-state error codes, closed-resource guards,
filtered listing, and field-version optimistic concurrency.

Queue B (Corner) — rbac, errors, endpoints, cross_cutting_complexity_layers (OCC).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_arena_payload, create_rental_payload, create_league_match_payload,
    create_waiver_profile_payload,
    TEST_USERS,
    create_arena, create_field, setup_arena_and_field, create_held_booking,
    create_confirmed_booking, create_equipment, check_in_booking, complete_booking,
    create_league, open_league,
)

AM = TEST_USERS["arena_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["field_marshal_headers"]
LD = TEST_USERS["league_director_headers"]


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — rbac
# ─────────────────────────────────────────────────────────────────────────────
def test_frontdesk_cannot_create_arena_returns_forbidden(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/frontdesk_cannot_create_arena_returns_forbidden
    """
    res = api.create_arena(create_arena_payload(name="Nope"), FD)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_frontdesk_cannot_check_in_returns_forbidden(api):
    """PRD §2.1: "`FieldMarshal` owns on-field operations: check-in, completion,
    no-show, equipment return, and referee assignment."

    Design: Corner/rbac/frontdesk_cannot_check_in_returns_forbidden
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    res = api.check_in_booking(booking["id"], {"checked_in_count": 4}, FD)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_leaguedirector_cannot_reserve_equipment_returns_forbidden(api):
    """PRD §2.1: "`FrontDesk` owns the counter surface for reservations and walk-ins:
    bookings, waivers, rentals, and add-on orders."

    Design: Corner/rbac/leaguedirector_cannot_reserve_equipment_returns_forbidden
    """
    arena, field = setup_arena_and_field(
        clock="2026-06-15T09:00:00Z", arena_overrides={"marker_pool_total": 1}
    )
    unit = create_equipment(arena["id"], unit_type="MARKER", asset_tag="M-r3", deposit_cents=2000)
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    res = api.create_rental(create_rental_payload(arena["id"], booking["id"], unit["id"]), LD)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_missing_user_context_header_returns_401(api):
    """PRD §2.1: "A request missing either header, or carrying a malformed value, is
    rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 401)."

    Design: Corner/rbac/missing_user_context_header_returns_401
    """
    res = api.list_arenas(headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=401)


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — errors
# ─────────────────────────────────────────────────────────────────────────────
def test_get_rental_nonexistent_returns_rental_not_found(api):
    """PRD §2.5: "The first identifier that does not resolve causes the request to be
    rejected with the matching 404 error: ... `ERR_RENTAL_NOT_FOUND`, ..."

    Design: Corner/errors/get_rental_nonexistent_returns_rental_not_found
    """
    res = api.get_rental("11111111-1111-4111-8111-111111111111", FD)
    validate_error(res, "ERR_RENTAL_NOT_FOUND", expected_status=404)


def test_void_already_voided_waiver_returns_invalid_state(api):
    """PRD §3.6: "A waiver may be voided from either `DRAFT` or `SIGNED`, moving it to
    `VOID` and again recomputing those two booking flags; a waiver transition from a
    disallowed state is rejected with `ERR_WAIVER_INVALID_STATE`."

    Design: Corner/errors/void_already_voided_waiver_returns_invalid_state
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    waiver = validate_success(api.create_waiver_profile(create_waiver_profile_payload(
        arena["id"], booking["id"], participant_name="Adult",
        date_of_birth="1990-01-01T00:00:00Z"), FD), 201)
    validate_success(api.void_waiver(waiver["id"], FD), 200)
    res = api.void_waiver(waiver["id"], FD)
    validate_error(res, "ERR_WAIVER_INVALID_STATE", expected_status=409)


def test_void_result_recorded_match_returns_invalid_state(api):
    """PRD §3.9: "A scheduled match may instead be voided, moving it `SCHEDULED → VOID`;
    a match transition from a disallowed state is rejected with
    `ERR_MATCH_INVALID_STATE`."

    Design: Corner/errors/void_result_recorded_match_returns_invalid_state
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    check_in_booking(booking["id"], 4)
    complete_booking(booking["id"])
    league = create_league(arena["id"], total_rounds=1, name="Lw2")
    open_league(league["id"])
    match = validate_success(api.create_league_match(
        create_league_match_payload(arena["id"], league["id"], booking["id"],
                                    home_team="A", away_team="B"), LD), 201)
    validate_success(api.record_match_result(match["id"], {"home_score": 3, "away_score": 1}, LD), 200)
    res = api.void_match(match["id"], LD)
    validate_error(res, "ERR_MATCH_INVALID_STATE", expected_status=409)


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — endpoints (closed guards + filtered list)
# ─────────────────────────────────────────────────────────────────────────────
def test_create_booking_on_closed_arena_returns_arena_closed(api):
    """PRD §3.1: "The manager can later close the arena, moving `status` to `CLOSED`; a
    `CLOSED` arena blocks new bookings and rentals, surfacing as `ERR_ARENA_CLOSED`."

    Design: Corner/endpoints/create_booking_on_closed_arena_returns_arena_closed
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    validate_success(api.close_arena(arena["id"], AM), 200)
    from test_helpers import create_booking_payload
    res = api.create_booking(create_booking_payload(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z"), FD)
    validate_error(res, "ERR_ARENA_CLOSED", expected_status=409)


def test_create_booking_on_closed_field_returns_field_closed(api):
    """PRD §3.1: "Closing a field moves its `status` to `CLOSED`, which rejects new slot
    holds with `ERR_FIELD_CLOSED`."

    Design: Corner/endpoints/create_booking_on_closed_field_returns_field_closed
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    validate_success(api.close_field(field["id"], AM), 200)
    from test_helpers import create_booking_payload
    res = api.create_booking(create_booking_payload(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z"), FD)
    validate_error(res, "ERR_FIELD_CLOSED", expected_status=409)


def test_filtered_list_bookings_by_field_id(api):
    """PRD §2.3: "Where a list endpoint accepts a filter (for example a `arena_id`,
    `field_id`, `package_id`, `booking_id`, `equipment_unit_id`, `referee_id`, or
    `league_id` query parameter), pagination is applied after the filter narrows the
    collection."

    Design: Corner/endpoints/filtered_list_bookings_by_field_id
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    data, meta = validate_paginated(api.list_bookings(FD, params={"field_id": field["id"]}))
    assert len(data) >= 1
    for b in data:
        assert b["field_id"] == field["id"], \
            f"filtered list must only return bookings on {field['id']}, got {b['field_id']}"


# ─────────────────────────────────────────────────────────────────────────────
# Queue B — optimistic concurrency on field version
# ─────────────────────────────────────────────────────────────────────────────
def test_confirm_with_correct_field_version_succeeds_and_bumps(api):
    """PRD §2.6: "Because confirming a competing booking on the same field bumps that
    field's `version` (its slot ledger and reserved headcount changed), a confirm that
    still carries the older `expected_field_version` is observing stale field state and
    is rejected with `ERR_STALE_FIELD_VERSION` (HTTP 412)."
    PRD §3.3: "On success the booking transitions `HELD → CONFIRMED`, the field fee is
    computed and pinned onto the booking's `field_fee_cents`, the field's `version` is
    incremented by one, and `reserved_headcount` is recomputed."

    Design: Corner/cross_cutting_complexity_layers/confirm_with_correct_field_version_succeeds_and_bumps
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    booking = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    # Creating the booking recomputes the field's reserved_headcount, which is
    # itself a mutation of the field and bumps Field.version (PRD §2.4). Read the
    # live field version *after* the booking exists so the confirm echoes the
    # version the client would currently observe.
    field_pre = validate_success(api.get_field(field["id"], AM), 200)
    v_pre = field_pre["version"]
    confirmed = validate_success(
        api.confirm_booking(booking["id"], {"expected_field_version": v_pre}, FD), 200
    )
    assert confirmed["status"] == "CONFIRMED"
    field_after = validate_success(api.get_field(field["id"], AM), 200)
    assert field_after["version"] == v_pre + 1, \
        f"confirm must increment field version from {v_pre}, got {field_after['version']}"


def test_confirm_with_stale_field_version_returns_412(api):
    """PRD §2.6: "a confirm that still carries the older `expected_field_version` is
    observing stale field state and is rejected with `ERR_STALE_FIELD_VERSION`
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/confirm_with_stale_field_version_returns_412
    """
    arena, field = setup_arena_and_field(clock="2026-06-15T09:00:00Z")
    b1 = create_held_booking(
        arena["id"], field["id"], booking_type="WALK_IN", party_size=4,
        window_start="2026-06-15T09:00:00Z", window_end="2026-06-15T10:00:00Z",
    )
    b2 = create_held_booking(
        arena["id"], field["id"], booking_type="RESERVATION", party_size=4,
        window_start="2026-06-15T11:00:00Z", window_end="2026-06-15T12:00:00Z",
    )
    # Read the live field version once both bookings exist; both clients observed
    # this same version before either confirm.
    v_obs = validate_success(api.get_field(field["id"], AM), 200)["version"]
    # first confirm bumps Field.version to v_obs+1
    validate_success(api.confirm_booking(b1["id"], {"expected_field_version": v_obs}, FD), 200)
    # second confirm still carries pre-bump v_obs -> stale (PRD §2.6: confirming a
    # competing booking on the same field bumped the version)
    res = api.confirm_booking(b2["id"], {"expected_field_version": v_obs}, FD)
    validate_error(res, "ERR_STALE_FIELD_VERSION", expected_status=412)
