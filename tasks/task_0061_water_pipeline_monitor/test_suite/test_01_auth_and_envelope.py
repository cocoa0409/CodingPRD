"""Auth, envelope, pagination, and basic error semantics.

Covers PRD §2.1 (auth headers), §2.2 (success / error envelope shape),
§2.3 (pagination), and §2.7 (left-to-right path resolution).
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId, NON_EXISTENT_UUID,
    TEST_USERS, api_client,
    build_user_headers, create_network_payload,
    validate_error, validate_success, validate_paginated,
)


# ===========================================================================
# §2.1 — Auth headers
# ===========================================================================
class TestAuthentication:
    """PRD §2.1: missing/empty X-User-ID or X-User-Role → ERR_UNAUTHENTICATED 401."""

    def test_missing_user_id_header_unauthenticated(self, api):
        """PRD §2.1: "Missing or empty values on either header produce
        ERR_UNAUTHENTICATED with HTTP 401."

        Claim: omitting X-User-ID returns ERR_UNAUTHENTICATED.
        """
        headers = {"X-User-Role": "TopologyApprover"}
        resp = api.create_network(create_network_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_header_unauthenticated(self, api):
        """PRD §2.1: "Missing or empty values on either header produce
        ERR_UNAUTHENTICATED with HTTP 401."

        Claim: omitting X-User-Role returns ERR_UNAUTHENTICATED.
        """
        headers = {"X-User-ID": "some-id"}
        resp = api.create_network(create_network_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_empty_user_id_unauthenticated(self, api):
        """PRD §2.1: "Missing or empty values on either header produce
        ERR_UNAUTHENTICATED with HTTP 401."
        """
        headers = build_user_headers("", "TopologyApprover")
        resp = api.create_network(create_network_payload(), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# §2.1 — RBAC enforcement
# ===========================================================================
class TestRBAC:
    """PRD §2.1: role not permitted → ERR_FORBIDDEN 403."""

    def test_engineer_cannot_create_network(self, api, te_headers):
        """PRD §2.1: "When the role does not include the requested
        operation in its permission matrix, the request is rejected with
        ERR_FORBIDDEN and HTTP 403."

        PRD §4 RBAC table: POST /networks is restricted to TopologyApprover.
        Claim: TopologyEngineer attempting POST /networks → ERR_FORBIDDEN.
        """
        resp = api.create_network(create_network_payload(), te_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_control_operator_cannot_create_network(self, api, co_headers):
        """PRD §2.1: "the request is rejected with ERR_FORBIDDEN and HTTP 403."

        PRD §4: POST /networks is TopologyApprover-only.
        """
        resp = api.create_network(create_network_payload(), co_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_auditor_cannot_advance_clock(self, api, auditor_headers,
                                          ta_headers):
        """PRD §2.1 + §4: "/_clock/advance" is restricted to ControlOperator.

        Claim: an Auditor attempt → ERR_FORBIDDEN.
        """
        # First create a network so the path-id resolves.
        net_resp = api.create_network(create_network_payload(), ta_headers)
        network = validate_success(net_resp, expected_status=201)
        resp = api.advance_clock(network["id"], {"advance_ms": 1000},
                                 auditor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# §2.2 — Response envelope shape
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2 standard success and error envelope shapes."""

    def test_success_envelope_shape(self, api, ta_headers):
        """PRD §2.2: success body contains meta {api_request_id,
        api_request_timestamp}, response_type, and data fields.
        Claim: a POST /networks 201 response carries the envelope."""
        resp = api.create_network(create_network_payload(), ta_headers)
        body = resp.json()
        assert resp.status_code == 201
        assert "meta" in body and "data" in body
        assert "response_type" in body
        assert body["response_type"] in ("object", "array")
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: error body contains data.error_id and data.message.

        Claim: an unauthenticated request returns an error envelope with
        both fields populated.
        """
        resp = api.create_network(create_network_payload(),
                                  {"X-User-Role": "TopologyApprover"})
        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED.value
        assert isinstance(body["data"]["message"], str)


# ===========================================================================
# §2.3 — Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: list endpoints accept limit (1..100, default 10) and offset
    (default 0); meta carries limit, offset, total_count, has_more."""

    def test_list_dmas_returns_pagination_meta(self, api, te_headers):
        """PRD §2.3: "The response meta block carries limit, offset,
        total_count, and has_more so a client can detect whether further
        pages remain."
        """
        from test_helpers import (
            create_network, create_dma, TA,
        )
        net = create_network(api)
        create_dma(api, net["id"])
        resp = api.list_dmas(net["id"], te_headers)
        data, meta = validate_paginated(resp)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert meta["limit"] == 10  # PRD §2.3: "default limit is 10".


# ===========================================================================
# §2.7 — Left-to-right path resolution
# ===========================================================================
class TestNestedPathResolution:
    """PRD §2.7: parent 404 surfaces before child existence is checked."""

    def test_missing_network_404s_before_dma_check(self, api, te_headers):
        """PRD §2.7: "if the Network does not exist, the request is
        rejected with ERR_NOT_FOUND before any child resource is even
        looked up."

        Claim: GET /networks/{bogus}/dmas/{anything} → ERR_NOT_FOUND for
        the Network, not for the DMA.
        """
        resp = api.get_dma(NON_EXISTENT_UUID, NON_EXISTENT_UUID, te_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
