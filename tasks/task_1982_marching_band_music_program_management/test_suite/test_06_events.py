"""Event scheduling: half-open facility conflicts, temporal-vs-constraint
validation priority, weather watch, postpone/reschedule, terminal lockdown."""
from test_helpers import (
    ApiErrorId,
    assert_event,
    create_event,
    create_event_payload,
    create_open_program,
    get_event,
    parse_instant,
    postpone_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# --- Difficulty: facility_half_open_adjacency_allowed ---------------------------

def test_back_to_back_facility_booking_is_legal(api, director_headers,
                                                reader_headers):
    """PRD §3.6: "Two events in the same program may not share a facility across overlapping windows: the check is half-open, so back-to-back events where one's `starts_at` equals the other's `ends_at` are legal, and a conflict exists exactly when the other event is in `SCHEDULED`, `WEATHER_WATCH`, or `INDOOR_RELOCATED` status, the facility and program match, and the new window begins strictly before the other's end while the other's window begins strictly before the new window's end. A conflicting schedule is rejected with `ERR_FACILITY_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/facility_half_open_adjacency_allowed
    """
    program = create_open_program(season_name="FH")
    create_event(program["id"], event_type="REHEARSAL", facility="STADIUM",
                 starts_at="2026-08-10T10:00:00Z", ends_at="2026-08-10T12:00:00Z",
                 is_outdoor=True)

    adjacent = validate_success(api.create_event(
        create_event_payload(program["id"], event_type="SECTIONAL",
                             facility="STADIUM",
                             starts_at="2026-08-10T12:00:00Z",
                             ends_at="2026-08-10T14:00:00Z", is_outdoor=True),
        director_headers), 201)
    assert adjacent["status"] == "SCHEDULED", (
        "starts_at == the other's ends_at is legal under half-open semantics")

    overlapping = api.create_event(
        create_event_payload(program["id"], event_type="SECTIONAL",
                             facility="STADIUM",
                             starts_at="2026-08-10T11:59:00Z",
                             ends_at="2026-08-10T13:00:00Z", is_outdoor=True),
        director_headers)
    validate_error(overlapping, ApiErrorId.ERR_FACILITY_CONFLICT)


def test_facility_conflict_scoped_to_same_program_and_facility(
        api, director_headers):
    """PRD §3.6: "Two events in the same program may not share a facility across overlapping windows: the check is half-open, so back-to-back events where one's `starts_at` equals the other's `ends_at` are legal, and a conflict exists exactly when the other event is in `SCHEDULED`, `WEATHER_WATCH`, or `INDOOR_RELOCATED` status, the facility and program match, and the new window begins strictly before the other's end while the other's window begins strictly before the new window's end. A conflicting schedule is rejected with `ERR_FACILITY_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/facility_half_open_adjacency_allowed
    """
    program = create_open_program(season_name="FH2")
    other_program = create_open_program(season_name="FH3")
    create_event(program["id"], event_type="REHEARSAL", facility="STADIUM",
                 starts_at="2026-08-10T10:00:00Z", ends_at="2026-08-10T12:00:00Z",
                 is_outdoor=True)

    different_facility = validate_success(api.create_event(
        create_event_payload(program["id"], event_type="SECTIONAL",
                             facility="GYM",
                             starts_at="2026-08-10T11:00:00Z",
                             ends_at="2026-08-10T13:00:00Z", is_outdoor=False),
        director_headers), 201)
    assert_event(different_facility)

    different_program = validate_success(api.create_event(
        create_event_payload(other_program["id"], event_type="SECTIONAL",
                             facility="STADIUM",
                             starts_at="2026-08-10T11:00:00Z",
                             ends_at="2026-08-10T13:00:00Z", is_outdoor=True),
        director_headers), 201)
    assert_event(different_program)


# --- Difficulty: temporal_error_beats_constraint_error_on_event_create ----------

def test_inverted_window_beats_facility_conflict(api, director_headers,
                                                 reader_headers):
    """PRD §2.11 item 9: "Temporal windows are sane: an event's `ends_at` strictly after `starts_at`, a charter's `window_end` strictly after `window_start`, an assignment's `due_date` strictly after checkout, an arrangement's `rights_end` in the future, a challenge inside its seven-day window — else `ERR_EVENT_WINDOW_INVALID`, `ERR_DUE_DATE_INVALID`, `ERR_LICENSE_WINDOW_INVALID`, or `ERR_CHALLENGE_WINDOW_EXPIRED`." PRD §2.11: "This ordering is observable: when two rules fail simultaneously, the response always carries the earlier-priority error."

    Design: Difficulty/priority_pair_validation_conflict/temporal_error_beats_constraint_error_on_event_create
    """
    program = create_open_program(season_name="PV2")
    create_event(program["id"], event_type="REHEARSAL", facility="STADIUM",
                 starts_at="2026-08-10T10:00:00Z", ends_at="2026-08-10T12:00:00Z",
                 is_outdoor=True)

    # 11:00 -> 10:30 is inverted AND overlaps the existing STADIUM booking
    resp = api.create_event(
        create_event_payload(program["id"], event_type="REHEARSAL",
                             facility="STADIUM",
                             starts_at="2026-08-10T11:00:00Z",
                             ends_at="2026-08-10T10:30:00Z", is_outdoor=True),
        director_headers)
    validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_INVALID)

    _rows, meta = validate_paginated(api.list_events(
        reader_headers, params={"program_id": program["id"],
                                "facility": "STADIUM"}))
    assert meta["total_count"] == 1, "the rejected create persists nothing"


