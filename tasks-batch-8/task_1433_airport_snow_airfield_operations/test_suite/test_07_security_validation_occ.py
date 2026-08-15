"""Authentication/authorization, well-formedness and existence ordering,
temporal validation, and optimistic concurrency on guarded write endpoints."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_condition_report_payload,
    create_friction_assessment_payload,
    create_notam_payload,
    create_snow_event,
    create_snow_event_payload,
    create_surface,
    create_surface_payload,
    create_ready_equipment,
    file_condition_report,
    get_surface_version,
    make_airline_coordinator_headers,
    record_friction_assessment,
    schedule_shift,
    setup_activated_event,
    setup_event_with_surface,
    surface_action,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:
    def test_request_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or carrying a malformed
        header, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/request_missing_auth_headers_unauthenticated
        """
        resp = api.create_snow_event(
            create_snow_event_payload(event_code="SNOW-V1"), headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestRoleDenial:
    def test_coordinator_cannot_file_condition_report(
            self, api, airline_coordinator_headers):
        """PRD §2.1: "A caller whose role is not permitted for the requested
        endpoint — or, on an action endpoint, whose role is not permitted for
        the specific action named in the request — is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."
        PRD §2.1: "`AirfieldInspector` — the airfield safety inspector. Files
        condition reports and friction assessments against surfaces."

        Design: Corner/rbac/coordinator_cannot_file_condition_report
        """
        surface = create_surface("RWY-09L")
        resp = api.create_condition_report(
            create_condition_report_payload(
                NON_EXISTENT_UUID, surface["id"], surface["version"],
                contaminant_type="DRY_SNOW", coverage_pct=40,
                depth_inches=0.2),
            airline_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_ops_controller_cannot_register_equipment(
            self, api, ops_controller_headers):
        """PRD §2.1: "`SystemAdmin` — the platform administrator. Registers
        airfield surfaces, chemical products, and equipment units; drives the
        logical clock." and the caller is rejected per
        PRD §2.1: "A caller whose role is not permitted for the requested endpoint — or, on
        an action endpoint, whose role is not permitted for the specific
        action named in the request — is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/ops_controller_cannot_register_equipment
        """
        resp = api.create_equipment_unit(
            {"unit_code": "PLOW-01", "unit_type": "PLOW",
             "hourly_rate_cents": 14500},
            ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_ops_controller_cannot_acknowledge_closure(
            self, api, ops_controller_headers):
        """PRD §2.1: "For closure actions specifically, `ACKNOWLEDGE` requires
        `AirlineCoordinator` while `PROPOSE` and `RATIFY` require
        `OpsController`; the role check must consider the action value, not
        merely the endpoint."

        Design: Corner/rbac/ops_controller_cannot_acknowledge_closure
        """
        from test_helpers import closure_action
        ctx = setup_activated_event(event_code="SNOW-R1")
        closure_action(ctx["event"]["id"], "PROPOSE")
        resp = api.closure_action(ctx["event"]["id"],
                                  {"action": "ACKNOWLEDGE"},
                                  ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
        data = validate_success(api.get_snow_event(ctx["event"]["id"],
                                                   ops_controller_headers))
        assert data["airline_acknowledged"] is False

    def test_inspector_cannot_drive_surface_actions(
            self, api, airfield_inspector_headers):
        """PRD §2.1: "`OpsController` — the airport operations duty officer.
        Creates snow events, drives the event lifecycle (ACTIVATE,
        ESCALATE, DE_ESCALATE, STAND_DOWN, CLOSE), drives the closure
        dimension (PROPOSE, RATIFY), takes surface status actions
        (RESTRICT, CLOSE, REOPEN, CLEAR), drafts and manages NOTAMs
        (ISSUE, REISSUE, RESCIND), schedules and completes operator
        shifts, and reads the per-event cost summary."
        PRD §2.1: "A caller whose role is not permitted for the requested
        endpoint — or, on an action endpoint, whose role is not permitted
        for the specific action named in the request — is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/inspector_cannot_drive_surface_actions
        """
        surface = create_surface("RWY-09L")
        resp = api.surface_action(
            surface["id"],
            {"action": "RESTRICT", "event_id": NON_EXISTENT_UUID},
            airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_airline_coordinator_can_read_notams(
            self, api, airline_coordinator_headers):
        """PRD §2.1: "`AirlineCoordinator` — the airline station coordination
        liaison. Acknowledges proposed airfield closures and reads events and
        NOTAMs."

        Design: Corner/rbac/airline_coordinator_can_read_notams
        """
        resp = api.list_notams(airline_coordinator_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["response_type"] == "array"


class TestValidationOrdering:
    def test_shape_validation_precedes_existence(
            self, api, airfield_inspector_headers):
        """PRD §2.9: "The order is not stylistic — a caller hitting two
        violations must see the earlier one." and rule 3:
        "Request well-formedness: required fields present, enum membership valid,
        numeric ranges satisfied (`mu_value` between `0.00` and `1.00`
        inclusive; `coverage_pct` between `0` and `100` inclusive;
        `depth_inches` at least `0`; `worked_hours` greater than `0`;
        lengths greater than `0`; `effective_from` strictly before
        `effective_until`; `start_utc` strictly before `end_utc`;
        `observed_at` and `measured_at` not ahead of the logical clock)
        (else `ERR_VALIDATION`)."

        Design: Corner/validations/shape_validation_precedes_existence
        """
        surface = create_surface("RWY-09L")
        resp = api.create_condition_report(
            create_condition_report_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                surface["version"], contaminant_type="ICE",
                coverage_pct=150, depth_inches=0.5),
            airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_existence_left_to_right_event_before_surface(
            self, api, airfield_inspector_headers):
        """PRD §2.7: "Where a request body references foreign keys, body
        references are then resolved **left to right** in the order the fields
        appear in the input contract — `event_id` before `surface_id` before
        `product_id` before `equipment_unit_id`."

        Design: Corner/validations/existence_left_to_right_event_before_surface
        """
        surface = create_surface("RWY-09L")
        resp = api.create_condition_report(
            create_condition_report_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                surface["version"], contaminant_type="ICE",
                coverage_pct=60, depth_inches=0.5),
            airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_EVENT_NOT_FOUND, 404)

    def test_notam_inverted_window_rejected(self, api,
                                            ops_controller_headers):
        """PRD §3.6: "The window is a **closed interval** — both endpoints are
        inclusive — and `effective_from` must be strictly earlier than
        `effective_until`."
        PRD §2.9 rule 3: "Request well-formedness: required fields present, enum
        membership valid, numeric ranges satisfied (`mu_value` between
        `0.00` and `1.00` inclusive; `coverage_pct` between `0` and `100`
        inclusive; `depth_inches` at least `0`; `worked_hours` greater
        than `0`; lengths greater than `0`; `effective_from` strictly
        before `effective_until`; `start_utc` strictly before `end_utc`;
        `observed_at` and `measured_at` not ahead of the logical clock)
        (else `ERR_VALIDATION`)."

        Design: Corner/validations/notam_inverted_window_rejected
        """
        resp = api.create_notam(
            create_notam_payload(
                NON_EXISTENT_UUID, NON_EXISTENT_UUID,
                notam_type="RUNWAY_CLOSURE",
                effective_from="2026-08-11T00:00:00Z",
                effective_until="2026-08-10T00:00:00Z",
                message="inverted"),
            ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_mu_out_of_range_rejected(self, api, airfield_inspector_headers):
        """PRD §2.9 rule 3: "Request well-formedness: required fields present,
        enum membership valid, numeric ranges satisfied (`mu_value`
        between `0.00` and `1.00` inclusive; `coverage_pct` between `0`
        and `100` inclusive; `depth_inches` at least `0`; `worked_hours`
        greater than `0`; lengths greater than `0`; `effective_from`
        strictly before `effective_until`; `start_utc` strictly before
        `end_utc`; `observed_at` and `measured_at` not ahead of the
        logical clock) (else `ERR_VALIDATION`)."
        PRD §3.5: "a `mu_value` between `0.00` and `1.00` at exactly two
        decimal places".

        Design: Corner/validations/mu_out_of_range_rejected
        """
        surface = create_surface("RWY-09L")
        resp = api.create_friction_assessment(
            create_friction_assessment_payload(
                NON_EXISTENT_UUID, surface["id"], surface["version"],
                mu_value=1.5),
            airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)

    def test_shift_complete_with_zero_worked_hours_rejected(
            self, api, ops_controller_headers):
        """PRD §3.9: "Completing a shift (`SCHEDULED → COMPLETED`) requires
        `worked_hours` (strictly greater than zero) in the action payload."
        PRD §2.9 rule 3: "Request well-formedness: required fields present, enum
        membership valid, numeric ranges satisfied (`mu_value` between
        `0.00` and `1.00` inclusive; `coverage_pct` between `0` and `100`
        inclusive; `depth_inches` at least `0`; `worked_hours` greater
        than `0`; lengths greater than `0`; `effective_from` strictly
        before `effective_until`; `start_utc` strictly before `end_utc`;
        `observed_at` and `measured_at` not ahead of the logical clock)
        (else `ERR_VALIDATION`)."

        Design: Corner/validations/shift_complete_with_zero_worked_hours_rejected
        """
        ctx = setup_activated_event(event_code="SNOW-V2")
        shift = schedule_shift(ctx["event"]["id"], operator_code="OP-W")
        resp = api.shift_action(shift["id"],
                                {"action": "COMPLETE", "worked_hours": 0},
                                ops_controller_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)
        data = validate_success(api.get_operator_shift(shift["id"],
                                                       ops_controller_headers))
        assert data["status"] == "SCHEDULED"

    def test_report_observed_after_logical_clock_rejected(
            self, api, airfield_inspector_headers):
        """PRD §2.5: "Observation-time checks on `observed_at` (condition
        reports) and `measured_at` (friction assessments) compare against this
        logical clock: values strictly greater than the current logical clock
        are rejected." and "The startup default is exactly
        `2026-08-01T00:00:00Z`; the logical clock never falls back to
        wall-clock time."

        Design: Corner/validations/report_observed_after_logical_clock_rejected
        """
        ctx = setup_event_with_surface(event_code="SNOW-V3")
        resp = api.create_condition_report(
            create_condition_report_payload(
                ctx["event"]["id"], ctx["surface"]["id"],
                ctx["surface"]["version"], contaminant_type="DRY_SNOW",
                coverage_pct=40, depth_inches=0.2,
                observed_at="2026-09-01T00:00:00Z"),
            airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION, 400)


class TestOptimisticConcurrency:
    def test_occ_stale_version_on_report_create_rejected(
            self, api, airfield_inspector_headers,
            ops_controller_headers):
        """PRD §2.6: "If the surface's current `version` has advanced since
        the client last read it — for example because another writer filed a
        report or took a surface action — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from overwriting
        a surface state it has not observed."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_report_create_rejected
        """
        ctx = setup_event_with_surface(event_code="SNOW-L1")
        event_id = ctx["event"]["id"]
        surface_id = ctx["surface"]["id"]
        stale_version = ctx["surface"]["version"]  # 1 at registration
        r1 = file_condition_report(event_id, surface_id,
                                   expected_surface_version=stale_version,
                                   contaminant_type="DRY_SNOW",
                                   coverage_pct=40, depth_inches=0.2)

        resp = api.create_condition_report(
            create_condition_report_payload(
                event_id, surface_id, stale_version,
                contaminant_type="ICE", coverage_pct=60, depth_inches=0.5),
            airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
        data = validate_success(api.get_condition_report(
            r1["id"], ops_controller_headers))
        assert data["status"] == "FILED", (
            "the stale write must not supersede the filed report")

    def test_occ_stale_version_on_friction_create_rejected(
            self, api, airfield_inspector_headers):
        """PRD §2.6: "If the surface's current `version` has advanced since
        the client last read it — for example because another writer filed a
        report or took a surface action — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)". and "Both requests must carry
        `expected_surface_version` holding the `version` of the target
        `AirfieldSurface` as the client last observed it."

        Design: Corner/cross_cutting_layers/occ_stale_version_on_friction_create_rejected
        """
        ctx = setup_event_with_surface(event_code="SNOW-L2")
        event_id = ctx["event"]["id"]
        surface_id = ctx["surface"]["id"]
        stale_version = ctx["surface"]["version"]  # 1 at registration
        restricted = surface_action(surface_id, "RESTRICT", event_id)

        resp = api.create_friction_assessment(
            create_friction_assessment_payload(
                event_id, surface_id, stale_version, mu_value=0.60),
            airfield_inspector_headers)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)

        resp2 = api.create_friction_assessment(
            create_friction_assessment_payload(
                event_id, surface_id, restricted["version"], mu_value=0.60),
            airfield_inspector_headers)
        data = validate_success(resp2, 201)
        assert data["status"] == "REPORTED", (
            "the same payload with the current version succeeds")
