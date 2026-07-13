"""Sweep-event scheduling: block-window overlap, adjacency, invalid void, and
missed-sweep makeup creation.

Translates queue A (Difficulty) sweep-overlap instance and queue B (Corner)
adjacency, void-from-scheduled, and miss-creates-makeup instances.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    create_sweep_event_payload,
    TEST_USERS,
    create_route, create_block, create_sweep_event, set_clock,
)

DISPATCHER = TEST_USERS["route_dispatcher_headers"]


def _block_with_scheduled_sweep():
    route = create_route()
    block = create_block(route["id"], restriction_start_local="06:00", restriction_end_local="14:00")
    create_sweep_event(block["id"], scheduled_date="2026-03-10",
                       window_start_utc="2026-03-10T08:00:00Z", window_end_utc="2026-03-10T10:00:00Z")
    return block


def test_overlapping_sweep_window_rejected(api):
    """PRD §3.1: "A newly scheduled sweep is rejected with `ERR_SWEEP_OVERLAP` if its half-open window overlaps that of another sweep on the same block that is currently `SCHEDULED` or `SWEPT`; two sweeps whose windows merely touch at an endpoint are accepted."

    Design: Difficulty/resource_temporal_overlap/sweep_event_overlap_on_block_half_open
    """
    block = _block_with_scheduled_sweep()
    res = api.create_sweep_event(create_sweep_event_payload(
        block["id"], scheduled_date="2026-03-10",
        window_start_utc="2026-03-10T09:00:00Z", window_end_utc="2026-03-10T11:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_SWEEP_OVERLAP", expected_status=409)


def test_identical_sweep_window_rejected(api):
    """PRD §3.1: "A newly scheduled sweep is rejected with `ERR_SWEEP_OVERLAP` if its half-open window overlaps that of another sweep on the same block that is currently `SCHEDULED` or `SWEPT`"

    Design: Difficulty/resource_temporal_overlap/sweep_event_overlap_on_block_half_open
    """
    block = _block_with_scheduled_sweep()
    res = api.create_sweep_event(create_sweep_event_payload(
        block["id"], scheduled_date="2026-03-10",
        window_start_utc="2026-03-10T08:00:00Z", window_end_utc="2026-03-10T10:00:00Z"), DISPATCHER)
    validate_error(res, "ERR_SWEEP_OVERLAP", expected_status=409)


def test_adjacent_sweep_window_allowed(api):
    """PRD §2.8: "two intervals that merely touch — one ending exactly when the next begins — do *not* overlap; adjacency is permitted."

    Design: Corner/validations/sweep_event_adjacent_window_allowed
    """
    block = _block_with_scheduled_sweep()
    res = api.create_sweep_event(create_sweep_event_payload(
        block["id"], scheduled_date="2026-03-10",
        window_start_utc="2026-03-10T10:00:00Z", window_end_utc="2026-03-10T12:00:00Z"), DISPATCHER)
    created = validate_success(res, 201)
    assert created["status"] == "SCHEDULED"


def test_void_scheduled_sweep_rejected(api):
    """PRD §3.4: "Voiding a swept event advances it `SWEPT → VOIDED`, permitted only from `SWEPT`"

    Design: Corner/state_machines/void_from_scheduled_returns_invalid_state
    """
    route = create_route()
    block = create_block(route["id"], restriction_start_local="06:00", restriction_end_local="12:00")
    ev = create_sweep_event(block["id"])
    res = api.void_sweep_event(ev["id"], {}, DISPATCHER)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_miss_creates_makeup_event_seven_days_later(api):
    """PRD §3.5: "As a side effect the system automatically creates a **makeup** sweep event for the same block: the new event has `is_makeup` set to true, its `original_event_id` pointing back to the missed event, the same `block_id`, a `status` of `SCHEDULED`, and a `scheduled_date` set to the calendar date of the current logical clock advanced by the fixed makeup offset of **7 calendar days** (the `MAKEUP_OFFSET_DAYS` constant, whose value is 7)."

    Design: Corner/state_machines/miss_creates_makeup_event
    """
    route = create_route()
    block = create_block(route["id"], restriction_start_local="06:00", restriction_end_local="12:00")
    ev = create_sweep_event(block["id"])
    set_clock("2026-03-10T09:00:00Z")
    missed = validate_success(api.miss_sweep_event(ev["id"], {"reason": "breakdown"}, DISPATCHER), 200)
    assert missed["status"] == "MISSED"

    makeups, _ = validate_paginated(api.list_sweep_events(DISPATCHER, params={"original_event_id": ev["id"]}))
    assert len(makeups) == 1
    makeup = makeups[0]
    assert makeup["is_makeup"] is True
    assert makeup["original_event_id"] == ev["id"]
    assert makeup["scheduled_date"] == "2026-03-17"
