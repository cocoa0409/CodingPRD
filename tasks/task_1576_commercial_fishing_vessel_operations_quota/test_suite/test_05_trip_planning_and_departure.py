"""Trip planning and departure: opening-state gate, observer-duration boundary,
safety-vs-temporal precedence, gear readiness projection, and creation RBAC
(PRD §3.3, §2.7, §2.8)."""
from test_helpers import (
    TEST_USERS,
    add_gear_asset,
    add_gear_event,
    advance_clock,
    api_client,
    assert_gear_asset,
    create_fishing_trip_payload,
    create_opening,
    get_trip,
    list_trip_assignments,
    make_captain_headers,
    make_vessel_owner_headers,
    plan_trip,
    setup_vessel_ready,
    validate_error,
    validate_success,
)

REG = TEST_USERS["regulator_headers"]


class TestDepartGatedByOpeningState:
    def test_depart_rejected_while_opening_scheduled(self):
        """PRD §3.3: "the season opening must be `OPEN` with the logical clock inside
        the window from `opens_at` through `closes_at` (`ERR_OUTSIDE_OPENING_WINDOW`)".

        Design: Difficulty/cross_entity_state_dependency/depart_gated_by_opening_state
        """
        ctx = setup_vessel_ready()
        opening = create_opening(opens_at="2026-08-05T00:00:00Z")
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-12T06:00:00Z")
        resp = api_client.depart_trip(trip["id"], make_captain_headers(ctx["vessel"]["id"]))
        validate_error(resp, "ERR_OUTSIDE_OPENING_WINDOW", 409)
        assert get_trip(trip["id"])["status"] == "PLANNED"

    def test_depart_succeeds_after_clock_opens_fishery(self):
        """PRD §2.5: "A season opening in `SCHEDULED` moves to `OPEN` once the clock
        reaches its `opens_at` (the opening instant is inclusive)." PRD §3.3: "On
        success the trip moves from `PLANNED` to `DEPARTED`, `actual_departure_utc`
        is stamped from the logical clock".

        Design: Difficulty/cross_entity_state_dependency/depart_gated_by_opening_state
        """
        ctx = setup_vessel_ready()
        opening = create_opening(opens_at="2026-08-05T00:00:00Z")
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-12T06:00:00Z")
        captain = make_captain_headers(ctx["vessel"]["id"])
        validate_error(api_client.depart_trip(trip["id"], captain),
                       "ERR_OUTSIDE_OPENING_WINDOW", 409)
        advance_clock("2026-08-10T06:00:00Z")
        departed = validate_success(api_client.depart_trip(trip["id"], captain), 200)
        assert departed["status"] == "DEPARTED"
        assert departed["actual_departure_utc"].startswith("2026-08-10T06:00")


class TestSafetyBeatsTemporal:
    def test_depart_missing_coverage_beats_window_error(self):
        """PRD §2.7 evaluates "6. **Safety gates** — observer coverage at
        departure, observer debrief at landing verification, gear sufficiency at
        departure, and observer certification level at assignment
        (`ERR_OBSERVER_COVERAGE_MISSING`, `ERR_OBSERVER_NOT_DEBRIEFED`,
        `ERR_GEAR_SHORTAGE` are 409; `ERR_OBSERVER_CERT_INSUFFICIENT` is 422)."
        before "7. **Temporal rules** — opening-window containment, opening
        overlap, vessel trip overlap, and observer double-booking with its rest
        buffer (`ERR_OUTSIDE_OPENING_WINDOW`, `ERR_OPENING_WINDOW_OVERLAP`,
        `ERR_TRIP_WINDOW_OVERLAP`, `ERR_OBSERVER_DOUBLE_BOOKED`; all 409)."

        Design: Difficulty/priority_pair_validation_conflict/depart_safety_beats_temporal
        """
        ctx = setup_vessel_ready()
        opening = create_opening(opens_at="2026-08-05T00:00:00Z")
        # 100-hour trip on a PARTIAL vessel: observer-required, never assigned.
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-14T06:00:00Z")
        assert trip["observer_required"] is True
        resp = api_client.depart_trip(trip["id"], make_captain_headers(ctx["vessel"]["id"]))
        validate_error(resp, "ERR_OBSERVER_COVERAGE_MISSING", 409)

    def test_depart_waived_coverage_surfaces_window_error(self):
        """PRD §3.3: "observer coverage must be satisfied — the trip is not
        observer-required, or the requirement has been waived, or an assignment of
        the trip stands in `CONFIRMED` (`ERR_OBSERVER_COVERAGE_MISSING`)"; with the
        safety gate satisfied by a waiver, the §2.7 priority-7 temporal gate surfaces
        `ERR_OUTSIDE_OPENING_WINDOW` while the opening is still SCHEDULED.

        Design: Difficulty/priority_pair_validation_conflict/depart_safety_beats_temporal
        """
        ctx = setup_vessel_ready()
        opening = create_opening(opens_at="2026-08-05T00:00:00Z")
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-14T06:00:00Z")
        assignment = list_trip_assignments(trip["id"])[0]
        waived = validate_success(
            api_client.waive_observer_assignment(assignment["id"], REG), 200)
        assert waived["status"] == "WAIVED"
        resp = api_client.depart_trip(trip["id"], make_captain_headers(ctx["vessel"]["id"]))
        validate_error(resp, "ERR_OUTSIDE_OPENING_WINDOW", 409)


