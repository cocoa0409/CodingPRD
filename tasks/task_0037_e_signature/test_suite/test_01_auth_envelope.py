"""Authentication, RBAC, response envelope, and pagination behavior.

Covers PRD §2.1 (headers and roles), §2.2 (response envelope), §2.3
(pagination), and §2.6 (nested-path 404).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_published_template,
    create_template_payload,
    make_template_admin_headers,
    setup_pending_sign_single_party,
    stable_user_id,
    validate_error,
    validate_paginated,
    validate_success,
)


# =========================================================================
# §2.1 -- Headers must be present and well-formed.
# =========================================================================
class TestUnauthenticatedHeaders:

    def test_missing_user_id_header(self, api):
        """PRD §2.1: 'A request missing either header, or carrying a
        malformed value, is rejected with ERR_UNAUTHENTICATED and HTTP 401.'

        Claim: missing X-User-ID -> 401 ERR_UNAUTHENTICATED.
        """
        # Build headers with only X-User-Role.
        bad = {"X-User-Role": "TemplateAdmin"}
        res = api._request(
            "POST", "/templates",
            create_template_payload(), bad,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_header(self, api):
        """PRD §2.1: 'A request missing either header, or carrying a
        malformed value, is rejected with ERR_UNAUTHENTICATED and HTTP 401.'

        Claim: missing X-User-Role -> 401 ERR_UNAUTHENTICATED.
        """
        bad = {"X-User-ID": "user-001"}
        res = api._request(
            "GET", "/templates", headers=bad,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_empty_role_value(self, api):
        """PRD §2.1: 'A request ... carrying a malformed value, is rejected
        with ERR_UNAUTHENTICATED and HTTP 401.'

        Claim: empty X-User-Role -> 401 ERR_UNAUTHENTICATED.
        """
        bad = {"X-User-ID": "user-001", "X-User-Role": ""}
        res = api._request("GET", "/templates", headers=bad)
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)


# =========================================================================
# §2.1 -- Role authorization (ERR_FORBIDDEN at priority 2)
# =========================================================================
class TestRoleAuthorization:

    def test_signer_cannot_create_template(self, api, signer_headers_fallback):
        """PRD §2.1: 'A request whose role is not authorized to perform the
        operation is rejected with ERR_FORBIDDEN and HTTP 403.'

        PRD §4 (endpoint table): POST /templates is authorized only to
        TemplateAdmin.

        Claim: Signer attempting POST /templates -> 403 ERR_FORBIDDEN.
        """
        res = api.create_template(
            create_template_payload(), signer_headers_fallback
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_initiator_cannot_publish_template_version(
        self, api, contract_initiator_headers_fallback,
    ):
        """PRD §4 endpoint table: POST /templates/{id}/versions/{vid}/publish
        is authorized only to TemplateAdmin.

        Claim: ContractInitiator attempting publish -> 403 ERR_FORBIDDEN.
        """
        res = api.publish_template_version(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            contract_initiator_headers_fallback,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_signer_cannot_seal_evidence(
        self, api, signer_headers_fallback,
    ):
        """PRD §4 endpoint table: POST /contracts/{id}/evidence/seal is
        authorized only to EvidenceArchivist.

        Claim: Signer attempting seal -> 403 ERR_FORBIDDEN.
        """
        res = api.seal_evidence(
            NON_EXISTENT_UUID, {}, signer_headers_fallback,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# =========================================================================
# §2.2 -- Response envelope structure
# =========================================================================
class TestSuccessEnvelope:

    def test_success_envelope_has_meta_and_data(
        self, api, platform_admin_headers,
    ):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body'
        with meta.api_request_id, meta.api_request_timestamp, response_type
        and data.

        Claim: a 2xx response body has meta.api_request_id starting with
        'req_' and a server-generated timestamp.
        """
        res = api.list_templates(platform_admin_headers)
        body = res.json()
        assert "meta" in body and "data" in body
        meta = body["meta"]
        assert "api_request_id" in meta
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: 'The api_request_id is a server-generated unique "
            "identifier for the request that starts with req_'"
        )
        assert "api_request_timestamp" in meta


class TestPaginationEnvelope:

    def test_default_limit_and_offset(self, api, platform_admin_headers):
        """PRD §2.3: 'The default limit is 10... The default offset is 0.'
        And §2.2: meta carries 'limit, offset, total_count, has_more'.

        Claim: GET /templates returns meta.limit == 10 and meta.offset == 0.
        """
        # Seed at least a couple of templates to ensure the response is a
        # well-formed paginated list.
        create_published_template()
        create_published_template()
        res = api.list_templates(platform_admin_headers)
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert isinstance(data, list)
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    @pytest.mark.parametrize("limit", [0, -1, 101, 200])
    def test_invalid_limit_rejected(
        self, api, platform_admin_headers, limit,
    ):
        """PRD §2.3: 'The default limit is 10, the minimum is 1, and the
        maximum is 100; values outside this band are rejected with
        ERR_VALIDATION_FAILED.'

        Claim: limit outside [1, 100] -> 400 ERR_VALIDATION_FAILED.
        """
        res = api.list_templates(
            platform_admin_headers, params={"limit": limit, "offset": 0}
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value)

    def test_negative_offset_rejected(self, api, platform_admin_headers):
        """PRD §2.3: 'The default offset is 0; negative values are rejected.'

        Claim: offset = -1 -> 400 ERR_VALIDATION_FAILED.
        """
        res = api.list_templates(
            platform_admin_headers, params={"limit": 10, "offset": -1}
        )
        validate_error(res, ApiErrorId.ERR_VALIDATION_FAILED.value)


# =========================================================================
# §2.6 -- Nested path validation
# =========================================================================
class TestNestedPathExistence:

    def test_get_template_unknown_id_returns_404(
        self, api, platform_admin_headers,
    ):
        """PRD §5 + §2.6: 'a request against a TemplateVersion under a
        Template fails with ERR_NOT_FOUND if the Template id does not
        exist, even if the inner version id does.'

        Claim: GET /templates/{unknown_id} -> 404 ERR_NOT_FOUND.
        """
        res = api.get_template(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_template_version_unknown_template_returns_404(
        self, api, platform_admin_headers,
    ):
        """PRD §2.6: 'a request against a TemplateVersion under a Template
        fails with ERR_NOT_FOUND if the Template id does not exist, even
        if the inner version id does.'

        Claim: GET /templates/{bad}/versions/{anything} -> 404.
        """
        res = api.get_template_version(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, platform_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_real_template_with_unrelated_version_returns_404(
        self, api, platform_admin_headers,
    ):
        """PRD §2.6: 'When the leftmost path segment validates but a deeper
        one does not -- for example, a real Template id paired with a
        TemplateVersion id that belongs to a different Template -- the
        request still fails with ERR_NOT_FOUND.'

        Claim: GET /templates/{realA}/versions/{versionOfB} -> 404.
        """
        bundle_a = create_published_template()
        bundle_b = create_published_template()
        res = api.get_template_version(
            bundle_a["template"]["id"],
            bundle_b["version"]["id"],
            platform_admin_headers,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
