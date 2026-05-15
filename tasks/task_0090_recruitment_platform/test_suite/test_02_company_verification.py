"""Company verification lifecycle & posting-quota derivation (PRD §3.1)."""
from __future__ import annotations

from datetime import timedelta

import pytest

from test_helpers import (
    ApiErrorId,
    BASIC_POSTING_QUOTA,
    NON_EXISTENT_UUID,
    PREMIUM_POSTING_QUOTA,
    REVERIFICATION_DAYS,
    TEST_EPOCH,
    advance_clock_to,
    approve_company_verification,
    assert_company,
    bind_hr_user,
    blacklist_company,
    blacklist_company_payload,
    create_company,
    create_company_payload,
    create_live_posting,
    create_verified_company,
    reject_company_verification,
    reset_clock_to_epoch,
    submit_company_verification,
    validate_error,
    validate_success,
)


# ===========================================================================
# Company creation (PRD §3.1)
# ===========================================================================
class TestCompanyCreate:

    def test_company_starts_in_draft(self, api, hr_user_fallback_headers):
        """PRD §3.1: "The row starts in verification_status DRAFT."

        Claim: a freshly created Company has verification_status==DRAFT.
        """
        resp = api.create_company(
            create_company_payload(), hr_user_fallback_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_company(data)
        assert data["verification_status"] == "DRAFT"

    def test_company_default_tier_is_basic(self, api, hr_user_fallback_headers):
        """PRD §3.1: "the `verification_tier` is one of `BASIC` or
        `PREMIUM`, defaulting to `BASIC` when the field is absent."

        Claim: omitting verification_tier yields BASIC.
        """
        payload = create_company_payload()
        payload.pop("verification_tier", None)
        resp = api.create_company(payload, hr_user_fallback_headers)
        data = validate_success(resp, expected_status=201)
        assert data["verification_tier"] == "BASIC"

    def test_company_business_license_unique(self, api, hr_user_fallback_headers):
        """PRD §3.1: "The `business_license_number` must be unique across
        all companies."

        Claim: re-using a business_license_number yields ERR_VALIDATION.
        """
        payload = create_company_payload(business_license_number="LIC-DUP-001")
        validate_success(api.create_company(payload, hr_user_fallback_headers),
                         expected_status=201)
        # Second submission with same license.
        payload2 = create_company_payload(business_license_number="LIC-DUP-001")
        resp = api.create_company(payload2, hr_user_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Verification submit / approve / reject cycle (PRD §3.1)
# ===========================================================================
class TestVerificationCycle:

    def test_submit_advances_draft_to_pending(self, api, hr_user_fallback_headers):
        """PRD §3.1: "The HR caller submitting the company for review ...
        advances the row from `DRAFT` ... to `PENDING`."

        Claim: submit-verification moves DRAFT to PENDING.
        """
        company = create_company()
        resp = api.submit_verification(company["id"], hr_user_fallback_headers)
        data = validate_success(resp, expected_status=200)
        assert data["verification_status"] == "PENDING"

    def test_approve_advances_pending_to_verified(self, api, platform_admin_headers):
        """PRD §3.1: "Approving the verification transitions the company
        from `PENDING` to `VERIFIED`, sets `verified_at` to the current
        instant, sets `reverification_due_at` to three hundred and sixty-five
        days after `verified_at`, and recomputes the `posting_quota_limit`."

        Claim: approve-verification moves PENDING to VERIFIED and sets
        verified_at + reverification_due_at.
        """
        company = create_company()
        submit_company_verification(company["id"])
        resp = api.approve_verification(company["id"], platform_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["verification_status"] == "VERIFIED"
        assert data["verified_at"] is not None
        assert data["reverification_due_at"] is not None

    def test_reject_returns_pending_to_draft(self, api, platform_admin_headers):
        """PRD §3.1: "Rejecting the verification transitions the company
        back to `DRAFT` so the HR side can correct the submission and
        retry — a cyclic loop between `DRAFT`, `PENDING`, and (on failure)
        back to `DRAFT`."

        Claim: reject-verification moves PENDING back to DRAFT.
        """
        company = create_company()
        submit_company_verification(company["id"])
        resp = api.reject_verification(company["id"], platform_admin_headers)
        data = validate_success(resp, expected_status=200)
        assert data["verification_status"] == "DRAFT"

    def test_cyclic_resubmission_after_rejection(self, api, hr_user_fallback_headers):
        """PRD §3.1: "a cyclic loop between `DRAFT`, `PENDING`, and (on
        failure) back to `DRAFT`."

        Claim: after reject-verification we can submit-verification again,
        re-entering PENDING.
        """
        company = create_company()
        submit_company_verification(company["id"])
        reject_company_verification(company["id"])
        resp = api.submit_verification(company["id"], hr_user_fallback_headers)
        data = validate_success(resp, expected_status=200)
        assert data["verification_status"] == "PENDING"


# ===========================================================================
# Posting quota derivation (PRD §3.1)
# ===========================================================================
class TestPostingQuotaDerivation:

    def test_basic_tier_quota_is_five(self, api, hr_user_fallback_headers):
        """PRD §3.1: "if `verification_status` is anything other than
        `VERIFIED`, `posting_quota_limit` is zero; otherwise, a `BASIC`
        tier yields a `posting_quota_limit` of five, and a `PREMIUM` tier
        yields a `posting_quota_limit` of twenty-five."

        Claim: BASIC + VERIFIED → posting_quota_limit == 5.
        """
        company, _ = create_verified_company(verification_tier="BASIC")
        assert company["posting_quota_limit"] == BASIC_POSTING_QUOTA == 5

    def test_premium_tier_quota_is_twenty_five(self, api):
        """PRD §3.1: "a `PREMIUM` tier yields a `posting_quota_limit` of
        twenty-five."

        Claim: PREMIUM + VERIFIED → posting_quota_limit == 25.
        """
        company, _ = create_verified_company(verification_tier="PREMIUM")
        assert company["posting_quota_limit"] == PREMIUM_POSTING_QUOTA == 25

    def test_unverified_company_quota_is_zero(self, api):
        """PRD §3.1: "if `verification_status` is anything other than
        `VERIFIED`, `posting_quota_limit` is zero."

        Claim: a DRAFT company has posting_quota_limit == 0.
        """
        company = create_company()
        assert company["posting_quota_limit"] == 0


# ===========================================================================
# Reverification expiry (PRD §3.1)
# ===========================================================================
class TestReverificationExpiry:

    def test_clock_advance_past_due_expires_company(self, api, platform_admin_headers):
        """PRD §3.1: "Once `VERIFIED`, the verification is valid for three
        hundred and sixty-five days, after which the platform's
        test-driving capability to advance the logical clock ... triggers
        the automatic transition to `EXPIRED` once the current instant is
        at or after `reverification_due_at`."

        Claim: clock-advance past reverification_due_at moves VERIFIED → EXPIRED.
        """
        reset_clock_to_epoch()
        company, _ = create_verified_company()
        # Advance clock beyond verified_at + 365 days.
        advance_clock_to(TEST_EPOCH + timedelta(days=REVERIFICATION_DAYS + 1))
        data = validate_success(
            api.get_company(company["id"], platform_admin_headers),
            expected_status=200,
        )
        assert data["verification_status"] == "EXPIRED"

    def test_expired_company_can_resubmit_verification(self, api, hr_user_fallback_headers):
        """PRD §3.1: "An expired company can re-enter the verification
        workflow by re-submitting (going from `EXPIRED` back to `PENDING`)."

        Claim: from EXPIRED, submit-verification advances to PENDING.
        """
        reset_clock_to_epoch()
        company, _ = create_verified_company()
        advance_clock_to(TEST_EPOCH + timedelta(days=REVERIFICATION_DAYS + 1))
        resp = api.submit_verification(company["id"], hr_user_fallback_headers)
        data = validate_success(resp, expected_status=200)
        assert data["verification_status"] == "PENDING"


# ===========================================================================
# Blacklist (PRD §3.1)
# ===========================================================================
class TestBlacklist:

    def test_blacklist_verified_company(self, api, platform_admin_headers):
        """PRD §3.1: "A `PlatformAdmin` may also blacklist a company at
        any non-terminal state — from `DRAFT`, `PENDING`, or `VERIFIED` —
        by supplying a `blacklist_reason`."

        Claim: blacklist transitions VERIFIED → BLACKLISTED.
        """
        company, _ = create_verified_company()
        resp = api.blacklist_company(
            company["id"], blacklist_company_payload(),
            platform_admin_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["verification_status"] == "BLACKLISTED"

    def test_blacklist_draft_company(self, api, platform_admin_headers):
        """PRD §3.1: "A `PlatformAdmin` may also blacklist a company at
        any non-terminal state — from `DRAFT`, `PENDING`, or `VERIFIED`."

        Claim: blacklist transitions DRAFT → BLACKLISTED.
        """
        company = create_company()
        resp = api.blacklist_company(
            company["id"], blacklist_company_payload(),
            platform_admin_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["verification_status"] == "BLACKLISTED"

    def test_blacklist_is_terminal(self, api, platform_admin_headers, hr_user_fallback_headers):
        """PRD §3.1: "The blacklist transition is terminal: a blacklisted
        company never returns to any other status."

        Claim: a blacklisted company cannot be re-submitted; subsequent
        verification transitions yield ERR_INVALID_STATE.
        """
        company, _ = create_verified_company()
        blacklist_company(company["id"])
        resp = api.submit_verification(company["id"], hr_user_fallback_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_blacklist_verified_cascades_to_live_postings(self, api, platform_admin_headers):
        """PRD §3.1: "When the source state was `VERIFIED`, blacklisting
        cascades to every job posting in `DRAFT`, `UNDER_REVIEW`, or `LIVE`
        (moving them to `OFF_SHELF` and chaining downward)."

        Claim: blacklisting a VERIFIED company drives its LIVE posting to
        OFF_SHELF.
        """
        company, hr_user = create_verified_company()
        posting = create_live_posting(company["id"], hr_user["id"])
        assert posting["posting_status"] == "LIVE"
        blacklist_company(company["id"])
        data = validate_success(
            api.get_job_posting(posting["id"], platform_admin_headers),
            expected_status=200,
        )
        assert data["posting_status"] == "OFF_SHELF"


# ===========================================================================
# Path not found (PRD §2.7 priority 4)
# ===========================================================================
class TestNotFound:

    def test_get_unknown_company_returns_not_found(self, api, platform_admin_headers):
        """PRD §2.7: "Path existence (left-to-right) — any path-referenced
        resource missing yields `ERR_NOT_FOUND` (404)."

        Claim: GET /recruitment/companies/{id} with unknown id → ERR_NOT_FOUND.
        """
        resp = api.get_company(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_approve_unknown_company_returns_not_found(self, api, platform_admin_headers):
        """PRD §2.7: "Path existence (left-to-right) — any path-referenced
        resource missing yields `ERR_NOT_FOUND` (404)."

        Claim: action endpoint on unknown company yields ERR_NOT_FOUND.
        """
        resp = api.approve_verification(NON_EXISTENT_UUID, platform_admin_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
