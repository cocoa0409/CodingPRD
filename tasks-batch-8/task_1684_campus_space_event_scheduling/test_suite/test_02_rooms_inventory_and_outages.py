"""Rooms: creation defaults, lookup failures, outages, and capacity edits."""

from test_helpers import (
    assert_same_instant,
    FACILITIES_MANAGER,
    NON_EXISTENT_UUID,
    SCHEDULER,
    ApiErrorId,
    assert_room,
    create_event,
    create_room,
    daily_close,
    get_event,
    get_room,
    set_clock,
    setup_confirmed_event,
    validate_error,
    validate_success,
)


def test_create_room_applies_declared_defaults(api):
    """PRD §3.2: "`turnaround_buffer_minutes`, defaulting to 30;
    `peak_multiplier_bps`, defaulting to 12500; and `key_count`, the number of
    physical key inventory slots, defaulting to zero."
    PRD §3.2: "Rooms are created in `ACTIVE` status with `keys_issued` and
    `keys_lost_total` at zero."

    Design: Corner/entities/room_create_applies_inventory_defaults
    """
    response = api.create_room(
        {
            "name": "DEF-1",
            "building_code": "DEF",
            "capacity": 10,
            "internal_hourly_rate_cents": 1000,
            "student_hourly_rate_cents": 500,
            "external_hourly_rate_cents": 2000,
        },
        FACILITIES_MANAGER,
    )
    data = validate_success(response, 201)
    assert_room(data)
    assert data["turnaround_buffer_minutes"] == 30
    assert data["peak_multiplier_bps"] == 12500
    assert data["features"] == []
    assert data["key_count"] == 0
    assert data["keys_issued"] == 0
    assert data["keys_lost_total"] == 0
    assert data["status"] == "ACTIVE"
    assert data["outage_windows"] == []


def test_get_room_with_unknown_id_returns_not_found(api):
    """PRD §2.10: "The request is rejected with `ERR_NOT_FOUND` at the first
    identifier that does not correspond to an existing resource."

    Design: Corner/entities/room_get_not_found_returns_404
    """
    response = api.get_room(NON_EXISTENT_UUID, SCHEDULER)
    validate_error(response, ApiErrorId.ERR_NOT_FOUND)


def test_room_auto_returns_to_service_after_outage_window(api):
    """PRD §3.2: "The daily-close checkpoint returns the room to `ACTIVE` once the
    clock reaches `outage_end_at`, clearing the two current-outage fields while
    the history in `outage_windows` is retained."
    PRD §2.4: "The checkpoint response reports per-step counters: `terms_advanced`,
    `rooms_returned`, `requests_expired`, `approvals_expired`, `no_shows_marked`,
    `events_completed`, `grants_overdue`, and `orgs_suspended`."

    Design: Corner/state_machines/room_auto_returns_to_service_after_outage
    """
    room = create_room(name="OUT-1", building_code="OUT", capacity=10)
    response = api.room_out_of_service(
        room["id"],
        {
            "outage_start_at": "2026-08-05T00:00:00Z",
            "outage_end_at": "2026-08-07T00:00:00Z",
        },
        FACILITIES_MANAGER,
    )
    out = validate_success(response, 200)
    assert out["status"] == "OUT_OF_SERVICE"

    set_clock("2026-08-08T00:00:00Z")
    counters = daily_close()
    assert counters["rooms_returned"] == 1

    room_after = get_room(room["id"])
    assert room_after["status"] == "ACTIVE"
    assert room_after["outage_start_at"] is None
    assert room_after["outage_end_at"] is None
    assert len(room_after["outage_windows"]) == 1
    window = room_after["outage_windows"][0]
    assert_same_instant(window["start_at"], "2026-08-05T00:00:00Z")
    assert_same_instant(window["end_at"], "2026-08-07T00:00:00Z")


def test_capacity_cut_blocked_by_confirmed_event_and_bumps_requested(api):
    """PRD §3.2: "A capacity reduction is a booking event in its own right: events
    in `REQUESTED` or `APPROVED` whose `expected_attendance` exceeds the new
    capacity are automatically bumped with the full bump cascade described in
    §3.4. If a `CONFIRMED` or `IN_PROGRESS` event would exceed the new capacity,
    the edit is rejected outright with `ERR_ROOM_EDIT_BLOCKED`."

    Design: Corner/validations/room_capacity_cut_blocked_by_confirmed_and_bumps_requested
    """
    scn = setup_confirmed_event(
        room_overrides={"capacity": 100},
        event_overrides={
            "expected_attendance": 80,
            "start_at": "2026-09-16T14:00:00Z",
            "end_at": "2026-09-16T15:00:00Z",
            "title": "Confirmed",
        },
    )
    big_ask = create_event(
        scn.org, scn.room["id"],
        expected_attendance=90,
        start_at="2026-09-17T14:00:00Z",
        end_at="2026-09-17T15:00:00Z",
        title="Big ask",
    )

    blocked = api.update_room(scn.room["id"], {"capacity": 60}, FACILITIES_MANAGER)
    validate_error(blocked, ApiErrorId.ERR_ROOM_EDIT_BLOCKED)
    assert get_room(scn.room["id"])["capacity"] == 100, "rejected edit changes nothing"

    updated = validate_success(
        api.update_room(scn.room["id"], {"capacity": 85}, FACILITIES_MANAGER), 200
    )
    assert updated["capacity"] == 85

    bumped = get_event(big_ask["id"])
    assert bumped["status"] == "BUMPED"
    assert bumped["room_id"] is None

    confirmed = get_event(scn.event["id"])
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["room_id"] == scn.room["id"]


def test_outage_overlapping_shielded_confirmed_event_is_blocked(api):
    """PRD §3.2: "The room refuses the outage with `ERR_ROOM_BLOCKED` whenever the
    window overlaps non-bumpable occupancy — a `CONFIRMED` event whose start is
    less than 72 hours away or that holds any `ISSUED` or `OVERDUE` access grant,
    or any `IN_PROGRESS` event."

    Design: Corner/validations/outage_overlapping_shielded_event_blocked
    """
    scn = setup_confirmed_event(
        event_overrides={
            "expected_attendance": 5,
            "start_at": "2026-09-10T14:00:00Z",
            "end_at": "2026-09-10T16:00:00Z",
            "title": "E",
        }
    )
    # 47 hours before the start: inside the 72-hour bump shield.
    set_clock("2026-09-08T15:00:00Z")
    response = api.room_out_of_service(
        scn.room["id"],
        {
            "outage_start_at": "2026-09-10T08:00:00Z",
            "outage_end_at": "2026-09-10T20:00:00Z",
        },
        FACILITIES_MANAGER,
    )
    validate_error(response, ApiErrorId.ERR_ROOM_BLOCKED)

    room = get_room(scn.room["id"])
    assert room["status"] == "ACTIVE"
    assert room["outage_windows"] == []
    assert get_event(scn.event["id"])["status"] == "CONFIRMED"
