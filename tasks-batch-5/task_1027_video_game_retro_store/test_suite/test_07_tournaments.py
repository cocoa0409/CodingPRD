"""Tournament scheduling (station double-booking) and registration guards.

Difficulty: resource_temporal_overlap (adjacency vs overlap),
priority_pair_validation_conflict (registration-window beats capacity). Corner:
validations.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, TEST_USERS,
    create_member, create_station_payload, create_tournament_payload,
    register_payload, setup_tournament, set_clock,
)

CLERK = TEST_USERS["clerk_headers"]
MANAGER = TEST_USERS["manager_headers"]


def _make_station(seat_capacity=16):
    return validate_success(
        api_client.create_station(create_station_payload(seat_capacity=seat_capacity), MANAGER), 201)


# ─── Difficulty: tournament adjacency allowed, overlap rejected ───────────
def test_adjacent_tournament_accepted(api):
    """PRD §3.9: "Using half-open intervals with no buffer, the new tournament conflicts
    with an existing one when the new starts_at is earlier than the other's ends_at and
    simultaneously the other's starts_at is earlier than the new ends_at. Exact adjacency
    — the new starts_at equal to the other's ends_at — does not conflict and is accepted."

    Design: Difficulty/resource_temporal_overlap/tournament_adjacent_allowed_but_overlap_rejected
    """
    station = _make_station()
    t1_payload = create_tournament_payload(
        station["id"], title="T1", starts_at="2026-07-03T10:00:00Z",
        ends_at="2026-07-03T12:00:00Z", registration_opens_at="2026-07-01T00:00:00Z",
        registration_closes_at="2026-07-03T09:00:00Z", max_participants=8)
    validate_success(api.create_tournament(t1_payload, CLERK), 201)

    t2_payload = create_tournament_payload(
        station["id"], title="T2 adjacent", starts_at="2026-07-03T12:00:00Z",
        ends_at="2026-07-03T14:00:00Z", registration_opens_at="2026-07-01T00:00:00Z",
        registration_closes_at="2026-07-03T11:00:00Z", max_participants=8)
    t2 = validate_success(api.create_tournament(t2_payload, CLERK), 201)
    assert t2["starts_at"] == "2026-07-03T12:00:00Z"


def test_overlapping_tournament_rejected(api):
    """PRD §3.9: "Using half-open intervals with no buffer, the new tournament conflicts
    with an existing one when the new starts_at is earlier than the other's ends_at and
    simultaneously the other's starts_at is earlier than the new ends_at. ... A conflict
    is rejected with ERR_STATION_DOUBLE_BOOKED (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/tournament_adjacent_allowed_but_overlap_rejected
    """
    station = _make_station()
    t1_payload = create_tournament_payload(
        station["id"], title="T1", starts_at="2026-07-03T10:00:00Z",
        ends_at="2026-07-03T12:00:00Z", registration_opens_at="2026-07-01T00:00:00Z",
        registration_closes_at="2026-07-03T09:00:00Z", max_participants=8)
    validate_success(api.create_tournament(t1_payload, CLERK), 201)
    t2_payload = create_tournament_payload(
        station["id"], title="T2 adjacent", starts_at="2026-07-03T12:00:00Z",
        ends_at="2026-07-03T14:00:00Z", registration_opens_at="2026-07-01T00:00:00Z",
        registration_closes_at="2026-07-03T11:00:00Z", max_participants=8)
    validate_success(api.create_tournament(t2_payload, CLERK), 201)

    t3_payload = create_tournament_payload(
        station["id"], title="T3 overlap", starts_at="2026-07-03T11:00:00Z",
        ends_at="2026-07-03T13:00:00Z", registration_opens_at="2026-07-01T00:00:00Z",
        registration_closes_at="2026-07-03T10:30:00Z", max_participants=8)
    res = api.create_tournament(t3_payload, CLERK)
    validate_error(res, "ERR_STATION_DOUBLE_BOOKED", expected_status=409)


# ─── Difficulty: registration-closed beats tournament-full ────────────────
def test_registration_closed_beats_full(api):
    """PRD §3.9: "Registration is guarded by three checks, evaluated in this order. First,
    the current clock time must fall within the half-open window from
    registration_opens_at (inclusive) up to registration_closes_at (exclusive); outside
    that window registration is rejected with ERR_REGISTRATION_CLOSED (HTTP 409). Second,
    the tournament must have remaining capacity ... a full tournament is rejected with
    ERR_TOURNAMENT_FULL (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/registration_closed_beats_tournament_full
    """
    station, tournament = setup_tournament(
        max_participants=1, starts_at="2026-07-03T10:00:00Z", ends_at="2026-07-03T12:00:00Z",
        registration_opens_at="2026-07-01T00:00:00Z",
        registration_closes_at="2026-07-02T00:00:00Z", title="Cup")
    m1 = create_member(full_name="First")
    m2 = create_member(full_name="Second")
    validate_success(api.register_tournament(tournament["id"], register_payload(m1["id"]), CLERK), 200)

    set_clock("2026-07-02T06:00:00Z")
    res = api.register_tournament(tournament["id"], register_payload(m2["id"]), CLERK)
    validate_error(res, "ERR_REGISTRATION_CLOSED", expected_status=409)


def test_registration_window_precedence_not_full_error(api):
    """PRD §3.9: "Registration is guarded by three checks, evaluated in this order. First,
    the current clock time must fall within the half-open window ... ERR_REGISTRATION_CLOSED
    (HTTP 409). Second, the tournament must have remaining capacity ... ERR_TOURNAMENT_FULL
    (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/registration_closed_beats_tournament_full
    """
    station, tournament = setup_tournament(
        max_participants=1, starts_at="2026-07-03T10:00:00Z", ends_at="2026-07-03T12:00:00Z",
        registration_opens_at="2026-07-01T00:00:00Z",
        registration_closes_at="2026-07-02T00:00:00Z", title="Cup")
    m1 = create_member(full_name="First")
    m2 = create_member(full_name="Second")
    validate_success(api.register_tournament(tournament["id"], register_payload(m1["id"]), CLERK), 200)

    set_clock("2026-07-02T06:00:00Z")
    res = api.register_tournament(tournament["id"], register_payload(m2["id"]), CLERK)
    assert res.status_code == 409
    assert res.json()["data"]["error_id"] != "ERR_TOURNAMENT_FULL"


# ─── Corner: validations / duplicate registration ─────────────────────────
def test_duplicate_registration_rejected(api):
    """PRD §3.9: "Third, the member must not already appear in registered_member_ids; a
    repeat registration is rejected with ERR_ALREADY_REGISTERED (HTTP 409)."

    Design: Corner/validations/duplicate_registration_returns_409
    """
    station, tournament = setup_tournament(
        max_participants=5, starts_at="2026-07-05T10:00:00Z", ends_at="2026-07-05T12:00:00Z",
        registration_opens_at="2026-07-01T00:00:00Z",
        registration_closes_at="2026-07-05T09:00:00Z", title="Open Cup")
    m1 = create_member(full_name="Reg")
    validate_success(api.register_tournament(tournament["id"], register_payload(m1["id"]), CLERK), 200)

    res = api.register_tournament(tournament["id"], register_payload(m1["id"]), CLERK)
    validate_error(res, "ERR_ALREADY_REGISTERED", expected_status=409)


# ─── Corner: validations / capacity full ──────────────────────────────────
def test_tournament_capacity_full_rejected(api):
    """PRD §3.9: "the tournament must have remaining capacity — registered_count strictly
    less than max_participants; a full tournament is rejected with ERR_TOURNAMENT_FULL
    (HTTP 409)."

    Design: Corner/validations/tournament_capacity_full_returns_409
    """
    station, tournament = setup_tournament(
        max_participants=1, starts_at="2026-07-06T10:00:00Z", ends_at="2026-07-06T12:00:00Z",
        registration_opens_at="2026-07-01T00:00:00Z",
        registration_closes_at="2026-07-06T09:00:00Z", title="Tiny")
    m1 = create_member(full_name="One")
    m2 = create_member(full_name="Two")
    validate_success(api.register_tournament(tournament["id"], register_payload(m1["id"]), CLERK), 200)

    res = api.register_tournament(tournament["id"], register_payload(m2["id"]), CLERK)
    validate_error(res, "ERR_TOURNAMENT_FULL", expected_status=409)
