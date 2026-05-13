"""Exercise windows, blackouts, and the sweep (PRD §3.6)."""
from __future__ import annotations

import datetime as _dt

import pytest

from test_helpers import (
    ApiErrorId,
    SECONDS_PER_DAY,
    TEST_USERS,
    advance_clock_by_seconds,
    assert_exercise_window,
    create_and_activate_plan,
    create_blackout,
    create_blackout_event_payload,
    create_exercise_window_payload,
    create_window,
    create_window_and_open,
    validate_error,
    validate_success,
)


def _offset_iso(anchor_iso: str, seconds: int) -> str:
    base = _dt.datetime.fromisoformat(anchor_iso.replace("Z", "+00:00"))
    return (base + _dt.timedelta(seconds=seconds)).isoformat().replace(
        "+00:00", "Z",
    )


def test_create_window_in_scheduled(api, plan_admin_headers):
    """PRD §3.6: "The window is born in SCHEDULED."""
    plan = create_and_activate_plan()
    open_ts = _offset_iso(plan["current_clock_ts"], SECONDS_PER_DAY)
    close_ts = _offset_iso(plan["current_clock_ts"], 5 * SECONDS_PER_DAY)
    res = api.create_exercise_window(
        plan["id"],
        create_exercise_window_payload(open_ts, close_ts),
        plan_admin_headers,
    )
    window = validate_success(res, expected_status=201)
    assert_exercise_window(window)
    assert window["status"] == "SCHEDULED"


def test_create_window_rejects_open_after_close(api, plan_admin_headers):
    """PRD §3.6: "if open_ts is at or after close_ts the request is
    rejected with ERR_INVALID_TIME_INTERVAL."
    """
    plan = create_and_activate_plan()
    open_ts = _offset_iso(plan["current_clock_ts"], 5 * SECONDS_PER_DAY)
    close_ts = _offset_iso(plan["current_clock_ts"], SECONDS_PER_DAY)
    res = api.create_exercise_window(
        plan["id"],
        create_exercise_window_payload(open_ts, close_ts),
        plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_INVALID_TIME_INTERVAL.value)


def test_create_window_rejects_blackout_overlap(api, plan_admin_headers):
    """PRD §3.6: "A window may not overlap any blackout using half-open
    intervals on both sides ... Any non-empty intersection is rejected
    with ERR_BLACKOUT_OVERLAPS_WINDOW. This check fires both when
    creating the window..."
    """
    plan = create_and_activate_plan()
    anchor = plan["current_clock_ts"]
    # Blackout [t+24h, t+48h)
    create_blackout(
        plan["id"],
        _offset_iso(anchor, 24 * 3600),
        _offset_iso(anchor, 48 * 3600),
    )
    # Window [t+30h, t+50h) — overlaps the blackout
    open_ts = _offset_iso(anchor, 30 * 3600)
    close_ts = _offset_iso(anchor, 50 * 3600)
    res = api.create_exercise_window(
        plan["id"],
        create_exercise_window_payload(open_ts, close_ts),
        plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_BLACKOUT_OVERLAPS_WINDOW.value)


def test_blackout_creation_rejects_window_overlap(api, plan_admin_headers):
    """PRD §3.6: "...This check fires both when creating the window
    (against the set of existing blackouts) and when creating a blackout
    (against the set of existing windows)."
    """
    plan = create_and_activate_plan()
    anchor = plan["current_clock_ts"]
    # Window [t+10h, t+30h)
    create_window(
        plan["id"],
        _offset_iso(anchor, 10 * 3600),
        _offset_iso(anchor, 30 * 3600),
    )
    # Blackout [t+20h, t+40h) — overlaps
    res = api.create_corporate_event(
        plan["id"],
        create_blackout_event_payload(
            "EARNINGS_BLACKOUT",
            _offset_iso(anchor, 20 * 3600),
            _offset_iso(anchor, 40 * 3600),
        ),
        plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_BLACKOUT_OVERLAPS_WINDOW.value)


def test_window_touching_blackout_end_is_not_overlap(api, plan_admin_headers):
    """PRD §3.6: "the window's [open_ts, close_ts) interval must have
    empty intersection with every blackout's [effective_ts,
    blackout_end_ts) interval. Any non-empty intersection is rejected
    with ERR_BLACKOUT_OVERLAPS_WINDOW."

    Half-open boundary: window.open_ts == blackout.blackout_end_ts is
    NOT an overlap and must succeed.
    """
    plan = create_and_activate_plan()
    anchor = plan["current_clock_ts"]
    # Blackout [t+24h, t+48h)
    create_blackout(
        plan["id"],
        _offset_iso(anchor, 24 * 3600),
        _offset_iso(anchor, 48 * 3600),
    )
    # Window [t+48h, t+72h) — touching, NOT overlapping
    res = api.create_exercise_window(
        plan["id"],
        create_exercise_window_payload(
            _offset_iso(anchor, 48 * 3600),
            _offset_iso(anchor, 72 * 3600),
        ),
        plan_admin_headers,
    )
    window = validate_success(res, expected_status=201)
    assert window["status"] == "SCHEDULED"


def test_sweep_opens_window_when_clock_inside_interval(api,
                                                       plan_admin_headers):
    """PRD §3.6: "A SCHEDULED window auto-transitions to OPEN when the
    plan clock has reached or passed open_ts and is strictly before
    close_ts..."
    """
    plan = create_and_activate_plan()
    anchor = plan["current_clock_ts"]
    create_window(
        plan["id"],
        _offset_iso(anchor, 0),
        _offset_iso(anchor, 10 * SECONDS_PER_DAY),
    )
    res = api.sweep_exercise_windows(plan["id"], plan_admin_headers)
    validate_success(res, expected_status=200)
    windows = api.list_exercise_windows(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    assert any(w["status"] == "OPEN" for w in windows)


def test_sweep_closes_window_when_clock_past_close_ts(api,
                                                      plan_admin_headers):
    """PRD §3.6: "An OPEN window auto-transitions to CLOSED when the
    plan clock has reached close_ts..."
    """
    plan = create_and_activate_plan()
    anchor = plan["current_clock_ts"]
    create_window(
        plan["id"],
        _offset_iso(anchor, 0),
        _offset_iso(anchor, 1 * SECONDS_PER_DAY),
    )
    # First sweep opens.
    api.sweep_exercise_windows(plan["id"], plan_admin_headers)
    advance_clock_by_seconds(plan["id"], 2 * SECONDS_PER_DAY)
    api.sweep_exercise_windows(plan["id"], plan_admin_headers)
    windows = api.list_exercise_windows(
        plan["id"], plan_admin_headers,
    ).json()["data"]
    assert any(w["status"] == "CLOSED" for w in windows)


def test_archive_rejects_non_closed_window(api, plan_admin_headers):
    """PRD §3.6: "Archiving a window transitions it from CLOSED to
    ARCHIVED and is rejected with ERR_WINDOW_NOT_CLOSED if the window is
    not in CLOSED..."
    """
    plan = create_and_activate_plan()
    anchor = plan["current_clock_ts"]
    window = create_window(
        plan["id"],
        _offset_iso(anchor, 1 * SECONDS_PER_DAY),
        _offset_iso(anchor, 3 * SECONDS_PER_DAY),
    )
    # window is SCHEDULED, not CLOSED.
    res = api.archive_exercise_window(
        plan["id"], window["id"], plan_admin_headers,
    )
    validate_error(res, ApiErrorId.ERR_WINDOW_NOT_CLOSED.value)
