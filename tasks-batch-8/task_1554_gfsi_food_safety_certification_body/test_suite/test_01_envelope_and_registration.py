"""Response envelopes, authentication gate, and actor registration defaults."""
from test_helpers import (
    ApiErrorId,
    assert_client,
    assert_instant_equal,
    assert_scheme,
    create_scheme_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_client,
    make_client_admin_headers,
    make_scheme,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestEnvelopeShape:
    def test_success_envelope_single_and_list(self, api, scheme_admin_headers):
        """PRD §2.2: "The `response_type` is either "object" for a single
        resource or "array" for a list of resources."
        PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.3: "The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/success_response_envelope_shape
        """
        client = make_client()
        resp = api.get_client(client["id"], scheme_admin_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["id"] == client["id"]

        resp = api.list_schemes(scheme_admin_headers)
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert isinstance(data, list)
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, f"missing pagination field {field}"

    def test_error_envelope_shape(self, api, scheme_admin_headers):
        """PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/endpoints/error_response_envelope_shape
        """
        resp = api.get_audit("11111111-2222-4333-8444-555555555555",
                             scheme_admin_headers)
        error = validate_error(resp, ApiErrorId.ERR_AUDIT_NOT_FOUND)
        body = resp.json()
        assert body["response_type"] == "error"
        assert error["error_id"] == "ERR_AUDIT_NOT_FOUND"
        assert isinstance(error["message"], str) and error["message"].strip()


class TestRegistration:
    def test_scheme_creation_stores_all_rule_constants(self, api,
                                                       scheme_admin_headers):
        """PRD §3.1: "Everything downstream is parameterized by a **Scheme**,
        and a `SchemeAdmin` registers one with its full set of rule constants."
        PRD §2.6: "At startup the logical clock reads 2026-08-01T00:00:00Z."
        PRD §2.4: "The `version` is an integer that starts at its initial value
        on creation and increments by one on every mutation"

        Design: Corner/entities/scheme_creation_stores_all_rule_constants
        """
        payload = create_scheme_payload()
        resp = api.create_scheme(payload, scheme_admin_headers)
        data = validate_success(resp, 201)
        assert_scheme(data)
        assert data["code"] == "SQF"
        assert data["critical_nc_days"] == 7
        assert data["major_nc_days"] == 28
        assert data["minor_nc_days"] == 84
        assert data["pass_score"] == 70
        assert data["unannounced_every_n"] == 3
        assert data["supported_category_codes"] == ["BAKERY", "DAIRY", "MEAT"]
        assert is_valid_uuid(data["id"])
        # created_at is stamped from the logical clock, which starts at the
        # PRD §2.6 default.
        assert_instant_equal(data["created_at"], "2026-08-01T00:00:00Z")
        assert data["version"] == 1

    def test_client_creation_success(self, api, scheme_admin_headers):
        """PRD §3.2: "A `SchemeAdmin` registers each **Client** with its legal
        `name`, a `contact_email`, and a `country`; the returned client `id` is
        exactly the value the client's administrators will present as
        `X-User-ID` with role `ClientAdmin`."

        Design: Corner/entities/client_creation_success
        """
        resp = api.create_client(
            {"name": "Acme Baking Co", "contact_email": "qa@acme.test",
             "country": "US"},
            scheme_admin_headers)
        data = validate_success(resp, 201)
        assert_client(data)
        assert data["name"] == "Acme Baking Co"
        assert data["contact_email"] == "qa@acme.test"
        assert data["country"] == "US"
        assert data["version"] == 1

    def test_auditor_defaults_calibration_lapsed_and_zero_active(
            self, api, scheme_admin_headers):
        """PRD §3.2: "The `calibration_status` is `CURRENT` or `LAPSED` and
        starts at `LAPSED`"
        PRD §3.2: "Auditors are registered with a `name`, the
        `competency_categories` they are qualified to audit, and an optional
        `conflicted_client_ids` list that defaults to empty"
        PRD §3.2: "The `last_witnessed_on` field holds the most recent passing
        witness date and is null when the auditor has never passed one."
        PRD §3.2: "The `active_audit_count` counts the audits assigned to the
        auditor that are currently in `SCHEDULED` or `IN_PROGRESS` status"

        Design: Corner/entities/auditor_defaults_calibration_lapsed_and_zero_active
        """
        make_scheme()
        resp = api.create_auditor(
            {"name": "Audrey Auditor", "competency_categories": ["BAKERY"]},
            scheme_admin_headers)
        data = validate_success(resp, 201)
        assert data["calibration_status"] == "LAPSED"
        assert data["active_audit_count"] == 0
        assert data["conflicted_client_ids"] == []
        assert data["last_witnessed_on"] is None

    def test_request_without_auth_headers_unauthenticated(self, api):
        """PRD §2.1: "Missing or unrecognized headers are rejected with
        `ERR_UNAUTHENTICATED` (HTTP 401) on every endpoint except the public
        certification directory, which an `Anonymous` caller may query without
        any authentication headers."

        Design: Corner/validations/request_without_role_header_unauthenticated
        """
        resp = api.create_scheme(create_scheme_payload(), headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)


class TestSchemeRegistrationRbac:
    def test_client_admin_cannot_create_scheme(self, api):
        """PRD §2.1: "A caller whose role is not listed among an endpoint's
        authorized roles is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /certification-body/schemes lists only SchemeAdmin.

        Design: Corner/rbac/client_admin_cannot_create_scheme
        """
        client = make_client()
        resp = api.create_scheme(create_scheme_payload(code="BRC"),
                                 make_client_admin_headers(client["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
