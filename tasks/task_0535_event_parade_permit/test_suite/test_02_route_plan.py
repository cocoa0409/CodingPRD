"""Route plan assembly: closure-schedule guards (suspended, min-gap conflict),
gap boundary acceptance, and route-segment reverse-reachability.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    make_applicant_headers, officer_headers,
    create_venue, create_applicant, create_closure_schedule, create_application,
    add_segment,
)
import test_helpers.factories as F


def _draft_app(schedule_gap=30, venue_type="STREET_CORRIDOR"):
    venue = create_venue(venue_type=venue_type, max_capacity=6000)
    schedule = create_closure_schedule(min_gap_minutes=schedule_gap)
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind="RACE",
                             expected_attendance=3000,
                             occupy_start="2026-07-03T09:00:00Z",
                             occupy_end="2026-07-03T14:00:00Z")
    return venue, schedule, applicant, app


# ==========================================================================
# Closure min-gap: half-open geometry (queue A)
# ==========================================================================
def test_closure_min_gap_half_open_conflict(api):
    """PRD §3.3: "the new interval must stay at least min_gap_minutes clear of every
    other non-terminal closure already scheduled on the same corridor; back-to-back
    closures are permitted only when the clear gap between them is at least
    min_gap_minutes. A violation is rejected with ERR_CLOSURE_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/closure_min_gap_half_open_conflict
    """
    venue, schedule, applicant, app = _draft_app(schedule_gap=30)
    hdrs = make_applicant_headers(applicant["id"])
    add_segment(app["id"], applicant["id"], schedule["id"], segment_label="N first",
                closure_start="2026-06-17T10:00:00Z", closure_end="2026-06-17T12:00:00Z")
    # second [12:20,13:00): gap 20m < 30m
    resp = api.add_route_segment(app["id"],
                                 F.create_route_segment_payload(schedule["id"],
                                                               segment_label="N second",
                                                               closure_start="2026-06-17T12:20:00Z",
                                                               closure_end="2026-06-17T13:00:00Z"),
                                 hdrs)
    validate_error(resp, ApiErrorId.ERR_CLOSURE_CONFLICT, expected_status=409)


def test_closure_conflict_overlapping_interval(api):
    """PRD §3.3: "the new interval must stay at least min_gap_minutes clear of every
    other non-terminal closure already scheduled on the same corridor". PRD §3.3:
    "A violation is rejected with ERR_CLOSURE_CONFLICT."

    Design: Difficulty/resource_temporal_overlap/closure_min_gap_half_open_conflict
    """
    venue, schedule, applicant, app = _draft_app(schedule_gap=30)
    hdrs = make_applicant_headers(applicant["id"])
    add_segment(app["id"], applicant["id"], schedule["id"], segment_label="first",
                closure_start="2026-06-17T10:00:00Z", closure_end="2026-06-17T12:00:00Z")
    # directly overlapping [11:00,13:00) — 0 gap, clear violation
    resp = api.add_route_segment(app["id"],
                                 F.create_route_segment_payload(schedule["id"],
                                                               segment_label="overlap",
                                                               closure_start="2026-06-17T11:00:00Z",
                                                               closure_end="2026-06-17T13:00:00Z"),
                                 hdrs)
    validate_error(resp, ApiErrorId.ERR_CLOSURE_CONFLICT, expected_status=409)


# ==========================================================================
# Gap boundary: exactly min_gap passes (queue B)
# ==========================================================================
def test_closure_gap_exactly_min_allows_segment(api):
    """PRD §3.3: "back-to-back closures are permitted only when the clear gap between
    them is at least min_gap_minutes." PRD §2.8: "two closures may be scheduled
    back-to-back only if the clear gap between them is at least min_gap_minutes."

    Design: Corner/validations/closure_gap_exactly_min_allows_segment
    """
    venue, schedule, applicant, app = _draft_app(schedule_gap=30)
    hdrs = make_applicant_headers(applicant["id"])
    add_segment(app["id"], applicant["id"], schedule["id"], segment_label="W first",
                closure_start="2026-07-03T10:00:00Z", closure_end="2026-07-03T12:00:00Z")
    # second [12:30,13:00): exactly 30m clear == min_gap -> accepted
    resp = api.add_route_segment(app["id"],
                                 F.create_route_segment_payload(schedule["id"],
                                                               segment_label="W second",
                                                               closure_start="2026-07-03T12:30:00Z",
                                                               closure_end="2026-07-03T13:00:00Z"),
                                 hdrs)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "PLANNED"


# ==========================================================================
# Suspended schedule rejects new segment (queue B)
# ==========================================================================
def test_add_segment_to_suspended_schedule_rejected(api):
    """PRD §3.3: "the target schedule must be accepting closures: if its status is
    SUSPENDED, the add is rejected with ERR_CLOSURE_SCHEDULE_SUSPENDED."

    Design: Corner/validations/add_segment_to_suspended_schedule_rejected
    """
    venue = create_venue(venue_type="STREET_CORRIDOR", max_capacity=6000)
    schedule = create_closure_schedule(min_gap_minutes=30)
    api.suspend_closure_schedule(schedule["id"], officer_headers())
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind="PARADE",
                             expected_attendance=500,
                             occupy_start="2026-07-04T10:00:00Z",
                             occupy_end="2026-07-04T14:00:00Z")
    hdrs = make_applicant_headers(applicant["id"])
    resp = api.add_route_segment(app["id"],
                                 F.create_route_segment_payload(schedule["id"],
                                                               segment_label="X 1",
                                                               closure_start="2026-07-04T10:00:00Z",
                                                               closure_end="2026-07-04T11:00:00Z"),
                                 hdrs)
    validate_error(resp, ApiErrorId.ERR_CLOSURE_SCHEDULE_SUSPENDED, expected_status=409)


# ==========================================================================
# Reverse-reachability (queue B)
# ==========================================================================
def test_route_segments_reverse_reachable_by_application(api):
    """PRD §4 (endpoint): "GET /permit-applications/{appId}/route-segments — List an
    application's route segments". PRD §3.3: each route segment carries the
    application it belongs to (it is attached to a specific application).

    Design: Corner/endpoints/route_segments_reverse_reachable_by_application
    """
    venue = create_venue(venue_type="STREET_CORRIDOR", max_capacity=6000)
    schedule = create_closure_schedule(min_gap_minutes=30)
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind="RACE",
                             expected_attendance=3000,
                             occupy_start="2026-07-13T08:00:00Z",
                             occupy_end="2026-07-13T16:00:00Z")
    add_segment(app["id"], applicant["id"], schedule["id"], segment_label="EE 1",
                closure_start="2026-07-13T09:00:00Z", closure_end="2026-07-13T11:00:00Z")
    resp = api.list_route_segments(app["id"], officer_headers())
    data, meta = validate_paginated(resp)
    assert meta["total_count"] >= 1
    for seg in data:
        assert seg["application_id"] == app["id"]


def test_route_segments_reverse_reachable_by_closure_schedule(api):
    """PRD §4 (endpoint): "GET /route-segments — List route segments (filterable by
    closure_schedule_id, application_id)". PRD §3.3: each segment "names the
    closure_schedule_id of the corridor it closes".

    Design: Corner/endpoints/route_segments_reverse_reachable_by_closure_schedule
    """
    venue = create_venue(venue_type="STREET_CORRIDOR", max_capacity=6000)
    schedule = create_closure_schedule(min_gap_minutes=30)
    applicant = create_applicant()
    app = create_application(venue["id"], applicant["id"], event_kind="RACE",
                             expected_attendance=3000,
                             occupy_start="2026-07-14T08:00:00Z",
                             occupy_end="2026-07-14T16:00:00Z")
    add_segment(app["id"], applicant["id"], schedule["id"], segment_label="FF 1",
                closure_start="2026-07-14T10:00:00Z", closure_end="2026-07-14T12:00:00Z")
    resp = api.list_route_segments_global(officer_headers(),
                                          params={"closure_schedule_id": schedule["id"]})
    data, meta = validate_paginated(resp)
    for seg in data:
        assert seg["closure_schedule_id"] == schedule["id"]
