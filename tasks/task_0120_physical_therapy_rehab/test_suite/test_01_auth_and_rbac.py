"""Auth headers, role-based access control, NotFound, response envelope.

PRD §2.1 (auth/RBAC), §2.2 (envelope), §2.3 (pagination), §2.5
(left-to-right path resolution).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_episode_payload,
    create_patient_payload,
    create_therapist_payload,
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
        """PRD §2.1: "Every request other than GET /_health must carry
        two HTTP headers: X-User-ID, identifying the acting principal,
        and X-User-Role, declaring the principal's operational
        capacity. If either header is missing or empty the request is
        rejected with ERR_AUTH_MISSING."

        Claim: request with neither header set → ERR_AUTH_MISSING.
        """
        res = api.create_therapist(create_therapist_payload(), headers={})
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty the request
        is rejected with ERR_AUTH_MISSING."

        Claim: omitting X-User-ID → ERR_AUTH_MISSING.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            headers={"X-User-Role": "ClinicAdmin"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty the request
        is rejected with ERR_AUTH_MISSING."

        Claim: omitting X-User-Role → ERR_AUTH_MISSING.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            headers={"X-User-ID": "anyone"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty the request
        is rejected with ERR_AUTH_MISSING."

        Claim: empty X-User-ID → ERR_AUTH_MISSING.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            headers={"X-User-ID": "", "X-User-Role": "ClinicAdmin"},
        )
        validate_error(res, "ERR_AUTH_MISSING")

    def test_empty_user_role_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty the request
        is rejected with ERR_AUTH_MISSING."

        Claim: empty X-User-Role → ERR_AUTH_MISSING.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            headers={"X-User-ID": "admin-x", "X-User-Role": ""},
        )
        validate_error(res, "ERR_AUTH_MISSING")


# ===========================================================================
# §2.1 / §4 RBAC — wrong role → ERR_FORBIDDEN
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "If the role is not authorized for the requested
    operation the request is rejected with ERR_FORBIDDEN.\""""

    def test_therapist_cannot_create_patient(self, api):
        """PRD §4: POST /patients is authorized for ClinicAdmin only.

        PRD §2.1: "If the role is not authorized for the requested
        operation the request is rejected with ERR_FORBIDDEN."

        Claim: Therapist calling POST /patients → ERR_FORBIDDEN.
        """
        res = api.create_patient(
            create_patient_payload(),
            TEST_USERS["therapist_fallback_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_biller_cannot_create_episode(self, api):
        """PRD §4: POST /episodes is authorized for Therapist only.

        Claim: Biller → ERR_FORBIDDEN.
        """
        res = api.create_episode(
            create_episode_payload(patient_id=NON_EXISTENT_UUID),
            TEST_USERS["biller_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_clinic_admin_cannot_create_episode(self, api):
        """PRD §4: POST /episodes is authorized for Therapist only.

        Claim: ClinicAdmin → ERR_FORBIDDEN.
        """
        res = api.create_episode(
            create_episode_payload(patient_id=NON_EXISTENT_UUID),
            TEST_USERS["clinic_admin_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_patient_cannot_create_therapist(self, api):
        """PRD §4: POST /therapists is authorized for ClinicAdmin only.

        Claim: Patient → ERR_FORBIDDEN.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            TEST_USERS["patient_fallback_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_therapist_cannot_submit_claim(self, api):
        """PRD §4: POST /visits/{id}/submit-claim is authorized for
        Biller only.

        Claim: Therapist → ERR_FORBIDDEN.
        """
        res = api.submit_claim(
            NON_EXISTENT_UUID, TEST_USERS["therapist_fallback_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.5 Path resolution — ERR_NOT_FOUND on first unresolved path id
# ===========================================================================
class TestPathResolution:
    """PRD §2.5 (Nested Path Resolution)."""

    def test_fetch_unknown_therapist_returns_not_found(self, api):
        """PRD §2.5: "the system resolves them strictly left-to-right
        and returns ERR_NOT_FOUND against the first id that does not
        resolve."

        Claim: GET /therapists/{id} for a UUID that does not exist
        returns ERR_NOT_FOUND.
        """
        res = api.get_therapist(
            NON_EXISTENT_UUID, TEST_USERS["clinic_admin_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_fetch_unknown_episode_returns_not_found(self, api):
        """PRD §2.5 (path resolution).

        Claim: GET /episodes/{id} for an unknown id → ERR_NOT_FOUND.
        """
        res = api.get_episode(
            NON_EXISTENT_UUID, TEST_USERS["clinic_admin_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_fetch_unknown_patient_returns_not_found(self, api):
        """PRD §2.5 (path resolution).

        Claim: GET /patients/{id} for an unknown id → ERR_NOT_FOUND.
        """
        res = api.get_patient(
            NON_EXISTENT_UUID, TEST_USERS["clinic_admin_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.2 Response envelope (success + error)
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2."""

    def test_success_envelope_object_for_create_therapist(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format ... The
        response_type is either object for a single resource or array
        for a list of resources."

        Claim: POST /therapists succeeds with response_type=object and
        a data payload that is a dict.
        """
        from test_helpers import create_therapist_payload, validate_success
        res = api.create_therapist(
            create_therapist_payload(credential="PT"),
            TEST_USERS["clinic_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert isinstance(data, dict), (
            "Success response.data must be a dict (response_type=object)"
        )
        assert "id" in data

    def test_error_envelope_for_unknown_resource(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format ... data: error_id, message."

        Claim: 4xx response carries response_type=error and a data
        object with error_id + message.
        """
        res = api.get_therapist(
            NON_EXISTENT_UUID, TEST_USERS["clinic_admin_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.3 Pagination — limit / offset range
# ===========================================================================
class TestPagination:
    """PRD §2.3."""

    def test_list_therapists_returns_paginated_envelope(self, api):
        """PRD §2.3: "Each list response includes limit, offset,
        total_count, and has_more in the meta envelope."

        Claim: GET /therapists returns a paginated envelope with the
        four meta fields.
        """
        res = api.list_therapists(TEST_USERS["clinic_admin_headers"])
        data, meta = validate_paginated(res)
        assert isinstance(data, list)
        for field in ("limit", "offset", "total_count", "has_more"):
            assert field in meta, (
                f"meta.{field} must be present per PRD §2.3"
            )

    @pytest.mark.parametrize("limit", [0, -1, 101, 1000])
    def test_invalid_limit_rejected(self, api, limit):
        """PRD §2.3: "Any limit outside [1, 100] or offset below 0 is
        rejected with ERR_PAGINATION_RANGE."

        Claim: limit outside [1, 100] → ERR_PAGINATION_RANGE.
        """
        res = api.list_therapists(
            TEST_USERS["clinic_admin_headers"],
            params={"limit": limit},
        )
        validate_error(res, "ERR_PAGINATION_RANGE")

    @pytest.mark.parametrize("offset", [-1, -10])
    def test_invalid_offset_rejected(self, api, offset):
        """PRD §2.3: "Any limit outside [1, 100] or offset below 0 is
        rejected with ERR_PAGINATION_RANGE."

        Claim: offset < 0 → ERR_PAGINATION_RANGE.
        """
        res = api.list_therapists(
            TEST_USERS["clinic_admin_headers"],
            params={"offset": offset},
        )
        validate_error(res, "ERR_PAGINATION_RANGE")

    def test_boundary_limit_1_accepted(self, api):
        """PRD §2.3: "limit ... has a minimum of 1."

        Claim: limit=1 is accepted.
        """
        res = api.list_therapists(
            TEST_USERS["clinic_admin_headers"],
            params={"limit": 1},
        )
        data, meta = validate_paginated(res)
        assert meta["limit"] == 1

    def test_boundary_limit_100_accepted(self, api):
        """PRD §2.3: "limit ... a maximum of 100."

        Claim: limit=100 is accepted.
        """
        res = api.list_therapists(
            TEST_USERS["clinic_admin_headers"],
            params={"limit": 100},
        )
        data, meta = validate_paginated(res)
        assert meta["limit"] == 100
