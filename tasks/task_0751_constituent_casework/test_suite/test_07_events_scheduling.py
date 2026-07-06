"""Event scheduling: representative half-open overlap semantics, time-range and
capacity-ceiling validation, and optimistic-concurrency reschedule."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    new_representative, new_venue, new_event,
    create_event_payload,
    TEST_USERS,
)

ADMIN = TEST_USERS["office_admin_headers"]


# --- Difficulty: resource_temporal_overlap / representative_halfopen_adjacent_allowed ---

def test_back_to_back_representative_events_allowed(api):
    """PRD §3.7: "because the interval is half-open, two events that meet exactly
    end-to-start do not conflict."

    Design: Difficulty/resource_temporal_overlap/representative_halfopen_adjacent_allowed
    """
    rep = new_representative(api)
    v1 = new_venue(api, capacity=200)
    v2 = new_venue(api, capacity=200)
    new_event(api, rep["id"], v1["id"], "2026-04-02T10:00:00Z", "2026-04-02T11:00:00Z", capacity=10)
    resp = api.create_event(
        create_event_payload(rep["id"], v2["id"], "2026-04-02T11:00:00Z", "2026-04-02T12:00:00Z", capacity=10),
        ADMIN)
    data = validate_success(resp, expected_status=201)
    assert data["lifecycle_status"] == "SCHEDULED"


def test_overlapping_representative_event_rejected(api):
    """PRD §3.7: "The representative rule uses the raw half-open interval with no buffer
    and rejects with `ERR_REPRESENTATIVE_CONFLICT` if it overlaps any other `SCHEDULED`
    event hosted by the same representative".

    Design: Difficulty/resource_temporal_overlap/representative_halfopen_adjacent_allowed
    """
    rep = new_representative(api)
    v1 = new_venue(api, capacity=200)
    v3 = new_venue(api, capacity=200)
    new_event(api, rep["id"], v1["id"], "2026-04-02T10:00:00Z", "2026-04-02T11:00:00Z", capacity=10)
    resp = api.create_event(
        create_event_payload(rep["id"], v3["id"], "2026-04-02T10:30:00Z", "2026-04-02T11:30:00Z", capacity=10),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_REPRESENTATIVE_CONFLICT)


# --- Corner: validations / event_invalid_time_range_rejected ---

def test_event_invalid_time_range_rejected(api):
    """PRD §3.7: "The time range must be valid — `start_at` strictly before `end_at`,
    else `ERR_INVALID_TIME_RANGE`."

    Design: Corner/validations/event_invalid_time_range_rejected
    """
    rep = new_representative(api)
    venue = new_venue(api, capacity=30)
    resp = api.create_event(
        create_event_payload(rep["id"], venue["id"], "2026-07-01T12:00:00Z", "2026-07-01T12:00:00Z", capacity=5),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_TIME_RANGE)


# --- Corner: validations / event_capacity_exceeds_venue_rejected ---

def test_event_capacity_exceeds_venue_rejected(api):
    """PRD §3.7: "The event's `capacity` must not exceed the venue's `capacity` at
    creation, else `ERR_EVENT_FULL`."

    Design: Corner/validations/event_capacity_exceeds_venue_rejected
    """
    rep = new_representative(api)
    venue = new_venue(api, capacity=30)
    resp = api.create_event(
        create_event_payload(rep["id"], venue["id"], "2026-07-02T10:00:00Z", "2026-07-02T11:00:00Z", capacity=50),
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_EVENT_FULL)


# --- Corner: cross_cutting_complexity_layers / event_reschedule_stale_version_conflict ---

def test_event_reschedule_stale_version_conflict(api):
    """PRD §2.9: "A reschedule request must carry `expected_event_version` ... If
    `expected_event_version` does not equal the target event's current `version`, the
    request is rejected with `ERR_STALE_VERSION` (HTTP 412)".

    Design: Corner/cross_cutting_complexity_layers/event_reschedule_stale_version_conflict
    """
    rep = new_representative(api)
    venue = new_venue(api, capacity=60)
    event = new_event(api, rep["id"], venue["id"], "2026-09-01T10:00:00Z", "2026-09-01T11:00:00Z", capacity=10)
    v0 = event["version"]
    validate_success(api.reschedule_event(
        event["id"],
        {"expected_event_version": v0, "start_at": "2026-09-01T14:00:00Z", "end_at": "2026-09-01T15:00:00Z"},
        ADMIN))
    # v0 is now stale — version advanced past it.
    resp = api.reschedule_event(
        event["id"],
        {"expected_event_version": v0, "start_at": "2026-09-01T16:00:00Z", "end_at": "2026-09-01T17:00:00Z"},
        ADMIN)
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


# --- Corner: cross_cutting_complexity_layers / event_reschedule_correct_version_succeeds ---

def test_event_reschedule_correct_version_succeeds(api):
    """PRD §3.7: "requires `expected_event_version` to match the event's current
    `version` (else `ERR_STALE_VERSION`), re-runs the same time-range, venue-buffer,
    representative-overlap, and capacity-ceiling checks as creation, and on success
    updates `start_at`, `end_at`, and `venue_id` (when supplied) and increments the
    event's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/event_reschedule_correct_version_succeeds
    """
    rep = new_representative(api)
    venue = new_venue(api, capacity=60)
    event = new_event(api, rep["id"], venue["id"], "2026-09-02T10:00:00Z", "2026-09-02T11:00:00Z", capacity=10)
    v0 = event["version"]
    data = validate_success(api.reschedule_event(
        event["id"],
        {"expected_event_version": v0, "start_at": "2026-09-02T14:00:00Z", "end_at": "2026-09-02T15:00:00Z"},
        ADMIN))
    assert data["version"] == v0 + 1, f"version must increment by one, got {data['version']} from {v0}"
    assert data["start_at"] == "2026-09-02T14:00:00.000Z", f"start_at not updated: {data['start_at']}"
