"""Authentication, role validation, response envelope, pagination, RBAC.

Coverage targets (PRD §2.1, §2.2, §2.3, §4):
- Missing X-User-ID or X-User-Role header -> ERR_AUTH_MISSING (401).
- Role recognized but lacks endpoint permission -> ERR_FORBIDDEN (403).
- Success / error response envelope shape (meta + response_type + data).
- Pagination meta on list endpoints.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_borrower_payload,
    create_loan_payload,
    setup_borrower_and_current_loan,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing headers — PRD §2.1
# ===========================================================================
class TestAuthMissing:
    """PRD §2.1: 'If either header is missing or empty, the request is
    rejected with ERR_AUTH_MISSING and HTTP 401.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING and HTTP 401."

        Claim: omitting both headers -> ERR_AUTH_MISSING / 401.
        """
        resp = api._request("POST", "/borrowers",
                            create_borrower_payload(), headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING and HTTP 401."

        Claim: only X-User-ID present -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "POST", "/borrowers", create_borrower_payload(),
            headers={"X-User-ID": "anything"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING and HTTP 401."

        Claim: only X-User-Role present -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "POST", "/borrowers", create_borrower_payload(),
            headers={"X-User-Role": "Servicer"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_empty_role_header_rejected(self, api):
        """PRD §2.1: "If either header is missing or empty, the request
        is rejected with ERR_AUTH_MISSING and HTTP 401."

        Claim: empty X-User-Role -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "POST", "/borrowers", create_borrower_payload(),
            headers={"X-User-Role": "", "X-User-ID": "x"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# RBAC — PRD §2.1, §4
# ===========================================================================
class TestRbacForbidden:
    """PRD §2.1: 'if the acting role is not permitted to call the
    endpoint per the RBAC matrix in §4, the request is rejected with
    ERR_FORBIDDEN and HTTP 403.'"""

    def test_borrower_cannot_create_borrower(self, api,
                                             borrower_fallback_headers):
        """PRD §4: "POST /borrowers — Authorized Role(s): Servicer,
        PlatformAdmin"
        PRD §2.1: "if the acting role is not permitted to call the
        endpoint per the RBAC matrix in §4, the request is rejected
        with ERR_FORBIDDEN and HTTP 403."

        Claim: Borrower role cannot POST /borrowers.
        """
        resp = api.create_borrower(create_borrower_payload(),
                                   borrower_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_pmi_underwriter_cannot_create_loan(
        self, api, pmi_underwriter_headers,
    ):
        """PRD §4: "POST /loans — Authorized Role(s): Servicer,
        PlatformAdmin"
        PRD §2.1: "if the acting role is not permitted to call the
        endpoint per the RBAC matrix in §4, the request is rejected
        with ERR_FORBIDDEN and HTTP 403."

        Claim: PmiUnderwriter cannot POST /loans.
        """
        # Need a borrower id but the call should reject on RBAC before
        # touching it (priority 3 before priority 5 per PRD §2.6).
        payload = create_loan_payload(borrower_id="any-borrower-id")
        resp = api.create_loan(payload, pmi_underwriter_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_foreclosure_attorney_cannot_post_payment(
        self, api, foreclosure_attorney_headers,
    ):
        """PRD §4: "POST /loans/{id}/payments — Authorized Role(s):
        Servicer, Borrower"
        PRD §2.1: "if the acting role is not permitted to call the
        endpoint per the RBAC matrix in §4, the request is rejected
        with ERR_FORBIDDEN and HTTP 403."

        Claim: ForeclosureAttorney cannot POST /loans/{id}/payments.
        """
        b, loan = setup_borrower_and_current_loan()
        resp = api.create_payment(
            loan["id"], {"received_date": "2026-05-17T00:00:00.000Z",
                         "amount_cents": 100_000},
            foreclosure_attorney_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_servicer_cannot_approve_pmi_removal(
        self, api, servicer_headers,
    ):
        """PRD §4: "POST /loans/{loan_id}/pmi-removal-requests/{id}/approve
        — Authorized Role(s): PmiUnderwriter"
        PRD §2.1: "if the acting role is not permitted to call the
        endpoint per the RBAC matrix in §4, the request is rejected
        with ERR_FORBIDDEN and HTTP 403."

        Claim: Servicer cannot approve a PMI removal request.
        """
        from test_helpers import setup_pmi_pending_borrower_request
        b, loan, req = setup_pmi_pending_borrower_request()
        resp = api.approve_pmi_removal_request(
            loan["id"], req["id"], servicer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_servicer_cannot_run_clock_advance(self, api, servicer_headers):
        """PRD §4: "POST /_clock/advance — Authorized Role(s):
        PlatformAdmin"
        PRD §2.1: "if the acting role is not permitted to call the
        endpoint per the RBAC matrix in §4, the request is rejected
        with ERR_FORBIDDEN and HTTP 403."

        Claim: Servicer cannot POST /_clock/advance.
        """
        resp = api.clock_advance({"days": 1}, servicer_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Borrower ownership — PRD §2.1
# ===========================================================================
class TestBorrowerOwnership:
    """PRD §2.1: 'A borrower who attempts to operate on a loan whose
    borrower_id does not equal their X-User-ID is treated as forbidden
    (ERR_FORBIDDEN).'"""

    def test_borrower_cannot_post_payment_on_other_loan(
        self, api, borrower_fallback_headers,
    ):
        """PRD §2.1: "A borrower who attempts to operate on a loan
        whose borrower_id does not equal their X-User-ID is treated as
        forbidden (ERR_FORBIDDEN)."

        Claim: Borrower role with a different X-User-ID than the loan's
        borrower_id -> ERR_FORBIDDEN on POST /loans/{id}/payments.
        """
        b, loan = setup_borrower_and_current_loan()
        # borrower_fallback_headers carries a Borrower X-User-ID that does
        # NOT equal loan.borrower_id.
        resp = api.create_payment(
            loan["id"],
            {"received_date": "2026-05-17T00:00:00.000Z",
             "amount_cents": 100_000},
            borrower_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Success envelope — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: 'All successful API responses (those with 2xx status
    codes) follow this standard envelope format in their JSON body'."""

    def test_create_borrower_envelope(self, api, servicer_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body".

        Claim: POST /borrowers returns the standard success envelope
        (meta with api_request_id/timestamp; response_type 'object';
        data carrying the created Borrower).
        """
        resp = api.create_borrower(create_borrower_payload(),
                                   servicer_headers)
        data = validate_success(resp, expected_status=201)
        assert isinstance(data, dict)
        assert "id" in data and "full_name" in data and "email" in data


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:
    """PRD §2.3: 'For every list response, the meta block carries
    limit, offset, total_count ... and has_more'."""

    def test_list_loans_returns_paginated_meta(self, api,
                                               servicer_headers):
        """PRD §2.3: "For every list response, the meta block carries
        limit, offset, total_count (the total number of records
        matching the filter, ignoring limit and offset), and has_more
        (true when more records exist beyond the current window)."

        Claim: GET /loans response carries the four pagination meta
        fields.
        """
        # Ensure at least one loan exists.
        setup_borrower_and_current_loan()
        resp = api.list_loans(servicer_headers)
        data, meta = validate_paginated(resp)
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta, f"missing pagination field {k!r}: {meta!r}"
        assert isinstance(data, list)