class TestObserverDurationBoundary:
    def test_exactly_72h_trip_requires_no_observer(self):
        """PRD §2.8: "the 72-hour observer-duration threshold is strict (exactly
        72 hours does not trigger the requirement)"; PRD §3.3:
        "`observer_required` is true when the vessel's `observer_coverage_class`
        is `FULL`, or when the class is `PARTIAL` and the planned trip duration
        is strictly longer than 72 hours; it is false for `EXEMPT` vessels."

        Design: Difficulty/boundary_precision_check/observer_duration_72h_boundary
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T06:00:00Z",
                         return_="2026-08-13T06:00:00Z")  # exactly 72h
        assert trip["observer_required"] is False
        assert list_trip_assignments(trip["id"]) == []

    def test_72h_plus_one_minute_requires_observer(self):
        """PRD §3.3: "When the requirement holds, an observer assignment is
        auto-created in `REQUESTED` status with `auto_created` set to true."

        Design: Difficulty/boundary_precision_check/observer_duration_72h_boundary
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-14T06:00:00Z",
                         return_="2026-08-17T06:01:00Z")  # 72h + 1min
        assert trip["observer_required"] is True
        assignments = list_trip_assignments(trip["id"])
        assert len(assignments) == 1
        assert assignments[0]["status"] == "REQUESTED"
        assert assignments[0]["auto_created"] is True


class TestExemptVessel:
    def test_exempt_vessel_never_requires_observer(self):
        """PRD §3.3: "`observer_required` is true when the vessel's
        `observer_coverage_class` is `FULL`, or when the class is `PARTIAL` and the
        planned trip duration is strictly longer than 72 hours; it is false for
        `EXEMPT` vessels."

        Design: Corner/cross_cutting_layers/exempt_vessel_never_requires_observer
        """
        ctx = setup_vessel_ready(observer_coverage_class="EXEMPT", with_holding=False)
        opening = create_opening()
        advance_clock("2026-08-10T00:00:00Z")
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         departure="2026-08-10T00:00:00Z",
                         return_="2026-08-18T08:00:00Z")  # 200h
        assert trip["observer_required"] is False
        assert list_trip_assignments(trip["id"]) == []
        departed = validate_success(api_client.depart_trip(
            trip["id"], make_captain_headers(ctx["vessel"]["id"])), 200)
        assert departed["status"] == "DEPARTED"


