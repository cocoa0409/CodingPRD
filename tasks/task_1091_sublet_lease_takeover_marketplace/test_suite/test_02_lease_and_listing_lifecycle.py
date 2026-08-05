"""Lease verification lifecycle and listing approval gating."""
from test_helpers import (
    validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_lease_payload, make_landlord_headers, make_leaseholder_headers,
    new_landlord, new_leaseholder, new_lease, new_verified_lease, new_draft_listing,
    set_clock,
)


def test_lease_dates_invalid_returns_422(api):
    """PRD §3.1: "The `term_end_date` must be strictly after the `term_start_date`;
    otherwise the lease is rejected with `ERR_LEASE_DATES_INVALID` (HTTP 422)."

    Design: Corner/validations/lease_dates_invalid_returns_422
    """
    landlord = new_landlord(api)
    leaseholder = new_leaseholder(api)
    payload = create_lease_payload(landlord["id"], leaseholder["id"],
                                   term_start_date="2026-12-31", term_end_date="2026-01-01")
    resp = api.create_lease(payload, make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_LEASE_DATES_INVALID.value)


def test_verify_lease_not_pending_review_rejected(api):
    """PRD §3.1: "a verify decision on a lease not in `PENDING_REVIEW` is rejected with
    `ERR_LEASE_NOT_PENDING_REVIEW`."

    Design: Corner/state_machines/verify_lease_not_pending_review_rejected
    """
    landlord = new_landlord(api)
    leaseholder = new_leaseholder(api)
    lease = new_lease(api, landlord, leaseholder)  # still UNVERIFIED
    resp = api.verify_lease(lease["id"], {"decision": "VERIFIED"}, TEST_USERS["compliance_headers"])
    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_PENDING_REVIEW.value)


def test_submit_verification_twice_rejected(api):
    """PRD §3.1: "submitting a lease that is not currently `UNVERIFIED` is rejected with
    `ERR_LEASE_NOT_VERIFIABLE`."

    Design: Corner/state_machines/submit_verification_twice_idempotency_rejected
    """
    landlord = new_landlord(api)
    leaseholder = new_leaseholder(api)
    lease = new_lease(api, landlord, leaseholder)
    ll_headers = make_landlord_headers(landlord["id"])
    validate_success(api.submit_lease_verification(lease["id"], ll_headers))  # -> PENDING_REVIEW
    resp = api.submit_lease_verification(lease["id"], ll_headers)
    validate_error(resp, ApiErrorId.ERR_LEASE_NOT_VERIFIABLE.value)


def test_lease_verify_rejected_path(api):
    """PRD §3.1: "A `ComplianceOfficer` then records a `decision` of either `VERIFIED`
    or `REJECTED`, moving the lease from `PENDING_REVIEW` to `VERIFIED` or to the
    terminal `REJECTED` state respectively".

    Design: Corner/state_machines/lease_verify_rejected_path
    """
    landlord = new_landlord(api)
    leaseholder = new_leaseholder(api)
    lease = new_lease(api, landlord, leaseholder)
    validate_success(api.submit_lease_verification(lease["id"], make_landlord_headers(landlord["id"])))
    resp = api.verify_lease(lease["id"], {"decision": "REJECTED"}, TEST_USERS["compliance_headers"])
    data = validate_success(resp)
    assert data["status"] == "REJECTED", f"expected REJECTED, got {data['status']}"


def test_approve_listing_not_pending_approval_rejected(api):
    """PRD §3.2: "Both actions require the listing to be `PENDING_APPROVAL`, else
    `ERR_LISTING_NOT_PENDING_APPROVAL`."

    Design: Corner/state_machines/approve_listing_not_pending_approval_rejected
    """
    landlord = new_landlord(api)
    leaseholder = new_leaseholder(api)
    lease = new_verified_lease(api, landlord, leaseholder)
    listing = new_draft_listing(api, lease, leaseholder)  # DRAFT, never requested approval
    resp = api.approve_listing(listing["id"], make_landlord_headers(landlord["id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_NOT_PENDING_APPROVAL.value)


def test_request_approval_listing_type_not_allowed_by_lease(api):
    """PRD §3.2: "the requested `listing_type` must be permitted by the lease's flags —
    a `SUBLET` requires `allows_sublet` to be true and a `TAKEOVER` requires
    `allows_assignment` to be true, else `ERR_LISTING_TYPE_NOT_ALLOWED`."

    Design: Corner/validations/listing_type_not_allowed_by_lease
    """
    landlord = new_landlord(api)
    leaseholder = new_leaseholder(api)
    lease = new_verified_lease(api, landlord, leaseholder, allows_sublet=False, allows_assignment=False)
    listing = new_draft_listing(api, lease, leaseholder, listing_type="SUBLET")
    resp = api.request_listing_approval(listing["id"], make_leaseholder_headers(leaseholder["id"]))
    validate_error(resp, ApiErrorId.ERR_LISTING_TYPE_NOT_ALLOWED.value)


class TestRequestApprovalRequiresLeaseVerified:
    """Difficulty: cross_entity_state_dependency — request-approval blocked while the
    referenced Lease is not VERIFIED."""

    def test_request_approval_on_unverified_lease_rejected(self, api):
        """PRD §3.2: "the underlying lease must be `VERIFIED` (else `ERR_LEASE_NOT_VERIFIED`)".

        Design: Difficulty/cross_entity_state_dependency/request_approval_requires_lease_verified
        """
        set_clock(api)
        landlord = new_landlord(api)
        leaseholder = new_leaseholder(api)
        lease = new_lease(api, landlord, leaseholder, allows_sublet=True)  # UNVERIFIED
        listing = new_draft_listing(api, lease, leaseholder, listing_type="SUBLET")
        resp = api.request_listing_approval(listing["id"], make_leaseholder_headers(leaseholder["id"]))
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_VERIFIED.value)

    def test_request_approval_on_pending_review_lease_rejected(self, api):
        """PRD §3.2: "the underlying lease must be `VERIFIED` (else `ERR_LEASE_NOT_VERIFIED`)".

        Design: Difficulty/cross_entity_state_dependency/request_approval_requires_lease_verified
        """
        set_clock(api)
        landlord = new_landlord(api)
        leaseholder = new_leaseholder(api)
        lease = new_lease(api, landlord, leaseholder, allows_sublet=True)
        validate_success(api.submit_lease_verification(lease["id"], make_landlord_headers(landlord["id"])))
        # lease now PENDING_REVIEW — still not VERIFIED
        listing = new_draft_listing(api, lease, leaseholder, listing_type="SUBLET")
        resp = api.request_listing_approval(listing["id"], make_leaseholder_headers(leaseholder["id"]))
        validate_error(resp, ApiErrorId.ERR_LEASE_NOT_VERIFIED.value)
