"""Event lifecycle: creation, scheduling, open/suspend/resume/complete, repricing, and the
cross-entity/temporal preconditions that gate scheduling.

All tests translate exactly one design-index instance; each docstring ends with its Design tag.
"""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    assert_event, NON_EXISTENT_UUID, TEST_USERS,
    provision_draft_event, provision_scheduled_event, provision_open_event,
    create_series, create_venue, create_chef, create_event, schedule_event,
    add_menu_course, open_event, get_event,
)

ADMIN = TEST_USERS["platform_admin_headers"]


# ─── Corner: entities / create + not-found ─────────────────────────────

def test_create_event_returns_draft_and_version_one(api):
    """PRD §3.2: "A VenueManager (or the operator) creates an Event in the DRAFT state."
    PRD §2.4: "version — an integer that starts at creation and increments by one on every mutation."

    Design: Corner/entities/create_event_returns_all_fields_and_draft
    """
    series = create_series()
    venue = create_venue()
    chef = create_chef()
    res = api.create_event(
        {
            "series_id": series["id"], "venue_id": venue["id"], "chef_id": chef["id"],
            "title": "E", "event_start": "2026-03-15T18:00:00Z",
            "event_end": "2026-03-15T21:00:00Z", "booking_deadline": "2026-03-14T00:00:00Z",
            "table_mode": "COMMUNAL", "seat_capacity": 2,
            "seat_price_cents": 10000, "deposit_pct": 0.25,
        },
        ADMIN,
    )
    event = validate_success(res, 201)
    assert_event(event)
    assert event["status"] == "DRAFT", f"new event must be DRAFT, got {event['status']}"
    assert event["version"] == 1, f"new event version must be 1, got {event['version']}"


