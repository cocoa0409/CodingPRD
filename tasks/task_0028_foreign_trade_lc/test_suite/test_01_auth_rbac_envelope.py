"""Auth headers, RBAC, response-envelope and pagination (PRD §2.1, §2.2, §2.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_applicant_payload,
    create_bank_payload,
    create_beneficiary_payload,
    create_lc_payload,
    setup_active_lc,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 — auth headers
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: 'Every request must carry two headers: X-User-ID and
        X-User-Role. If either is missing, malformed, or carries an
        unknown role, the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""
        bad_headers = {"X-User-Role": "Operator"}
        res = api.create_applicant(create_applicant_payload(), bad_headers)
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: 'Every request must carry two headers: X-User-ID and
        X-User-Role. If either is missing, malformed, or carries an
        unknown role, the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""
        bad_headers = {"X-User-ID": "op-001"}
        res = api.create_applicant(create_applicant_payload(), bad_headers)
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    def test_unknown_role_value_rejected(self, api):
        """PRD §2.1: 'Every request must carry two headers: X-User-ID and
        X-User-Role. If either is missing, malformed, or carries an
        unknown role, the request is rejected with
        ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.'"""
        bad_headers = build_user_headers("op-001", "MysteryRole")
        res = api.create_applicant(create_applicant_payload(), bad_headers)
        validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")


