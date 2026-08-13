"""SnowEvent lifecycle machine and the parallel closure-coordination axis."""
from test_helpers import (
    ApiErrorId,
    activate_event,
    closure_action,
    create_ready_equipment,
    create_snow_event,
    create_surface,
    event_action,
    get_surface,
    record_friction_assessment,
    setup_activated_event,
    setup_event_with_surface,
    setup_issued_notam,
    surface_action,
    validate_error,
    validate_success,
)


class TestEventLifecycleGuards:
    def test_event_close_from_forecast_rejected(self, api,
                                                ops_controller_headers):
        """PRD §3.1: "Final closure moves `STANDING_DOWN → CLOSED` and
        requires that no NOTAM on this event has `status` = `ISSUED`".
        PRD §2.9: "State preconditions: the named action is valid for the current
        state of the target entity, and any cross-entity state gates are
        satisfied (else the per-entity state error —
        `ERR_INVALID_EVENT_STATE`, `ERR_EVENT_NOT_ACTIVE`,
        `ERR_INVALID_SURFACE_STATE`, `ERR_INVALID_NOTAM_STATE`,
        `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_SHIFT_STATE`)."

        Design: Corner/state_machines/event_close_from_forecast_rejected
        """
        event = create_snow_event("SNOW-C1")
        resp = api.event_action(event["id"], {"action": "CLOSE"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_STATE, 409)
        data = validate_success(api.get_snow_event(event["id"],
                                                   ops_controller_headers))
        assert data["status"] == "FORECAST"

    def test_event_terminal_lockdown_rejected(self, api,
                                              ops_controller_headers):
        """PRD §3.1: "`CLOSED` is terminal."
        PRD §2.9: "State preconditions: the named action is valid for the current
        state of the target entity, and any cross-entity state gates are
        satisfied (else the per-entity state error —
        `ERR_INVALID_EVENT_STATE`, `ERR_EVENT_NOT_ACTIVE`,
        `ERR_INVALID_SURFACE_STATE`, `ERR_INVALID_NOTAM_STATE`,
        `ERR_INVALID_APPLICATION_STATE`, `ERR_INVALID_SHIFT_STATE`)."

        Design: Corner/state_machines/event_terminal_lockdown_rejected
        """
        ctx = setup_activated_event(event_code="SNOW-C2")
        event_id = ctx["event"]["id"]
        # No surfaces exist, so the all-OPEN stand-down gate holds; no NOTAMs
        # exist, so the close gate holds.
        event_action(event_id, "STAND_DOWN")
        closed = event_action(event_id, "CLOSE")
        assert closed["status"] == "CLOSED"

        resp = api.event_action(event_id, {"action": "ESCALATE"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_STATE, 409)
        data = validate_success(api.get_snow_event(event_id,
                                                   ops_controller_headers))
        assert data["status"] == "CLOSED", (
            "a terminal event must not move regardless of the failed action")

    def test_activate_with_readiness_shortfall_rejected(
            self, api, ops_controller_headers):
        """PRD §3.1: "Activation moves the event `FORECAST → ACTIVATED` and
        requires a fleet readiness floor: at least three `EquipmentUnit` rows
        in `READY` readiness must exist, otherwise the activation is rejected
        with `ERR_EQUIPMENT_READINESS_SHORTFALL`."

        Design: Corner/state_machines/activate_with_readiness_shortfall_rejected
        """
        create_ready_equipment([("PLOW-01", "PLOW", 14500),
                                ("PLOW-02", "PLOW", 14500)])
        event = create_snow_event("SNOW-C3")
        resp = api.event_action(event["id"], {"action": "ACTIVATE"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_EQUIPMENT_READINESS_SHORTFALL, 409)
        data = validate_success(api.get_snow_event(event["id"],
                                                   ops_controller_headers))
        assert data["status"] == "FORECAST"
        assert data.get("activated_at") is None

    def test_activate_side_effect_sets_activated_at(
            self, api, ops_controller_headers):
        """PRD §3.1: "On success, `activated_at` is stamped with the current
        logical clock time and the event's `version` increments."
        PRD §2.5: "The startup default is exactly `2026-08-01T00:00:00Z`; the
        logical clock never falls back to wall-clock time."

        Design: Corner/state_machines/activate_side_effect_sets_activated_at
        """
        create_ready_equipment()
        event = create_snow_event("SNOW-C4")
        resp = api.event_action(event["id"], {"action": "ACTIVATE"},
                                ops_controller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVATED"
        # PRD pins the stamped instant (the logical clock's startup default,
        # §2.5) but not a string serialization for this field, so compare
        # instants rather than exact strings.
        from datetime import datetime, timezone
        stamped = datetime.fromisoformat(
            data["activated_at"].replace("Z", "+00:00"))
        assert stamped == datetime(2026, 8, 1, tzinfo=timezone.utc), (
            f"activated_at must equal the logical clock time, got "
            f"{data['activated_at']}")

    def test_stand_down_blocked_by_uncleared_surface_rejected(
            self, api, ops_controller_headers):
        """PRD §3.1: "Stand-down is initiated from `ACTIVATED` or `ESCALATED`
        and requires every `AirfieldSurface` in the system to be `OPEN`; any
        surface still `RESTRICTED` or `CLOSED` produces
        `ERR_SURFACE_NOT_CLEARED`."

        Design: Corner/state_machines/stand_down_blocked_by_uncleared_surface_rejected
        """
        ctx = setup_event_with_surface(event_code="SNOW-C5")
        surface_action(ctx["surface"]["id"], "RESTRICT", ctx["event"]["id"])
        resp = api.event_action(ctx["event"]["id"], {"action": "STAND_DOWN"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_SURFACE_NOT_CLEARED, 409)
        data = validate_success(api.get_snow_event(ctx["event"]["id"],
                                                   ops_controller_headers))
        assert data["status"] == "ACTIVATED"

    def test_event_close_blocked_by_active_notam_rejected(
            self, api, ops_controller_headers):
        """PRD §3.1: "Final closure moves `STANDING_DOWN → CLOSED` and
        requires that no NOTAM on this event has `status` = `ISSUED`; any
        outstanding issued NOTAM produces `ERR_ACTIVE_NOTAMS_REMAIN`."

        Design: Corner/state_machines/event_close_blocked_by_active_notam_rejected
        """
        ctx = setup_issued_notam(event_code="SNOW-C6")
        event_id = ctx["event"]["id"]
        # Bring the surface back to OPEN so the stand-down gate passes.
        surface_action(ctx["surface"]["id"], "CLEAR", event_id)
        standing = event_action(event_id, "STAND_DOWN")
        assert standing["status"] == "STANDING_DOWN"

        resp = api.event_action(event_id, {"action": "CLOSE"},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_ACTIVE_NOTAMS_REMAIN, 409)
        data = validate_success(api.get_snow_event(event_id,
                                                   ops_controller_headers))
        assert data["status"] == "STANDING_DOWN"


class TestParallelClosureDimension:
    def test_escalate_leaves_closure_status_proposed(
            self, api, ops_controller_headers):
        """PRD §3.2: "The closure dimension runs in parallel with the
        operational status."
        PRD §3.1: "From `ACTIVATED` an `OpsController` may escalate the
        posture (`ACTIVATED → ESCALATED`)".

        Design: Difficulty/non_linear_state_machine/snow_event_parallel_state_dimensions_independent
        """
        ctx = setup_activated_event(event_code="SNOW-E")
        event_id = ctx["event"]["id"]
        proposed = closure_action(event_id, "PROPOSE")
        assert proposed["closure_status"] == "PROPOSED"

        resp = api.event_action(event_id, {"action": "ESCALATE"},
                                ops_controller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ESCALATED"
        assert data["closure_status"] == "PROPOSED", (
            "escalating the storm status must not disturb the parallel "
            f"closure dimension, got {data['closure_status']}")

    def test_de_escalate_leaves_closure_status_proposed(
            self, api, ops_controller_headers):
        """PRD §3.2: "The closure dimension runs in parallel with the
        operational status."
        PRD §3.1: "and later de-escalate (`ESCALATED → ACTIVATED`); each of
        these transitions also increments `version`."

        Design: Difficulty/non_linear_state_machine/snow_event_parallel_state_dimensions_independent
        """
        ctx = setup_activated_event(event_code="SNOW-E")
        event_id = ctx["event"]["id"]
        closure_action(event_id, "PROPOSE")
        event_action(event_id, "ESCALATE")

        resp = api.event_action(event_id, {"action": "DE_ESCALATE"},
                                ops_controller_headers)
        data = validate_success(resp, 200)
        assert data["status"] == "ACTIVATED"
        assert data["closure_status"] == "PROPOSED", (
            "cycling the status axis back must still leave the closure axis "
            f"untouched, got {data['closure_status']}")


class TestClosureRatification:
    def test_ratify_with_runways_open_rejected(self, api,
                                               ops_controller_headers):
        """PRD §3.2: "Ratification by an `OpsController` moves `PROPOSED →
        RATIFIED` but is gated by two checks evaluated in order: first, every
        `AirfieldSurface` whose `surface_type` is `RUNWAY` must have `status`
        = `CLOSED`, otherwise `ERR_RUNWAYS_NOT_CLOSED`".

        Design: Corner/errors/ratify_with_runways_open_rejected
        """
        from test_helpers import make_airline_coordinator_headers
        ctx = setup_event_with_surface(event_code="SNOW-X4")
        event_id = ctx["event"]["id"]
        closure_action(event_id, "PROPOSE")
        acked = closure_action(
            event_id, "ACKNOWLEDGE",
            make_airline_coordinator_headers("al-coord-1"))
        assert acked["airline_acknowledged"] is True

        resp = api.closure_action(event_id, {"action": "RATIFY"},
                                  ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_RUNWAYS_NOT_CLOSED, 409)
        data = validate_success(api.get_snow_event(event_id,
                                                   ops_controller_headers))
        assert data["closure_status"] == "PROPOSED"

    def test_ratify_without_airline_ack_rejected(self, api,
                                                 ops_controller_headers):
        """PRD §3.2: "second, only after the runway check passes,
        `airline_acknowledged` must be `true`, otherwise
        `ERR_AIRLINE_ACK_REQUIRED`."

        Design: Corner/errors/ratify_without_airline_ack_rejected
        """
        ctx = setup_event_with_surface(event_code="SNOW-X5")
        event_id = ctx["event"]["id"]
        surface_action(ctx["surface"]["id"], "CLOSE", event_id)
        closure_action(event_id, "PROPOSE")

        resp = api.closure_action(event_id, {"action": "RATIFY"},
                                  ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_AIRLINE_ACK_REQUIRED, 409)
        data = validate_success(api.get_snow_event(event_id,
                                                   ops_controller_headers))
        assert data["closure_status"] == "PROPOSED"
        assert data["airline_acknowledged"] is False

    def test_closure_ratify_success_path(self, api, ops_controller_headers):
        """PRD §3.2: "Ratification by an `OpsController` moves `PROPOSED →
        RATIFIED` but is gated by two checks evaluated in order: first, every
        `AirfieldSurface` whose `surface_type` is `RUNWAY` must have `status`
        = `CLOSED`, otherwise `ERR_RUNWAYS_NOT_CLOSED`; second, only after the
        runway check passes, `airline_acknowledged` must be `true`, otherwise
        `ERR_AIRLINE_ACK_REQUIRED`."

        Design: Corner/errors/closure_ratify_success_path
        """
        from test_helpers import make_airline_coordinator_headers
        ctx = setup_event_with_surface(event_code="SNOW-X6")
        event_id = ctx["event"]["id"]
        surface_action(ctx["surface"]["id"], "CLOSE", event_id)
        closure_action(event_id, "PROPOSE")
        closure_action(event_id, "ACKNOWLEDGE",
                       make_airline_coordinator_headers("al-coord-1"))

        resp = api.closure_action(event_id, {"action": "RATIFY"},
                                  ops_controller_headers)
        data = validate_success(resp, 200)
        assert data["closure_status"] == "RATIFIED"
