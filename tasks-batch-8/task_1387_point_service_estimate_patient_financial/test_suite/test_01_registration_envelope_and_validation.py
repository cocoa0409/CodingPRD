"""Registration, response envelope, and base request-validation claims."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_patient,
    create_charge_item_payload,
    create_patient_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_success,
)


class TestPatientRegistration:
    def test_patient_create_returns_201_with_startup_clock_defaults(self, api, registrar_headers):
        """PRD §2.4: "All "current time" semantics come from a **logical clock**
        whose startup default, before anyone has set it, is exactly
        `2026-08-01T00:00:00Z`."
        PRD §2.5: "`version` (integer): starts at 1 at creation and increments
        by exactly 1 on every mutation, again including cascade-driven mutations."

        Design: Corner/entities/patient_create_returns_201_with_system_defaults
        """
        res = api.create_patient(
            create_patient_payload(mrn="MRN-E-1", full_name="Pat Entity",
                                   date_of_birth="1990-01-01"),
            registrar_headers)
        patient = validate_success(res, 201)
        assert_patient(patient)
        assert is_valid_uuid(patient["id"]), "id is a server-minted UUID"
        assert patient["version"] == 1, "version starts at 1 at creation"
        assert patient["created_at"] == "2026-08-01T00:00:00.000Z", (
            "created_at must be stamped from the startup-default logical clock")
        # Retrieval round-trip returns the same persisted values.
        fetched = validate_success(api.get_patient(patient["id"], registrar_headers), 200)
        assert fetched["id"] == patient["id"]
        assert fetched["mrn"] == "MRN-E-1"
        assert fetched["full_name"] == "Pat Entity"
        assert fetched["date_of_birth"] == "1990-01-01"
        assert fetched["created_at"] == patient["created_at"]

    def test_patient_create_missing_mrn_returns_400(self, api, registrar_headers):
        """PRD §3.2: "A `Registrar` registers each patient with a medical record
        number `mrn`, a `full_name`, and a `date_of_birth`."
        PRD §2.8: "then (4) request-body shape — required fields present, types
        correct, enum values in range, amounts positive where required, and
        structural rules such as installment counts and date-window ordering".

        Design: Corner/entities/patient_create_missing_mrn_returns_400
        """
        payload = create_patient_payload(mrn="MRN-MISSING")
        del payload["mrn"]
        res = api.create_patient(payload, registrar_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)
        # No patient was persisted: a retry carrying mrn succeeds.
        retry = api.create_patient(
            create_patient_payload(mrn="MRN-MISSING", full_name="No Mrn"),
            registrar_headers)
        validate_success(retry, 201)

    def test_charge_item_create_with_wrong_type_returns_400(self, api, admin_headers):
        """PRD §2.8: "then (4) request-body shape — required fields present,
        types correct, enum values in range, amounts positive where required,
        and structural rules such as installment counts and date-window
        ordering".

        Design: Corner/entities/charge_item_create_with_wrong_type_returns_400
        """
        payload = create_charge_item_payload(
            cpt_code="27447", list_price_cents=5000000, requires_auth_prior="yes")
        res = api.create_charge_item(payload, admin_headers)
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST)

    def test_case_get_unknown_id_returns_error_envelope_404(self, api, registrar_headers):
        """PRD §2.7: "the first identifier in the path that does not correspond
        to an existing resource determines the failure, and the request is
        rejected with `ERR_NOT_FOUND` (HTTP 404) before any later identifier or
        any business rule is examined."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/case_get_not_found_returns_error_envelope_404
        """
        res = api.get_case(NON_EXISTENT_UUID, registrar_headers)
        err = validate_error(res, ApiErrorId.ERR_NOT_FOUND)
        assert isinstance(err.get("message"), str) and err["message"], (
            "error envelope must carry a human-readable message")

    def test_success_envelope_shape_on_patient_create(self, api, registrar_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/success_envelope_shape_on_patient_create
        """
        res = api.create_patient(
            create_patient_payload(mrn="MRN-EN-1", full_name="Pat Envelope"),
            registrar_headers)
        patient = validate_success(res, 201)
        body = res.json()
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_"), (
            "api_request_id starts with req_")
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))
        assert body["response_type"] == "object"
        assert patient["mrn"] == "MRN-EN-1"

    def test_patient_create_missing_user_context_headers_returns_400(self, api):
        """PRD §2.1: "A request with either header missing or empty, or whose
        role value is not one of the declared roles, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/validations/patient_create_missing_header_returns_400
        """
        res = api.create_patient(
            create_patient_payload(mrn="MRN-V-1", full_name="No Headers"),
            headers={})
        validate_error(res, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

    def test_duplicate_mrn_returns_409(self, api, registrar_headers):
        """PRD §3.2: "The `mrn` is unique across patients; a duplicate
        registration is rejected with `ERR_DUPLICATE_MRN` (HTTP 409)."

        Design: Corner/validations/duplicate_mrn_returns_409
        """
        first = api.create_patient(
            create_patient_payload(mrn="MRN-DUP", full_name="First",
                                   date_of_birth="1993-07-07"),
            registrar_headers)
        validate_success(first, 201)
        res = api.create_patient(
            create_patient_payload(mrn="MRN-DUP", full_name="Second",
                                   date_of_birth="1993-07-08"),
            registrar_headers)
        validate_error(res, ApiErrorId.ERR_DUPLICATE_MRN)
