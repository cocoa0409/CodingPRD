"""Temporal contention between vessel watches: travel buffers and area capacity."""

from test_helpers import (
    ADMIN,
    STANDARD_HOURS_OPEN_CLOCK,
    ApiErrorId,
    abort_watch,
    api_client,
    assert_vessel_watch,
    create_request,
    read_area,
    schedule_watch,
    setup_office,
    validate_error,
    validate_paginated,
    validate_success,
    vessel_watch_payload,
)


def _export_request(office, lot_identifier="LOT-WATCH"):
    return create_request(
        office["applicant"]["id"],
        office["area"]["id"],
        lot_identifier=lot_identifier,
        requested_services=["GRADING", "EXPORT_SUPERVISION"],
    )


def _attempt(request_id, inspector_id, start, end, holds_declared=3):
    return api_client.create_vessel_watch(
        vessel_watch_payload(request_id, inspector_id, start, end, holds_declared),
        ADMIN,
    )


def _buffer_office():
    return setup_office(
        "DESIGNATED",
        clock=STANDARD_HOURS_OPEN_CLOCK,
        area_overrides={"concurrent_watch_capacity": 9},
    )


def test_a_watch_inside_the_travel_buffer_is_refused_and_at_its_edge_accepted():
    """Second, a supervising inspector cannot be in two places at once, and
    needs travel time between them: each of the inspector's non-terminal watch
    windows is notionally extended by a three-quarter-hour travel buffer at
    both ends, and the new window conflicts with an existing one when the new
    window's start falls before the existing window's end plus 45 minutes
    **and** the existing window's start falls before the new window's end plus
    45 minutes. A conflict is refused with `ERR_INSPECTOR_WATCH_OVERLAP`.

    A new watch is `SCHEDULED` with `stowage_certified` false, a null
    `started_at`, a null `closed_at` and a null `supervision_minutes`, and the
    owning area's `open_watch_count` increases by one.

    Design: Difficulty/resource_temporal_overlap/inspector_watch_windows_conflict_inside_a_45_minute_travel_buffer
    """
    office = _buffer_office()
    request = _export_request(office)
    incumbent = schedule_watch(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
    )
    assert_vessel_watch(incumbent)
    assert incumbent["status"] == "SCHEDULED"
    assert incumbent["started_at"] is None
    assert incumbent["closed_at"] is None
    assert incumbent["supervision_minutes"] is None

    inside_buffer = _attempt(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T12:30:00Z",
        "2026-08-03T15:00:00Z",
    )
    validate_error(inside_buffer, ApiErrorId.ERR_INSPECTOR_WATCH_OVERLAP.value, 422)

    listed = api_client.list_vessel_watches(
        ADMIN, {"supervisor_inspector_id": office["supervisor"]["id"]}
    )
    _rows, meta = validate_paginated(listed)
    assert meta["total_count"] == 1

    at_the_edge = _attempt(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T12:45:00Z",
        "2026-08-03T15:00:00Z",
    )
    validate_success(at_the_edge, 201)


def test_the_travel_buffer_is_measured_from_both_ends_of_the_existing_window():
    """Second, a supervising inspector cannot be in two places at once, and
    needs travel time between them: each of the inspector's non-terminal watch
    windows is notionally extended by a three-quarter-hour travel buffer at
    both ends, and the new window conflicts with an existing one when the new
    window's start falls before the existing window's end plus 45 minutes
    **and** the existing window's start falls before the new window's end plus
    45 minutes.

    Second, a supervising inspector cannot be in two places at once, and needs
    travel time between them: each of the inspector's non-terminal watch
    windows is notionally extended by a three-quarter-hour travel buffer at
    both ends, and the new window conflicts with an existing one when the new
    window's start falls before the existing window's end plus 45 minutes
    **and** the existing window's start falls before the new window's end plus
    45 minutes.

    Design: Difficulty/resource_temporal_overlap/inspector_watch_windows_conflict_inside_a_45_minute_travel_buffer
    """
    office = _buffer_office()
    request = _export_request(office)
    schedule_watch(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
    )

    one_second_too_late = _attempt(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T06:00:00Z",
        "2026-08-03T07:16:00Z",
    )
    validate_error(
        one_second_too_late, ApiErrorId.ERR_INSPECTOR_WATCH_OVERLAP.value, 422
    )

    just_clear = _attempt(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T06:00:00Z",
        "2026-08-03T07:15:00Z",
    )
    validate_success(just_clear, 201)


