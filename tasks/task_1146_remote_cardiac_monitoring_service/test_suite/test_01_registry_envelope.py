"""Registry input validation, response envelopes, and not-found vocabulary."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_patient,
    create_device_payload,
    create_order_payload,
    create_patient_payload,
    create_physician_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_physician_headers,
    register_device,
    register_patient,
    register_physician,
    validate_error,
    validate_success,
)

COORDINATOR = TEST_USERS["enrollment_coordinator_headers"]
TECHNICIAN = TEST_USERS["monitoring_technician_headers"]


class TestPatientRegistrationValidation:
    def test_patient_create_missing_mrn_rejected(self, api, enrollment_coordinator_headers):
        """PRD §2.8: "required inputs present and enums and ranges valid
        (`prescribed_days` within 5 to 45, `signal_quality` within 0 to 100,
        `limit` within 1 to 100), else `ERR_VALIDATION` (400)."
        PRD §3.1: "The medical record number `mrn` must be unique across all
        patients; a duplicate is rejected with `ERR_DUPLICATE_MRN` (HTTP 409)."

        Design: Corner/entities/patient_create_missing_required_mrn_rejected
        """
        payload = create_patient_payload()
        del payload["mrn"]
        resp = api.create_patient(payload, enrollment_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_patient_create_invalid_insurance_plan_rejected(self, api, enrollment_coordinator_headers):
        """PRD §3.1: "An `EnrollmentCoordinator` registers a patient with a
        `full_name`, a `date_of_birth` in ISO `YYYY-MM-DD` form, a contact
        `phone`, and an `insurance_plan` of `MEDICARE`, `COMMERCIAL`, or
        `SELF_PAY`."
        PRD §2.8: "required inputs present and enums and ranges valid
        (`prescribed_days` within 5 to 45, `signal_quality` within 0 to 100,
        `limit` within 1 to 100), else `ERR_VALIDATION` (400)."

        Design: Corner/entities/patient_create_invalid_enum_rejected
        """
        resp = api.create_patient(
            create_patient_payload(insurance_plan="GOLD"), enrollment_coordinator_headers
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

    def test_patient_create_ignores_client_supplied_id(self, api, enrollment_coordinator_headers):
        """PRD §2.4: "`id` (string): a unique, server-minted identifier
        formatted as a UUID, with no type prefix."
        PRD §2.4: "`version` (integer): starts at 1 at creation and increments
        on every mutation."
        PRD §2.5: "At startup the logical clock reads 2026-05-01T00:00:00Z,
        and it never falls back to wall time."

        Design: Corner/entities/patient_create_extra_id_field_input_ignored
        """
        payload = create_patient_payload()
        payload["id"] = "client-supplied"
        resp = api.create_patient(payload, enrollment_coordinator_headers)
        data = validate_success(resp, 201)
        assert is_valid_uuid(data["id"]), "server must mint a UUID id"
        assert data["id"] != "client-supplied", "client-supplied id must not be adopted"
        assert data["version"] == 1, f"version starts at 1, got {data['version']}"
        assert data["created_at"].startswith("2026-05-01T00:00:00"), (
            f"created_at must be stamped from the logical clock default, got {data['created_at']}"
        )
        assert_patient(data)


class TestUniquenessConflicts:
    def test_patient_duplicate_mrn_conflict(self, api, enrollment_coordinator_headers):
        """PRD §3.1: "The medical record number `mrn` must be unique across all
        patients; a duplicate is rejected with `ERR_DUPLICATE_MRN` (HTTP 409)."

        Design: Corner/entities/patient_duplicate_mrn_conflict
        """
        payload = create_patient_payload(mrn="MRN-2003")
        validate_success(api.create_patient(payload, enrollment_coordinator_headers), 201)
        resp = api.create_patient(
            create_patient_payload(mrn="MRN-2003"), enrollment_coordinator_headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_MRN)

    def test_physician_duplicate_npi_conflict(self, api, platform_admin_headers):
        """PRD §3.1: "A physician record carries `full_name`, `specialty`, and
        an `npi` that must be exactly 10 digits and unique across physicians —
        duplicates are rejected with `ERR_DUPLICATE_NPI` (HTTP 409)."

        Design: Corner/entities/physician_duplicate_npi_conflict
        """
        validate_success(
            api.create_physician(create_physician_payload(npi="2000000001"), platform_admin_headers),
            201,
        )
        resp = api.create_physician(
            create_physician_payload(npi="2000000001"), platform_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_NPI)

    def test_device_duplicate_serial_conflict(self, api, inventory_manager_headers):
        """PRD §3.1: "Each device is enrolled with a manufacturer
        `serial_number`, unique across the fleet (duplicates rejected with
        `ERR_DUPLICATE_SERIAL`, HTTP 409), and a `model` of `HOLTER`, `EVENT`,
        or `IMPLANTABLE`."

        Design: Corner/entities/device_duplicate_serial_conflict
        """
        validate_success(
            api.create_device(create_device_payload(serial_number="EV-2003"), inventory_manager_headers),
            201,
        )
        resp = api.create_device(
            create_device_payload(serial_number="EV-2003", model="EVENT"), inventory_manager_headers
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SERIAL)


class TestResponseEnvelopes:
    def test_success_envelope_shape(self, api, enrollment_coordinator_headers):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body:"
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        resp = api.create_patient(create_patient_payload(), enrollment_coordinator_headers)
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str) and body["meta"]["api_request_id"]
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert is_valid_uuid(body["data"]["id"])

    def test_error_envelope_shape(self, api, enrollment_coordinator_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:"
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/error_envelope_shape
        """
        resp = api.get_episode(NON_EXISTENT_UUID, enrollment_coordinator_headers)
        body = resp.json()
        assert resp.status_code == 404
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_EPISODE_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestNotFoundVocabulary:
    def test_episode_read_not_found(self, api, enrollment_coordinator_headers):
        """PRD §2.9: "The not-found vocabulary is resource-specific: a missing
        patient yields `ERR_PATIENT_NOT_FOUND`, a missing device reference —
        whether in the path or in the request body — yields
        `ERR_DEVICE_NOT_FOUND`, a missing order yields `ERR_ORDER_NOT_FOUND`, a
        missing episode yields `ERR_EPISODE_NOT_FOUND`, and a missing alert
        yields `ERR_ALERT_NOT_FOUND` (all HTTP 404)."

        Design: Corner/entities/episode_read_not_found_returns_404
        """
        resp = api.get_episode(NON_EXISTENT_UUID, enrollment_coordinator_headers)
        validate_error(resp, ApiErrorId.ERR_EPISODE_NOT_FOUND)

    def test_report_read_not_found_generic(self, api, physician_headers):
        """PRD §2.9: "Every other addressed resource — enrollment, physician,
        technician, transmission, notification attempt, report, billing period,
        shipment, or compliance event — falls back to the generic
        `ERR_RESOURCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/report_read_not_found_returns_generic_404
        """
        resp = api.get_report(NON_EXISTENT_UUID, physician_headers)
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    def test_not_found_matrix(self, api):
        """PRD §2.9: "The not-found vocabulary is resource-specific: a missing
        patient yields `ERR_PATIENT_NOT_FOUND`, a missing device reference —
        whether in the path or in the request body — yields
        `ERR_DEVICE_NOT_FOUND`, a missing order yields `ERR_ORDER_NOT_FOUND`, a
        missing episode yields `ERR_EPISODE_NOT_FOUND`, and a missing alert
        yields `ERR_ALERT_NOT_FOUND` (all HTTP 404)."

        Design: Corner/errors/not_found_matrix
        """
        patient = register_patient()
        physician = register_physician()
        device = register_device()
        order = validate_success(
            api.create_order(
                create_order_payload(patient["id"], prescribed_days=7),
                make_physician_headers(physician["id"]),
            ),
            201,
        )

        resp1 = api.create_order(
            create_order_payload(NON_EXISTENT_UUID, prescribed_days=7),
            make_physician_headers(physician["id"]),
        )
        validate_error(resp1, ApiErrorId.ERR_PATIENT_NOT_FOUND)

        resp2 = api.create_enrollment(
            NON_EXISTENT_UUID,
            {"device_id": device["id"], "expected_order_version": order["version"]},
            COORDINATOR,
        )
        validate_error(resp2, ApiErrorId.ERR_ORDER_NOT_FOUND)

        resp3 = api.create_enrollment(
            order["id"],
            {"device_id": NON_EXISTENT_UUID, "expected_order_version": order["version"]},
            COORDINATOR,
        )
        validate_error(resp3, ApiErrorId.ERR_DEVICE_NOT_FOUND)

        resp4 = api.acknowledge_alert(NON_EXISTENT_UUID, TECHNICIAN)
        validate_error(resp4, ApiErrorId.ERR_ALERT_NOT_FOUND)


