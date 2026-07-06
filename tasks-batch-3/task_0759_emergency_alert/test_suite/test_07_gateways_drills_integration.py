"""Gateways, maintenance windows, drills, integration ingest, and listing."""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, TEST_USERS,
)
from test_helpers.fixtures import set_clock, create_gateway, create_group, run_tick

ADMIN = TEST_USERS["contact_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
INTEGRATOR = TEST_USERS["integrator_headers"]


def test_overlapping_maintenance_window_rejected(api):
    """PRD §3.8: "A maintenance window is half-open: it includes its `start_at` and
    excludes its `end_at`, so a new window whose `start_at` equals an existing window's
    `end_at` is adjacent and allowed, but any true overlap with an existing window on that
    gateway is rejected with `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/gateway_maintenance_halfopen_overlap
    """
    gateway = create_gateway(api, channel_type="SMS", capacity_per_window=100)
    get_success_data(api.create_maintenance_window(
        gateway["id"], {"start_at": "2026-03-12T10:00:00Z", "end_at": "2026-03-12T12:00:00Z"}, ADMIN))
    resp = api.create_maintenance_window(
        gateway["id"], {"start_at": "2026-03-12T11:00:00Z", "end_at": "2026-03-12T13:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value)


def test_adjacent_maintenance_window_allowed(api):
    """PRD §3.8: "a new window whose `start_at` equals an existing window's `end_at` is
    adjacent and allowed, but any true overlap with an existing window on that gateway is
    rejected with `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/gateway_maintenance_halfopen_overlap
    """
    gateway = create_gateway(api, channel_type="SMS", capacity_per_window=100)
    get_success_data(api.create_maintenance_window(
        gateway["id"], {"start_at": "2026-03-12T10:00:00Z", "end_at": "2026-03-12T12:00:00Z"}, ADMIN))
    # New window starting exactly at the previous window's end is adjacent, not overlapping.
    resp = api.create_maintenance_window(
        gateway["id"], {"start_at": "2026-03-12T12:00:00Z", "end_at": "2026-03-12T13:00:00Z"}, ADMIN)
    validate_success(resp, expected_status=201)


def test_drill_within_buffer_gap_rejected(api):
    """PRD §3.8: "Drill scheduling is closed on both ends (both the start and end instants
    are part of the exercise) and enforces a 30-minute buffer gap: a new drill on the same
    group that falls within 30 minutes of an existing `SCHEDULED` drill on that group is
    rejected with `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/drill_buffer_gap_overlap_on_group
    """
    group = create_group(api, name="G1")
    get_success_data(api.create_drill(
        {"group_id": group["id"], "scheduled_start": "2026-03-12T10:00:00Z",
         "scheduled_end": "2026-03-12T11:00:00Z"}, ADMIN))
    # New drill starts 20 min after the prior one's end — inside the 30-min buffer.
    resp = api.create_drill(
        {"group_id": group["id"], "scheduled_start": "2026-03-12T11:20:00Z",
         "scheduled_end": "2026-03-12T12:00:00Z"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_WINDOW_OVERLAP.value)


def test_drill_outside_buffer_gap_allowed(api):
    """PRD §3.8: "a new drill on the same group that falls within 30 minutes of an
    existing `SCHEDULED` drill on that group is rejected with `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/drill_buffer_gap_overlap_on_group
    """
    group = create_group(api, name="G1")
    get_success_data(api.create_drill(
        {"group_id": group["id"], "scheduled_start": "2026-03-12T10:00:00Z",
         "scheduled_end": "2026-03-12T11:00:00Z"}, ADMIN))
    # New drill starts 60 min after the prior one's end — well outside the 30-min buffer.
    resp = api.create_drill(
        {"group_id": group["id"], "scheduled_start": "2026-03-12T12:00:00Z",
         "scheduled_end": "2026-03-12T13:00:00Z"}, ADMIN)
    validate_success(resp, expected_status=201)


def test_drill_auto_completes_on_tick_when_due(api):
    """PRD §3.8: "tick processing completes a scheduled drill (`SCHEDULED → COMPLETED`)
    once its `scheduled_end` is at or before the current clock."

    Design: Corner/state_machines/drill_auto_completes_on_tick_when_due
    """
    set_clock(api, "2026-03-12T09:00:00Z")
    group = create_group(api, name="G1")
    drill = get_success_data(api.create_drill(
        {"group_id": group["id"], "scheduled_start": "2026-03-12T10:00:00Z",
         "scheduled_end": "2026-03-12T11:00:00Z"}, ADMIN))
    set_clock(api, "2026-03-12T12:00:00Z")
    run_tick(api)
    reread = get_success_data(api.get_drill(drill["id"], ADMIN))
    assert reread["status"] == "COMPLETED", f"Expected COMPLETED, got {reread['status']}"


def test_new_gateway_window_count_zero(api):
    """PRD §3.8: "a new gateway opens `ONLINE` and exposes the computed `window_count` of
    §2.10."
    PRD §2.9: "A gateway's `window_count` is the number of non-`SUPPRESSED` notifications
    whose `channel_type` equals the gateway's `channel_type` and whose `created_at` falls
    in the current throttle window."

    Design: Corner/consistency_model/immediate_visibility_of_created_gateway
    """
    gateway = create_gateway(api, channel_type="SMS", capacity_per_window=100)
    reread = get_success_data(api.get_gateway(gateway["id"], ADMIN))
    assert reread["window_count"] == 0, f"Expected window_count 0, got {reread['window_count']}"


def test_integration_ingest_creates_draft_geo_alert(api):
    """PRD §3.8: "Ingest creates a `DRAFT` alert with `target_type` `GEO`, its
    `source_incident_ref` set to the supplied `external_ref`, and `author_user_id` set
    from the integrator's `X-User-ID`".

    Design: Corner/endpoints/integration_ingest_creates_draft_alert
    """
    resp = api.ingest_incident(
        {"source": "CAD", "external_ref": "INC-1", "severity": "WARNING",
         "center_lat": 0.0, "center_lon": 0.0, "radius_m": 1000, "channels": ["SMS"]}, INTEGRATOR)
    data = validate_success(resp, expected_status=201)
    assert data["status"] == "DRAFT", f"Expected DRAFT, got {data['status']}"
    assert data["source_incident_ref"] == "INC-1", f"Expected source_incident_ref INC-1, got {data['source_incident_ref']}"


def test_alerts_list_pagination(api):
    """PRD §2.3: "The `limit` parameter caps the number of items returned; when omitted it
    defaults to 10, with a minimum of 1 and a maximum of 100."
    PRD §2.3: "Every list response reports `limit`, `offset`, `total_count`, and
    `has_more` inside the envelope's `meta` object."

    Design: Corner/endpoints/alerts_list_pagination
    """
    for title in ("A", "B"):
        get_success_data(api.create_alert({
            "title": title, "severity": "WARNING", "channels": ["SMS"], "target_type": "GEO",
            "center_lat": 0.0, "center_lon": 0.0, "radius_m": 1000,
            "effective_from": "2026-03-10T00:00:00Z", "effective_until": "2026-03-11T00:00:00Z",
        }, DISPATCHER))
    resp = api.list_alerts(DISPATCHER, params={"limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert len(data) == 1, f"Expected 1 item with limit=1, got {len(data)}"
    assert meta["total_count"] == 2, f"Expected total_count 2, got {meta['total_count']}"
    assert meta["has_more"] is True, f"Expected has_more True, got {meta['has_more']}"