def test_temporal_and_constraint_rules_each_fire_in_isolation(
        api, director_headers):
    """PRD §3.6: "a `starts_at` and `ends_at` window that must be strictly increasing else `ERR_EVENT_WINDOW_INVALID` (HTTP 422)". PRD §3.6: "A conflicting schedule is rejected with `ERR_FACILITY_CONFLICT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_error_beats_constraint_error_on_event_create
    """
    program = create_open_program(season_name="PV3")
    create_event(program["id"], event_type="REHEARSAL", facility="STADIUM",
                 starts_at="2026-08-10T10:00:00Z", ends_at="2026-08-10T12:00:00Z",
                 is_outdoor=True)

    inverted_only = api.create_event(
        create_event_payload(program["id"], event_type="REHEARSAL",
                             facility="GYM",
                             starts_at="2026-08-10T12:00:00Z",
                             ends_at="2026-08-10T11:00:00Z", is_outdoor=False),
        director_headers)
    validate_error(inverted_only, ApiErrorId.ERR_EVENT_WINDOW_INVALID)

    conflict_only = api.create_event(
        create_event_payload(program["id"], event_type="REHEARSAL",
                             facility="STADIUM",
                             starts_at="2026-08-10T11:00:00Z",
                             ends_at="2026-08-10T13:00:00Z", is_outdoor=True),
        director_headers)
    validate_error(conflict_only, ApiErrorId.ERR_FACILITY_CONFLICT)


# --- Corner: weather watch, postpone cycle, terminal lockdown --------------------

def test_weather_watch_on_indoor_event_rejected(api, director_headers,
                                                reader_headers):
    """PRD §3.6: "Weather-watch moves a `SCHEDULED` event to `WEATHER_WATCH` and is permitted only on outdoor events — an indoor event is rejected with `ERR_EVENT_NOT_OUTDOOR` (HTTP 422) and an event not in `SCHEDULED` with `ERR_EVENT_NOT_SCHEDULED`."

    Design: Corner/validations/weather_watch_on_indoor_event_conditional_rejected
    """
    program = create_open_program(season_name="WW")
    event = create_event(program["id"], event_type="REHEARSAL", facility="GYM",
                         starts_at="2026-08-10T10:00:00Z",
                         ends_at="2026-08-10T12:00:00Z", is_outdoor=False)

    resp = api.weather_watch_event(event["id"], director_headers)
    validate_error(resp, ApiErrorId.ERR_EVENT_NOT_OUTDOOR)
    event = validate_success(api.get_event(event["id"], reader_headers))
    assert event["status"] == "SCHEDULED"