class TestOrderFieldValidation:
    def test_prescribed_days_out_of_range(self, api):
        """PRD §3.2: "A monitoring engagement starts when a `Physician` creates
        an order naming the `patient_id`, the `monitor_type` (`HOLTER`,
        `EVENT`, or `IMPLANTABLE`), and the `prescribed_days` — the monitoring
        length, which must be at least 5 and at most 45 days, with
        out-of-range values rejected as `ERR_VALIDATION`."

        Design: Corner/validations/prescribed_days_out_of_range_rejected
        """
        patient = register_patient()
        physician = register_physician()
        headers = make_physician_headers(physician["id"])
        for bad_days in (4, 46):
            resp = api.create_order(
                create_order_payload(patient["id"], prescribed_days=bad_days), headers
            )
            validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestAuthentication:
    def test_missing_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or naming a role outside
        this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/patient_create_missing_auth_header_unauthenticated
        """
        resp = api.create_patient(create_patient_payload(), headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unauthenticated_beats_not_found_on_episode_read(self, api):
        """PRD §2.8: "A failure at any rung masks all later rungs: the response
        always carries the highest-priority failure present, never a lower one."
        PRD §2.1: "A request missing either header, or naming a role outside
        this set, is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

        Design: Corner/validations/unauthenticated_beats_not_found_on_episode_read
        """
        resp = api.get_episode(NON_EXISTENT_UUID, headers=None)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
