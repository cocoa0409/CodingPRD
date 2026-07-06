"""Focus-group temporal overlap rules: facility buffer and panelist conflict.

Difficulty queue (A): resource_temporal_overlap (facility double-book with
turnaround buffer, panelist schedule conflict half-open no buffer).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId, TEST_USERS,
    create_facility, create_panelist,
    create_focus_group_payload, create_focus_group_booking_payload,
)

RM = TEST_USERS["research_manager_headers"]
OPS = TEST_USERS["panel_ops_headers"]
FC = TEST_USERS["field_coordinator_headers"]


def _study(api):
    return get_success_data(api.create_study(
        {"title": "FG Study", "irb_protocol_number": "IRB-FG", "estimated_minutes": 10,
         "base_incentive_points": 100, "screener_min_age": 0}, RM))


def test_facility_double_booked_inside_turnaround_buffer(api):
    """PRD §3.8: "The session's window, extended by the facility's turnaround
    buffer, must not overlap any other `SCHEDULED` session on the same facility; a
    clash is rejected with `ERR_FACILITY_DOUBLE_BOOKED` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/facility_double_booked_with_turnaround_buffer
    """
    study = _study(api)
    facility = create_facility(capacity=10, turnaround_minutes=30)
    # FG1 10:00-11:00 + 30-min buffer blocks the room until 11:30.
    get_success_data(api.create_focus_group(
        create_focus_group_payload(study["id"], facility["id"],
                                   starts_at="2026-04-01T10:00:00Z",
                                   ends_at="2026-04-01T11:00:00Z", seats=5), FC))
    # FG2 11:15-12:00 starts inside the buffer -> clash.
    validate_error(api.create_focus_group(
        create_focus_group_payload(study["id"], facility["id"],
                                   starts_at="2026-04-01T11:15:00Z",
                                   ends_at="2026-04-01T12:00:00Z", seats=5), FC),
        ApiErrorId.ERR_FACILITY_DOUBLE_BOOKED.value)


def test_facility_booking_at_buffer_end_succeeds(api):
    """PRD §3.8: "The session's window, extended by the facility's turnaround
    buffer, must not overlap any other `SCHEDULED` session on the same facility".
    PRD §3.8: "the session window `starts_at` (inclusive) and `ends_at`
    (exclusive) as ISO 8601 UTC instants".

    A session starting exactly at the buffer end (11:30) no longer overlaps the
    buffered window, confirming the buffered boundary is non-inclusive at the end.

    Design: Difficulty/resource_temporal_overlap/facility_double_booked_with_turnaround_buffer
    """
    study = _study(api)
    facility = create_facility(capacity=10, turnaround_minutes=30)
    get_success_data(api.create_focus_group(
        create_focus_group_payload(study["id"], facility["id"],
                                   starts_at="2026-04-01T10:00:00Z",
                                   ends_at="2026-04-01T11:00:00Z", seats=5), FC))
    # Starts exactly at the buffer end 11:30 -> no overlap -> 201.
    ok = validate_success(api.create_focus_group(
        create_focus_group_payload(study["id"], facility["id"],
                                   starts_at="2026-04-01T11:30:00Z",
                                   ends_at="2026-04-01T12:30:00Z", seats=5), FC),
        expected_status=201)
    assert ok["status"] == "SCHEDULED"


def test_panelist_schedule_conflict_overlapping_sessions(api):
    """PRD §3.8: "the panelist must not already hold a `CONFIRMED` booking on
    another `SCHEDULED` session whose window overlaps this one (compared on the
    half-open `starts_at`–`ends_at` interval, with no turnaround buffer between a
    panelist's own sessions); a clash is rejected with
    `ERR_PANELIST_SCHEDULE_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/panelist_schedule_conflict_no_buffer_halfopen
    """
    study = _study(api)
    facA = create_facility(capacity=10)
    facB = create_facility(capacity=10)
    fgA = get_success_data(api.create_focus_group(
        create_focus_group_payload(study["id"], facA["id"],
                                   starts_at="2026-04-02T14:00:00Z",
                                   ends_at="2026-04-02T15:00:00Z", seats=5), FC))
    fgB = get_success_data(api.create_focus_group(
        create_focus_group_payload(study["id"], facB["id"],
                                   starts_at="2026-04-02T14:30:00Z",
                                   ends_at="2026-04-02T15:30:00Z", seats=5), FC))
    panelist = create_panelist(segment_key="SEG_T2")
    # First booking confirmed on session A.
    get_success_data(api.create_focus_group_booking(
        create_focus_group_booking_payload(fgA["id"], panelist["id"], fgA["version"]), FC))

    # Session B overlaps A (14:30-15:30 vs 14:00-15:00) -> conflict.
    validate_error(api.create_focus_group_booking(
        create_focus_group_booking_payload(fgB["id"], panelist["id"], fgB["version"]), FC),
        ApiErrorId.ERR_PANELIST_SCHEDULE_CONFLICT.value)


def test_panelist_back_to_back_sessions_half_open_no_conflict(api):
    """PRD §3.8: "compared on the half-open `starts_at`–`ends_at` interval, with no
    turnaround buffer between a panelist's own sessions".
    PRD §3.8: "the session window `starts_at` (inclusive) and `ends_at`
    (exclusive) as ISO 8601 UTC instants".

    A second session starting exactly when the first ends (15:00) does not overlap
    on the half-open interval, so the panelist may hold both bookings.

    Design: Difficulty/resource_temporal_overlap/panelist_schedule_conflict_no_buffer_halfopen
    """
    study = _study(api)
    facA = create_facility(capacity=10)
    facB = create_facility(capacity=10)
    fgA = get_success_data(api.create_focus_group(
        create_focus_group_payload(study["id"], facA["id"],
                                   starts_at="2026-04-02T14:00:00Z",
                                   ends_at="2026-04-02T15:00:00Z", seats=5), FC))
    fgB = get_success_data(api.create_focus_group(
        create_focus_group_payload(study["id"], facB["id"],
                                   starts_at="2026-04-02T15:00:00Z",
                                   ends_at="2026-04-02T16:00:00Z", seats=5), FC))
    panelist = create_panelist(segment_key="SEG_T2B")
    get_success_data(api.create_focus_group_booking(
        create_focus_group_booking_payload(fgA["id"], panelist["id"], fgA["version"]), FC))

    ok = validate_success(api.create_focus_group_booking(
        create_focus_group_booking_payload(fgB["id"], panelist["id"], fgB["version"]), FC),
        expected_status=201)
    assert ok["status"] == "CONFIRMED"
