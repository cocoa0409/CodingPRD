"""RBAC enforcement, auth headers, uniqueness, envelope shape."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_aircraft_payload,
    create_firefighter_payload,
    create_profile_payload,
    create_vehicle_payload,
    get_success_data,
    make_firefighter_headers,
    setup_compliant_index_c_airport,
    setup_profile_only,
    validate_error,
    validate_paginated,
    validate_success,
)

AM = TEST_USERS["airport_manager_headers"]
AC = TEST_USERS["arff_chief_headers"]
SO = TEST_USERS["safety_officer_headers"]


class TestMissingAuthHeader:
    def test_missing_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: `X-User-ID` and
        `X-User-Role`. A request missing either header, or whose role value
        does not match one of the declared roles below, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/val_missing_auth_header_returns_unauthenticated
        """
        setup_profile_only()
        # No X-User-ID / X-User-Role headers
        resp = api.get_profile(headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestUniqueness:
    def test_duplicate_call_sign_rejected(self, api):
        """PRD §3.2: "An `ArffChief` builds the fleet one vehicle at a time,
        registering each with a unique `call_sign` (for example, `RED-1`), a
        `water_capacity_gal` strictly greater than zero, and a
        `dry_chem_capacity_lb` greater than or equal to zero. A duplicate
        `call_sign` is rejected with `ERR_DUPLICATE_CALL_SIGN`."

        Design: Corner/validations/val_uniqueness_call_sign_and_employee_no
        """
        setup_profile_only()
        api.create_vehicle(
            create_vehicle_payload(call_sign="RED-1",
                                   water_capacity_gal=2000,
                                   dry_chem_capacity_lb=500),
            AC,
        )
        resp = api.create_vehicle(
            create_vehicle_payload(call_sign="RED-1",
                                   water_capacity_gal=1500,
                                   dry_chem_capacity_lb=300),
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CALL_SIGN)

    def test_duplicate_employee_no_rejected(self, api):
        """PRD §3.4: "A firefighter is added with a unique `employee_no`
        (duplicates rejected with `ERR_DUPLICATE_EMPLOYEE_NO`) and a
        `full_name`."

        Design: Corner/validations/val_uniqueness_call_sign_and_employee_no
        """
        setup_profile_only()
        api.create_firefighter(
            create_firefighter_payload(employee_no="FF-101",
                                       full_name="Ann Lee"),
            AC,
        )
        resp = api.create_firefighter(
            create_firefighter_payload(employee_no="FF-101",
                                       full_name="Other Person"),
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_EMPLOYEE_NO)


class TestEnvelopeShape:
    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body:
        ... `meta`, `response_type` ... `data`"

        Design: Corner/endpoints/ep_response_envelope_success_shape
        """
        setup_profile_only()
        resp = api.create_vehicle(
            create_vehicle_payload(call_sign="RED-1",
                                   water_capacity_gal=2000,
                                   dry_chem_capacity_lb=500),
            AC,
        )
        body = resp.json()
        assert "meta" in body
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert body["response_type"] == "object"
        assert body["data"]["call_sign"] == "RED-1"
        assert "id" in body["data"]

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format: ... `response_type`: "error", `data`:
        `error_id`, `message`"

        Design: Corner/endpoints/ep_error_envelope_shape
        """
        setup_profile_only()
        resp = api.get_vehicle(NON_EXISTENT_UUID, AC)
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_VEHICLE_NOT_FOUND"
        assert "message" in body["data"]
        assert "api_request_id" in body["meta"]


class TestRbacFirefighterCannotCreateVehicle:
    def test_firefighter_role_create_vehicle_denied(self, api):
        """PRD §2.1: "After the headers validate, the role is checked against
        the endpoint's authorization list; a role not permitted for the
        endpoint is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."

        Design: Corner/rbac/rbac_firefighter_cannot_create_vehicle_unauthorized
        """
        setup_profile_only()
        ff = validate_success(
            api.create_firefighter(
                create_firefighter_payload(employee_no="FF-101",
                                           full_name="Ann Lee"),
                AC,
            ),
            expected_status=201,
        )
        resp = api.create_vehicle(
            create_vehicle_payload(call_sign="RED-9",
                                   water_capacity_gal=1000,
                                   dry_chem_capacity_lb=100),
            make_firefighter_headers(ff["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)


class TestRbacFirefighterReadsOwnRecord:
    def test_firefighter_reads_own_record_succeeds(self, api):
        """PRD §2.1: "When `X-User-Role` is `Firefighter`, `X-User-ID` is the
        `id` of the acting `Firefighter` entity; ownership checks on any
        resource that references a `Firefighter` compare the resource's
        foreign-key field to `X-User-ID`. In particular, when a `Firefighter`
        reads their own roster record, the path `id` must equal `X-User-ID`."

        Design: Corner/rbac/rbac_firefighter_reads_own_record
        """
        setup_profile_only()
        ff = validate_success(
            api.create_firefighter(
                create_firefighter_payload(employee_no="FF-101",
                                           full_name="Ann Lee"),
                AC,
            ),
            expected_status=201,
        )
        resp = api.get_firefighter(
            ff["id"], make_firefighter_headers(ff["id"]),
        )
        data = validate_success(resp)
        assert data["full_name"] == "Ann Lee"


class TestSuspendAndTrainingGates:
    def test_double_suspend_rejected(self, api):
        """PRD §3.4: "Suspending an `ACTIVE` firefighter (a suspend on a
        `SUSPENDED` firefighter is rejected with `ERR_INVALID_STATE`)..."

        Design: Corner/errors/err_operations_misc_error_battery
        """
        ctx = setup_compliant_index_c_airport()
        ff = ctx["firefighters"][0]
        api.suspend_firefighter(ff["id"], AC)
        resp = api.suspend_firefighter(ff["id"], AC)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_training_record_for_suspended_firefighter_rejected(self, api):
        """PRD §3.4: "The named firefighter must currently be `ACTIVE`;
        recording training for a `SUSPENDED` firefighter is rejected with
        `ERR_FIREFIGHTER_NOT_ACTIVE`."

        Design: Corner/errors/err_operations_misc_error_battery
        """
        ctx = setup_compliant_index_c_airport()
        ff = ctx["firefighters"][0]
        api.suspend_firefighter(ff["id"], AC)
        resp = api.create_training_record(
            {
                "firefighter_id": ff["id"],
                "completed_on": "2026-05-01",
                "drill_type": "AIRCRAFT",
                "result": "PASS",
            },
            AC,
        )
        validate_error(resp, ApiErrorId.ERR_FIREFIGHTER_NOT_ACTIVE)


class TestRateThresholdBoundary:
    def test_qualifying_threshold_4_99_excluded_5_0_included(self, api):
        """PRD §3.1: "`qualifies_for_index` is `true` exactly when
        `in_scheduled_service` is `true` and `avg_daily_departures` is at
        least `5.0` — the threshold is inclusive, so exactly 5.0 qualifies."

        Design: Corner/cross_cutting_complexity_layers/x_rate_threshold_five_departures_boundary
        """
        setup_profile_only(certificated_index="E")
        r1 = api.create_aircraft(
            create_aircraft_payload(
                model_name="A380", length_ft=238.6,
                avg_daily_departures=4.99, in_scheduled_service=True,
            ),
            AM,
        )
        a = validate_success(r1, expected_status=201)
        r2 = api.create_aircraft(
            create_aircraft_payload(
                model_name="B747-8", length_ft=250.2,
                avg_daily_departures=5.0, in_scheduled_service=True,
            ),
            AM,
        )
        b = validate_success(r2, expected_status=201)
        assert a["qualifies_for_index"] is False
        assert b["qualifies_for_index"] is True
        profile = get_success_data(api.get_profile(AM))
        assert profile["required_index_by_aircraft"] == "E"
