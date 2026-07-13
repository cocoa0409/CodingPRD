"""Routes and contraflow: cross-entity activation, window overlap, adjacency, close cascade."""
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    create_active_incident, create_route, set_route_status, create_contraflow,
    setup_route_open_with_contraflow, TEST_USERS,
)

TRAFFIC = TEST_USERS["traffic_headers"]


def test_contraflow_activate_route_planned_rejected(api):
    """PRD 3.5: "Activating `SCHEDULED → ACTIVE` requires the parent route to be `OPEN` (else `ERR_ROUTE_NOT_OPEN`) and the current clock to fall within the window — `window_start_utc` at or before now and now strictly before `window_end_utc` — otherwise `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/contraflow_activate_requires_route_open
    """
    inc = create_active_incident(name="Coast Tsunami", jurisdiction="Del Norte", hazard_type="TSUNAMI")
    route = create_route(inc["id"])  # left PLANNED
    seg = create_contraflow(route["id"], segment_key="SEG-A",
                            window_start_utc="2026-02-01T00:00:00Z",
                            window_end_utc="2026-12-01T00:00:00Z")

    resp = api.set_contraflow_segment_status(seg["id"], {"state": "ACTIVE"}, TRAFFIC)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_OPEN)


def test_contraflow_activate_route_open_succeeds(api):
    """PRD 3.5: "Activating `SCHEDULED → ACTIVE` requires the parent route to be `OPEN` (else `ERR_ROUTE_NOT_OPEN`) and the current clock to fall within the window — `window_start_utc` at or before now and now strictly before `window_end_utc` — otherwise `ERR_INVALID_STATE`."

    Design: Difficulty/cross_entity_state_dependency/contraflow_activate_requires_route_open
    """
    inc = create_active_incident(name="Coast Tsunami", jurisdiction="Del Norte", hazard_type="TSUNAMI")
    route = create_route(inc["id"])
    set_route_status(route["id"], "OPEN")
    seg = create_contraflow(route["id"], segment_key="SEG-A",
                            window_start_utc="2026-02-01T00:00:00Z",
                            window_end_utc="2026-12-01T00:00:00Z")

    data = validate_success(api.set_contraflow_segment_status(seg["id"], {"state": "ACTIVE"}, TRAFFIC))
    assert data["status"] == "ACTIVE"


def test_contraflow_window_overlap_rejected(api):
    """PRD 3.5: "Two `SCHEDULED` or `ACTIVE` segments on the same `route_id` and `segment_key` must not overlap on their half-open windows; adjacency, where one window's end equals the next window's start, is permitted, but any true overlap is rejected with `ERR_CONTRAFLOW_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/contraflow_window_overlap_violation
    """
    inc = create_active_incident(name="Coast Tsunami", jurisdiction="Del Norte", hazard_type="TSUNAMI")
    route = create_route(inc["id"])
    create_contraflow(route["id"], segment_key="SEG-B",
                      window_start_utc="2026-03-01T10:00:00Z",
                      window_end_utc="2026-03-01T12:00:00Z")

    resp = api.create_contraflow_segment(
        {"route_id": route["id"], "segment_key": "SEG-B", "direction": "INBOUND_REVERSED",
         "window_start_utc": "2026-03-01T11:00:00Z", "window_end_utc": "2026-03-01T13:00:00Z"},
        TRAFFIC,
    )
    validate_error(resp, ApiErrorId.ERR_CONTRAFLOW_WINDOW_OVERLAP)


