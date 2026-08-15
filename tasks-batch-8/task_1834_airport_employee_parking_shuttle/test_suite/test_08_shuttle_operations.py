"""Shuttle operations: the SCHEDULED vs OBSERVED service-level variants, the
route-state gate on DEPART, and trip spacing."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_lot,
    create_program,
    create_route_payload,
    create_trip_payload,
    set_logical_clock,
    trip_event_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["parking_admin_headers"]
DISPATCHER = TEST_USERS["shuttle_dispatcher_headers"]

WINDOW = {"window_start": "2026-08-03T00:00:00Z",
          "window_end": "2026-08-03T23:59:59Z"}


class TestShuttleSlaScheduledVsObserved:
    """One trip set (4 trips at 10-minute headways, middle two cancelled) is
    SLA-compliant under SCHEDULED but not under OBSERVED."""

    def _drive(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        program = create_program(name="P-SLA")
        lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=10)
        route = validate_success(
            api.create_route(
                create_route_payload(lot["id"], code="R1",
                                     headway_target_minutes=10,
                                     operating_cost_per_trip_cents=4000),
                DISPATCHER,
            ),
            201,
        )
        trips = {}
        for label, hh in (("t1", "08:00"), ("t2", "08:10"), ("t3", "08:20"),
                          ("t4", "08:30")):
            trips[label] = validate_success(
                api.create_trip(
                    create_trip_payload(route["id"], f"2026-08-03T{hh}:00Z"),
                    DISPATCHER,
                ),
                201,
            )
        # Trips 1 and 4 depart on schedule; the middle two are cancelled.
        set_logical_clock("2026-08-03T08:00:00Z")
        validate_success(
            api.trip_event(trips["t1"]["id"], trip_event_payload("DEPART"),
                           DISPATCHER),
            200,
        )
        set_logical_clock("2026-08-03T08:30:00Z")
        validate_success(
            api.trip_event(trips["t4"]["id"], trip_event_payload("DEPART"),
                           DISPATCHER),
            200,
        )
        for label in ("t2", "t3"):
            validate_success(
                api.trip_event(trips[label]["id"], trip_event_payload("CANCEL"),
                               DISPATCHER),
                200,
            )
        return route

    def test_scheduled_mode_uses_published_timetable(self, api):
        """PRD section 3.8: "Under `SCHEDULED` mode every selected trip
        participates by its scheduled departure — the published timetable,
        whatever the trip's status."
        PRD section 3.8: "In both modes the participating trips are ordered by
        departure ascending with `created_at` ascending as the tie-break, gaps
        are the consecutive departure deltas in whole minutes, `max_gap_minutes`
        is the largest gap, and `expected_wait_minutes` is half the mean of the
        gaps, rounded half-up to two decimal places. A route is `sla_compliant`
        exactly when its largest gap is at most twice its
        `headway_target_minutes`."

        Design: Difficulty/dual_variant_calc/shuttle_sla_scheduled_vs_observed
        """
        route = self._drive(api)
        report = validate_success(
            api.get_route_service_level(route["id"], DISPATCHER,
                                        params={**WINDOW, "mode": "SCHEDULED"}),
            200,
        )
        assert report["trip_count"] == 4, "every trip in the window participates"
        assert report["max_gap_minutes"] == 10
        assert report["expected_wait_minutes"] == 5.0, "half the mean gap (10)"
        assert report["sla_compliant"] is True, "10 <= 2 x 10"

    def test_observed_mode_sees_the_30_minute_hole(self, api):
        """PRD section 3.8: "Under `OBSERVED` mode only trips with an
        `actual_departure_at` — those `DEPARTED` or `COMPLETED` — participate,
        and they participate by their actual departure; cancelled and
        never-departed trips drop out, which stretches the adjacent observed
        gaps."
        PRD section 3.8: "The two modes can disagree sharply: a route whose
        timetable shows four trips ten minutes apart reports a compliant
        10-minute maximum gap under `SCHEDULED`, yet if the middle two trips were
        cancelled, `OBSERVED` mode sees a 30-minute hole between the surviving
        departures and reports non-compliance for the same window."

        Design: Difficulty/dual_variant_calc/shuttle_sla_scheduled_vs_observed
        """
        route = self._drive(api)
        scheduled = validate_success(
            api.get_route_service_level(route["id"], DISPATCHER,
                                        params={**WINDOW, "mode": "SCHEDULED"}),
            200,
        )
        observed = validate_success(
            api.get_route_service_level(route["id"], DISPATCHER,
                                        params={**WINDOW, "mode": "OBSERVED"}),
            200,
        )
        assert observed["max_gap_minutes"] == 30, (
            "only the 08:00 and 08:30 departures survive"
        )
        assert observed["expected_wait_minutes"] == 15.0, "half the mean gap (30)"
        assert observed["sla_compliant"] is False, "30 > 2 x 10"
        assert scheduled["sla_compliant"] != observed["sla_compliant"], (
            "same window, same trips, divergent verdicts"
        )


class TestDepartRequiresActiveRoute:
    """ShuttleTrip -> ShuttleRoute dependency: DEPART is valid only while the
    route is ACTIVE."""

    def _setup(self, api):
        set_logical_clock("2026-08-01T00:00:00Z")
        program = create_program(name="P-XE2")
        lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=5)
        route = validate_success(
            api.create_route(create_route_payload(lot["id"]), DISPATCHER), 201
        )
        trip = validate_success(
            api.create_trip(
                create_trip_payload(route["id"], "2026-08-03T08:00:00Z"),
                DISPATCHER,
            ),
            201,
        )
        set_logical_clock("2026-08-03T07:55:00Z")
        validate_success(
            api.route_event(route["id"], {"event_type": "SUSPEND"}, DISPATCHER), 200
        )
        set_logical_clock("2026-08-03T08:00:00Z")
        return route, trip

    def test_depart_on_suspended_route_rejected(self, api):
        """PRD section 3.8: "Suspension — either a dispatcher route event whose
        `event_type` is `SUSPEND`, or a route-suspension notice becoming
        effective — moves the route to `SUSPENDED`; crucially, its trips are not
        cancelled: `SCHEDULED` trips remain on the books, but any departure
        attempt is rejected with `ERR_ROUTE_NOT_ACTIVE` while the route is
        suspended."

        Design: Difficulty/cross_entity_state_dependency/depart_requires_active_route
        """
        _route, trip = self._setup(api)
        res = api.trip_event(trip["id"], trip_event_payload("DEPART"), DISPATCHER)
        validate_error(res, "ERR_ROUTE_NOT_ACTIVE", expected_status=409)

    def test_rejected_depart_leaves_trip_scheduled(self, api):
        """PRD section 3.8: "Suspension — either a dispatcher route event whose
        `event_type` is `SUSPEND`, or a route-suspension notice becoming
        effective — moves the route to `SUSPENDED`; crucially, its trips are not
        cancelled: `SCHEDULED` trips remain on the books, but any departure
        attempt is rejected with `ERR_ROUTE_NOT_ACTIVE` while the route is
        suspended."
        PRD section 3.8: "A departure event (`event_type` `DEPART`) requires the
        route to be `ACTIVE`, stamps `actual_departure_at` with the current
        logical time, and moves the trip to `DEPARTED`."

        Design: Difficulty/cross_entity_state_dependency/depart_requires_active_route
        """
        _route, trip = self._setup(api)
        validate_error(
            api.trip_event(trip["id"], trip_event_payload("DEPART"), DISPATCHER),
            "ERR_ROUTE_NOT_ACTIVE",
        )

        after = validate_success(api.get_trip(trip["id"], DISPATCHER), 200)
        assert after["status"] == "SCHEDULED", "route suspension does not cancel trips"
        assert after["actual_departure_at"] is None, (
            "a rejected DEPART stamps nothing"
        )


def test_trip_spacing_conflict_boundary(api):
    """PRD section 3.8: "Departures on one route must breathe: the scheduled
    departures of all non-`CANCELLED` trips on a route must sit at least 5
    minutes apart, so a new trip landing within five minutes of an existing one
    is rejected with `ERR_TRIP_SPACING_CONFLICT` — exactly five minutes is
    acceptable."

    Design: Corner/validations/trip_spacing_conflict_boundary
    """
    set_logical_clock("2026-08-01T00:00:00Z")
    program = create_program(name="P-V7")
    lot = create_lot(program["id"], code="CORE-A", tier="CORE", capacity=5)
    route = validate_success(
        api.create_route(create_route_payload(lot["id"]), DISPATCHER), 201
    )
    validate_success(
        api.create_trip(create_trip_payload(route["id"], "2026-08-03T08:00:00Z"),
                        DISPATCHER),
        201,
    )

    # Three minutes after an existing trip: inside the forbidden window.
    res = api.create_trip(
        create_trip_payload(route["id"], "2026-08-03T08:03:00Z"), DISPATCHER
    )
    validate_error(res, "ERR_TRIP_SPACING_CONFLICT", expected_status=409)

    # Exactly five minutes: acceptable.
    ok = validate_success(
        api.create_trip(create_trip_payload(route["id"], "2026-08-03T08:05:00Z"),
                        DISPATCHER),
        201,
    )
    assert ok["status"] == "SCHEDULED"

    _data, meta = validate_paginated(
        api.list_trips(DISPATCHER, params={"route_id": route["id"]})
    )
    assert meta["total_count"] == 2, "the rejected trip left no residue"
