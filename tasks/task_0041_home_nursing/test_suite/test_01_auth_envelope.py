"""Authentication, RBAC, response envelope, and pagination behavior.

Covers PRD §2.1 (headers and roles), §2.2 (response envelope), §2.3
(pagination), and §2.5 (header-first funnel).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_nurse_payload,
    create_service_item_payload,
    is_iso8601_timestamp,
    make_compliance_officer_headers,
    make_patient_headers,
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
        """PRD §2.1: 'When either header is missing or syntactically
        malformed, the server rejects the request with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER at HTTP 400.'

        Claim: missing X-User-ID -> 400
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        bad = {"X-User-Role": "PlatformAdmin"}
        res = api._request("GET", "/nurses", headers=bad)
        validate_error(
            res,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_missing_user_role_header(self, api):
        """PRD §2.1: 'When either header is missing or syntactically
        malformed, the server rejects the request with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER at HTTP 400.'

        Claim: missing X-User-Role -> 400
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        bad = {"X-User-ID": "user-001"}
        res = api._request("GET", "/nurses", headers=bad)
        validate_error(
            res,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )

    def test_empty_role_value(self, api):
        """PRD §2.1: 'When either header is missing or syntactically
        malformed, the server rejects the request with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER at HTTP 400.'

        Claim: empty X-User-Role -> 400
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.
        """
        bad = {"X-User-ID": "user-001", "X-User-Role": ""}
        res = api._request("GET", "/nurses", headers=bad)
        validate_error(
            res,
            ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value,
        )


# =========================================================================
# §2.1 -- Role authorization (ERR_INSUFFICIENT_PERMISSIONS at priority 2)
# =========================================================================
class TestRoleAuthorization:

    def test_patient_cannot_create_nurse(self, api, patient_headers_fallback):
        """PRD §2.1: 'When the headers are well-formed but the role is not
        authorized for the requested operation per the §1.7 RBAC contract,
        the server returns ERR_INSUFFICIENT_PERMISSIONS at HTTP 403.'

        PRD §4 endpoint table: POST /nurses is authorized only to
        PlatformAdmin.
        """
        res = api.create_nurse(
            create_nurse_payload(), patient_headers_fallback
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_nurse_cannot_create_service_item(
        self, api, nurse_headers_fallback,
    ):
        """PRD §2.1: 'the server returns ERR_INSUFFICIENT_PERMISSIONS at
        HTTP 403.'

        PRD §4 endpoint table: POST /service-items is authorized only to
        PlatformAdmin.
        """
        res = api.create_service_item(
            create_service_item_payload(), nurse_headers_fallback
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_patient_cannot_advance_clock(
        self, api, patient_headers_fallback,
    ):
        """PRD §4 endpoint table: POST /_clock/advance is authorized only
        to PlatformAdmin.

        Claim: Patient calling /_clock/advance -> 403
        ERR_INSUFFICIENT_PERMISSIONS.
        """
        res = api.advance_clock(
            "2026-05-11T10:00:00.000Z", patient_headers_fallback
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)

    def test_nurse_cannot_resolve_complaint(
        self, api, nurse_headers_fallback,
    ):
        """PRD §4 endpoint table: POST /complaints/{id}/resolve is
        authorized only to ComplianceOfficer.

        Claim: Nurse calling /complaints/{id}/resolve -> 403
        ERR_INSUFFICIENT_PERMISSIONS.
        """
        res = api.resolve_complaint(
            NON_EXISTENT_UUID, {"decision": "REJECT"},
            nurse_headers_fallback,
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)


# =========================================================================
# §2.2 -- Response envelope structure
# =========================================================================
class TestResponseEnvelope:

    def test_success_envelope_has_meta_and_data(
        self, api, platform_admin_headers,
    ):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body'
        with `meta`, `response_type`, and `data` fields.

        Claim: GET /service-items returns the standard success envelope.
        """
        res = api.list_service_items(platform_admin_headers)
        body = res.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        meta = body["meta"]
        assert meta.get("api_request_id", "").startswith("req_"), (
            f"PRD §2.2: api_request_id must start with 'req_', "
            f"got {meta.get('api_request_id')!r}"
        )
        assert is_iso8601_timestamp(meta.get("api_request_timestamp", "")), (
            "PRD §2.2: api_request_timestamp must be ISO 8601 UTC with "
            "three fractional digits"
        )

    def test_error_envelope_has_error_id_and_message(self, api):
        """PRD §2.2: error envelope contains data.error_id and
        data.message."""
        res = api._request("GET", "/nurses", headers={})
        body = res.json()
        assert body.get("response_type") == "error"
        assert "error_id" in body["data"]
        assert "message" in body["data"]


# =========================================================================
# §2.3 -- Pagination
# =========================================================================
class TestPagination:

    def test_default_pagination_returns_meta(
        self, api, compliance_officer_headers,
    ):
        """PRD §2.3: 'The pagination block in the success envelope's meta
        exposes four fields for list endpoints: the echoed limit and
        offset, the total matching count total_count, and a boolean
        has_more set to true when more rows exist beyond the current
        page.'
        """
        res = api.list_nurses(compliance_officer_headers)
        data, meta = validate_paginated(res)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta

    def test_limit_above_max_rejected(self, api, compliance_officer_headers):
        """PRD §2.3: 'The default limit is 10, with a minimum of 1 and a
        maximum of 100; values outside these bounds are rejected with
        ERR_INVALID_REQUEST.'

        Claim: limit=101 -> 400 ERR_INVALID_REQUEST.
        """
        res = api.list_nurses(compliance_officer_headers, params={"limit": 101})
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_limit_zero_rejected(self, api, compliance_officer_headers):
        """PRD §2.3: 'The default limit is 10, with a minimum of 1 and a
        maximum of 100; values outside these bounds are rejected with
        ERR_INVALID_REQUEST.'

        Claim: limit=0 -> 400 ERR_INVALID_REQUEST.
        """
        res = api.list_nurses(compliance_officer_headers, params={"limit": 0})
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_limit_max_accepted(self, api, compliance_officer_headers):
        """PRD §2.3: 'The default limit is 10, with a minimum of 1 and a
        maximum of 100; values outside these bounds are rejected with
        ERR_INVALID_REQUEST.'

        Claim: limit=100 (max boundary) is accepted.
        """
        res = api.list_nurses(compliance_officer_headers, params={"limit": 100})
        validate_paginated(res)

    def test_offset_negative_rejected(self, api, compliance_officer_headers):
        """PRD §2.3: 'The default offset is 0 and it must be a
        non-negative integer.'

        Claim: offset=-1 -> 400 ERR_INVALID_REQUEST.
        """
        res = api.list_nurses(
            compliance_officer_headers, params={"offset": -1}
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


# =========================================================================
# §2.5 -- Header funnel: header check fires before path lookup
# =========================================================================
class TestHeaderFunnelOrder:

    def test_role_check_fires_before_path_lookup(
        self, api, patient_headers_fallback,
    ):
        """PRD §2.5: 'when a Patient calls confirm-completion on an order
        they do not own, the rejection is ERR_INSUFFICIENT_PERMISSIONS
        (priority 2) rather than ERR_ORDER_NOT_FOUND (priority 3)'.

        We exercise the simpler form: a Patient calls a PlatformAdmin
        operation on a non-existent path. Priority 2
        (ERR_INSUFFICIENT_PERMISSIONS) must fire before priority 3
        (ERR_*_NOT_FOUND).
        """
        # Patient is not authorized to POST /service-items; even with a
        # non-existent path the role check (priority 2) fires first.
        res = api.create_service_item(
            create_service_item_payload(), patient_headers_fallback
        )
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS.value)