def test_contraflow_different_segment_key_allowed(api):
    """PRD 3.5: "Two `SCHEDULED` or `ACTIVE` segments on the same `route_id` and `segment_key` must not overlap on their half-open windows; adjacency, where one window's end equals the next window's start, is permitted, but any true overlap is rejected with `ERR_CONTRAFLOW_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/contraflow_window_overlap_violation
    """
    inc = create_active_incident(name="Coast Tsunami", jurisdiction="Del Norte", hazard_type="TSUNAMI")
    route = create_route(inc["id"])
    create_contraflow(route["id"], segment_key="SEG-B",
                      window_start_utc="2026-03-01T10:00:00Z",
                      window_end_utc="2026-03-01T12:00:00Z")

    # Time-overlapping window but a DIFFERENT segment_key -> not an overlap.
    data = validate_success(
        api.create_contraflow_segment(
            {"route_id": route["id"], "segment_key": "SEG-C", "direction": "INBOUND_REVERSED",
             "window_start_utc": "2026-03-01T11:00:00Z", "window_end_utc": "2026-03-01T13:00:00Z"},
            TRAFFIC,
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"


def test_contraflow_adjacent_window_gap_zero_allowed(api):
    """PRD 3.5: "adjacency, where one window's end equals the next window's start, is permitted, but any true overlap is rejected with `ERR_CONTRAFLOW_WINDOW_OVERLAP`."

    Design: Difficulty/boundary_precision_check/contraflow_adjacent_window_gap_zero_allowed
    """
    inc = create_active_incident(name="Coast Tsunami", jurisdiction="Del Norte", hazard_type="TSUNAMI")
    route = create_route(inc["id"])
    create_contraflow(route["id"], segment_key="SEG-A",
                      window_start_utc="2026-03-01T10:00:00Z",
                      window_end_utc="2026-03-01T12:00:00Z")

    data = validate_success(
        api.create_contraflow_segment(
            {"route_id": route["id"], "segment_key": "SEG-A", "direction": "INBOUND_REVERSED",
             "window_start_utc": "2026-03-01T12:00:00Z", "window_end_utc": "2026-03-01T14:00:00Z"},
            TRAFFIC,
        ),
        201,
    )
    assert data["id"]


def test_contraflow_adjacent_window_status_scheduled(api):
    """PRD 3.5: "A new segment begins `SCHEDULED`."
    PRD 3.5: "adjacency, where one window's end equals the next window's start, is permitted, but any true overlap is rejected with `ERR_CONTRAFLOW_WINDOW_OVERLAP`."

    Design: Difficulty/boundary_precision_check/contraflow_adjacent_window_gap_zero_allowed
    """
    inc = create_active_incident(name="Coast Tsunami", jurisdiction="Del Norte", hazard_type="TSUNAMI")
    route = create_route(inc["id"])
    create_contraflow(route["id"], segment_key="SEG-A",
                      window_start_utc="2026-03-01T10:00:00Z",
                      window_end_utc="2026-03-01T12:00:00Z")

    data = validate_success(
        api.create_contraflow_segment(
            {"route_id": route["id"], "segment_key": "SEG-A", "direction": "INBOUND_REVERSED",
             "window_start_utc": "2026-03-01T12:00:00Z", "window_end_utc": "2026-03-01T14:00:00Z"},
            TRAFFIC,
        ),
        201,
    )
    assert data["status"] == "SCHEDULED"


def test_route_close_cascades_cancel_contraflow(api):
    """PRD 3.5: "Closing a route from either `OPEN` or `CONGESTED` moves it to `CLOSED` and cancels every contraflow segment on that route currently `SCHEDULED` or `ACTIVE` (each moved to `CANCELLED`)."

    Design: Corner/consistency_model/route_close_cascades_cancel_contraflow
    """
    inc, route, seg = setup_route_open_with_contraflow(segment_key="SEG-A")

    set_route_status(route["id"], "CLOSED")

    route_after = validate_success(api.get_route(route["id"], TRAFFIC))
    assert route_after["status"] == "CLOSED"
    segs, _meta = validate_paginated(api.list_route_contraflow_segments(route["id"], TRAFFIC))
    match = [s for s in segs if s["id"] == seg["id"]]
    assert match and match[0]["status"] == "CANCELLED"
