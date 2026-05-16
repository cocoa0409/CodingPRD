"""Auth, RBAC, response envelope, pagination, and existence checks.

PRD §2.1 (auth/role), §2.2 (envelope), §2.3 (pagination), §2.7
(NotFound / left-to-right resolution).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_patient_payload,
    create_provider_payload,
    create_service_catalog_item_payload,
    is_iso8601_timestamp,
    make_provider_headers,
    setup_reference_data,
    setup_under_review_authorization,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing / malformed headers
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Requests missing or malformed in either header are
        rejected with ERR_AUTH_MISSING and HTTP 401."

        Claim: a POST with neither header set returns ERR_AUTH_MISSING.
        """
        res = api.create_patient(create_patient_payload(), headers={})
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Requests missing or malformed in either header are
        rejected with ERR_AUTH_MISSING and HTTP 401."

        Claim: omitting X-User-ID returns ERR_AUTH_MISSING.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Requests missing or malformed in either header are
        rejected with ERR_AUTH_MISSING and HTTP 401."

        Claim: omitting X-User-Role returns ERR_AUTH_MISSING.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-ID": "admin-001"},
        )
        validate_error(res, "ERR_AUTH_MISSING")


class TestRoleAuthorization:
    """PRD §2.1: "When a caller's role does not include the requested
    operation in the RBAC matrix, the request is rejected with
    ERR_FORBIDDEN and HTTP 403.\""""

    def test_provider_cannot_create_patient(self, api):
        """PRD §4: POST /patients is exclusive to PlatformAdmin.

        PRD §2.1: "When a caller's role does not include the requested
        operation in the RBAC matrix, the request is rejected with
        ERR_FORBIDDEN and HTTP 403."

        Claim: a Provider calling POST /patients returns ERR_FORBIDDEN.
        """
        res = api.create_patient(
            create_patient_payload(),
            build_user_headers("provider-x", "Provider"),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_initial_reviewer_cannot_create_service_catalog_item(
        self, api,
    ):
        """PRD §4: POST /service-catalog-items is exclusive to
        PlatformAdmin.

        PRD §2.1: "When a caller's role does not include the requested
        operation in the RBAC matrix, the request is rejected with
        ERR_FORBIDDEN and HTTP 403."

        Claim: an InitialReviewer calling POST /service-catalog-items
        returns ERR_FORBIDDEN.
        """
        res = api.create_service_catalog_item(
            create_service_catalog_item_payload(),
            TEST_USERS["initial_reviewer_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_provider_cannot_decide_authorization(self, api):
        """PRD §4: POST /authorization-requests/{id}/decide is exclusive
        to InitialReviewer.

        PRD §2.1: "When a caller's role does not include the requested
        operation in the RBAC matrix, the request is rejected with
        ERR_FORBIDDEN and HTTP 403."

        Claim: a Provider calling /decide returns ERR_FORBIDDEN.
        """
        _, provider, _, auth, _ = setup_under_review_authorization()
        res = api.decide_authorization_request(
            auth["id"],
            {"outcome": "APPROVED", "rationale": "x", "approved_units": 1},
            make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Response Envelope
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: every 2xx response carries meta with api_request_id and
    api_request_timestamp, response_type, and data."""

    def test_success_envelope_shape(self, api, admin_headers):
        """PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."

        Claim: a 201 response carries meta.api_request_id beginning with
        `req_` and a non-empty data object.
        """
        res = api.create_patient(create_patient_payload(), admin_headers)
        body = res.json()
        assert "meta" in body
        assert "response_type" in body
        assert body["response_type"] == "object"
        assert "data" in body and isinstance(body["data"], dict)
        meta = body["meta"]
        assert isinstance(meta.get("api_request_id"), str)
        assert meta["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", ""))


class TestErrorEnvelope:
    """PRD §2.2: error responses carry meta + response_type=error +
    data.error_id + data.message."""

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error. The message provides a
        human-readable explanation of what went wrong."

        Claim: an auth-missing 401 carries error_id and message under
        data, plus response_type='error'.
        """
        res = api.create_patient(create_patient_payload(), headers={})
        body = res.json()
        assert body.get("response_type") == "error"
        data = body.get("data", {})
        assert data.get("error_id") == "ERR_AUTH_MISSING"
        assert isinstance(data.get("message"), str) and data["message"]


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: list endpoints accept limit/offset."""

    def test_default_limit_and_offset(self, api):
        """PRD §2.3: "The limit parameter specifies the maximum number
        of items to return; it defaults to 10, with a minimum of 1 and a
        maximum of 100. The offset parameter specifies the number of
        items to skip and defaults to 0."

        Claim: GET /authorization-requests with no params returns
        meta with limit=10 and offset=0.
        """
        # Need at least one authorization to exist so the list runs.
        patient, provider, catalog_item = setup_reference_data()
        from test_helpers import create_authorization_request
        create_authorization_request(
            patient=patient, provider=provider, catalog_item=catalog_item,
        )
        res = api.list_authorization_requests(
            TEST_USERS["admin_headers"],
        )
        _, meta = validate_paginated(res)
        assert meta.get("limit") == 10
        assert meta.get("offset") == 0

    def test_limit_caps_results(self, api):
        """PRD §2.3: "The limit parameter specifies the maximum number
        of items to return".

        Claim: limit=1 returns exactly 1 row when at least 2 exist, and
        has_more is true.
        """
        from test_helpers import create_authorization_request
        patient, provider, catalog_item = setup_reference_data()
        for _ in range(3):
            create_authorization_request(
                patient=patient, provider=provider,
                catalog_item=catalog_item,
            )
        res = api.list_authorization_requests(
            TEST_USERS["admin_headers"], params={"limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(res)
        assert len(data) == 1
        assert meta.get("has_more") is True


# ===========================================================================
# §2.7 Existence checks
# ===========================================================================
class TestExistenceChecks:
    """PRD §2.7: path-parameter resources that do not exist produce
    ERR_NOT_FOUND."""

    def test_get_nonexistent_patient(self, api, admin_headers):
        """PRD §2.7: "The first identifier that does not resolve to an
        existing resource produces an immediate 404 Not Found with
        ERR_NOT_FOUND".

        Claim: GET /patients/{unknown-uuid} returns ERR_NOT_FOUND.
        """
        res = api.get_patient(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_nonexistent_authorization_request(self, api,
                                                   admin_headers):
        """PRD §2.7: "The first identifier that does not resolve to an
        existing resource produces an immediate 404 Not Found with
        ERR_NOT_FOUND".

        Claim: GET /authorization-requests/{unknown-uuid} returns
        ERR_NOT_FOUND.
        """
        res = api.get_authorization_request(
            NON_EXISTENT_UUID, admin_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_foreign_key_patient_id_does_not_resolve(self, api):
        """PRD §2.7: "foreign-key references that arrive in a request
        body — patient_id, provider_id, service_catalog_item_id,
        authorization_request_id, payer_reviewer_id, and
        prior_request_id — must resolve to existing rows; missing
        references produce ERR_REFERENCE_NOT_FOUND and HTTP 404."

        Claim: POST /authorization-requests with a non-existent
        patient_id returns ERR_REFERENCE_NOT_FOUND.
        """
        from test_helpers import (
            create_authorization_request_payload,
            create_provider, create_service_catalog_item,
        )
        provider = create_provider()
        catalog_item = create_service_catalog_item()
        payload = create_authorization_request_payload(
            patient_id=NON_EXISTENT_UUID,
            provider_id=provider["id"],
            service_catalog_item_id=catalog_item["id"],
        )
        res = api.create_authorization_request(
            payload, make_provider_headers(provider["id"]),
        )
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")

    def test_left_to_right_path_resolution(self, api):
        """PRD §2.7: "the server validates each identifier in
        left-to-right order, parent before child. The first identifier
        that does not resolve to an existing resource produces an
        immediate 404 Not Found with ERR_NOT_FOUND; later checks do not
        run."

        Claim: withdraw on a nonexistent authorization's nonexistent
        evidence returns ERR_NOT_FOUND.

        Identity: withdraw_clinical_evidence is Provider-only per the
        RBAC matrix; we use a Provider header (any well-formed id is
        sufficient — path resolution per §2.8 priority #3 fires before
        the ownership check) so that the test isolates the path-resolution
        rule rather than the role gate (§2.8 priority #2).
        """
        from test_helpers import PROVIDER_FALLBACK_ID, make_provider_headers
        res = api.withdraw_clinical_evidence(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            make_provider_headers(PROVIDER_FALLBACK_ID),
        )
        validate_error(res, "ERR_NOT_FOUND")
