"""Authentication, role authorization, and pagination tests (PRD §2.1 / §2.3)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    party_payload,
    setup_emd_held,
    validate_error,
    validate_paginated,
    validate_success,
    with_idempotency,
)


# ===========================================================================
# Authentication — PRD §2.1
# ===========================================================================
class TestAuthentication:

    def test_missing_x_user_id_rejected(self, api):
        """PRD §2.1: "A request that omits either header, or that names
        a role outside the closed set defined below, is rejected with
        ERR_UNAUTHENTICATED."

        Claim: omitting X-User-ID yields ERR_UNAUTHENTICATED (401).
        """
        headers = {
            "X-User-Role": "EscrowOfficer",
            "Content-Type": "application/json",
            "Idempotency-Key": "idem-missing-uid-1",
        }
        resp = api.create_party(party_payload(party_kind="BUYER"), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_missing_x_user_role_rejected(self, api):
        """PRD §2.1: "A request that omits either header, or that names
        a role outside the closed set defined below, is rejected with
        ERR_UNAUTHENTICATED."

        Claim: omitting X-User-Role yields ERR_UNAUTHENTICATED.
        """
        headers = {
            "X-User-ID": "test-1",
            "Content-Type": "application/json",
            "Idempotency-Key": "idem-missing-role-1",
        }
        resp = api.create_party(party_payload(party_kind="BUYER"), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: "A request that omits either header, or that names
        a role outside the closed set defined below, is rejected with
        ERR_UNAUTHENTICATED."

        Claim: an unknown role like 'Hacker' yields ERR_UNAUTHENTICATED.
        """
        headers = {
            "X-User-ID": "test-1",
            "X-User-Role": "Hacker",
            "Content-Type": "application/json",
            "Idempotency-Key": "idem-bogus-role-1",
        }
        resp = api.create_party(party_payload(party_kind="BUYER"), headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


# ===========================================================================
# Role authorization — PRD §2.1 + §4
# ===========================================================================
class TestRoleAuthorization:

    def test_buyer_cannot_create_party(self, api, buyer_fallback_headers):
        """PRD §2.1: "A request whose role is recognized but is not
        authorized for the targeted operation (per the role-to-endpoint
        matrix implicit in §4) is rejected with ERR_FORBIDDEN_ROLE."
        PRD §4: only EscrowOfficer can POST /parties.

        Claim: Buyer POSTing /parties yields ERR_FORBIDDEN_ROLE.
        """
        headers = with_idempotency(buyer_fallback_headers)
        resp = api.create_party(party_payload(party_kind="BUYER"), headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_seller_cannot_open_escrow_file(self, api, seller_fallback_headers):
        """PRD §4: opening an escrow file (POST /escrow-files) is
        restricted to EscrowOfficer.

        Claim: Seller POSTing /escrow-files yields ERR_FORBIDDEN_ROLE.
        """
        from test_helpers import escrow_file_payload
        headers = with_idempotency(seller_fallback_headers)
        # Payload values don't matter — role check fires before existence
        # check per PRD §2.8 priority.
        payload = escrow_file_payload(
            property_id=NON_EXISTENT_UUID,
            buyer_party_id=NON_EXISTENT_UUID,
            seller_party_id=NON_EXISTENT_UUID,
        )
        resp = api.create_escrow_file(payload, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_disb_approver_cannot_advance_escrow(
        self, api, disb_approver_headers,
    ):
        """PRD §4: POST /escrow-files/{id}/advance is restricted to
        EscrowOfficer.

        Claim: DisbursementApprover advancing escrow yields
        ERR_FORBIDDEN_ROLE.
        """
        headers = with_idempotency(disb_approver_headers)
        resp = api.advance_escrow_file(NON_EXISTENT_UUID, headers)
        # Role check (priority 2) fires before existence (priority 3).
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_list_default_pagination(self, api, escrow_officer_headers):
        """PRD §2.3: "The limit parameter caps the number of records
        returned and defaults to 10 when omitted ... The meta object of
        every list response carries limit, offset, total_count, and
        has_more."

        Claim: list endpoint returns paginated meta with defaults.
        """
        # Ensure at least one row exists.
        setup_emd_held()
        resp = api.list_escrow_files(escrow_officer_headers)
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert "total_count" in meta
        assert "has_more" in meta

    def test_list_custom_limit_and_offset(self, api, escrow_officer_headers):
        """PRD §2.3: "The offset parameter expresses how many records to
        skip from the head of the result set and defaults to 0 when
        omitted."

        Claim: limit=3 offset=0 returns at most 3 rows with meta
        echoing those values.
        """
        # Seed multiple files.
        for _ in range(4):
            setup_emd_held()
        resp = api.list_escrow_files(
            escrow_officer_headers, params={"limit": 3, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert len(data) <= 3
        assert meta["limit"] == 3
        assert meta["offset"] == 0

    def test_audit_events_pagination(self, api, escrow_officer_headers):
        """PRD §3.10: "The audit-event listing endpoint is keyed by
        escrow_file_id and accepts only the pagination parameters,
        returning events sorted by created_at ascending."

        Claim: GET /escrow-files/{id}/audit-events returns paginated
        list with the standard meta fields.
        """
        bundle = setup_emd_held()
        resp = api.list_audit_events(
            bundle["escrow_file"]["id"], escrow_officer_headers,
            params={"limit": 5, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert isinstance(data, list)
        assert meta["limit"] == 5
        assert meta["offset"] == 0
