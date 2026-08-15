"""Fleet sanitation and collection-route lifecycle (PRD §3.4, §2.4, §2.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_stop,
    assert_route,
    assert_vehicle,
    assert_wash_ticket,
    create_plant,
    create_route,
    create_vehicle,
    set_clock,
    setup_collected_stop,
    setup_planned_route_with_stop,
    setup_plant_with_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)

PM = TEST_USERS["plant_manager_headers"]
CO = TEST_USERS["compliance_officer_headers"]
RD = TEST_USERS["route_dispatcher_headers"]
ANY = TEST_USERS["any_headers"]


class TestVehicleCreation:
    def test_vehicle_create_defaults_sanitized(self, api):
        """PRD §3.4: "A new vehicle's `sanitation_status` is `SANITIZED` and its
        `completed_trip_count` is zero."

        Design: Corner/entities/vehicle_create_defaults_sanitized
        """
        plant = create_plant()
        from test_helpers import create_vehicle_payload

        res = api.create_vehicle(
            create_vehicle_payload(plant["id"], capacity_lbs=40000, duty_class="DUAL"), RD
        )
        vehicle = validate_success(res, 201)
        assert_vehicle(vehicle)
        assert vehicle["sanitation_status"] == "SANITIZED"
        assert vehicle["completed_trip_count"] == 0

    def test_wash_ticket_is_immutable_event(self, api):
        """PRD §2.4: "Two resource types are deliberately lighter. A wash ticket and a price
        index entry are both append-only records: each carries only `id` and `created_at`,
        and neither `updated_at` nor `version` exists on them, because they are never
        modified after creation."
        PRD §3.4: "A `FAIL` result leaves sanitation unchanged, and washing an
        already-`SANITIZED` vehicle is a harmless no-op that still records the ticket and
        returns success."

        Design: Corner/entities/wash_ticket_is_immutable_event
        """
        plant = create_plant()
        vehicle = create_vehicle(plant["id"], capacity_lbs=40000, duty_class="DUAL")
        res = api.create_wash_ticket(
            vehicle["id"],
            {
                "plant_id": plant["id"],
                "wash_type": "STANDARD",
                "washed_at": "2026-08-02T09:00:00Z",
                "detergent_ppm": 800.0,
                "result": "PASS",
            },
            RD,
        )
        ticket = validate_success(res, 201)
        assert_wash_ticket(ticket)
        assert ticket["recorded_by"] == "rd-1"
        assert ticket["result"] == "PASS"

        fetched = validate_success(api.get_wash_ticket(ticket["id"], ANY), 200)
        assert "updated_at" not in fetched
        assert "version" not in fetched

        vehicle_after = validate_success(api.get_vehicle(vehicle["id"], ANY), 200)
        assert vehicle_after["sanitation_status"] == "SANITIZED"


class TestRouteLifecycle:
    def test_dispatch_route_without_stops_rejected(self, api):
        """PRD §3.4: "A dispatcher may dispatch a route that is `PLANNED` (any other state:
        `ERR_ROUTE_INVALID_STATE`); ... at least one non-`CANCELLED` stop must exist
        (`ERR_ROUTE_EMPTY`); ..."

        Design: Corner/state_machines/dispatch_route_without_stops_rejected
        """
        plant = create_plant()
        vehicle = create_vehicle(plant["id"], capacity_lbs=40000)
        route = create_route(plant["id"], vehicle["id"])
        assert route["status"] == "PLANNED"

        res = api.dispatch_route(route["id"], RD)
        validate_error(res, ApiErrorId.ERR_ROUTE_EMPTY, expected_status=422)

        fetched = validate_success(api.get_collection_route(route["id"], ANY), 200)
        assert fetched["status"] == "PLANNED"

    def test_route_complete_marks_vehicle_dirty(self, api):
        """PRD §3.4: "Completion moves the route to `COMPLETED`, sets its
        `total_collected_lbs` to the sum of `actual_weight_lbs` over its stops in
        `DELIVERED` or `VOIDED`, turns the vehicle `DIRTY`, and adds 1 to its
        `completed_trip_count`."

        Design: Corner/state_machines/route_complete_marks_vehicle_dirty
        """
        ctx = setup_collected_stop(actual_weight_lbs=3000, actual_distance_miles=10,
                                   temperature_f=60.0)
        delivered = validate_success(api.deliver_stop(ctx["stop"]["id"], RD), 200)
        assert delivered["status"] == "DELIVERED"

        completed = validate_success(api.complete_route(ctx["route"]["id"], RD), 200)
        assert_route(completed)
        assert completed["status"] == "COMPLETED"
        assert completed["total_collected_lbs"] == 3000

        vehicle = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ANY), 200)
        assert vehicle["sanitation_status"] == "DIRTY"
        assert vehicle["completed_trip_count"] == 1

    def test_dispatch_after_return_window_rejected(self, api):
        """PRD §3.4: "... and the current logical time must not be later than
        `scheduled_return` (`ERR_ROUTE_WINDOW_PASSED`); ..."
        PRD §2.5: "The server maintains a deterministic logical clock. At startup, before
        any operator intervention, the clock reads exactly `2026-08-01T00:00:00Z`; it never
        silently falls back to wall-clock time."

        Design: Corner/validations/dispatch_after_return_window_rejected
        """
        ctx = setup_planned_route_with_stop()
        set_clock("2026-08-11T00:00:00Z")

        res = api.dispatch_route(ctx["route"]["id"], RD)
        validate_error(res, ApiErrorId.ERR_ROUTE_WINDOW_PASSED, expected_status=422)

        fetched = validate_success(api.get_collection_route(ctx["route"]["id"], ANY), 200)
        assert fetched["status"] == "PLANNED"


class TestVehicleDutyAndSanitation:
    def test_finished_vehicle_on_raw_route_rejected(self, api):
        """PRD §3.4: "The vehicle is validated at creation: it must be `SANITIZED`
        (`ERR_VEHICLE_NOT_SANITIZED`), its `duty_class` must be `RAW_MATERIAL` or `DUAL`
        (`ERR_VEHICLE_DUTY_MISMATCH`), and its schedule must be free of conflicts."

        Design: Corner/validations/finished_vehicle_on_raw_route_rejected
        """
        plant = create_plant()
        vehicle_f = create_vehicle(plant["id"], vehicle_tag="V-F", capacity_lbs=40000,
                                   duty_class="FINISHED_PRODUCT")
        res = api.create_collection_route(
            {
                "plant_id": plant["id"],
                "vehicle_id": vehicle_f["id"],
                "route_code": "R1",
                "service_date": "2026-08-10",
                "scheduled_departure": "2026-08-10T06:00:00Z",
                "scheduled_return": "2026-08-10T12:00:00Z",
            },
            RD,
        )
        validate_error(res, ApiErrorId.ERR_VEHICLE_DUTY_MISMATCH, expected_status=409)

        vehicle_d = create_vehicle(plant["id"], vehicle_tag="V-D", capacity_lbs=40000,
                                   duty_class="DUAL")
        ok = validate_success(
            api.create_collection_route(
                {
                    "plant_id": plant["id"],
                    "vehicle_id": vehicle_d["id"],
                    "route_code": "R2",
                    "service_date": "2026-08-10",
                    "scheduled_departure": "2026-08-10T06:00:00Z",
                    "scheduled_return": "2026-08-10T12:00:00Z",
                },
                RD,
            ),
            201,
        )
        assert ok["status"] == "PLANNED"

    def test_vehicle_double_quarantine_rejected(self, api):
        """PRD §3.4: "A `ComplianceOfficer` may quarantine a vehicle from `SANITIZED` or
        `DIRTY` — quarantining an already-`QUARANTINED` vehicle returns
        `ERR_VEHICLE_INVALID_STATE` — and a quarantined vehicle can only be cleared by a
        `DEEP` wash that passes: ..."

        Design: Corner/validations/vehicle_double_quarantine_rejected
        """
        plant = create_plant()
        vehicle = create_vehicle(plant["id"], capacity_lbs=40000, duty_class="DUAL")
        quarantined = validate_success(api.quarantine_vehicle(vehicle["id"], CO), 200)
        assert quarantined["sanitation_status"] == "QUARANTINED"

        res = api.quarantine_vehicle(vehicle["id"], CO)
        validate_error(res, ApiErrorId.ERR_VEHICLE_INVALID_STATE, expected_status=409)

        fetched = validate_success(api.get_vehicle(vehicle["id"], ANY), 200)
        assert fetched["sanitation_status"] == "QUARANTINED"

    def test_quarantined_vehicle_standard_wash_rejected(self, api):
        """PRD §3.4: "a quarantined vehicle can only be cleared by a `DEEP` wash that
        passes: requesting a `STANDARD` wash on a `QUARANTINED` vehicle is rejected with
        `ERR_DEEP_WASH_REQUIRED`, and a failing deep wash leaves the vehicle `QUARANTINED`."

        Design: Corner/validations/quarantined_vehicle_standard_wash_rejected
        """
        plant = create_plant()
        vehicle = create_vehicle(plant["id"], capacity_lbs=40000, duty_class="DUAL")
        validate_success(api.quarantine_vehicle(vehicle["id"], CO), 200)

        res = api.create_wash_ticket(
            vehicle["id"],
            {
                "plant_id": plant["id"],
                "wash_type": "STANDARD",
                "washed_at": "2026-08-05T09:00:00Z",
                "detergent_ppm": 800.0,
                "result": "PASS",
            },
            RD,
        )
        validate_error(res, ApiErrorId.ERR_DEEP_WASH_REQUIRED, expected_status=422)

        # The rejected wash persisted no ticket.
        tickets, meta = validate_paginated(
            api.list_wash_tickets(ANY, params={"vehicle_id": vehicle["id"]})
        )
        assert tickets == []
        assert meta["total_count"] == 0

        # A passing DEEP wash clears the quarantine.
        cleared = validate_success(
            api.create_wash_ticket(
                vehicle["id"],
                {
                    "plant_id": plant["id"],
                    "wash_type": "DEEP",
                    "washed_at": "2026-08-05T10:00:00Z",
                    "detergent_ppm": 1200.0,
                    "result": "PASS",
                },
                RD,
            ),
            201,
        )
        assert_wash_ticket(cleared)
        fetched = validate_success(api.get_vehicle(vehicle["id"], ANY), 200)
        assert fetched["sanitation_status"] == "SANITIZED"


class TestVehicleScheduleOverlap:
    def test_vehicle_adjacent_routes_allowed(self, api):
        """PRD §3.4: "Adjacency is explicitly not a conflict — a new route departing exactly
        when an existing one returns, or returning exactly when an existing one departs, is
        allowed."

        Design: Difficulty/resource_temporal_overlap/vehicle_half_open_adjacency
        """
        plant = create_plant()
        vehicle = create_vehicle(plant["id"])
        route_a = create_route(
            plant["id"], vehicle["id"], route_code="RA",
            scheduled_departure="2026-08-10T08:00:00Z",
            scheduled_return="2026-08-10T12:00:00Z",
        )
        # Adjacent: B departs exactly when A returns (12:00 == 12:00).
        route_b = validate_success(
            api.create_collection_route(
                {
                    "plant_id": plant["id"],
                    "vehicle_id": vehicle["id"],
                    "route_code": "RB",
                    "service_date": "2026-08-10",
                    "scheduled_departure": "2026-08-10T12:00:00Z",
                    "scheduled_return": "2026-08-10T16:00:00Z",
                },
                RD,
            ),
            201,
        )
        assert_route(route_b)
        assert route_b["status"] == "PLANNED"

        routes, meta = validate_paginated(
            api.list_collection_routes(ANY, params={"vehicle_id": vehicle["id"]})
        )
        assert meta["total_count"] == 2

    def test_vehicle_overlapping_route_rejected(self, api):
        """PRD §3.4: "Routes occupy half-open windows: a new route conflicts with an
        existing route of the same vehicle exactly when the existing route is `PLANNED`,
        `DISPATCHED`, or `IN_PROGRESS`, the new route's `scheduled_departure` is earlier
        than the existing route's `scheduled_return`, and the existing route's
        `scheduled_departure` is earlier than the new route's `scheduled_return`."
        PRD §3.4: "A genuine conflict is rejected with `ERR_VEHICLE_SCHEDULE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/vehicle_half_open_adjacency
        """
        plant = create_plant()
        vehicle = create_vehicle(plant["id"])
        create_route(
            plant["id"], vehicle["id"], route_code="RA",
            scheduled_departure="2026-08-10T08:00:00Z",
            scheduled_return="2026-08-10T12:00:00Z",
        )
        # Adjacent route succeeds (half-open semantics)...
        validate_success(
            api.create_collection_route(
                {
                    "plant_id": plant["id"],
                    "vehicle_id": vehicle["id"],
                    "route_code": "RB",
                    "service_date": "2026-08-10",
                    "scheduled_departure": "2026-08-10T12:00:00Z",
                    "scheduled_return": "2026-08-10T16:00:00Z",
                },
                RD,
            ),
            201,
        )
        # ...but an interior overlap with A ([11:00,15:00) vs [08:00,12:00)) is rejected.
        res = api.create_collection_route(
            {
                "plant_id": plant["id"],
                "vehicle_id": vehicle["id"],
                "route_code": "RC",
                "service_date": "2026-08-10",
                "scheduled_departure": "2026-08-10T11:00:00Z",
                "scheduled_return": "2026-08-10T15:00:00Z",
            },
            RD,
        )
        validate_error(res, ApiErrorId.ERR_VEHICLE_SCHEDULE_OVERLAP, expected_status=409)

        routes, meta = validate_paginated(
            api.list_collection_routes(ANY, params={"vehicle_id": vehicle["id"]})
        )
        assert meta["total_count"] == 2


class TestDispatchValidationPriority:
    def _setup_cancelled_route_with_quarantined_vehicle(self, api):
        """Route R2 CANCELLED; its vehicle QUARANTINED — dispatch violates both the
        source-state rule and the sanitation rule."""
        ctx = setup_planned_route_with_stop()
        # Complete R1 (miss the only stop) so the vehicle goes DIRTY, then wash it back.
        validate_success(api.dispatch_route(ctx["route"]["id"], RD), 200)
        validate_success(api.miss_stop(ctx["stop"]["id"], RD), 200)
        validate_success(api.complete_route(ctx["route"]["id"], RD), 200)
        vehicle = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ANY), 200)
        assert vehicle["sanitation_status"] == "DIRTY"
        validate_success(
            api.create_wash_ticket(
                vehicle["id"],
                {
                    "plant_id": ctx["plant"]["id"],
                    "wash_type": "STANDARD",
                    "washed_at": "2026-08-10T19:00:00Z",
                    "detergent_ppm": 800.0,
                    "result": "PASS",
                },
                RD,
            ),
            201,
        )
        # R2 on the next day, one stop, then cancelled.
        route2 = create_route(
            ctx["plant"]["id"], vehicle["id"], route_code="R2",
            service_date="2026-08-11",
            scheduled_departure="2026-08-11T06:00:00Z",
            scheduled_return="2026-08-11T18:00:00Z",
        )
        add_stop(route2["id"], ctx["supplier"]["id"], ctx["agreement"]["id"],
                 ctx["plant"]["id"],
                 scheduled_window_start="2026-08-11T08:00:00Z",
                 scheduled_window_end="2026-08-11T09:00:00Z")
        cancelled = validate_success(api.cancel_route(route2["id"], RD), 200)
        assert cancelled["status"] == "CANCELLED"
        validate_success(api.quarantine_vehicle(vehicle["id"], CO), 200)
        ctx["route2"] = route2
        return ctx

    def test_dispatch_cancelled_route_reports_state_error(self, api):
        """PRD §2.9: "When several validation rules could reject the same request, the
        server evaluates them in a fixed priority order and reports the first failure
        encountered."
        PRD §2.9 item 6: "**Source state.** The target resource must be in a valid
        from-state for the requested transition, otherwise the transition's specific 409:
        ... `ERR_ROUTE_INVALID_STATE`, ..."
        PRD §2.9 item 8: "**Vehicle sanitation and duty.** Dispatch requires a `SANITIZED`
        vehicle of `RAW_MATERIAL` or `DUAL` duty; ..."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_cancelled_route_dirty_vehicle
        """
        ctx = self._setup_cancelled_route_with_quarantined_vehicle(api)
        vehicle = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ANY), 200)
        assert vehicle["sanitation_status"] == "QUARANTINED"

        res = api.dispatch_route(ctx["route2"]["id"], RD)
        # Source state (priority 6) beats vehicle sanitation (priority 8).
        validate_error(res, ApiErrorId.ERR_ROUTE_INVALID_STATE, expected_status=409)

    def test_failed_dispatch_leaves_route_and_vehicle_untouched(self, api):
        """PRD §2.9: "When several validation rules could reject the same request, the
        server evaluates them in a fixed priority order and reports the first failure
        encountered."
        PRD §2.4: "`version` (integer): a system-managed integer that increments by one on
        every mutation of the resource; it anchors the optimistic concurrency checks of
        §2.8."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_cancelled_route_dirty_vehicle
        """
        ctx = self._setup_cancelled_route_with_quarantined_vehicle(api)
        res = api.dispatch_route(ctx["route2"]["id"], RD)
        validate_error(res, ApiErrorId.ERR_ROUTE_INVALID_STATE, expected_status=409)

        route_after = validate_success(
            api.get_collection_route(ctx["route2"]["id"], ANY), 200
        )
        assert route_after["status"] == "CANCELLED"
        vehicle_after = validate_success(api.get_vehicle(ctx["vehicle"]["id"], ANY), 200)
        assert vehicle_after["sanitation_status"] == "QUARANTINED"