def test_get_nonexistent_event_returns_not_found(api):
    """PRD §2.7: "a missing series yields ERR_SERIES_NOT_FOUND, a missing venue ERR_VENUE_NOT_FOUND,
    a missing chef ERR_CHEF_NOT_FOUND, a missing guest ERR_GUEST_NOT_FOUND, a missing event
    ERR_EVENT_NOT_FOUND, a missing seat ERR_SEAT_NOT_FOUND, a missing booking ERR_BOOKING_NOT_FOUND,
    a missing menu course ERR_MENU_COURSE_NOT_FOUND, and a missing waitlist entry
    ERR_WAITLIST_ENTRY_NOT_FOUND."

    Design: Corner/entities/get_event_nonexistent_returns_not_found
    """
    res = api.get_event(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_EVENT_NOT_FOUND")


# ─── Corner: state_machines / invalid transitions & preconditions ──────

def test_open_draft_event_rejected_invalid_state(api):
    """PRD §3.2: "attempting any Event lifecycle transition from a status that does not permit
    it fails with ERR_INVALID_EVENT_STATE."

    Design: Corner/state_machines/open_draft_event_rejected_invalid_state
    """
    ctx = provision_draft_event()
    res = api.open_event(ctx["event"]["id"], ADMIN)
    validate_error(res, "ERR_INVALID_EVENT_STATE")


def test_complete_before_event_end_rejected(api):
    """PRD §3.8: "Completion is refused unless the current logical-clock time is at or after
    the event's event_end; an earlier attempt fails with ERR_EVENT_NOT_ENDED."

    Design: Corner/state_machines/complete_before_event_end_rejected
    """
    # Clock at startup default 2026-03-01, which is before event_end 2026-03-15.
    ctx = provision_open_event()
    res = api.complete_event(ctx["event"]["id"], ADMIN)
    validate_error(res, "ERR_EVENT_NOT_ENDED")


def test_open_event_without_menu_rejected(api):
    """PRD §3.3: "an event with no menu cannot open and the request fails with ERR_MENU_REQUIRED."

    Design: Corner/validations/open_event_without_menu_returns_409
    """
    ctx = provision_scheduled_event()  # SCHEDULED, no menu course added
    res = api.open_event(ctx["event"]["id"], ADMIN)
    validate_error(res, "ERR_MENU_REQUIRED")


# ─── Difficulty: non_linear_state_machine / suspend-resume cycle ───────

def test_suspend_then_resume_returns_event_to_open(api):
    """PRD §3.4: "Resuming reverses this, advancing SUSPENDED → OPEN; this suspend/resume cycle
    is a non-linear edge that may be traversed repeatedly."

    Design: Difficulty/non_linear_state_machine/event_suspend_resume_cycle
    """
    ctx = provision_open_event()
    eid = ctx["event"]["id"]
    suspended = validate_success(api.suspend_event(eid, ADMIN), 200)
    assert suspended["status"] == "SUSPENDED"
    resumed = validate_success(api.resume_event(eid, ADMIN), 200)
    assert resumed["status"] == "OPEN", f"resume must return OPEN, got {resumed['status']}"


def test_suspend_resume_cycle_is_repeatable(api):
    """PRD §3.4: "Resuming reverses this, advancing SUSPENDED → OPEN; this suspend/resume cycle
    is a non-linear edge that may be traversed repeatedly."

    Design: Difficulty/non_linear_state_machine/event_suspend_resume_cycle
    """
    ctx = provision_open_event()
    eid = ctx["event"]["id"]
    validate_success(api.suspend_event(eid, ADMIN), 200)
    validate_success(api.resume_event(eid, ADMIN), 200)
    # Traverse the cycle a second time — the machine returns to a prior state.
    second_suspend = validate_success(api.suspend_event(eid, ADMIN), 200)
    assert second_suspend["status"] == "SUSPENDED"
    second_resume = validate_success(api.resume_event(eid, ADMIN), 200)
    assert second_resume["status"] == "OPEN"


# ─── Difficulty: cross_entity_state_dependency / schedule requires chef ─

def test_schedule_with_on_leave_chef_rejected(api):
    """PRD §3.2: "First, the chef referenced by chef_id must currently be AVAILABLE; if that
    chef is ON_LEAVE, the request fails with ERR_CHEF_UNAVAILABLE."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_chef_available
    """
    series = create_series()
    venue = create_venue()
    chef = create_chef()
    api_client.set_chef_availability(chef["id"], {"status": "ON_LEAVE"}, ADMIN)
    event = create_event(series["id"], venue["id"], chef["id"], seat_capacity=1)
    res = api.schedule_event(event["id"], {}, ADMIN)
    validate_error(res, "ERR_CHEF_UNAVAILABLE")


def test_schedule_succeeds_once_chef_available(api):
    """PRD §3.2: "First, the chef referenced by chef_id must currently be AVAILABLE; if that
    chef is ON_LEAVE, the request fails with ERR_CHEF_UNAVAILABLE."

    Design: Difficulty/cross_entity_state_dependency/schedule_requires_chef_available
    """
    series = create_series()
    venue = create_venue()
    chef = create_chef()
    api_client.set_chef_availability(chef["id"], {"status": "ON_LEAVE"}, ADMIN)
    api_client.set_chef_availability(chef["id"], {"status": "AVAILABLE"}, ADMIN)
    event = create_event(series["id"], venue["id"], chef["id"], seat_capacity=1)
    scheduled = validate_success(api.schedule_event(event["id"], {}, ADMIN), 200)
    assert scheduled["status"] == "SCHEDULED"


# ─── Difficulty: resource_temporal_overlap / venue turnover buffer ─────

def test_venue_overlapping_events_conflict(api):
    """PRD §3.2: "If these two half-open intervals share any instant, the request fails with
    ERR_VENUE_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/venue_turnover_buffer_overlap
    """
    series = create_series()
    venue = create_venue()
    chef_a = create_chef(name="ChefA")
    chef_b = create_chef(name="ChefB")
    e1 = create_event(series["id"], venue["id"], chef_a["id"], seat_capacity=1,
                      event_start="2026-03-15T15:00:00Z", event_end="2026-03-15T18:00:00Z")
    schedule_event(e1["id"])
    # Second event at the same venue whose base interval [16:00,19:00) already overlaps
    # [15:00,18:00) — a conflict independent of the turnover buffer's exact length.
    e2 = create_event(series["id"], venue["id"], chef_b["id"], seat_capacity=1,
                      event_start="2026-03-15T16:00:00Z", event_end="2026-03-15T19:00:00Z")
    res = api.schedule_event(e2["id"], {}, ADMIN)
    validate_error(res, "ERR_VENUE_TIME_CONFLICT")


def test_venue_non_overlapping_events_schedule(api):
    """PRD §3.2: "If these two half-open intervals share any instant, the request fails with
    ERR_VENUE_TIME_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/venue_turnover_buffer_overlap
    """
    series = create_series()
    venue = create_venue()
    chef_a = create_chef(name="ChefA")
    chef_b = create_chef(name="ChefB")
    e1 = create_event(series["id"], venue["id"], chef_a["id"], seat_capacity=1,
                      event_start="2026-03-15T15:00:00Z", event_end="2026-03-15T18:00:00Z",
                      booking_deadline="2026-03-14T00:00:00Z")
    schedule_event(e1["id"])
    # Second event a full day later — no shared instant under any reasonable turnover buffer.
    e2 = create_event(series["id"], venue["id"], chef_b["id"], seat_capacity=1,
                      event_start="2026-03-16T15:00:00Z", event_end="2026-03-16T18:00:00Z",
                      booking_deadline="2026-03-15T00:00:00Z")
    scheduled = validate_success(api.schedule_event(e2["id"], {}, ADMIN), 200)
    assert scheduled["status"] == "SCHEDULED"


# ─── Corner: cross_cutting_complexity_layers / OCC on reprice ──────────

def test_reprice_with_current_version_updates_and_bumps(api):
    """PRD §3.4: "When it succeeds, the event's seat_price_cents is updated to new_seat_price_cents
    and, if new_deposit_pct was supplied, deposit_pct is updated as well".
    PRD §3.4: "Repricing increments the Event's version by one".

    Design: Corner/cross_cutting_complexity_layers/reprice_with_current_version_bumps_version
    """
    ctx = provision_draft_event(event_overrides={"seat_capacity": 1})
    event = ctx["event"]
    res = api.reprice_event(
        event["id"],
        {"new_seat_price_cents": 12000, "expected_event_version": event["version"]},
        ADMIN,
    )
    repriced = validate_success(res, 200)
    assert repriced["seat_price_cents"] == 12000
    assert repriced["version"] == 2, f"version must bump 1->2, got {repriced['version']}"


def test_reprice_with_stale_version_rejected(api):
    """PRD §2.6: "If expected_event_version does not equal the Event's current version — meaning
    another writer has already advanced the Event's version since the client read it, superseding
    the price the client based its request on — the request is rejected with ERR_STALE_EVENT_VERSION
    (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/reprice_stale_version_returns_412
    """
    ctx = provision_draft_event(event_overrides={"seat_capacity": 1})
    event = ctx["event"]
    stale_version = event["version"]
    # First reprice succeeds and advances the version, making stale_version obsolete.
    validate_success(api.reprice_event(
        event["id"],
        {"new_seat_price_cents": 11000, "expected_event_version": stale_version}, ADMIN), 200)
    res = api.reprice_event(
        event["id"],
        {"new_seat_price_cents": 13000, "expected_event_version": stale_version}, ADMIN)
    validate_error(res, "ERR_STALE_EVENT_VERSION")


# ─── Corner: endpoints / list pagination envelope ──────────────────────

def test_list_events_pagination_envelope(api):
    """PRD §2.3: "The limit parameter caps the number of items returned; when omitted it defaults
    to 10, with a minimum accepted value of 1 and a maximum of 100."
    PRD §2.3: "Every list response reports limit, offset, total_count, and has_more inside the
    meta object of the envelope."

    Design: Corner/endpoints/list_events_pagination_envelope
    """
    series = create_series()
    venue = create_venue()
    chef = create_chef()
    create_event(series["id"], venue["id"], chef["id"], seat_capacity=1, title="E1")
    create_event(series["id"], venue["id"], chef["id"], seat_capacity=1, title="E2",
                 event_start="2026-03-22T18:00:00Z", event_end="2026-03-22T21:00:00Z",
                 booking_deadline="2026-03-21T00:00:00Z")
    data, meta = validate_paginated(
        api.list_events(ADMIN, params={"series_id": series["id"], "limit": 1, "offset": 0}))
    assert meta["total_count"] == 2, f"expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True
    assert len(data) == 1, f"expected 1 item with limit=1, got {len(data)}"
