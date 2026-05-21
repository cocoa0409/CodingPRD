"""Auth, response envelope, and pagination tests.

Covers PRD §2.1 (auth/RBAC), §2.2 (envelope), §2.3 (pagination),
§2.11 (validation ordering — header precedence).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_and_activate_entity,
    create_entity_payload,
    create_registered_agent,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Auth — PRD §2.1
# ---------------------------------------------------------------------------
class TestAuthRequired:

    def test_missing_both_headers_returns_missing_auth(self, api):
        """PRD §2.1: "Every request must carry two custom headers:
        X-User-ID (the actor's stable identifier) and X-User-Role (the
        actor's role). When either header is absent, empty, or missing
        entirely, the request is rejected with ERR_MISSING_AUTH and
        HTTP 401"

        Claim: empty headers → ERR_MISSING_AUTH.
        """
        resp = api.list_entities(headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_missing_x_user_id_only_returns_missing_auth(self, api):
        """PRD §2.1: "When either header is absent, empty, or missing
        entirely, the request is rejected with ERR_MISSING_AUTH and
        HTTP 401"

        Claim: missing X-User-ID alone → ERR_MISSING_AUTH.
        """
        resp = api.list_entities(headers={"X-User-Role": "Filer"})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_missing_x_user_role_only_returns_missing_auth(self, api):
        """PRD §2.1: "When either header is absent, empty, or missing
        entirely, the request is rejected with ERR_MISSING_AUTH and
        HTTP 401"

        Claim: missing X-User-Role alone → ERR_MISSING_AUTH.
        """
        resp = api.list_entities(headers={"X-User-ID": "anyone"})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_empty_x_user_id_returns_missing_auth(self, api):
        """PRD §2.1: "When either header is absent, empty, or missing
        entirely, the request is rejected with ERR_MISSING_AUTH and
        HTTP 401"

        Claim: empty X-User-ID string → ERR_MISSING_AUTH.
        """
        resp = api.list_entities(
            headers={"X-User-ID": "", "X-User-Role": "Filer"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)


class TestInvalidRole:

    def test_unknown_role_returns_invalid_role(self, api):
        """PRD §2.1: "Any other value yields ERR_INVALID_ROLE with HTTP
        403."

        Claim: unknown X-User-Role → ERR_INVALID_ROLE.
        """
        resp = api.list_entities(headers={
            "X-User-ID": "rando",
            "X-User-Role": "Hackerman",
        })
        validate_error(resp, ApiErrorId.ERR_INVALID_ROLE.value)


class TestForbidden:

    def test_filer_cannot_create_tax_assessment(self, api,
                                                filer_headers):
        """PRD §4 table: "POST /business-registry/tax-assessments"
        is restricted to TaxOfficer.
        PRD §2.1: "When the role spelling is valid but the role is not
        authorized for the requested endpoint per the role-permission
        matrix in §4, the request is rejected with ERR_FORBIDDEN and
        HTTP 403."

        Claim: Filer calling TaxOfficer-only endpoint → ERR_FORBIDDEN.
        """
        # Use a payload that wouldn't fail other checks first — the
        # role-check (priority 3) fires before existence (priority 4).
        resp = api.create_tax_assessment(
            {"business_entity_id": NON_EXISTENT_UUID,
             "tax_year": 2024, "calculation_method": "FLAT"},
            filer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_tax_officer_cannot_form_entity(self, api,
                                            tax_officer_headers):
        """PRD §4 table: "POST /business-registry/entities/{id}/form"
        is restricted to StateRegistrar.

        Claim: TaxOfficer calling form → ERR_FORBIDDEN.
        """
        resp = api.form_entity(NON_EXISTENT_UUID, tax_officer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Envelope — PRD §2.2
# ---------------------------------------------------------------------------
class TestSuccessEnvelope:

    def test_success_envelope_carries_meta_and_response_type(
        self, api, state_registrar_headers,
    ):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format ... { meta:
        {...}, response_type: "object" | "array", data: { } }"

        Claim: 2xx body must carry meta + response_type + data and
        meta.api_request_id starts with 'req_'.
        """
        resp = api.list_entities(state_registrar_headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        assert body["response_type"] in ("object", "array")
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_', got "
            f"{body['meta']['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


class TestErrorEnvelope:

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format: ... response_type: "error",
        data: { error_id: ..., message: ... }"

        Claim: error responses carry response_type=error + data with
        error_id and non-empty message.
        """
        resp = api.list_entities(headers={})
        body = resp.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)
        assert len(body["data"]["message"].strip()) > 0


# ---------------------------------------------------------------------------
# Pagination — PRD §2.3
# ---------------------------------------------------------------------------
class TestPagination:

    def test_list_endpoint_returns_pagination_meta(
        self, api, state_registrar_headers,
    ):
        """PRD §2.3: "The four pagination fields surfaced under meta
        are limit, offset, total_count, and has_more"

        Claim: list endpoints return meta with limit/offset/
        total_count/has_more.
        """
        resp = api.list_entities(state_registrar_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta

    def test_default_limit_is_10(self, api, state_registrar_headers):
        """PRD §2.3: "The limit defaults to 10 when omitted"

        Claim: default limit value reported back as 10.
        """
        resp = api.list_entities(state_registrar_headers)
        _data, meta = validate_paginated(resp)
        assert meta["limit"] == 10, (
            f"Default limit must be 10, got {meta['limit']}"
        )

    def test_explicit_limit_offset_round_trip(
        self, api, state_registrar_headers,
    ):
        """PRD §2.3: "List endpoints accept two optional query
        parameters: limit and offset."

        Claim: explicit limit/offset echo through meta.
        """
        resp = api.list_entities(
            state_registrar_headers, params={"limit": 5, "offset": 2},
        )
        _data, meta = validate_paginated(resp)
        assert meta["limit"] == 5
        assert meta["offset"] == 2


# ---------------------------------------------------------------------------
# Validation ordering — PRD §2.11
# ---------------------------------------------------------------------------
class TestValidationOrdering:

    def test_missing_auth_beats_role_authorization(self, api):
        """PRD §2.11: "(1) auth headers present, (2) role spelling valid,
        (3) role authorized for the endpoint per the matrix in §4"
        PRD §2.11: "tests assert, for example, that a request with both
        a missing auth header and a body-level legal-name collision is
        rejected with ERR_MISSING_AUTH, not ERR_DUPLICATE_LEGAL_NAME."

        Claim: missing auth always wins, regardless of the endpoint's
        role gate.
        """
        # Form-entity is StateRegistrar-only; with no headers, auth
        # (priority 1) fires before role-authorization (priority 3).
        resp = api.form_entity(NON_EXISTENT_UUID, headers={})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_role_authorization_beats_existence(
        self, api, tax_officer_headers,
    ):
        """PRD §2.11: "(3) role authorized for the endpoint per the
        matrix in §4, (4) URL-path resources exist"

        Claim: role-authorization error (priority 3) wins over not-
        found (priority 4) when both would fire.
        """
        # TaxOfficer is not authorized to call /form; the URL points
        # at NON_EXISTENT_UUID which would also fail existence.
        resp = api.form_entity(NON_EXISTENT_UUID, tax_officer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ---------------------------------------------------------------------------
# Not-found path — PRD §2.7
# ---------------------------------------------------------------------------
class TestNotFound:

    def test_get_entity_nonexistent_returns_not_found(
        self, api, state_registrar_headers,
    ):
        """PRD §2.7: "The outer entity ({id} for the business entity) is
        resolved first; if it does not exist, the response is
        ERR_NOT_FOUND with HTTP 404"

        Claim: GET on nonexistent entity → ERR_NOT_FOUND.
        """
        resp = api.get_entity(NON_EXISTENT_UUID, state_registrar_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_body_referenced_fk_nonexistent_returns_not_found(
        self, api, filer_headers,
    ):
        """PRD §2.7: "After URL-path resources are confirmed,
        body-referenced foreign keys (registered_agent_id,
        business_entity_id, beneficial_owner_id,
        foreign_registered_agent_id) are resolved; an unresolved foreign
        key likewise yields ERR_NOT_FOUND with HTTP 404."

        Claim: body FK pointing at non-existent registered_agent_id →
        ERR_NOT_FOUND.
        """
        payload = create_entity_payload(
            registered_agent_id=NON_EXISTENT_UUID,
        )
        resp = api.create_entity(payload, filer_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
