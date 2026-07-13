"""Provisioning (venues, events) and scheduling conflicts (lanes, shifts)."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId, NON_EXISTENT_UUID, TEST_USERS,
    is_valid_uuid, assert_event,
    create_venue_payload, create_event_payload, create_lane_assignment_payload,
    create_shift_payload,
)
from test_helpers.fixtures import create_venue, create_event, create_attendant, setup_checked_in_ticket

SUP = TEST_USERS["supervisor_headers"]


def test_create_venue_returns_201_and_defaults_currency(api):
    """PRD §4: "Operations that create a new resource return `201 Created`".
    PRD §3.1: "The root configuration entity is the **Venue**, created by a `Supervisor`
    with a display `name`, a street `address`, and optionally a `currency` code (defaulting
    to `USD`)."

    Design: Corner/entities/create_venue_returns_201_with_system_fields
    """
    res = api.create_venue(create_venue_payload(name="V1", address="1 St"), SUP)
    venue = validate_success(res, 201)
    assert is_valid_uuid(venue["id"]), "id must be a server-minted UUID"
    assert venue["currency"] == "USD", "currency defaults to USD when omitted"


def test_event_rate_card_defaults_applied(api):
    """PRD §3.1: "An event embeds its rate card at creation time, all fields optional with
    defaults: `free_grace_minutes` (default 15), `hourly_rate_cents` (default 800),
    `daily_max_cents` (default 2500), `event_surcharge_cents` (default 500),
    `overflow_surcharge_cents` (default 700), and `tip_split_mode` (default `EQUAL`, the
    alternative being `WEIGHTED`)."

    Design: Corner/entities/event_default_rate_fields_applied
    """
    venue = create_venue()
    res = api.create_event(create_event_payload(venue["id"], name="E1"), SUP)
    event = validate_success(res, 201)
    assert_event(event)
    assert event["free_grace_minutes"] == 15
    assert event["hourly_rate_cents"] == 800
    assert event["daily_max_cents"] == 2500
    assert event["event_surcharge_cents"] == 500
    assert event["overflow_surcharge_cents"] == 700
    assert event["tip_split_mode"] == "EQUAL"


def test_event_missing_name_rejected(api):
    """PRD §2.4: "a request whose body is missing a required field, carries a value of the
    wrong type, or supplies an out-of-domain enum value is rejected with `ERR_VALIDATION`."

    Design: Corner/errors/event_missing_required_name_returns_validation
    """
    venue = create_venue()
    payload = create_event_payload(venue["id"])
    del payload["name"]
    res = api.create_event(payload, SUP)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_event_unknown_venue_fk_rejected(api):
    """PRD §2.4: "The first identifier that does not resolve to an existing resource halts
    processing and yields the corresponding not-found error — `ERR_VENUE_NOT_FOUND`,
    `ERR_EVENT_NOT_FOUND`, `ERR_LOT_NOT_FOUND`, `ERR_ATTENDANT_NOT_FOUND`, `ERR_SHIFT_NOT_FOUND`,
    `ERR_TICKET_NOT_FOUND`, `ERR_RETRIEVAL_NOT_FOUND`, `ERR_VALIDATION_GRANT_NOT_FOUND`,
    `ERR_DAMAGE_CLAIM_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, or `ERR_LANE_ASSIGNMENT_NOT_FOUND` —
    before any business rule is evaluated."

    Design: Corner/errors/event_bad_venue_fk_not_found
    """
    res = api.create_event(create_event_payload(NON_EXISTENT_UUID, name="E1"), SUP)
    validate_error(res, ApiErrorId.ERR_VENUE_NOT_FOUND)


def test_event_end_before_start_rejected(api):
    """PRD §3.1: "the operating window as `window_start` (inclusive) and `window_end`
    (exclusive), where the end must be strictly after the start; a window whose end is at or
    before its start is rejected with `ERR_INVALID_TIME_WINDOW`."

    Design: Corner/validations/event_bad_window_returns_invalid_time_window
    """
    venue = create_venue()
    res = api.create_event(create_event_payload(
        venue["id"], name="Bad",
        window_start="2026-06-01T12:00:00Z", window_end="2026-06-01T08:00:00Z"), SUP)
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_WINDOW)


def test_get_unknown_ticket_returns_not_found(api):
    """PRD §2.4: "The first identifier that does not resolve to an existing resource halts
    processing and yields the corresponding not-found error ... `ERR_TICKET_NOT_FOUND` ...
    before any business rule is evaluated."

    Design: Corner/errors/get_ticket_not_found
    """
    res = api.get_ticket(NON_EXISTENT_UUID, SUP)
    validate_error(res, ApiErrorId.ERR_TICKET_NOT_FOUND)


def test_list_tickets_returns_paginated_envelope(api):
    """PRD §2.3: "Every list response echoes `limit`, `offset`, `total_count`, and `has_more`
    inside the `meta` object of the envelope."

    Design: Corner/entities/list_tickets_pagination_envelope
    """
    env = setup_checked_in_ticket()
    res = api.list_tickets(SUP, params={"event_id": env["event"]["id"], "limit": 10, "offset": 0})
    data, meta = validate_paginated(res)
    assert meta["total_count"] == 1
    assert "has_more" in meta
    assert len(data) == 1


def test_adjacent_lane_window_allowed(api):
    """PRD §3.3: "Two reservations of the same venue and `lane_code` may not overlap in time;
    overlap is judged on half-open intervals, so a reservation ending exactly when another
    begins does not conflict, while any true overlap is rejected with `ERR_LANE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/lane_assignment_half_open_adjacency_allowed
    """
    venue = create_venue()
    event = create_event(venue["id"])
    validate_success(api.create_lane_assignment(create_lane_assignment_payload(
        venue["id"], event["id"], lane_code="A1",
        window_start="2026-06-01T10:00:00Z", window_end="2026-06-01T12:00:00Z"), SUP), 201)
    res = api.create_lane_assignment(create_lane_assignment_payload(
        venue["id"], event["id"], lane_code="A1",
        window_start="2026-06-01T12:00:00Z", window_end="2026-06-01T14:00:00Z"), SUP)
    la2 = validate_success(res, 201)
    assert la2["window_start"] == "2026-06-01T12:00:00Z"


def test_overlapping_lane_window_rejected(api):
    """PRD §3.3: "Two reservations of the same venue and `lane_code` may not overlap in time;
    overlap is judged on half-open intervals, so a reservation ending exactly when another
    begins does not conflict, while any true overlap is rejected with `ERR_LANE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/lane_assignment_half_open_adjacency_allowed
    """
    venue = create_venue()
    event = create_event(venue["id"])
    validate_success(api.create_lane_assignment(create_lane_assignment_payload(
        venue["id"], event["id"], lane_code="A1",
        window_start="2026-06-01T10:00:00Z", window_end="2026-06-01T12:00:00Z"), SUP), 201)
    res = api.create_lane_assignment(create_lane_assignment_payload(
        venue["id"], event["id"], lane_code="A1",
        window_start="2026-06-01T11:00:00Z", window_end="2026-06-01T13:00:00Z"), SUP)
    validate_error(res, ApiErrorId.ERR_LANE_WINDOW_CONFLICT)


def test_shift_with_rest_gap_allowed(api):
    """PRD §3.4: "A new shift may not overlap another shift of the same attendant, and even
    when they do not overlap, consecutive shifts of one attendant must be separated by at least
    a 30-minute rest gap; a shift that overlaps another of the same attendant, or that leaves
    less than 30 minutes of separation, is rejected with `ERR_SHIFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/shift_rest_buffer_gap_required
    """
    venue = create_venue()
    attendant = create_attendant(venue["id"])
    validate_success(api.create_shift(create_shift_payload(
        attendant["id"], "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z"), SUP), 201)
    res = api.create_shift(create_shift_payload(
        attendant["id"], "2026-06-01T12:30:00Z", "2026-06-01T14:00:00Z"), SUP)
    s3 = validate_success(res, 201)
    assert s3["start_at"] == "2026-06-01T12:30:00Z"


def test_shift_violating_rest_buffer_rejected(api):
    """PRD §3.4: "A new shift may not overlap another shift of the same attendant, and even
    when they do not overlap, consecutive shifts of one attendant must be separated by at least
    a 30-minute rest gap; a shift that overlaps another of the same attendant, or that leaves
    less than 30 minutes of separation, is rejected with `ERR_SHIFT_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/shift_rest_buffer_gap_required
    """
    venue = create_venue()
    attendant = create_attendant(venue["id"])
    validate_success(api.create_shift(create_shift_payload(
        attendant["id"], "2026-06-01T08:00:00Z", "2026-06-01T12:00:00Z"), SUP), 201)
    # Starts exactly when the prior ends → 0-minute gap, violates the 30-minute rest buffer.
    res = api.create_shift(create_shift_payload(
        attendant["id"], "2026-06-01T12:00:00Z", "2026-06-01T12:20:00Z"), SUP)
    validate_error(res, ApiErrorId.ERR_SHIFT_OVERLAP)