def test_postpone_then_reschedule_reruns_conflict_check(api, director_headers):
    """PRD §3.6: "Postponement moves an event from `SCHEDULED`, `WEATHER_WATCH`, or `POSTPONED` to `POSTPONED` — operating on a terminally `COMPLETED` or `CANCELLED` event yields `ERR_EVENT_TERMINAL` — and leaves the times unchanged; postponing a `POSTPONED` event again with fresh `new_starts_at` and `new_ends_at` reschedules it back to `SCHEDULED` with the new window, provided the window is strictly increasing (else `ERR_EVENT_WINDOW_INVALID`) and conflict-free (else `ERR_FACILITY_CONFLICT`)."

    Design: Corner/state_machines/event_postpone_reschedule_cycle
    """
    program = create_open_program(season_name="PP")
    event_a = create_event(program["id"], event_type="REHEARSAL",
                           facility="STADIUM",
                           starts_at="2026-08-10T10:00:00Z",
                           ends_at="2026-08-10T12:00:00Z", is_outdoor=True)
    create_event(program["id"], event_type="REHEARSAL", facility="STADIUM",
                 starts_at="2026-08-10T13:00:00Z", ends_at="2026-08-10T15:00:00Z",
                 is_outdoor=True)

    # Plain postponement moves to POSTPONED and leaves the times unchanged.
    postponed = validate_success(api.postpone_event(
        event_a["id"],
        postpone_event_payload("2026-08-12T10:00:00Z", "2026-08-12T12:00:00Z"),
        director_headers))
    assert postponed["status"] == "POSTPONED"
    assert parse_instant(postponed["starts_at"]) == parse_instant(
        "2026-08-10T10:00:00Z")
    assert parse_instant(postponed["ends_at"]) == parse_instant(
        "2026-08-10T12:00:00Z")

    # Reschedule into a window overlapping the 13:00-15:00 booking -> conflict.
    conflicted = api.postpone_event(
        event_a["id"],
        postpone_event_payload("2026-08-10T14:00:00Z", "2026-08-10T16:00:00Z"),
        director_headers)
    validate_error(conflicted, ApiErrorId.ERR_FACILITY_CONFLICT)
    event_a = get_event(event_a["id"])
    assert event_a["status"] == "POSTPONED"
    assert parse_instant(event_a["starts_at"]) == parse_instant(
        "2026-08-10T10:00:00Z")

    # A conflict-free window reschedules back to SCHEDULED with the new times.
    rescheduled = validate_success(api.postpone_event(
        event_a["id"],
        postpone_event_payload("2026-08-11T10:00:00Z", "2026-08-11T12:00:00Z"),
        director_headers))
    assert rescheduled["status"] == "SCHEDULED"
    assert parse_instant(rescheduled["starts_at"]) == parse_instant(
        "2026-08-11T10:00:00Z")
    assert parse_instant(rescheduled["ends_at"]) == parse_instant(
        "2026-08-11T12:00:00Z")


def test_cancelled_event_is_terminal_for_completion(api, director_headers,
                                                    reader_headers):
    """PRD §3.6: "Completion moves an event from `SCHEDULED`, `WEATHER_WATCH`, or `INDOOR_RELOCATED` to `COMPLETED`; from any other state the completion is rejected with `ERR_EVENT_TERMINAL`."

    Design: Corner/state_machines/event_terminal_lockdown_cancel
    """
    program = create_open_program(season_name="TL")
    event = create_event(program["id"], event_type="REHEARSAL", facility="GYM",
                         starts_at="2026-08-10T10:00:00Z",
                         ends_at="2026-08-10T12:00:00Z", is_outdoor=False)
    cancelled = validate_success(api.cancel_event(event["id"], director_headers))
    assert cancelled["status"] == "CANCELLED"

    resp = api.complete_event(event["id"], director_headers)
    validate_error(resp, ApiErrorId.ERR_EVENT_TERMINAL)
    event = validate_success(api.get_event(event["id"], reader_headers))
    assert event["status"] == "CANCELLED"
