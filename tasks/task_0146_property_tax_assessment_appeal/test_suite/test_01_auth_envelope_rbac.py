"""Authentication, RBAC, response envelope, NOT_FOUND resolution.

PRD §2.1, §2.2, §2.5: missing headers → ERR_UNAUTHENTICATED; role not
authorized → ERR_FORBIDDEN; envelope shape; path validation
left-to-right with ERR_NOT_FOUND.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    clock_advance_payload,
    create_owner_payload,
    create_property_payload,
    create_tax_bill_payload,
    iso_now_utc,
    make_owner_headers,
    setup_issued_assessment,
    setup_issued_tax_bill,
    setup_owner_and_property,
    validate_error,
    validate_success,
)


# ===========================================================================
# Missing headers — PRD §2.1
# ===========================================================================
class TestAuthMissing:
    """PRD §2.1: 'A request missing either header is rejected with
    ERR_UNAUTHENTICATED.'"""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_UNAUTHENTICATED."

        Claim: omitting both auth headers -> ERR_UNAUTHENTICATED / 401.
        """
        resp = api._request(
            "POST", "/_clock/advance",
            clock_advance_payload(target_timestamp=iso_now_utc()),
            headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_UNAUTHENTICATED."

        Claim: only X-User-ID present -> ERR_UNAUTHENTICATED / 401.
        """
        resp = api._request(
            "POST", "/_clock/advance",
            clock_advance_payload(target_timestamp=iso_now_utc()),
            headers={"X-User-ID": "anything"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request missing either header is rejected with
        ERR_UNAUTHENTICATED."

        Claim: only X-User-Role present -> ERR_UNAUTHENTICATED / 401.
        """
        resp = api._request(
            "POST", "/_clock/advance",
            clock_advance_payload(target_timestamp=iso_now_utc()),
            headers={"X-User-Role": "Assessor"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# RBAC enforcement — PRD §2.1, §4
# ===========================================================================
class TestRbacForbidden:

    def test_owner_cannot_register_property(
        self, api, owner_fallback_headers,
    ):
        """PRD §2.1: "A request that carries valid headers but whose
        role is not authorized for the requested operation is rejected
        with ERR_FORBIDDEN."

        Claim: Owner cannot POST /properties (PRD §4 endpoint table
        lists Assessor as the only authorized role).
        """
        # Use a synthetic owner_id; no real Owner needed because
        # ERR_FORBIDDEN must fire before any body validation.
        resp = api.create_property(
            create_property_payload(
                owner_id=NON_EXISTENT_UUID, market_value=100_000.00,
            ),
            owner_fallback_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_treasurer_cannot_register_property(
        self, api, treasurer_headers,
    ):
        """PRD §2.1: "A request that carries valid headers but whose
        role is not authorized for the requested operation is rejected
        with ERR_FORBIDDEN."

        Claim: Treasurer cannot POST /properties (PRD §4 endpoint
        table lists Assessor as the only authorized role).
        """
        resp = api.create_property(
            create_property_payload(
                owner_id=NON_EXISTENT_UUID, market_value=100_000.00,
            ),
            treasurer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_assessor_cannot_create_tax_bill(self, api, assessor_headers):
        """PRD §2.8: "A Treasurer may create and issue TaxBills,
        schedule hearings, and activate DeferralPlans".
        PRD §2.1: "A request that carries valid headers but whose role
        is not authorized for the requested operation is rejected with
        ERR_FORBIDDEN."

        Claim: Assessor cannot create a TaxBill.
        """
        resp = api.create_tax_bill(
            NON_EXISTENT_UUID,
            create_tax_bill_payload(roll_year=2025),
            assessor_headers,
        )
        # The path id won't resolve, but ERR_FORBIDDEN (priority 2)
        # fires before ERR_NOT_FOUND (priority 3) per PRD §2.9.
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_owner_cannot_approve_exemption(self, api):
        """PRD §2.1: "A request that carries valid headers but whose
        role is not authorized for the requested operation is rejected
        with ERR_FORBIDDEN."

        Claim: Owner cannot approve an exemption application (PRD §4
        endpoint table lists Assessor as the only authorized role).
        """
        owner, prop = setup_owner_and_property()
        resp = api.approve_exemption_application(
            prop["id"], NON_EXISTENT_UUID,
            make_owner_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_assessor_cannot_decide_appeal(self, api, assessor_headers):
        """PRD §2.8: "an Assessor may not schedule, conduct, or decide
        an Appeal."

        Claim: Assessor cannot decide an Appeal (Assessor not in the
        authorized roles for /decide).
        """
        from test_helpers import decide_appeal_payload
        resp = api.decide_appeal(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            decide_appeal_payload(
                decision_outcome="UPHELD", decided_value=100_000.00,
            ),
            assessor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_treasurer_cannot_approve_exemption(self, api, treasurer_headers):
        """PRD §2.8: "a Treasurer may not approve exemptions or render
        appeal decisions."

        Claim: Treasurer cannot approve an ExemptionApplication.
        """
        resp = api.approve_exemption_application(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            treasurer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Owner ownership enforcement — PRD §2.1
# ===========================================================================
class TestOwnershipMismatch:

    def test_other_owner_cannot_file_appeal(self, api):
        """PRD §2.1: "When X-User-Role is Owner, X-User-ID is the id
        of the acting Owner entity; for every owner-scoped write —
        filing an appeal, submitting an exemption application, making
        a payment, requesting or cancelling a deferral, withdrawing
        an appeal — the server compares Property.owner_id against
        X-User-ID and rejects mismatches with ERR_OWNERSHIP_MISMATCH."

        Claim: an Owner whose id != Property.owner_id is rejected with
        ERR_OWNERSHIP_MISMATCH when filing an appeal.
        """
        from test_helpers import (
            create_owner,
            file_appeal_payload,
            setup_issued_assessment as _siu,
        )
        owner, prop, assessment = _siu()
        other_owner = create_owner()
        resp = api.file_appeal(
            prop["id"],
            file_appeal_payload(
                assessment_id=assessment["id"], claimed_value=10_000.00,
            ),
            make_owner_headers(other_owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)

    def test_other_owner_cannot_make_payment(self, api):
        """PRD §2.1: "When X-User-Role is Owner, X-User-ID is the id
        of the acting Owner entity; for every owner-scoped write —
        filing an appeal, submitting an exemption application, making
        a payment, requesting or cancelling a deferral, withdrawing
        an appeal — the server compares Property.owner_id against
        X-User-ID and rejects mismatches with ERR_OWNERSHIP_MISMATCH."

        Claim: an Owner whose id != Property.owner_id is rejected with
        ERR_OWNERSHIP_MISMATCH when making a payment.
        """
        from test_helpers import create_owner, create_payment_payload
        owner, prop, _assessment, bill = setup_issued_tax_bill()
        other_owner = create_owner()
        resp = api.create_payment(
            prop["id"], bill["id"],
            create_payment_payload(amount=100.00),
            make_owner_headers(other_owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH.value)


# ===========================================================================
# Path NOT_FOUND — PRD §2.5
# ===========================================================================
class TestPathNotFound:

    def test_unknown_property_id_returns_not_found(self, api, assessor_headers):
        """PRD §2.5: "the server validates path identifiers strictly
        left-to-right and stops at the first one that does not
        resolve. The error returned is always ERR_NOT_FOUND and refers
        to the first unresolved segment, never to a deeper one."

        Claim: GET /properties/{unknown_id} -> ERR_NOT_FOUND.
        """
        resp = api.get_property(NON_EXISTENT_UUID, assessor_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_unknown_assessment_id_returns_not_found(
        self, api, assessor_headers,
    ):
        """PRD §2.5: "the server validates path identifiers strictly
        left-to-right and stops at the first one that does not
        resolve. The error returned is always ERR_NOT_FOUND and refers
        to the first unresolved segment, never to a deeper one."

        Claim: GET /properties/{ok}/assessments/{unknown} -> ERR_NOT_FOUND.
        """
        _, prop = setup_owner_and_property()
        resp = api.get_assessment(
            prop["id"], NON_EXISTENT_UUID, assessor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_leftmost_segment_wins_left_to_right(self, api, assessor_headers):
        """PRD §2.5: "the server validates path identifiers strictly
        left-to-right and stops at the first one that does not
        resolve. The error returned is always ERR_NOT_FOUND and refers
        to the first unresolved segment, never to a deeper one."

        Claim: with both property_id AND assessment_id unknown, the
        property_id segment is the one that fails first.
        """
        resp = api.get_assessment(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID, assessor_headers,
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Success envelope shape — PRD §2.2
# ===========================================================================
class TestSuccessEnvelope:

    def test_post_owner_returns_201_and_envelope(self, api, assessor_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body".
        PRD §4: "endpoints that create a brand-new resource return
        201; endpoints that read, modify, or transition an existing
        resource return 200".

        Claim: POST /owners returns 201, response_type=object, data
        with id + created_at + updated_at + version.
        """
        resp = api.create_owner(
            create_owner_payload(), assessor_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert "id" in data
        assert "created_at" in data
        assert "updated_at" in data
        assert "version" in data
        assert data["version"] == 1, (
            f"PRD §2.4: 'version ... starting at 1' — got {data['version']}"
        )
