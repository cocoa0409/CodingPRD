"""Representative registration: defaults, required fields, uniqueness,
registration guards, termination cascade surface, and validation ordering."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_approved_content,
    create_assignment,
    create_representative_payload,
    create_rep,
    get_success_data,
    setup_lapsed_rep,
    validate_error,
    validate_paginated,
    validate_success,
)

OFFICER = TEST_USERS["officer_headers"]


class TestRepresentativeCreation:
    def test_creation_defaults(self, api, admin_headers):
        """PRD §3.1: "Every new representative begins with
        `registration_status` set to `ACTIVE`."
        PRD §3.1: "When omitted, `prior_year_excess_hours` defaults to zero; it
        may never be negative."
        PRD §2.5: "`id` (string): a unique, server-minted identifier formatted
        as a UUID, with no type prefix."

        Design: Corner/entities/c_rep_creation_defaults
        """
        payload = create_representative_payload(crd_number="CRD-C01")
        payload.pop("prior_year_excess_hours")  # omit the optional field
        resp = api.create_representative(payload, admin_headers)
        data = validate_success(resp, expected_status=201)
        assert data["registration_status"] == "ACTIVE"
        assert data["prior_year_excess_hours"] == 0, (
            f"omitted prior_year_excess_hours must default to 0, "
            f"got {data['prior_year_excess_hours']}")
        assert data["version"] == 1
        from test_helpers import is_valid_uuid
        assert is_valid_uuid(data["id"])

    def test_missing_crd_number_returns_400(self, api, admin_headers):
        """PRD §2.6: "Required fields are present, enum values are valid, a
        completion `score` lies between 0 and 100 inclusive, an enrollment
        create carries exactly one of `content_id` or `session_id`, a void's
        `justification` is at least ten characters long, and similar shape
        rules hold — violations yield `ERR_INVALID_REQUEST` (HTTP 400)."
        PRD §3.1: "A `TrainingAdmin` registers a new representative by
        supplying the rep's `crd_number`, `full_name`, `email`, `role_tier`,
        `insurance_licensed` flag, and `resident_state_code`."

        Design: Corner/entities/c_rep_missing_required_crd_returns_400
        """
        payload = create_representative_payload()
        payload.pop("crd_number")
        resp = api.create_representative(payload, admin_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestDuplicateCrd:
    def test_duplicate_crd_rejected(self, api, admin_headers):
        """PRD §3.1: "The `crd_number` must be unique across all
        representatives; a second registration with an existing number is
        rejected with `ERR_DUPLICATE_CRD_NUMBER`."

        Design: Corner/validations/c_duplicate_crd_returns_409
        """
        create_rep(crd_number="CRD-DUP", full_name="First")
        resp = api.create_representative(
            create_representative_payload(
                crd_number="CRD-DUP", full_name="Second",
                role_tier="PRINCIPAL", insurance_licensed=True,
                resident_state_code="CA"),
            admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CRD_NUMBER)


class TestRegistrationGuards:
    def test_enroll_inactive_rep_rejected(self, api, admin_headers):
        """PRD §3.1: "enrollment creation, starting, completing, and
        reattempting coursework, as well as the creation of regulatory
        assignments and firm element plans, all require the rep to be
        `ACTIVE`. An operation attempted for an `INACTIVE_CE` rep is rejected
        with `ERR_REGISTRATION_INACTIVE`; for a `TERMINATED` rep, with
        `ERR_REGISTRATION_TERMINATED`."

        Design: Corner/errors/c_enroll_while_registration_inactive_returns_409
        """
        rep, _assignment = setup_lapsed_rep()  # sweep lapses -> INACTIVE_CE
        rep_data = validate_success(api.get_representative(rep["id"], OFFICER))
        assert rep_data["registration_status"] == "INACTIVE_CE"

        content = create_approved_content(code="FE-RIA", ce_category="FIRM_ELEMENT")
        resp = api.create_enrollment(
            {"rep_id": rep["id"], "content_id": content["id"]}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_INACTIVE)

    def test_enroll_terminated_rep_rejected(self, api, admin_headers, officer_headers):
        """PRD §3.1: "An operation attempted for an `INACTIVE_CE` rep is
        rejected with `ERR_REGISTRATION_INACTIVE`; for a `TERMINATED` rep, with
        `ERR_REGISTRATION_TERMINATED`."

        Design: Corner/errors/c_enroll_terminated_rep_returns_409
        """
        rep = create_rep(crd_number="CRD-TRM")
        content = create_approved_content(code="FE-TRM", ce_category="FIRM_ELEMENT")
        get_success_data(api.terminate_representative(rep["id"], officer_headers))

        resp = api.create_enrollment(
            {"rep_id": rep["id"], "content_id": content["id"]}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_REGISTRATION_TERMINATED)


class TestValidationOrdering:
    def test_existence_beats_registration_state(self, api, admin_headers, officer_headers):
        """PRD §2.6: "Every incoming request is evaluated against an ordered
        validation chain, and the first failing check determines the response;
        later checks are not evaluated once an earlier one has failed."
        PRD §2.6: "3. **Existence.** The path identifier resolves to an
        existing resource, and then any foreign keys carried in the request
        body — `rep_id`, `content_id`, `session_id`,
        `required_training_content_id` — resolve to existing resources; the
        first unresolvable reference yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/c_existence_beats_state_on_enroll
        """
        rep = create_rep(crd_number="CRD-C20")
        get_success_data(api.terminate_representative(rep["id"], officer_headers))
        # Nonexistent content FK: existence (step 3) fires before the
        # registration-standing guard (step 7).
        resp = api.create_enrollment(
            {"rep_id": rep["id"], "content_id": NON_EXISTENT_UUID}, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestNotFound:
    def test_get_rep_not_found(self, api, admin_headers):
        """PRD §2.6: "3. **Existence.** The path identifier resolves to an
        existing resource, and then any foreign keys carried in the request
        body — `rep_id`, `content_id`, `session_id`,
        `required_training_content_id` — resolve to existing resources; the
        first unresolvable reference yields `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/c_get_rep_not_found_returns_404
        """
        resp = api.get_representative(NON_EXISTENT_UUID, admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api, auditor_headers):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard error envelope format: ... `response_type`: "error", `data`:
        { `error_id`, `message` }."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error. The `message` provides a human-readable
        explanation of what went wrong."

        Design: Corner/endpoints/c_error_envelope_shape
        """
        resp = api.get_content(NON_EXISTENT_UUID, auditor_headers)
        assert resp.status_code == 404
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            "error envelope must carry a non-empty message")