# ===========================================================================
# §2.1 — RBAC forbidden-role
# ===========================================================================
class TestRbacForbidden:

    @pytest.mark.parametrize(
        "role",
        ["Applicant", "Beneficiary", "IssuingBank", "AdvisingBank",
         "ConfirmingBank", "NegotiatingBank", "Auditor"],
    )
    def test_create_bank_requires_operator(self, api, role):
        """PRD §2.1: 'When the headers are well-formed but the role does
        not appear in the authorised-role list of the requested endpoint,
        the request is rejected with ERR_FORBIDDEN_FOR_ROLE.'

        PRD §3.1: 'An Operator registers each Bank ...'."""
        headers = build_user_headers(f"x-{role}", role)
        res = api.create_bank(create_bank_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")

    @pytest.mark.parametrize(
        "role",
        ["Applicant", "Beneficiary", "IssuingBank", "AdvisingBank",
         "ConfirmingBank", "NegotiatingBank", "Auditor"],
    )
    def test_create_applicant_requires_operator(self, api, role):
        """PRD §2.1: 'When the headers are well-formed but the role does
        not appear in the authorised-role list of the requested endpoint,
        the request is rejected with ERR_FORBIDDEN_FOR_ROLE.'"""
        headers = build_user_headers(f"x-{role}", role)
        res = api.create_applicant(create_applicant_payload(), headers)
        validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")

    @pytest.mark.parametrize(
        "role",
        ["Beneficiary", "IssuingBank", "AdvisingBank", "ConfirmingBank",
         "NegotiatingBank", "Operator", "Auditor"],
    )
    def test_create_lc_requires_applicant(self, api, role):
        """PRD §4 endpoint table: 'POST /letters-of-credit | Create a
        draft LC application | Applicant'.

        PRD §2.1: 'When the headers are well-formed but the role does
        not appear in the authorised-role list of the requested endpoint,
        the request is rejected with ERR_FORBIDDEN_FOR_ROLE.'"""
        headers = build_user_headers(f"x-{role}", role)
        # Body with bogus party ids — RBAC must fire before existence checks.
        payload = create_lc_payload(
            applicant_id=NON_EXISTENT_UUID,
            beneficiary_id=NON_EXISTENT_UUID,
            issuing_bank_id=NON_EXISTENT_UUID,
            advising_bank_id=NON_EXISTENT_UUID,
            latest_shipment_date="2099-01-01T00:00:00.000Z",
            expiry_date="2099-02-01T00:00:00.000Z",
        )
        res = api.create_lc(payload, headers)
        validate_error(res, "ERR_FORBIDDEN_FOR_ROLE")


# ===========================================================================
# §2.7 — path resource existence
# ===========================================================================
class TestNotFound:

    def test_get_unknown_lc_returns_not_found(self, api, operator_headers):
        """PRD §2.7: 'For a request such as a discrepancy listing under a
        specific examination, the server first verifies that the
        examinationId exists; if not, it returns ERR_NOT_FOUND without
        consulting any deeper segment.'"""
        res = api.get_lc(NON_EXISTENT_UUID, operator_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_unknown_presentation_returns_not_found(self, api, operator_headers):
        """PRD §2.7: 'For a request such as a discrepancy listing under a
        specific examination, the server first verifies that the
        examinationId exists; if not, it returns ERR_NOT_FOUND without
        consulting any deeper segment.'"""
        res = api.get_presentation(NON_EXISTENT_UUID, operator_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_submit_unknown_lc_returns_not_found(self, api):
        """PRD §2.7: 'the server first verifies that the examinationId
        exists; if not, it returns ERR_NOT_FOUND without consulting any
        deeper segment.'"""
        res = api.submit_lc(NON_EXISTENT_UUID, TEST_USERS["applicant_headers"])
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.2 / §2.3 — envelope + pagination
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_carries_meta_and_data(self, api, operator_headers):
        """PRD §2.2: 'All successful API responses (those with 2xx status
        codes) follow this standard envelope format in their JSON body.'"""
        from test_helpers import create_applicant_payload  # noqa: WPS433
        res = api.create_applicant(
            create_applicant_payload(), operator_headers,
        )
        # validate_success asserts envelope meta + response_type + data.
        data = validate_success(res, expected_status=201)
        assert "id" in data and isinstance(data["id"], str)

    def test_list_envelope_carries_pagination_meta(self, api, operator_headers):
        """PRD §2.3: 'The response meta block on every list endpoint
        includes limit, offset, total_count, and has_more.'"""
        # Use list_lcs which is paginatable.
        res = api.list_lcs(operator_headers)
        data, meta = validate_paginated(res)
        for key in ("limit", "offset", "total_count", "has_more"):
            assert key in meta, f"meta must include {key} (PRD §2.3)"
        assert isinstance(data, list)


class TestPagination:

    def test_limit_zero_rejected(self, api, operator_headers):
        """PRD §2.3: 'The default limit is 10, the minimum is 1, and the
        maximum is 100; values outside that range are rejected with
        ERR_INVALID_REQUEST.'"""
        res = api.list_lcs(operator_headers, params={"limit": 0})
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_limit_above_max_rejected(self, api, operator_headers):
        """PRD §2.3: 'The default limit is 10, the minimum is 1, and the
        maximum is 100; values outside that range are rejected with
        ERR_INVALID_REQUEST.'"""
        res = api.list_lcs(operator_headers, params={"limit": 101})
        validate_error(res, "ERR_INVALID_REQUEST")

    def test_limit_at_max_accepted(self, api, operator_headers):
        """PRD §2.3: 'the maximum is 100; values outside that range are
        rejected with ERR_INVALID_REQUEST.'"""
        res = api.list_lcs(operator_headers, params={"limit": 100})
        data, meta = validate_paginated(res)
        assert meta["limit"] == 100


# Note on Applicant/Beneficiary ownership: PRD §2.1 specifies that
# X-User-ID is compared to the resource's applicant_id / beneficiary_id /
# *_bank_id, but does not pin a specific error_id when the comparison
# fails. The doc-generator's silence here means an ownership-mismatch
# test cannot be uniquely derived from PRD prose; an implementer could
# faithfully return ERR_FORBIDDEN_FOR_ROLE, ERR_NOT_FOUND, or a
# different error. Therefore no ownership-mismatch error_id assertion
# is generated. The successful path (correct entity owner) is exercised
# in every fixture-driven test in subsequent files.
# Silence-pattern category: applies_to-scope (PRD does not specify the
# error_id for ownership-mismatch).
