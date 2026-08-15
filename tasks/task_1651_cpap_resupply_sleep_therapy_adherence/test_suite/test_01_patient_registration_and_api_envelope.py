"""Patient registration, patient reads, and the standard API envelope.

Covers PRD §2.2 (response envelopes), §2.3 (pagination), §2.4 (identity and
versioning), §2.7 (evaluation order), and §3.2 (patient intake).
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_patient,
    create_patient_payload,
    create_payer_policy,
    is_iso8601_timestamp,
    register_patient,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPatientRegistration:
    def test_patient_creation_required_fields(self, api, intake_coordinator_headers):
        """PRD §3.2: "A new patient starts in `INTAKE` status."
        PRD §2.4: "The `version` is an integer that starts at 1 and increments
        by one on every mutation of the resource."

        Design: Corner/entities/patient_creation_required_fields
        """
        policy = create_payer_policy()
        res = api.create_patient(
            create_patient_payload(policy["id"], full_name="New Patient",
                                   date_of_birth="1990-01-01",
                                   prescribing_clinician_npi="1234567890"),
            intake_coordinator_headers)
        patient = validate_success(res, 201)
        assert_patient(patient)
        assert patient["patient_status"] == "INTAKE"
        assert patient["version"] == 1
        assert patient["full_name"] == "New Patient"
        assert patient["payer_policy_id"] == policy["id"]

    def test_patient_creation_missing_required_field_rejected(
            self, api, intake_coordinator_headers):
        """PRD §2.7: "The malformed-body check `ERR_INVALID_REQUEST` (missing
        required fields, invalid types, or invalid enum values) has the lowest
        priority of all and surfaces only when no earlier check has failed."

        Design: Corner/entities/patient_creation_missing_required_field_rejected
        """
        policy = create_payer_policy()
        payload = create_patient_payload(policy["id"])
        del payload["full_name"]
        res = api.create_patient(payload, intake_coordinator_headers)
        validate_error(res, "ERR_INVALID_REQUEST", expected_status=400)

    def test_patient_get_not_found(self, api, ops_admin_headers):
        """PRD §2.7: "First come the two authentication checks — user-context
        headers, then role authorization — followed by existence: path
        parameters are resolved left to right (a failure yields
        `ERR_NOT_FOUND`)"

        Design: Corner/entities/patient_get_not_found
        """
        res = api.get_patient(NON_EXISTENT_UUID, ops_admin_headers)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)

    def test_patient_list_pagination_envelope(self, api, ops_admin_headers):
        """PRD §2.3: "The `meta` object of a list response carries `limit`,
        `offset`, `total_count` (the total number of matching records), and
        `has_more` (whether additional records exist beyond the current page)."

        Design: Corner/entities/patient_list_pagination_envelope
        """
        policy = create_payer_policy()
        register_patient(policy["id"], full_name="P1")
        register_patient(policy["id"], full_name="P2",
                         prescribing_clinician_npi="1234567891")

        data, meta = validate_paginated(
            api.list_patients(ops_admin_headers, params={"limit": 1, "offset": 0}))
        assert meta["total_count"] == 2
        assert len(data) == 1
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["has_more"] is True

        data, meta = validate_paginated(
            api.list_patients(ops_admin_headers, params={"limit": 1, "offset": 1}))
        assert len(data) == 1
        assert meta["has_more"] is False

    def test_patient_computed_fields_present(self, api, ops_admin_headers):
        """PRD §3.2: "`adherence_percentage` and `is_compliance_current`
        reflect the most recent finalized adherence report and stay null/false
        until one exists; `outstanding_balance_cents` aggregates invoiced
        patient responsibility"

        Design: Corner/entities/patient_computed_fields_present
        """
        policy = create_payer_policy()
        patient = register_patient(policy["id"], full_name="Comp")

        fetched = validate_success(api.get_patient(patient["id"], ops_admin_headers))
        assert_patient(fetched)
        assert fetched["adherence_percentage"] is None
        assert fetched["is_compliance_current"] is False
        assert fetched["outstanding_balance_cents"] == 0


class TestApiEnvelope:
    def test_response_envelope_success_shape(self, api, ops_admin_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`." and "The
        `response_type` is either "object" for a single resource or "array"
        for a list of resources."

        Design: Corner/endpoints/response_envelope_success_shape
        """
        policy = create_payer_policy(payer_name="Payer A")
        res = api.get_payer_policy(policy["id"], ops_admin_headers)
        assert res.status_code == 200
        body = res.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"] == policy["id"]
        assert body["data"]["payer_name"] == "Payer A"

    def test_response_envelope_error_shape(self, api, ops_admin_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error." and "The `message` provides a
        human-readable explanation of what went wrong."

        Design: Corner/endpoints/response_envelope_error_shape
        """
        res = api.get_patient(NON_EXISTENT_UUID, ops_admin_headers)
        assert res.status_code == 404
        body = res.json()
        assert body["response_type"] == "error"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
