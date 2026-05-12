"""Authentication, RBAC, response envelope, pagination, and nested-path
existence checks. Covers PRD §2.1, §2.2, §2.3, §2.5."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_patient_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


# =========================================================================
# §2.1 -- Headers must be present.
# =========================================================================
class TestMissingAuthHeaders:

    def test_missing_user_id_header(self, api):
        """PRD §2.1: 'Every request to the API must carry two HTTP
        headers: X-User-ID, identifying the acting user, and X-User-Role,
        naming the role being asserted. If either header is absent the
        request is rejected with ERR_AUTH_MISSING.'

        Claim: missing X-User-ID -> ERR_AUTH_MISSING / 401.
        """
        bad = {"X-User-Role": "PlatformAdmin"}
        res = api._request(
            "POST", "/consultation/patients",
            create_patient_payload(), bad,
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_role_header(self, api):
        """PRD §2.1: 'Every request to the API must carry two HTTP
        headers: X-User-ID, identifying the acting user, and X-User-Role,
        naming the role being asserted. If either header is absent the
        request is rejected with ERR_AUTH_MISSING.'

        Claim: missing X-User-Role -> ERR_AUTH_MISSING / 401.
        """
        bad = {"X-User-ID": "admin-001"}
        res = api._request(
            "GET", "/consultation/department-mappings", headers=bad,
        )
        validate_error(res, ApiErrorId.ERR_AUTH_MISSING.value)


# =========================================================================
# §2.1 -- RBAC: role-not-authorised yields ERR_FORBIDDEN.
# =========================================================================
class TestRoleAuthorization:

    def test_patient_cannot_create_patient(
        self, api, patient_headers_fallback,
    ):
        """PRD §2.1: 'if the asserted role lacks permission for the
        requested operation, the request is rejected with ERR_FORBIDDEN.'
        PRD §4: POST /consultation/patients is authorised only to
        PlatformAdmin.

        Claim: Patient attempting POST /consultation/patients -> 403
        ERR_FORBIDDEN.
        """
        res = api.create_patient(
            create_patient_payload(), patient_headers_fallback,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_doctor_cannot_create_pharmacist(
        self, api, doctor_headers_fallback,
    ):
        """PRD §2.1: 'if the asserted role lacks permission for the
        requested operation, the request is rejected with ERR_FORBIDDEN.'
        PRD §4: POST /consultation/pharmacists is authorised only to
        PlatformAdmin.

        Claim: Doctor attempting POST /consultation/pharmacists -> 403.
        """
        res = api._request(
            "POST", "/consultation/pharmacists",
            {"full_name": "Px", "license_number": "LIC1"},
            doctor_headers_fallback,
        )
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# =========================================================================
# §2.2 -- Standard success envelope.
# =========================================================================
class TestResponseEnvelope:

    def test_get_list_envelope_meta_keys(self, api, admin_headers):
        """PRD §2.2: list responses carry meta.limit, meta.offset,
        meta.total_count, meta.has_more.

        Claim: a GET-list call returns meta with all four pagination keys.
        """
        res = api.list_department_mappings(admin_headers)
        data, meta = validate_paginated(res)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta missing key {key!r}"

    def test_create_returns_201(self, api, admin_headers):
        """PRD §4: 'Operations that create new resources return HTTP 201.'

        Claim: POST /consultation/department-mappings returns 201.
        """
        from test_helpers import create_department_mapping_payload
        res = api.create_department_mapping(
            create_department_mapping_payload(
                department_code=f"DEPT_{__import__('uuid').uuid4().hex[:6]}",
            ),
            admin_headers,
        )
        validate_success(res, expected_status=201)


# =========================================================================
# §2.3 -- Pagination validation.
# =========================================================================
class TestPaginationValidation:

    @pytest.mark.parametrize("bad_params", [
        {"limit": 0},
        {"limit": 101},
        {"offset": -1},
    ])
    def test_pagination_out_of_range(self, api, admin_headers, bad_params):
        """PRD §2.3: 'limit ... with a minimum of 1 and a maximum of 100.
        offset ... must be at least 0. When the caller supplies values
        outside these bounds, the request is rejected with
        ERR_PAGINATION_INVALID.'

        Claim: limit < 1, limit > 100, or offset < 0 -> ERR_PAGINATION_INVALID.
        """
        res = api.list_department_mappings(admin_headers, params=bad_params)
        validate_error(res, ApiErrorId.ERR_PAGINATION_INVALID.value)

    def test_pagination_defaults(self, api, admin_headers):
        """PRD §2.3: 'limit ... if not supplied, it defaults to 10' and
        'offset ... if not supplied, it defaults to 0'.

        Claim: omitted pagination params -> meta.limit == 10, meta.offset == 0.
        """
        res = api.list_department_mappings(admin_headers)
        data, meta = validate_paginated(res)
        assert meta["limit"] == 10
        assert meta["offset"] == 0


# =========================================================================
# §2.5 -- Nested resource validation: path 404 vs body 422.
# =========================================================================
class TestPathExistence:

    def test_get_missing_patient_returns_404(self, api, admin_headers):
        """PRD §2.5: 'each identifier is validated in left-to-right order,
        and the first one that does not resolve yields a 404 ERR_NOT_FOUND.'

        Claim: GET /consultation/patients/{non-existent} -> 404 ERR_NOT_FOUND.
        """
        res = api.get_patient(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_missing_consultation_returns_404(self, api, admin_headers):
        """PRD §2.5: path-existence yields 404 ERR_NOT_FOUND.

        Claim: GET /consultation/consultations/{non-existent} -> 404.
        """
        res = api.get_consultation(NON_EXISTENT_UUID, admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