class TestGearReadiness:
    def test_gear_shortage_blocks_depart(self):
        """PRD §3.3: "for every `gear_requirements` entry, the summed
        `units_operational` across the vessel's gear assets of that `gear_type` must
        be at least the required `units` (`ERR_GEAR_SHORTAGE`)".

        Design: Corner/state_machines/gear_shortage_blocks_depart
        """
        ctx = setup_vessel_ready()
        add_gear_asset(ctx["vessel"]["id"], gear_type="LONGLINE", units_total=4)
        opening = create_opening()
        advance_clock("2026-08-10T06:00:00Z")
        trip = plan_trip(ctx["vessel"]["id"], opening["id"],
                         gear_requirements=[{"gear_type": "LONGLINE", "units": 5}])
        resp = api_client.depart_trip(trip["id"], make_captain_headers(ctx["vessel"]["id"]))
        validate_error(resp, "ERR_GEAR_SHORTAGE", 409)
        assert get_trip(trip["id"])["status"] == "PLANNED"

    def test_gear_projection_replay(self):
        """PRD §3.3: "The asset's counters are a projection replayed over its
        events in `occurred_at` ascending order, with ties broken by `created_at`
        ascending: a `LOSS` event adds its units to `units_lost`; a `REPAIR`
        event subtracts its units from `units_lost`, floored at zero; a
        `MAINTENANCE_START` event adds its units to `units_in_maintenance` and is
        legal only if at least that many units are operational, otherwise
        `ERR_INVALID_GEAR_EVENT` (HTTP 422); a `MAINTENANCE_END` event subtracts
        its units from `units_in_maintenance` and is legal only if at least that
        many units are currently in maintenance, otherwise the same
        `ERR_INVALID_GEAR_EVENT`."
        PRD §3.3: "The derived `units_operational` is `units_total` minus
        `units_lost` minus `units_in_maintenance`, and the asset's status is
        `OPERATIONAL` while that figure is greater than zero, otherwise `DOWN` —
        there is no explicit gear state machine, only this projection."

        Design: Corner/calculations/gear_projection_replay
        """
        ctx = setup_vessel_ready(with_holding=False)
        vessel_id = ctx["vessel"]["id"]
        asset = add_gear_asset(vessel_id, gear_type="LONGLINE", units_total=4)
        assert_gear_asset(asset)
        assert asset["units_operational"] == 4

        add_gear_event(asset["id"], vessel_id, event_type="LOSS", units=1,
                       occurred_at="2026-08-02T00:00:00Z")
        assert api_client.get_gear_asset(asset["id"], REG).json()["data"]["units_operational"] == 3

        add_gear_event(asset["id"], vessel_id, event_type="MAINTENANCE_START", units=1,
                       occurred_at="2026-08-03T00:00:00Z")
        assert api_client.get_gear_asset(asset["id"], REG).json()["data"]["units_operational"] == 2

        add_gear_event(asset["id"], vessel_id, event_type="MAINTENANCE_END", units=1,
                       occurred_at="2026-08-04T00:00:00Z")
        assert api_client.get_gear_asset(asset["id"], REG).json()["data"]["units_operational"] == 3

        add_gear_event(asset["id"], vessel_id, event_type="REPAIR", units=1,
                       occurred_at="2026-08-04T01:00:00Z")
        assert api_client.get_gear_asset(asset["id"], REG).json()["data"]["units_operational"] == 4

        add_gear_event(asset["id"], vessel_id, event_type="LOSS", units=2,
                       occurred_at="2026-08-05T00:00:00Z")
        final = api_client.get_gear_asset(asset["id"], REG).json()["data"]
        assert final["units_operational"] == 2
        assert final["status"] == "OPERATIONAL"

    def test_gear_event_illegal_rejected(self):
        """PRD §3.3: "a `MAINTENANCE_START` event adds its units to
        `units_in_maintenance` and is legal only if at least that many units are
        operational, otherwise `ERR_INVALID_GEAR_EVENT` (HTTP 422); a
        `MAINTENANCE_END` event subtracts its units from `units_in_maintenance` and
        is legal only if at least that many units are currently in maintenance,
        otherwise the same `ERR_INVALID_GEAR_EVENT`."

        Design: Corner/errors/gear_event_illegal_rejected
        """
        ctx = setup_vessel_ready(with_holding=False)
        vessel_id = ctx["vessel"]["id"]
        asset = add_gear_asset(vessel_id, gear_type="LONGLINE", units_total=4)
        owner = make_vessel_owner_headers(vessel_id)
        resp = api_client.create_gear_event(
            asset["id"],
            {"event_type": "MAINTENANCE_START", "units": 5,
             "occurred_at": "2026-08-02T00:00:00Z"},
            owner)
        validate_error(resp, "ERR_INVALID_GEAR_EVENT", 422)
        resp2 = api_client.create_gear_event(
            asset["id"],
            {"event_type": "MAINTENANCE_END", "units": 1,
             "occurred_at": "2026-08-02T01:00:00Z"},
            owner)
        validate_error(resp2, "ERR_INVALID_GEAR_EVENT", 422)
        final = api_client.get_gear_asset(asset["id"], REG).json()["data"]
        assert final["units_operational"] == 4
        assert final["units_in_maintenance"] == 0