def test_aborting_a_watch_frees_its_holder_and_another_inspector_is_never_blocked():
    """A watch may be aborted with an optional `reason` from either `SCHEDULED`
    or `IN_PROGRESS`; in both cases the area's `open_watch_count` decreases by
    one and the window is released for capacity purposes, so a later watch may
    occupy it.

    Second, a supervising inspector cannot be in two places at once, and needs
    travel time between them: each of the inspector's non-terminal watch
    windows is notionally extended by a three-quarter-hour travel buffer at
    both ends, and the new window conflicts with an existing one when the new
    window's start falls before the existing window's end plus 45 minutes
    **and** the existing window's start falls before the new window's end plus
    45 minutes.

    Design: Difficulty/resource_temporal_overlap/inspector_watch_windows_conflict_inside_a_45_minute_travel_buffer
    """
    office = _buffer_office()
    request = _export_request(office)
    incumbent = schedule_watch(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
    )

    # A different inspector is unaffected by the incumbent's travel buffer.
    other_holder = _attempt(
        request["id"],
        office["inspector"]["id"],
        "2026-08-03T12:30:00Z",
        "2026-08-03T15:00:00Z",
    )
    validate_success(other_holder, 201)

    aborted = abort_watch(incumbent["id"])
    assert aborted["status"] == "ABORTED"

    reoccupied = _attempt(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T12:30:00Z",
        "2026-08-03T15:00:00Z",
    )
    validate_success(reoccupied, 201)


def _capacity_office():
    return setup_office(
        "DELEGATED",
        area_overrides={"concurrent_watch_capacity": 1},
        second_supervisor=True,
    )


def test_windows_that_merely_touch_at_an_endpoint_count_against_area_capacity():
    """Third, the area itself has a ceiling: count the area's non-terminal watches
    whose windows intersect the new window, treating windows that merely touch at
    an endpoint as intersecting, and that count must be strictly below the area's
    `concurrent_watch_capacity`, otherwise `ERR_AREA_WATCH_CAPACITY_EXCEEDED`.

    A new watch is `SCHEDULED` with `stowage_certified` false, a null
    `started_at`, a null `closed_at` and a null `supervision_minutes`, and the
    owning area's `open_watch_count` increases by one.

    Design: Difficulty/resource_temporal_overlap/area_watch_capacity_counts_touching_windows_at_the_shared_endpoint
    """
    office = _capacity_office()
    request = _export_request(office)
    schedule_watch(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
    )
    assert read_area(office["area"]["id"])["open_watch_count"] == 1

    touching = _attempt(
        request["id"],
        office["supervisor_2"]["id"],
        "2026-08-03T12:00:00Z",
        "2026-08-03T15:00:00Z",
    )
    validate_error(touching, ApiErrorId.ERR_AREA_WATCH_CAPACITY_EXCEEDED.value, 422)
    assert read_area(office["area"]["id"])["open_watch_count"] == 1


def test_a_window_starting_one_second_later_clears_the_shared_endpoint():
    """Third, the area itself has a ceiling: count the area's non-terminal
    watches whose windows intersect the new window, treating windows that
    merely touch at an endpoint as intersecting, and that count must be
    strictly below the area's `concurrent_watch_capacity`, otherwise
    `ERR_AREA_WATCH_CAPACITY_EXCEEDED`.

    The area is not supplied by the client: `service_area_id` is copied from
    the inspection request at creation and is the resource against which area
    capacity is measured.

    Design: Difficulty/resource_temporal_overlap/area_watch_capacity_counts_touching_windows_at_the_shared_endpoint
    """
    office = _capacity_office()
    request = _export_request(office)
    schedule_watch(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
    )

    clear = _attempt(
        request["id"],
        office["supervisor_2"]["id"],
        "2026-08-03T12:00:01Z",
        "2026-08-03T15:00:00Z",
    )
    accepted = validate_success(clear, 201)

    assert accepted["service_area_id"] == office["area"]["id"]
    assert read_area(office["area"]["id"])["open_watch_count"] == 2


def test_aborting_releases_area_capacity_and_a_zero_length_window_is_invalid():
    """A watch may be aborted with an optional `reason` from either `SCHEDULED` or
    `IN_PROGRESS`; in both cases the area's `open_watch_count` decreases by one
    and the window is released for capacity purposes, so a later watch may occupy
    it.

    First, `window_end_at` must be strictly after `window_start_at`, or the watch
    is refused with `ERR_WATCH_WINDOW_INVALID`.

    Design: Difficulty/resource_temporal_overlap/area_watch_capacity_counts_touching_windows_at_the_shared_endpoint
    """
    office = _capacity_office()
    request = _export_request(office)
    incumbent = schedule_watch(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T08:00:00Z",
        "2026-08-03T12:00:00Z",
    )

    abort_watch(incumbent["id"])
    assert read_area(office["area"]["id"])["open_watch_count"] == 0

    reoccupied = _attempt(
        request["id"],
        office["supervisor"]["id"],
        "2026-08-03T10:00:00Z",
        "2026-08-03T12:00:00Z",
    )
    validate_success(reoccupied, 201)

    zero_length = _attempt(
        request["id"],
        office["supervisor_2"]["id"],
        "2026-08-03T12:00:00Z",
        "2026-08-03T12:00:00Z",
    )
    validate_error(zero_length, ApiErrorId.ERR_WATCH_WINDOW_INVALID.value, 422)
