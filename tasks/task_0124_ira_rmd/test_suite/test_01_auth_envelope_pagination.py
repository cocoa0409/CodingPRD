"""Authentication, role validation, response envelope, and pagination.

Coverage targets (PRD §2.1, §2.2, §2.3):
- Missing X-User-ID or X-User-Role header -> ERR_AUTH_MISSING (401).
- Unrecognized X-User-Role -> ERR_AUTH_INVALID_ROLE (401).
- Role recognized but lacks endpoint permission -> ERR_FORBIDDEN (403).
- Success / error response envelope shape.
- Pagination parameters limit / offset bounds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_participant_payload,
    setup_owner_rmd_eligible,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing headers — PRD §2.1
# ===========================================================================
class TestAuthMissing:
    """PRD §2.1: 'A missing or empty X-User-ID or X-User-Role causes the
    request to be rejected with ERR_AUTH_MISSING.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A missing or empty X-User-ID or X-User-Role causes
        the request to be rejected with ERR_AUTH_MISSING."

        Claim: omitting both auth headers -> ERR_AUTH_MISSING / 401.
        """
        resp = api._request("GET", "/_clock", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A missing or empty X-User-ID or X-User-Role causes
        the request to be rejected with ERR_AUTH_MISSING."

        Claim: only X-User-ID present -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/_clock", headers={"X-User-ID": "anything"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A missing or empty X-User-ID or X-User-Role causes
        the request to be rejected with ERR_AUTH_MISSING."

        Claim: only X-User-Role present -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/_clock", headers={"X-User-Role": "Custodian"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: "A missing or empty X-User-ID or X-User-Role causes
        the request to be rejected with ERR_AUTH_MISSING."

        Claim: empty X-User-ID -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/_clock",
            headers={"X-User-ID": "", "X-User-Role": "Custodian"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# Invalid role — PRD §2.1
# ===========================================================================
class TestAuthInvalidRole:
    """PRD §2.1: 'A header that names a role outside the four-value set
    is rejected with ERR_AUTH_INVALID_ROLE.'"""

    @pytest.mark.parametrize(
        "bad_role",
        ["Admin", "User", "Manager", "Member", "participant"],
    )
    def test_unknown_role_rejected(self, api, bad_role):
        """PRD §2.1: "A header that names a role outside the four-value
        set is rejected with ERR_AUTH_INVALID_ROLE."

        Claim: unrecognized X-User-Role -> ERR_AUTH_INVALID_ROLE / 401.
        """
        resp = api._request(
            "GET", "/_clock",
            headers={"X-User-Role": bad_role, "X-User-ID": "user-1"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_INVALID_ROLE.value)


# ===========================================================================
# RBAC enforcement — PRD §2.1, §4
# ===========================================================================
class TestRbacForbidden:
    """PRD §2.1: 'A role that is recognized but not authorized for the
    requested endpoint is rejected with ERR_FORBIDDEN.'"""

    def test_auditor_cannot_create_participant(self, api,
                                               auditor_headers):
        """PRD §4: "POST /participants — Authorized Role(s): Custodian"
        and PRD §2.1: "A role that is recognized but not authorized for
        the requested endpoint is rejected with ERR_FORBIDDEN."

        Claim: Auditor cannot POST /participants.
        """
        resp = api.create_participant(
            create_participant_payload(), auditor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_compliance_officer_cannot_create_participant(
        self, api, compliance_headers,
    ):
        """PRD §4: "POST /participants — Authorized Role(s): Custodian"
        and PRD §2.1: "A role that is recognized but not authorized for
        the requested endpoint is rejected with ERR_FORBIDDEN."

        Claim: ComplianceOfficer cannot POST /participants.
        """
        resp = api.create_participant(
            create_participant_payload(), compliance_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_participant_role_cannot_create_participant(
        self, api, participant_fallback_headers,
    ):
        """PRD §4: "POST /participants — Authorized Role(s): Custodian"
        and PRD §2.1: "A role that is recognized but not authorized for
        the requested endpoint is rejected with ERR_FORBIDDEN."

        Claim: Participant cannot POST /participants.
        """
        resp = api.create_participant(
            create_participant_payload(), participant_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_auditor_cannot_freeze_account(self, api, auditor_headers,
                                           custodian_headers):
        """PRD §4: "POST /accounts/{account_id}/freeze — Authorized
        Role(s): Custodian, ComplianceOfficer" and PRD §2.1: "A role
        that is recognized but not authorized for the requested
        endpoint is rejected with ERR_FORBIDDEN."

        Claim: Auditor cannot POST /accounts/{id}/freeze.
        """
        p, a = setup_owner_rmd_eligible()
        resp = api.freeze_account(a["id"], auditor_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Success envelope shape — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: success bodies carry meta, response_type, data."""

    def test_get_clock_envelope_shape(self, api, auditor_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body".

        Claim: GET /_clock returns the standard success envelope.
        """
        resp = api.get_clock(auditor_headers)
        data = validate_success(resp, expected_status=200)
        assert isinstance(data, dict)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:
    """PRD §2.3: limit defaults to 10, min 1, max 100; offset defaults
    to 0."""

    def test_list_forms_1099r_returns_paginated_meta(
        self, api, custodian_headers,
    ):
        """PRD §2.3: "The meta object on every list response includes
        the four pagination-related fields limit, offset, total_count,
        and has_more."

        Claim: list endpoint returns paginated meta fields.
        """
        p, _ = setup_owner_rmd_eligible()
        resp = api.list_forms_1099r(
            p["id"], custodian_headers, params={"tax_year": 2026},
        )
        data, meta = validate_paginated(resp)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, (
                f"meta missing {key}; got keys: {list(meta)}"
            )

    def test_pagination_limit_above_max_rejected(self, api,
                                                 custodian_headers):
        """PRD §2.3: "The limit parameter defaults to 10, with a
        minimum of 1 and a maximum of 100."

        Claim: limit > 100 -> ERR_VALIDATION.
        """
        p, _ = setup_owner_rmd_eligible()
        resp = api.list_forms_1099r(
            p["id"], custodian_headers,
            params={"tax_year": 2026, "limit": 101},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)

    def test_pagination_limit_below_min_rejected(self, api,
                                                 custodian_headers):
        """PRD §2.3: "The limit parameter defaults to 10, with a
        minimum of 1 and a maximum of 100."

        Claim: limit < 1 -> ERR_VALIDATION.
        """
        p, _ = setup_owner_rmd_eligible()
        resp = api.list_forms_1099r(
            p["id"], custodian_headers,
            params={"tax_year": 2026, "limit": 0},
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)