class TestTripStateGates:
    def test_depart_from_returned_returns_invalid_state(self):
        """PRD §3.3: "The trip must be `PLANNED` (`ERR_TRIP_NOT_PLANNED`)" for
        departure; a RETURNED trip rejects the call.

        Design: Corner/state_machines/depart_from_returned_returns_invalid_state
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        advance_clock("2026-08-10T06:00:00Z")
        trip = plan_trip(ctx["vessel"]["id"], opening["id"])
        captain = make_captain_headers(ctx["vessel"]["id"])
        validate_success(api_client.depart_trip(trip["id"], captain), 200)
        advance_clock("2026-08-12T06:00:00Z")
        validate_success(api_client.return_trip(trip["id"], captain), 200)
        resp = api_client.depart_trip(trip["id"], captain)
        validate_error(resp, "ERR_TRIP_NOT_PLANNED", 409)
        assert get_trip(trip["id"])["status"] == "RETURNED"

    def test_cancel_cancelled_trip_terminal_lockdown(self):
        """PRD §3.3: "A planned trip can be cancelled by the owner or the captain,
        moving `PLANNED` → `CANCELLED`" — from CANCELLED the state gate rejects a
        second cancel with `ERR_TRIP_NOT_PLANNED`.

        Design: Corner/state_machines/cancel_cancelled_trip_terminal_lockdown
        """
        ctx = setup_vessel_ready()
        opening = create_opening()
        trip = plan_trip(ctx["vessel"]["id"], opening["id"])
        owner = make_vessel_owner_headers(ctx["vessel"]["id"])
        cancelled = validate_success(api_client.cancel_trip(trip["id"], owner), 200)
        assert cancelled["status"] == "CANCELLED"
        resp = api_client.cancel_trip(trip["id"], owner)
        validate_error(resp, "ERR_TRIP_NOT_PLANNED", 409)
        assert get_trip(trip["id"])["status"] == "CANCELLED"


class TestTripCreationRbac:
    def test_rbac_regulator_cannot_create_trip(self):
        """PRD §4: POST /fishing-trips lists VesselOwner and Captain only; PRD §2.1:
        "a role that is not listed for the endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)".

        Design: Corner/rbac/rbac_regulator_cannot_create_trip
        """
        ctx = setup_vessel_ready(with_holding=False)
        opening = create_opening()
        resp = api_client.create_fishing_trip(
            create_fishing_trip_payload(
                vessel_id=ctx["vessel"]["id"], season_opening_id=opening["id"]),
            REG)
        validate_error(resp, "ERR_FORBIDDEN_ROLE", 403)

    def test_rbac_owner_of_other_vessel_denied(self):
        """PRD §2.1: "For creation payloads that name a vessel (trip planning,
        expense recording), the caller's `X-User-ID` must equal the `vessel_id` in
        the payload." and "a caller whose role is allowed but whose identity fails
        ownership is rejected with `ERR_NOT_RESOURCE_OWNER` (HTTP 403)."

        Design: Corner/rbac/rbac_owner_of_other_vessel_denied
        """
        ctx_a = setup_vessel_ready(with_holding=False)
        ctx_b = setup_vessel_ready(observer_coverage_class="EXEMPT", with_holding=False)
        opening = create_opening()
        resp = api_client.create_fishing_trip(
            create_fishing_trip_payload(
                vessel_id=ctx_b["vessel"]["id"], season_opening_id=opening["id"]),
            make_vessel_owner_headers(ctx_a["vessel"]["id"]))
        validate_error(resp, "ERR_NOT_RESOURCE_OWNER", 403)
