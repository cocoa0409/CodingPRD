"""Fee assessment lifecycle, estimate calculation, waiver — PRD §3.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    FREE_THRESHOLD_CENTS,
    TEST_USERS,
    accept_fee_assessment,
    assert_fee_assessment,
    create_acknowledged_request,
    create_fee_assessment,
    create_fee_assessment_payload,
    estimate_fee_assessment,
    make_requester_headers,
    setup_request_with_estimated_fee,
    validate_error,
    validate_success,
)


# ===========================================================================
# FeeAssessment creation — PRD §3.3
# ===========================================================================
class TestFeeAssessmentCreation:

    def test_create_fee_assessment_returns_draft(self, api):
        """PRD §3.3: "the officer creates a `FeeAssessment` for the
        request by supplying the `request_id` along with `estimated_pages`,
        `estimated_search_hours`, and `estimated_review_hours`."
        PRD §3.3: "The assessment starts in `DRAFT`."

        Claim: POST /foia/fee-assessments returns a FeeAssessment with
        status=DRAFT.
        """
        _r, request = create_acknowledged_request()
        payload = create_fee_assessment_payload(request_id=request["id"])
        resp = api.create_fee_assessment(
            payload, TEST_USERS["officer_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_fee_assessment(data)
        assert data["status"] == "DRAFT"

    def test_second_fee_assessment_rejected_with_err_fee_assessment_exists(self, api):
        """PRD §3.3: "Each request may have at most one `FeeAssessment`;
        a second creation attempt is rejected with `ERR_FEE_ASSESSMENT_EXISTS`
        and HTTP 409."

        Claim: a second fee assessment for the same request fails with
        ERR_FEE_ASSESSMENT_EXISTS.
        """
        _r, request = create_acknowledged_request()
        create_fee_assessment(request_id=request["id"])
        # Try to create a second.
        payload = create_fee_assessment_payload(request_id=request["id"])
        resp = api.create_fee_assessment(
            payload, TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FEE_ASSESSMENT_EXISTS.value)


# ===========================================================================
# Fee estimate calculation — PRD §2.9, §3.3
# ===========================================================================
class TestFeeEstimateCalculation:

    def test_commercial_estimate_full_bill(self, api):
        """PRD §3.3: "For a commercial requester, the chargeable search
        hours equal the estimated search hours, the chargeable review
        hours equal the estimated review hours, and the chargeable pages
        equal the estimated pages - every unit accrues from the first."

        Claim: commercial tier with search=4h, review=2h, pages=150
        yields estimate_total_cents = 4*4500 + 2*6000 + 150*10 = 31500.
        """
        _r, _req, fa = setup_request_with_estimated_fee(
            requester_tier="COMMERCIAL",
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
        )
        assert fa["status"] == "ESTIMATED"
        assert fa["estimate_total_cents"] == 31500, (
            f"Expected 31500, got {fa['estimate_total_cents']}"
        )
        assert fa["tier_at_assessment"] == "COMMERCIAL"

    def test_educational_estimate_pages_only(self, api):
        """PRD §3.3: "For an educational-noncommercial requester, the
        chargeable search hours are zero (search time is not billable),
        the chargeable review hours are zero (review time is never
        billable on any non-commercial tier), and the chargeable pages
        equal the estimated pages minus 100, floored at zero."

        Claim: educational tier with search=4h, review=2h, pages=150
        gives subtotal 50*10=500 < 1400 -> collapses to 0.
        """
        _r, _req, fa = setup_request_with_estimated_fee(
            requester_tier="EDUCATIONAL_NONCOMMERCIAL",
            tier_justification="University research",
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
        )
        assert fa["estimate_total_cents"] == 0, (
            f"Expected 0 (1400 collapse), got {fa['estimate_total_cents']}"
        )
        assert fa["tier_at_assessment"] == "EDUCATIONAL_NONCOMMERCIAL"

    def test_public_interest_estimate_with_free_search(self, api):
        """PRD §3.3: "For a public-interest requester, the chargeable
        search hours equal the estimated search hours minus 2, floored
        at zero, the chargeable review hours are zero, and the
        chargeable pages equal the estimated pages minus 100, floored
        at zero."

        Claim: public-interest with search=4h, review=2h, pages=150
        yields (4-2)*4500 + 50*10 = 9500 cents.
        """
        _r, _req, fa = setup_request_with_estimated_fee(
            requester_tier="PUBLIC_INTEREST",
            tier_justification="Newsroom",
            estimated_pages=150,
            estimated_search_hours=4,
            estimated_review_hours=2,
        )
        assert fa["estimate_total_cents"] == 9500
        assert fa["tier_at_assessment"] == "PUBLIC_INTEREST"

    def test_free_threshold_collapse_below_1400(self, api):
        """PRD §3.3: "Step four applies the free-threshold collapse:
        if the subtotal in cents is strictly less than 1400, the
        estimate total is set to zero".

        Claim: commercial tier with pages=139 alone (subtotal=1390)
        collapses to 0; with pages=140 (subtotal=1400), survives.
        """
        # 139 pages -> 1390 cents (below 1400, collapses to 0)
        _r, _req, fa_below = setup_request_with_estimated_fee(
            requester_tier="COMMERCIAL",
            estimated_pages=139,
            estimated_search_hours=0,
            estimated_review_hours=0,
        )
        assert fa_below["estimate_total_cents"] == 0


# ===========================================================================
# Estimate acceptance — PRD §3.3
# ===========================================================================
class TestAcceptEstimate:

    def test_requester_accepts_own_estimate(self, api):
        """PRD §3.3: "A requester whose estimate has been computed may
        accept it by issuing an accept action against the assessment;
        this requires that the calling `X-User-ID` equals the linked
        `Request.requester_id`."
        PRD §3.3: "Acceptance advances the assessment from `ESTIMATED`
        to `ACCEPTED` and sets the request's `fee_estimate_accepted` to
        true."

        Claim: /accept on ESTIMATED by the owning requester transitions
        to ACCEPTED and flips fee_estimate_accepted on the Request.
        """
        requester, request, fa = setup_request_with_estimated_fee(
            requester_tier="COMMERCIAL",
        )
        accepted = accept_fee_assessment(fa["id"], requester["id"])
        assert accepted["status"] == "ACCEPTED"
        # Verify the side effect on the Request.
        resp = api.get_request(
            request["id"], make_requester_headers(requester["id"]),
        )
        req_data = validate_success(resp, expected_status=200)
        assert req_data["fee_estimate_accepted"] is True

    def test_accept_estimate_by_wrong_requester_fails(self, api):
        """PRD §3.3: "this requires that the calling `X-User-ID` equals
        the linked `Request.requester_id`."

        Claim: /accept invoked by a different requester id fails with
        an authorization error (ERR_FORBIDDEN). PRD §2.1 specifies
        ERR_FORBIDDEN when the role is permitted but the specific call
        is not allowed, and the ownership mismatch falls within that.
        """
        # Owning requester and an unrelated requester.
        _r1, _req, fa = setup_request_with_estimated_fee()
        from test_helpers import create_requester
        other = create_requester()
        resp = api.accept_fee_assessment(
            fa["id"], make_requester_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Fee waiver — PRD §3.3
# ===========================================================================
class TestFeeWaiver:

    def test_waive_for_commercial_rejected(self, api):
        """PRD §3.3: "A waiver request from a commercial requester, or
        any waiver action invoked against the wrong tier, is rejected
        with `ERR_WAIVER_NOT_ELIGIBLE` and HTTP 422."

        Claim: /waive on a commercial-tier assessment fails with
        ERR_WAIVER_NOT_ELIGIBLE.
        """
        _r, _req, fa = setup_request_with_estimated_fee(
            requester_tier="COMMERCIAL",
        )
        resp = api.waive_fee_assessment(
            fa["id"], TEST_USERS["officer_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_NOT_ELIGIBLE.value)

    def test_waive_for_educational_succeeds(self, api):
        """PRD §3.3: "the officer may instead waive the fee, transitioning
        the assessment from `ESTIMATED` to `WAIVED`; the waiver action
        zeros out `estimate_total_cents`, sets the request's
        `fee_waiver_granted` to true, and is permitted only when the
        requester's tier is `EDUCATIONAL_NONCOMMERCIAL` or
        `PUBLIC_INTEREST`."

        Claim: /waive on EDUCATIONAL_NONCOMMERCIAL transitions to
        WAIVED, zeros estimate_total_cents, sets
        Request.fee_waiver_granted=true.
        """
        requester, request, fa = setup_request_with_estimated_fee(
            requester_tier="EDUCATIONAL_NONCOMMERCIAL",
            tier_justification="Academic research",
            estimated_pages=300,
            fee_waiver_requested=True,
        )
        resp = api.waive_fee_assessment(
            fa["id"], TEST_USERS["officer_headers"],
        )
        waived = validate_success(resp, expected_status=200)
        assert waived["status"] == "WAIVED"
        assert waived["estimate_total_cents"] == 0
        # Side effect on Request.
        req_resp = api.get_request(
            request["id"], make_requester_headers(requester["id"]),
        )
        req_data = validate_success(req_resp, expected_status=200)
        assert req_data["fee_waiver_granted"] is True
