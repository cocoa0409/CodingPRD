"""Authentication, role validation, response envelope, and pagination.

Coverage targets (PRD §2.1, §2.2, §2.3, §2.8):
- Missing X-User-Role / X-User-ID -> ERR_AUTH_REQUIRED (401).
- Role lacks permission -> ERR_FORBIDDEN (403).
- Path-resolution: taxpayer/return/resource NOT_FOUND.
- Standard envelope shape.
- Pagination defaults / bounds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    create_taxpayer,
    make_taxpayer_headers,
    setup_active_taxpayer_with_draft_return,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing headers — PRD §2.1
# ===========================================================================
class TestAuthRequired:

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_REQUIRED".

        Claim: omitting both auth headers -> ERR_AUTH_REQUIRED / 401.
        """
        resp = api._request("GET", "/tax-returns", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_REQUIRED".

        Claim: missing X-User-Role -> ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/tax-returns",
            headers={"X-User-ID": "any"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected
        with ERR_AUTH_REQUIRED".

        Claim: missing X-User-ID -> ERR_AUTH_REQUIRED.
        """
        resp = api._request(
            "GET", "/tax-returns",
            headers={"X-User-Role": "Taxpayer"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_REQUIRED.value)


# ===========================================================================
# Role lacks permission — PRD §2.1
# ===========================================================================
class TestForbidden:

    def test_irs_adjudicator_cannot_create_return(
        self, api, irs_adjudicator_headers,
    ):
        """PRD §2.1: "a request whose role is not authorised for the
        targeted operation is rejected with ERR_FORBIDDEN."

        Claim: IRSAdjudicator role is NOT permitted to POST
        /tax-returns (PRD §4 lists Taxpayer only for that endpoint).
        """
        resp = api.create_tax_return(
            {
                "taxpayer_id": NON_EXISTENT_UUID,
                "tax_year": 2025,
                "filing_status": "SINGLE",
            },
            irs_adjudicator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_taxpayer_cannot_compliance_lock(self, api):
        """PRD §2.1: "a request whose role is not authorised for the
        targeted operation is rejected with ERR_FORBIDDEN."

        Claim: Taxpayer role is NOT permitted to POST
        /taxpayers/{id}/compliance-lock (PRD §4 lists IRSAdjudicator
        only).
        """
        taxpayer = create_taxpayer()
        resp = api.compliance_lock(
            taxpayer["id"], {}, make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_taxpayer_cannot_decide_efiling(self, api):
        """PRD §2.1: "a request whose role is not authorised for the
        targeted operation is rejected with ERR_FORBIDDEN."

        Claim: Taxpayer cannot POST /efilings/{id}/decide.
        """
        taxpayer = create_taxpayer()
        resp = api.decide_efiling(
            NON_EXISTENT_UUID,
            {"outcome": "ACCEPTED"},
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_taxpayer_cannot_read_audit_logs(self, api):
        """PRD §2.11: "The audit log is read-only and is exposed only
        to the IRSAdjudicator role".

        Claim: Taxpayer GET /audit-logs -> ERR_FORBIDDEN.
        """
        taxpayer = create_taxpayer()
        resp = api.list_audit_logs(make_taxpayer_headers(taxpayer["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Path resolution — PRD §2.8 and §2.10 (priority 3/4/5)
# ===========================================================================
class TestPathResolution:

    def test_taxpayer_not_found(self, api, irs_adjudicator_headers):
        """PRD §2.8: "A Taxpayer referenced in a path that does not
        exist produces ERR_TAXPAYER_NOT_FOUND."

        Claim: GET /taxpayers/{unknown-uuid} -> ERR_TAXPAYER_NOT_FOUND.
        """
        resp = api.get_taxpayer(NON_EXISTENT_UUID, irs_adjudicator_headers)
        validate_error(resp, ApiErrorId.ERR_TAXPAYER_NOT_FOUND.value)

    def test_return_not_found(self, api, irs_adjudicator_headers):
        """PRD §2.8: "A request whose tax-returns/{id} segment does not
        resolve fails with ERR_RETURN_NOT_FOUND before any child
        lookup is even attempted."

        Claim: GET /tax-returns/{unknown} -> ERR_RETURN_NOT_FOUND.
        """
        resp = api.get_tax_return(
            NON_EXISTENT_UUID, irs_adjudicator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_FOUND.value)

    def test_child_resource_not_found_under_existing_return(
        self, api,
    ):
        """PRD §2.8: "Once the parent is known to exist, the child
        identifier is checked and produces ERR_RESOURCE_NOT_FOUND if
        it does not match."

        Claim: PATCH /income-documents/{unknown} on an existing return
        -> ERR_RESOURCE_NOT_FOUND.
        """
        taxpayer, _ = setup_active_taxpayer_with_draft_return()
        resp = api.patch_income_document(
            NON_EXISTENT_UUID, {"wages_cents": 1},
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND.value)

    def test_parent_resolved_before_child(self, api):
        """PRD §2.8: "Endpoints whose URL embeds more than one
        identifier ... validate path identifiers in strict
        left-to-right order. A request whose tax-returns/{id} segment
        does not resolve fails with ERR_RETURN_NOT_FOUND before any
        child lookup is even attempted."

        Claim: nested call where BOTH parent and child are unknown
        surfaces ERR_RETURN_NOT_FOUND (parent error), not
        ERR_RESOURCE_NOT_FOUND.
        """
        taxpayer = create_taxpayer()
        resp = api.create_income_document(
            NON_EXISTENT_UUID, {"doc_type": "W2", "payer_ein": "1", "payer_name": "x"},
            make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_FOUND.value)


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_structure(self, api, irs_adjudicator_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" with meta.api_request_id starting with 'req_' and
        a response_type and data.

        Claim: successful POST /taxpayers returns the standard
        envelope.
        """
        from test_helpers import create_taxpayer_payload
        resp = api.create_taxpayer(
            create_taxpayer_payload(), irs_adjudicator_headers,
        )
        assert resp.status_code == 201
        body = resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id must start with 'req_'; got "
            f"{meta['api_request_id']!r}"
        )
        assert body["response_type"] == "object"

    def test_error_envelope_structure(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format" with response_type 'error',
        a data.error_id, and data.message.

        Claim: ERR_AUTH_REQUIRED response carries the documented
        envelope shape.
        """
        resp = api._request("GET", "/tax-returns", headers={})
        body = resp.json()
        assert body["response_type"] == "error"
        assert "meta" in body
        assert "api_request_id" in body["meta"]
        assert isinstance(body["data"]["error_id"], str)
        assert isinstance(body["data"]["message"], str)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_default_limit_is_ten(self, api, irs_adjudicator_headers):
        """PRD §2.3: "The limit parameter caps the number of items
        returned and defaults to 10 when omitted".

        Claim: omitted limit -> meta.limit == 10.
        """
        resp = api.list_estimated_payments(irs_adjudicator_headers)
        _, meta = validate_paginated(resp)
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT, (
            f"default limit must be {PAGINATION_DEFAULT_LIMIT}; "
            f"got {meta['limit']}"
        )

    def test_pagination_max_limit(self, api, irs_adjudicator_headers):
        """PRD §2.3: "with a minimum of 1 and a maximum of 100".

        Claim: limit=100 succeeds and the response carries limit=100.
        """
        resp = api.list_estimated_payments(
            irs_adjudicator_headers,
            params={"limit": PAGINATION_MAX_LIMIT, "offset": 0},
        )
        _, meta = validate_paginated(resp)
        assert meta["limit"] == PAGINATION_MAX_LIMIT
        assert meta["offset"] == 0

    def test_pagination_carries_total_count_and_has_more(
        self, api, irs_adjudicator_headers,
    ):
        """PRD §2.3: "The meta envelope of every list response carries
        limit, offset, total_count ... and has_more (a boolean
        indicating whether further pages remain)."

        Claim: list responses always include total_count and has_more.
        """
        resp = api.list_estimated_payments(irs_adjudicator_headers)
        _, meta = validate_paginated(resp)
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)


# ===========================================================================
# Ownership — PRD §2.1
# ===========================================================================
class TestOwnership:

    def test_taxpayer_cannot_read_other_taxpayer_return(self, api):
        """PRD §2.1: "A Taxpayer principal may only read and mutate
        resources whose ownership chain resolves to their own id."

        Claim: Taxpayer A is forbidden from GETing Taxpayer B's
        TaxReturn.
        """
        # Two distinct active taxpayers, each with their own return.
        taxpayer_a, _ = setup_active_taxpayer_with_draft_return()
        taxpayer_b, return_b = setup_active_taxpayer_with_draft_return()
        # Taxpayer A tries to read Taxpayer B's return.
        resp = api.get_tax_return(
            return_b["id"], make_taxpayer_headers(taxpayer_a["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_taxpayer_can_read_own_return(self, api):
        """PRD §2.1: "A Taxpayer principal may only read and mutate
        resources whose ownership chain resolves to their own id."

        Claim: a Taxpayer can GET their own TaxReturn.
        """
        taxpayer, tax_return = setup_active_taxpayer_with_draft_return()
        resp = api.get_tax_return(
            tax_return["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        data = validate_success(resp)
        assert data["id"] == tax_return["id"]
        assert data["taxpayer_id"] == taxpayer["id"]
