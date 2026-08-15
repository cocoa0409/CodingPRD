"""Authentication and role-based access control, the response envelope,
the 404 error family, pagination, list filtering, and computed reads."""
import pytest

from test_helpers import (
    ApiErrorId,
    UNKNOWN_UUID,
    create_drone_payload,
    create_show_event_payload,
    create_site,
    create_site_payload,
    create_weather_reading_payload,
    is_iso8601_timestamp,
    register_drone,
    set_clock,
    setup_authorized_show,
    create_authorization,
    submit_authorization,
    create_show,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS, make_safety_officer_headers

PLANNER = TEST_USERS["planner_headers"]
AUTHORITY = TEST_USERS["authority_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]
OPS = TEST_USERS["ops_admin_headers"]


class TestAuthentication:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD: "A request that arrives without these headers, or whose
        `X-User-Role` value is not one of the five declared roles, is rejected
        with `ERR_UNAUTHENTICATED`."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        resp = api.create_site(create_site_payload(name="NoAuth Site"), {})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestRolePermissions:
    def test_production_planner_cannot_decide_authorization(self, api):
        """PRD: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD section 4: "| POST | `/api/airspace-authorizations/{authorizationId}/decide` | UNDER_REVIEW to APPROVED or DENIED; approval re-validates | AuthorityOfficer |"

        Design: Corner/rbac/production_planner_cannot_decide_authorization
        """
        site = create_site()
        set_clock()
        show = create_show(site["id"])
        auth = create_authorization(show["id"])
        submit_authorization(auth["id"])

        resp = api.decide_authorization(auth["id"], {"decision": "APPROVED"},
                                        PLANNER)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        after = validate_success(api.get_authorization(auth["id"], AUTHORITY))
        assert after["status"] == "UNDER_REVIEW", "the forbidden decide is a no-op"

    def test_fleet_manager_cannot_create_show_event(self, api):
        """PRD: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD section 4: "| POST | `/api/show-events` | Create a show (pricing computed; PLANNING / DEPOSIT_DUE) | ProductionPlanner |"

        Design: Corner/rbac/fleet_manager_cannot_create_show_event
        """
        site = create_site()
        set_clock()
        resp = api.create_show_event(
            create_show_event_payload(site["id"], name="Forbidden Show"), FLEET)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_safety_officer_cannot_register_drone(self, api):
        """PRD: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD section 4: "| POST | `/api/drones` | Register a drone (AVAILABLE) | FleetManager |"

        Design: Corner/rbac/safety_officer_cannot_register_drone
        """
        resp = api.create_drone(create_drone_payload("SN-NOPE"),
                                make_safety_officer_headers("so-1"))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_authority_officer_cannot_record_weather(self, api):
        """PRD: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD section 4: "| POST | `/api/weather-readings` | Record a weather observation (immutable) | SafetyOfficer |"

        Design: Corner/rbac/authority_officer_cannot_record_weather
        """
        site = create_site()
        set_clock()
        resp = api.create_weather_reading(
            create_weather_reading_payload(site["id"],
                                           recorded_at="2026-07-31T23:00:00Z"),
            AUTHORITY)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_ops_admin_cannot_file_incident(self, api):
        """PRD: "A request whose role is recognized but not permitted on the
        target endpoint is rejected with `ERR_FORBIDDEN`."
        PRD: "When several validations could reject the same request, they are
        evaluated in a fixed priority order, and the first failing check
        produces the response." — role permission (item 3) precedes existence
        (item 4), so the bogus show id is never consulted.
        PRD section 4: "| POST | `/api/incident-reports` | File an incident against an EXECUTED show; MAJOR requires a drone | SafetyOfficer |"

        Design: Corner/rbac/ops_admin_cannot_file_incident
        """
        resp = api.create_incident_report(
            {"show_event_id": UNKNOWN_UUID, "severity": "MINOR",
             "description": "x"}, OPS)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestNotFoundFamily:
    @pytest.mark.parametrize("path,error_id", [
        ("/api/sites/{}", ApiErrorId.ERR_SITE_NOT_FOUND),
        ("/api/show-events/{}", ApiErrorId.ERR_SHOW_NOT_FOUND),
        ("/api/airspace-authorizations/{}", ApiErrorId.ERR_AUTHORIZATION_NOT_FOUND),
        ("/api/show-designs/{}", ApiErrorId.ERR_DESIGN_NOT_FOUND),
        ("/api/simulation-runs/{}", ApiErrorId.ERR_SIMULATION_RUN_NOT_FOUND),
        ("/api/safety-configurations/{}", ApiErrorId.ERR_SAFETY_CONFIG_NOT_FOUND),
        ("/api/drones/{}", ApiErrorId.ERR_DRONE_NOT_FOUND),
        ("/api/charge-bays/{}", ApiErrorId.ERR_CHARGE_BAY_NOT_FOUND),
        ("/api/charge-sessions/{}", ApiErrorId.ERR_CHARGE_SESSION_NOT_FOUND),
        ("/api/launch-grid-assignments/{}", ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
        ("/api/weather-readings/{}", ApiErrorId.ERR_WEATHER_READING_NOT_FOUND),
        ("/api/go-no-go-evaluations/{}", ApiErrorId.ERR_EVALUATION_NOT_FOUND),
        ("/api/incident-reports/{}", ApiErrorId.ERR_INCIDENT_NOT_FOUND),
        ("/api/flight-logs/{}", ApiErrorId.ERR_FLIGHT_LOG_NOT_FOUND),
    ], ids=["site", "show", "authorization", "design", "simulation_run",
            "safety_config", "drone", "charge_bay", "charge_session",
            "assignment", "weather_reading", "evaluation", "incident",
            "flight_log"])
    def test_unknown_id_returns_resource_specific_404(self, api, path, error_id):
        """PRD: "Path identifiers — `siteId`, `showEventId`,
        `authorizationId`, `designId`, `simulationRunId`, `configId`,
        `droneId`, `chargeBayId`, `chargeSessionId`, `assignmentId`,
        `weatherReadingId`, `evaluationId`, `incidentId`, and `flightLogId` —
        are validated first, in left-to-right order as they appear in the path;
        the first identifier that does not resolve produces the corresponding
        404 error and no further validation runs." and "The 404 family is keyed
        per resource type: `ERR_SITE_NOT_FOUND`, `ERR_SHOW_NOT_FOUND`,
        `ERR_AUTHORIZATION_NOT_FOUND`, `ERR_DESIGN_NOT_FOUND`,
        `ERR_SIMULATION_RUN_NOT_FOUND`, `ERR_SAFETY_CONFIG_NOT_FOUND`,
        `ERR_DRONE_NOT_FOUND`, `ERR_CHARGE_BAY_NOT_FOUND`,
        `ERR_CHARGE_SESSION_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`,
        `ERR_WEATHER_READING_NOT_FOUND`, `ERR_EVALUATION_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, and `ERR_FLIGHT_LOG_NOT_FOUND`."

        Design: Corner/errors/not_found_sweep_all_resources
        """
        resp = api.get(path.format(UNKNOWN_UUID), headers=PLANNER)
        validate_error(resp, error_id, expected_status=404)


class TestResponseEnvelope:
    def test_envelope_shape_on_success_and_error(self, api):
        """PRD: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/errors/response_envelope_shape_on_success_and_error
        """
        drone = register_drone(serial_number="SN-ENV")
        resp = api.get_drone(drone["id"], OPS)
        body = resp.json()
        assert resp.status_code == 200
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["serial_number"] == "SN-ENV"

        resp = api.get_drone(UNKNOWN_UUID, OPS)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_DRONE_NOT_FOUND"
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0


class TestListEndpoints:
    def test_drones_pagination_defaults_and_limit_bounds(self, api):
        """PRD: "The `limit` parameter caps the number of items returned: it
        defaults to 10, accepts a minimum of 1, and accepts a maximum of 100.
        The `offset` parameter controls how many items are skipped and defaults
        to 0. A `limit` outside the 1-to-100 range, or a negative `offset`, is a
        request-body-level validation failure rejected with `ERR_VALIDATION`."
        PRD: "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the response envelope."

        Design: Corner/endpoints/drones_pagination_defaults_and_limit_bounds
        """
        for i in range(12):
            register_drone(serial_number=f"SN-P{i + 1:02d}")

        resp = api.list_drones(FLEET)
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert len(data) == 10, "default page caps at 10 rows"
        assert meta["limit"] == 10 and meta["offset"] == 0
        assert meta["total_count"] == 12 and meta["has_more"] is True

        data, meta = validate_paginated(
            api.list_drones(FLEET, params={"limit": 2, "offset": 10}))
        assert len(data) == 2
        assert meta["total_count"] == 12 and meta["has_more"] is False

        validate_error(api.list_drones(FLEET, params={"limit": 0}),
                       ApiErrorId.ERR_VALIDATION)
        validate_error(api.list_drones(FLEET, params={"limit": 101}),
                       ApiErrorId.ERR_VALIDATION)

    def test_drones_filtered_by_status(self, api):
        """PRD section 4: "| GET | `/api/drones` | List drones (filterable by `status`; paginated) | All roles |"

        Design: Corner/endpoints/drones_filtered_by_status
        """
        register_drone(serial_number="SN-F1")
        register_drone(serial_number="SN-F2")
        d3 = register_drone(serial_number="SN-F3")
        resp_ground = api.ground_drone(d3["id"], make_safety_officer_headers("so-1"))
        assert resp_ground.status_code == 200

        data, meta = validate_paginated(
            api.list_drones(PLANNER, params={"status": "GROUNDED"}))
        assert meta["total_count"] == 1
        assert data[0]["serial_number"] == "SN-F3"

        _, meta = validate_paginated(
            api.list_drones(PLANNER, params={"status": "AVAILABLE"}))
        assert meta["total_count"] == 2


class TestReadinessRead:
    def test_readiness_gate_breakdown_computed_read(self, api):
        """PRD: "The readiness computed read reports `posture`, the per-gate
        breakdown `gates` in the fixed order g1 through g6, the current
        `assigned_count`, and `required_drone_count` — the pinned design's
        `drone_count`, or null when no design is pinned."
        PRD: "The posture is `GO` when all six gates hold, `CLEARED` when g1
        through g5 hold, and `NOT_READY` otherwise."

        Design: Corner/endpoints/readiness_gate_breakdown_computed_read
        """
        ctx = setup_authorized_show(
            show_overrides={"drone_count_planned": 2},
            design_overrides={"drone_count": 2})
        readiness = validate_success(api.get_readiness(ctx["show"]["id"], FLEET))
        assert readiness["posture"] == "NOT_READY"
        assert readiness["assigned_count"] == 0
        assert readiness["required_drone_count"] == 2

        gates = readiness["gates"]
        if isinstance(gates, dict):
            try:
                values = [gates[k] for k in ("g1", "g2", "g3", "g4", "g5", "g6")]
            except KeyError:
                values = list(gates.values())
        else:
            values = list(gates)
        # g1 design+sim, g2 config, g3 authorization, g4 perimeter hold;
        # g5 (grid incomplete) and g6 (no certified GO) fail.
        assert values == [True, True, True, True, False, False], \
            f"gates g1..g6 in fixed order, got {values}"
