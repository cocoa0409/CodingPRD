"""Stops and Routes: creation, state transitions, publish-time calculations.

Covers PRD §3.1 (stops), §3.2 (routes), §2.9 (numerical precision),
§2.10 (frequency windows).
"""
from __future__ import annotations
import math
import pytest

from prd_bench_local_runner.testing import (
    validate_error,
    validate_success,
    validate_paginated,
)
from test_helpers import (
    ApiErrorId,
    assert_stop, assert_route, assert_route_published_fields,
    assert_route_version,
    create_active_stop, create_active_stop_at, create_draft_stop,
    create_active_vehicle, create_active_driver,
    create_and_publish_route, create_draft_route,
    create_run_sheet, retire_route,
    create_route_payload, create_stop_payload, update_route_payload,
    expected_route_distance_km,
    expected_base_duration_minutes,
    setup_active_route_basic,
    setup_four_active_stops_in_line,
    api_client, iso_z, parse_iso,
    unique_route_code,
)
from datetime import timedelta


# ===========================================================================
# Stop CRUD and lifecycle (PRD §3.1)
# ===========================================================================
class TestStops:

    def test_create_draft_stop_sets_status_draft(self, dispatcher_headers):
        """PRD §3.1: "A Dispatcher registers a new stop in DRAFT status by
        providing its code, display name, latitude, longitude, an amenities
        array (zero or more of LIGHTING, SEATING, USB, DISPLAY, RAMP), a
        has_shelter flag (defaulting to false), and a capacity_reference
        integer between 1 and 500 inclusive that represents how many waiting
        riders the stop can hold without crowding."

        Claim: POST /shuttle/stops returns a Stop with status=DRAFT.
        """
        data = validate_success(
            api_client.create_stop(create_stop_payload(), dispatcher_headers),
            201,
        )
        assert_stop(data)
        assert data["status"] == "DRAFT"

    def test_activate_draft_stop_transitions_to_active(self, dispatcher_headers):
        """PRD §3.1: "A DRAFT stop becomes available for inclusion in
        published routes by activation, which a Dispatcher initiates; the
        only precondition is that the row's coordinates and capacity_reference
        are populated. The transition pair is DRAFT -> ACTIVE."

        Claim: DRAFT -> ACTIVE via POST /shuttle/stops/{id}/activate.
        """
        stop = create_draft_stop()
        activated = validate_success(
            api_client.activate_stop(stop["id"], dispatcher_headers), 200,
        )
        assert activated["status"] == "ACTIVE"

    def test_offshelf_active_stop_succeeds_when_no_active_route_references(
            self, dispatcher_headers):
        """PRD §3.1: "Once activated, a stop can be taken off-shelf with the
        transition ACTIVE -> OFFSHELF — but only if no ACTIVE route
        references it as its start stop, its end stop, or in its
        intermediate stop list; otherwise the request is rejected with
        ERR_INVALID_STATE."

        Claim: with no ACTIVE route referencing it, ACTIVE -> OFFSHELF
        succeeds.
        """
        stop = create_active_stop()
        data = validate_success(
            api_client.offshelf_stop(stop["id"], dispatcher_headers), 200,
        )
        assert data["status"] == "OFFSHELF"

    def test_reactivate_offshelf_stop(self, dispatcher_headers):
        """PRD §3.1: "Off-shelf stops can be brought back via OFFSHELF ->
        ACTIVE with no extra precondition."

        Claim: OFFSHELF -> ACTIVE succeeds.
        """
        stop = create_active_stop()
        api_client.offshelf_stop(stop["id"], dispatcher_headers)
        data = validate_success(
            api_client.activate_stop(stop["id"], dispatcher_headers), 200,
        )
        assert data["status"] == "ACTIVE"

    def test_offshelf_referenced_by_active_route_rejected(
            self, dispatcher_headers):
        """PRD §3.1: "Once activated, a stop can be taken off-shelf with the
        transition ACTIVE -> OFFSHELF — but only if no ACTIVE route
        references it as its start stop, its end stop, or in its
        intermediate stop list; otherwise the request is rejected with
        ERR_INVALID_STATE."

        Claim: ACTIVE Route referencing the stop as start_stop_id ->
        ERR_INVALID_STATE on offshelf.
        """
        route, stops = setup_active_route_basic()
        start_stop = stops[0]
        resp = api_client.offshelf_stop(start_stop["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


# ===========================================================================
# Route creation / edit / publish (PRD §3.2)
# ===========================================================================
class TestRouteLifecycle:

    def test_create_draft_route_sets_version_one(self, dispatcher_headers):
        """PRD §3.2: "A new route is created in DRAFT and assigned
        version_number 1. The fields estimated_distance_km and
        estimated_duration_minutes are computed at publish time and are
        not accepted as input."

        Claim: POST /shuttle/routes returns a DRAFT Route with
        version_number=1.
        """
        s1 = create_active_stop()
        s2 = create_active_stop_at(0.0, 0.05)
        data = validate_success(
            api_client.create_route(
                create_route_payload(s1["id"], s2["id"]),
                dispatcher_headers,
            ),
            201,
        )
        assert_route(data)
        assert data["status"] == "DRAFT"
        assert data["version_number"] == 1

    def test_edit_active_route_rejected(self, dispatcher_headers):
        """PRD §3.2: "A DRAFT route may be edited in place by a Dispatcher,
        who supplies any subset of name, start_stop_id, end_stop_id,
        intermediate_stop_ids, peak_frequency_minutes,
        offpeak_frequency_minutes, peak_windows, and an optional version
        for OCC; ACTIVE and RETIRED routes are immutable, and an attempt
        to modify them is rejected with ERR_INVALID_STATE."

        Claim: PATCH on ACTIVE route -> ERR_INVALID_STATE.
        """
        route, _ = setup_active_route_basic()
        resp = api_client.update_route(
            route["id"], update_route_payload(name="Renamed"),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_publish_route_with_inactive_stop_rejected(self, dispatcher_headers):
        """PRD §3.2: "First, the start_stop_id, the end_stop_id, and every
        entry in intermediate_stop_ids must currently be in ACTIVE stop
        status; otherwise the publish is rejected with ERR_STOP_NOT_ACTIVE."

        Claim: publish with a DRAFT (non-active) start_stop -> ERR_STOP_NOT_ACTIVE.
        """
        draft_stop = create_draft_stop()           # status=DRAFT
        end_stop = create_active_stop_at(0.0, 0.05)
        route = create_draft_route(draft_stop["id"], end_stop["id"])
        resp = api_client.publish_route(route["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_STOP_NOT_ACTIVE)

    def test_publish_invalid_peak_windows_rejected_overlap(self, dispatcher_headers):
        """PRD §2.10: "Each window in peak_windows is a [HH:MM, HH:MM)
        half-open local-time interval (start inclusive, end exclusive).
        The full peak-windows array must be sorted ascending, must not
        overlap, and successive windows must be separated by a gap of at
        least one minute; the peak headway must be no greater than the
        off-peak headway. Any structural violation — unsorted, overlapping,
        touching, or peak headway exceeding off-peak — is rejected with
        ERR_INVALID_FREQUENCY_WINDOWS both at route creation and at
        publish time."

        Claim: peak_windows that overlap -> ERR_INVALID_FREQUENCY_WINDOWS.
        """
        s1, s2 = create_active_stop(), create_active_stop_at(0.0, 0.05)
        resp = api_client.create_route(
            create_route_payload(s1["id"], s2["id"],
                                 peak_windows=[["09:00", "11:00"],
                                               ["10:00", "12:00"]]),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_FREQUENCY_WINDOWS)

    def test_publish_peak_exceeds_offpeak_rejected(self, dispatcher_headers):
        """PRD §2.10: "the peak headway must be no greater than the off-peak
        headway... Any structural violation — unsorted, overlapping,
        touching, or peak headway exceeding off-peak — is rejected with
        ERR_INVALID_FREQUENCY_WINDOWS both at route creation and at
        publish time."

        Claim: peak_frequency_minutes > offpeak_frequency_minutes ->
        ERR_INVALID_FREQUENCY_WINDOWS at route creation.
        """
        s1, s2 = create_active_stop(), create_active_stop_at(0.0, 0.05)
        resp = api_client.create_route(
            create_route_payload(s1["id"], s2["id"],
                                 peak_frequency_minutes=60,
                                 offpeak_frequency_minutes=30),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_FREQUENCY_WINDOWS)

    def test_publish_touching_peak_windows_rejected(self, dispatcher_headers):
        """PRD §2.10: "successive windows must be separated by a gap of at
        least one minute... Any structural violation — unsorted, overlapping,
        touching, or peak headway exceeding off-peak — is rejected with
        ERR_INVALID_FREQUENCY_WINDOWS both at route creation and at
        publish time."

        Claim: two peak windows whose end and start meet exactly (touching)
        -> ERR_INVALID_FREQUENCY_WINDOWS.
        """
        s1, s2 = create_active_stop(), create_active_stop_at(0.0, 0.05)
        resp = api_client.create_route(
            create_route_payload(s1["id"], s2["id"],
                                 peak_windows=[["09:00", "10:00"],
                                               ["10:00", "11:00"]]),
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_FREQUENCY_WINDOWS)

    def test_publish_computes_distance_and_duration_base_variant(
            self, dispatcher_headers):
        """PRD §3.2: "The route's estimated_distance_km is recomputed:
        starting from the ordered stop list [start_stop, intermediate_stop_1,
        ..., end_stop], the great-circle distance between each consecutive
        pair of stops is computed using the haversine formula on their
        latitude and longitude with an Earth radius of 6371.0088 kilometres,
        rounded half-up to four decimal places per segment, and the
        resulting per-segment distances are summed and then rounded half-up
        to two decimal places. The route's estimated_duration_minutes is
        then computed in the BASE variant: take the route's distance in
        kilometres, divide by the configured average speed of 25 kilometres
        per hour, multiply by 60 to express the travel time in minutes,
        add a one-minute dwell allowance per intermediate stop, and ceiling
        the result to a whole minute."

        Claim: publish stamps estimated_distance_km and
        estimated_duration_minutes matching the helper formulas.
        """
        stops = setup_four_active_stops_in_line(spacing_lng=0.01)
        route = create_and_publish_route(
            start_stop_id=stops[0]["id"],
            end_stop_id=stops[-1]["id"],
            intermediate_stop_ids=[stops[1]["id"], stops[2]["id"]],
        )
        assert_route_published_fields(route)
        expected_distance = expected_route_distance_km([
            {"latitude": s["latitude"], "longitude": s["longitude"]}
            for s in stops
        ])
        assert route["estimated_distance_km"] == pytest.approx(expected_distance, abs=0.005), \
            f"PRD §3.2 distance: expected {expected_distance}, got {route['estimated_distance_km']}"
        # BASE duration: (distance/25)*60 + 1*intermediate_count, ceil.
        expected_duration = expected_base_duration_minutes(
            route["estimated_distance_km"], intermediate_count=2,
        )
        assert route["estimated_duration_minutes"] == expected_duration, \
            f"PRD §3.2 BASE duration: expected {expected_duration}, got {route['estimated_duration_minutes']}"


# ===========================================================================
# Publish cascades and RouteVersion snapshots
# ===========================================================================
class TestPublishCascadeAndVersions:

    def test_publish_appends_route_version_snapshot(self, dispatcher_headers):
        """PRD §3.2: "A RouteVersion snapshot row is appended whose
        route_code matches the route's code, whose version_number is the
        largest prior version_number for that code plus one, and which
        freezes the stop_sequence_snapshot (the ordered start, intermediates,
        end), the peak_frequency_minutes, the offpeak_frequency_minutes,
        the peak_windows, and stamps published_at to the current instant
        with retired_at left null."

        Claim: GET /shuttle/routes/{id}/versions returns a snapshot whose
        version_number=1 and retired_at is null.
        """
        route, stops = setup_active_route_basic()
        data, _meta = validate_paginated(
            api_client.list_route_versions(route["id"], dispatcher_headers),
        )
        assert data, "RouteVersion snapshot missing after publish"
        snap = data[0]
        assert_route_version(snap)
        assert snap["route_code"] == route["code"]
        assert snap["version_number"] == 1
        assert snap.get("retired_at") in (None, "")

    def test_publish_same_code_retires_predecessor_and_increments_version(
            self, dispatcher_headers):
        """PRD §3.2: "If a prior ACTIVE route with the same code exists, its
        status is set to RETIRED and the corresponding RouteVersion.retired_at
        is stamped — and this retire-step in turn cascades..."

        Claim: publishing a second route with the same code retires the
        first and appends a RouteVersion with version_number=2.
        """
        s1 = create_active_stop()
        s2 = create_active_stop_at(0.0, 0.05)
        code = unique_route_code("SAME")
        first = create_draft_route(s1["id"], s2["id"], code=code)
        validate_success(
            api_client.publish_route(first["id"], dispatcher_headers), 200,
        )
        second = create_draft_route(s1["id"], s2["id"], code=code)
        second_active = validate_success(
            api_client.publish_route(second["id"], dispatcher_headers), 200,
        )
        assert second_active["status"] == "ACTIVE"
        # Predecessor must be RETIRED.
        prev = validate_success(
            api_client.get_route(first["id"], dispatcher_headers), 200,
        )
        assert prev["status"] == "RETIRED", \
            f"Prior ACTIVE route with same code must transition to RETIRED, got {prev['status']}"
        # Latest snapshot for the same code has version_number == 2.
        data, _ = validate_paginated(
            api_client.list_route_versions(second["id"], dispatcher_headers),
        )
        versions = sorted(d["version_number"] for d in data)
        assert versions[-1] == 2

    def test_retire_active_route_transitions_to_retired(self, dispatcher_headers):
        """PRD §3.2: "An explicit retire (ACTIVE -> RETIRED) is also
        available to a Dispatcher and triggers the same cascade chain into
        pending run-sheets and reservations. The transition is not blocked
        by the presence of pending runs — those are auto-cancelled rather
        than refused."

        Claim: POST /shuttle/routes/{id}/retire transitions ACTIVE -> RETIRED.
        """
        route, _ = setup_active_route_basic()
        retired = retire_route(route["id"])
        assert retired["status"] == "RETIRED"

    def test_audit_log_event_route_published(self, dispatcher_headers):
        """PRD §2.11: "Selected state transitions append a row to the audit
        log with an event_type drawn from the set RESERVATION_CREATED,
        RESERVATION_CANCELLED, RESERVATION_CHECKED_IN, RESERVATION_NO_SHOW,
        DELAY_REPORTED, SUBSTITUTE_DISPATCHED, ROUTE_PUBLISHED, and
        BILL_REFUNDED."

        Claim: a publish operation appends an AuditLog whose event_type ==
        ROUTE_PUBLISHED and subject_id == route["id"].
        """
        route, _ = setup_active_route_basic()
        from test_helpers import list_all_audit_logs
        logs = list_all_audit_logs(event_type="ROUTE_PUBLISHED",
                                   subject_id=route["id"])
        assert any(log["event_type"] == "ROUTE_PUBLISHED"
                   and log["subject_id"] == route["id"]
                   for log in logs), \
            "Expected at least one ROUTE_PUBLISHED audit log for the published route"


# ===========================================================================
# Route-code uniqueness scope (PRD §3.2)
# ===========================================================================
class TestRouteCodeUniqueness:

    def test_two_drafts_with_same_code_allowed(self, dispatcher_headers):
        """PRD §3.2: "The route code is unique only among ACTIVE routes:
        multiple DRAFT or RETIRED rows may share a code."

        Claim: creating two DRAFT routes with the same code is permitted.
        """
        s1, s2 = create_active_stop(), create_active_stop_at(0.0, 0.05)
        code = unique_route_code("DUP")
        validate_success(
            api_client.create_route(
                create_route_payload(s1["id"], s2["id"], code=code),
                dispatcher_headers,
            ),
            201,
        )
        # Second DRAFT must also succeed.
        validate_success(
            api_client.create_route(
                create_route_payload(s1["id"], s2["id"], code=code),
                dispatcher_headers,
            ),
            201,
        )
