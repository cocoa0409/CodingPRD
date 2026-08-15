"""Incidents: automatic trips, dispatch cascade, plant posture, closure
rules, terminal lockdown, and the boiler reset gates."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_boiler,
    create_dispatch,
    create_incident_payload,
    create_online_boiler,
    create_plant,
    get_boiler,
    get_plant,
    make_operator_headers,
    record_outcome,
    schedule_inspection,
    set_clock,
    setup_plant_with_operators,
    trip_boiler_via_incident,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestIncidentTripCascade:
    def test_incident_to_lag_dispatch_depth3(self, api, plant_manager_headers):
        """PRD §3.9: "A qualifying incident trips its boiler automatically:
        when `severity` is `HIGH` or `CRITICAL`, `kind` is one of
        `OVERPRESSURE`, `LOW_WATER`, `FLAME_FAILURE`, or `RELIEF_VALVE_LIFT`,
        and `triggered_boiler_id` names a boiler, that boiler moves to
        `TRIPPED` from wherever it stands". "Depth two: every `SCHEDULED`
        dispatch window that contains the tripped boiler and whose
        `window_start_at` lies after the current moment is `CANCELLED`."
        "Depth one: if the tripped boiler was the lead, `lead_boiler_id` is
        recomputed and may go null, and the plant `posture` becomes `DEGRADED`
        if at least one boiler remains `ONLINE`, otherwise `EMERGENCY`."

        Design: Difficulty/transitive_cascade/incident_to_lag_dispatch_depth3
        """
        set_clock("2026-08-05T00:00:00Z")
        plant, ops = setup_plant_with_operators(name="Casc Plant", count=1)
        op = ops[0]
        b1 = create_online_boiler(
            plant["id"], op["id"], tag="B-1", rated_capacity_lb_hr=60000
        )
        b2 = create_online_boiler(
            plant["id"], op["id"], tag="B-2", rated_capacity_lb_hr=50000
        )
        assert get_plant(plant["id"])["lead_boiler_id"] == b1["id"]
        dispatch = create_dispatch(
            plant["id"], [b1["id"], b2["id"]],
            window_start_at="2026-08-10T00:00:00Z",
            window_end_at="2026-08-10T08:00:00Z",
            target_steam_lb_hr=50000,
        )

        trip_boiler_via_incident(
            plant["id"], b1["id"], op["id"],
            severity="HIGH", kind="FLAME_FAILURE",
            raised_at="2026-08-05T12:00:00Z",
        )

        assert get_boiler(plant["id"], b1["id"])["ops_status"] == "TRIPPED"
        cancelled = validate_success(
            api.get_load_dispatch(plant["id"], dispatch["id"], plant_manager_headers)
        )
        assert cancelled["status"] == "CANCELLED"
        plant_state = get_plant(plant["id"])
        assert plant_state["lead_boiler_id"] == b2["id"]
        assert plant_state["posture"] == "DEGRADED"

        # Depth three re-evaluation only auto-creates a replacement when a
        # window becomes active-eligible within fifteen minutes; this window
        # is days out, so no replacement is created.
        dispatches, meta = validate_paginated(
            api.list_load_dispatches(plant["id"], plant_manager_headers)
        )
        assert meta["total_count"] == 1

    def test_trip_with_no_remaining_online_boiler_is_emergency(
        self, api, plant_manager_headers
    ):
        """PRD §3.9: "the plant `posture` becomes `DEGRADED` if at least one
        boiler remains `ONLINE`, otherwise `EMERGENCY`." PRD §3.4: "When no
        boiler is eligible, `lead_boiler_id` becomes null."

        Design: Difficulty/transitive_cascade/incident_to_lag_dispatch_depth3
        """
        plant, ops = setup_plant_with_operators(name="Em2 Plant", count=1)
        op = ops[0]
        boiler = create_online_boiler(plant["id"], op["id"], tag="B-E1")
        assert get_plant(plant["id"])["lead_boiler_id"] == boiler["id"]

        trip_boiler_via_incident(plant["id"], boiler["id"], op["id"])

        plant_state = get_plant(plant["id"])
        assert plant_state["posture"] == "EMERGENCY"
        assert plant_state["lead_boiler_id"] is None
        assert get_boiler(plant["id"], boiler["id"])["ops_status"] == "TRIPPED"


class TestBoilerResetGates:
    def _suspended_tripped_boiler(self, api, plant, op):
        """ONLINE boiler -> explicit FAILED pop test -> SUSPENDED + TRIPPED,
        plus a mitigated HIGH incident so the unresolved-incident gate is not
        what fires."""
        boiler = create_online_boiler(plant["id"], op["id"], tag="B-X2")
        pop = schedule_inspection(
            plant["id"], boiler["id"], inspection_kind="RELIEF_VALVE_POP",
            scheduled_on="2026-08-06T08:00:00Z",
        )
        record_outcome(plant["id"], boiler["id"], pop["id"], "FAILED")
        headers = make_operator_headers(op["id"])
        incident = trip_boiler_via_incident(
            plant["id"], boiler["id"], op["id"],
            severity="HIGH", kind="RELIEF_VALVE_LIFT",
            raised_at="2026-08-06T09:00:00Z",
        )
        validate_success(api.acknowledge_incident(plant["id"], incident["id"], headers))
        validate_success(api.mitigate_incident(plant["id"], incident["id"], headers))
        return boiler

    def test_reset_blocked_without_post_incident_pass(
        self, api, plant_manager_headers
    ):
        """PRD §3.4: "if the boiler's `cert_status` is `SUSPENDED`, a
        `POST_INCIDENT` inspection with `outcome` `PASSED` recorded after the
        boiler's most recent trip must exist (else
        `ERR_REINSPECTION_REQUIRED`)".

        Design: Difficulty/cross_entity_state_dependency/inspection_outcome_gates_boiler_reset
        """
        plant, ops = setup_plant_with_operators(name="XD2 Plant", count=1)
        op = ops[0]
        boiler = self._suspended_tripped_boiler(api, plant, op)

        resp = api.reset_boiler(
            plant["id"], boiler["id"], make_operator_headers(op["id"])
        )
        validate_error(resp, ApiErrorId.ERR_REINSPECTION_REQUIRED)
        state = get_boiler(plant["id"], boiler["id"])
        assert state["ops_status"] == "TRIPPED"
        assert state["cert_status"] == "SUSPENDED"

    def test_reset_blocked_by_unresolved_high_incident(
        self, api, plant_manager_headers
    ):
        """PRD §3.4: "every incident naming this boiler in
        `triggered_boiler_id` at `severity` `HIGH` or `CRITICAL` must already
        be `MITIGATED` or `CLOSED` (else `ERR_INCIDENT_UNRESOLVED`)".

        Design: Difficulty/cross_entity_state_dependency/inspection_outcome_gates_boiler_reset
        """
        plant, ops = setup_plant_with_operators(name="XD3 Plant", count=1)
        op = ops[0]
        boiler = create_online_boiler(plant["id"], op["id"], tag="B-X3")
        trip_boiler_via_incident(plant["id"], boiler["id"], op["id"])
        assert get_boiler(plant["id"], boiler["id"])["cert_status"] == "VALID"

        resp = api.reset_boiler(
            plant["id"], boiler["id"], make_operator_headers(op["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INCIDENT_UNRESOLVED)
        assert get_boiler(plant["id"], boiler["id"])["ops_status"] == "TRIPPED"

    def test_reset_succeeds_after_mitigation_when_cert_valid(
        self, api, plant_manager_headers
    ):
        """PRD §3.9: "if the incident names a `triggered_boiler_id` and no
        other `OPEN` or `ACKNOWLEDGED` incident at `HIGH` or `CRITICAL`
        severity remains against that boiler, the boiler becomes eligible for
        the reset described in §3.4". PRD §3.4: "Resetting a tripped boiler —
        `TRIPPED` to `STANDBY`, performed by an `Operator`".

        Design: Difficulty/cross_entity_state_dependency/inspection_outcome_gates_boiler_reset
        """
        plant, ops = setup_plant_with_operators(name="XD4 Plant", count=1)
        op = ops[0]
        boiler = create_online_boiler(plant["id"], op["id"], tag="B-X4")
        headers = make_operator_headers(op["id"])
        incident = trip_boiler_via_incident(plant["id"], boiler["id"], op["id"])
        validate_success(api.acknowledge_incident(plant["id"], incident["id"], headers))
        validate_success(api.mitigate_incident(plant["id"], incident["id"], headers))

        resp = api.reset_boiler(plant["id"], boiler["id"], headers)
        reset = validate_success(resp, expected_status=200)
        assert reset["ops_status"] == "STANDBY"


class TestIncidentClosure:
    def test_incident_terminal_state_lockdown(self, api, plant_manager_headers):
        """PRD §3.9: "A `MITIGATED` incident of any severity closes to the
        terminal `CLOSED` state." PRD §2.7: "State — the target resource is in
        a valid from-state for the requested transition; otherwise
        `ERR_INVALID_STATE` (409)." Acknowledge is only defined on an `OPEN`
        incident ("An `Operator` with an `ACTIVE` license acknowledges an
        `OPEN` incident, moving it to `ACKNOWLEDGED`").

        Design: Corner/state_machines/incident_terminal_state_lockdown
        """
        plant, ops = setup_plant_with_operators(name="Term Plant", count=1)
        op = ops[0]
        resp = api.create_incident(
            plant["id"],
            create_incident_payload(
                raised_by_operator_id=op["id"], severity="LOW", kind="OTHER"
            ),
            make_operator_headers(op["id"]),
        )
        incident = validate_success(resp, expected_status=201)
        closed = validate_success(
            api.close_incident(
                plant["id"], incident["id"], "trivial", plant_manager_headers
            )
        )
        assert closed["status"] == "CLOSED"

        resp = api.acknowledge_incident(
            plant["id"], incident["id"], make_operator_headers(op["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
        reread = validate_success(
            api.get_incident(plant["id"], incident["id"], plant_manager_headers)
        )
        assert reread["status"] == "CLOSED"

    @pytest.mark.parametrize("notes_payload", ["empty_string", "missing_field"])
    def test_err_resolution_notes_required_on_close(
        self, api, plant_manager_headers, notes_payload
    ):
        """PRD §3.9: "Closure belongs to the `PlantManager` and always
        requires non-empty `resolution_notes`, else
        `ERR_RESOLUTION_NOTES_REQUIRED`."

        Design: Corner/errors/err_resolution_notes_required_on_close
        """
        plant, ops = setup_plant_with_operators(name="RN Plant", count=1)
        op = ops[0]
        resp = api.create_incident(
            plant["id"],
            create_incident_payload(
                raised_by_operator_id=op["id"], severity="LOW", kind="OTHER"
            ),
            make_operator_headers(op["id"]),
        )
        incident = validate_success(resp, expected_status=201)

        notes = "" if notes_payload == "empty_string" else None
        resp = api.close_incident(
            plant["id"], incident["id"], notes, plant_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_RESOLUTION_NOTES_REQUIRED)

    def test_err_incident_not_closable_high_severity_direct_close(
        self, api, plant_manager_headers
    ):
        """PRD §3.9: "An incident still `OPEN` may close directly only when
        its `severity` is `LOW`; a `HIGH` or `CRITICAL` incident must traverse
        `ACKNOWLEDGED` and then `MITIGATED` first, and a direct-close attempt
        is refused with `ERR_INCIDENT_NOT_CLOSABLE`."

        Design: Corner/errors/err_incident_not_closable_high_severity_direct_close
        """
        plant, ops = setup_plant_with_operators(name="NC Plant", count=1)
        op = ops[0]
        boiler = create_boiler(plant["id"], tag="B-NC")
        resp = api.create_incident(
            plant["id"],
            create_incident_payload(
                raised_by_operator_id=op["id"], severity="HIGH",
                kind="FLAME_FAILURE", triggered_boiler_id=boiler["id"],
            ),
            make_operator_headers(op["id"]),
        )
        incident = validate_success(resp, expected_status=201)
        assert incident["status"] == "OPEN"

        resp = api.close_incident(
            plant["id"], incident["id"], "skip", plant_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_INCIDENT_NOT_CLOSABLE,
                       expected_status=409)
