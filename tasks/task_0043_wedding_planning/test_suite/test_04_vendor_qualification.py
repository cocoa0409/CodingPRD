"""Vendor onboarding, qualification transitions, and quote lifecycle.
Covers PRD §3.2.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    AUDITOR_ID,
    create_approved_vendor,
    create_quote_payload,
    create_vendor_payload,
    far_future_seconds,
    make_auditor_headers,
    make_vendor_rep_headers,
    now_seconds,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.2 -- Vendor registration and approval transitions.
# ===========================================================================
class TestVendorRegistration:

    def test_register_vendor_starts_in_pending_review(
        self, api, vendor_rep_headers_fallback
    ):
        """PRD §3.2: "Vendor onboarding is initiated by a VendorRep, who
        registers a new Vendor with a business name and a category drawn
        from VENUE, PHOTOGRAPHY, FLORAL, CATERING, MC, or BAND. The new
        vendor begins with qualification_status set to PENDING_REVIEW."

        Claim: POST /vendors -> qualification_status==PENDING_REVIEW.
        """
        res = api.create_vendor(
            create_vendor_payload(category="VENUE"),
            vendor_rep_headers_fallback,
        )
        data = validate_success(res, expected_status=201)
        assert data["qualification_status"] == "PENDING_REVIEW"


class TestVendorTransitions:

    def test_auditor_approve_vendor(self, api, auditor_headers,
                                    vendor_rep_headers_fallback):
        """PRD §3.2: "An Auditor then either approves the vendor
        (transitioning qualification_status to APPROVED) or rejects it
        (transitioning to REJECTED)."

        Claim: PENDING_REVIEW + auditor approve -> APPROVED.
        """
        res = api.create_vendor(
            create_vendor_payload(category="MC"),
            vendor_rep_headers_fallback,
        )
        v = validate_success(res, expected_status=201)
        res2 = api.approve_vendor(v["id"], auditor_headers)
        approved = validate_success(res2)
        assert approved["qualification_status"] == "APPROVED"

    def test_auditor_reject_vendor(self, api, auditor_headers,
                                   vendor_rep_headers_fallback):
        """PRD §3.2: "An `Auditor` then either approves the vendor
        (transitioning `qualification_status` to `APPROVED`) or rejects it
        (transitioning to `REJECTED`)."

        Claim: PENDING_REVIEW + auditor reject -> REJECTED.
        """
        res = api.create_vendor(
            create_vendor_payload(category="MC"),
            vendor_rep_headers_fallback,
        )
        v = validate_success(res, expected_status=201)
        res2 = api.reject_vendor(v["id"], auditor_headers)
        rejected = validate_success(res2)
        assert rejected["qualification_status"] == "REJECTED"

    def test_suspend_then_reinstate(self, api, auditor_headers):
        """PRD §3.2: "An APPROVED vendor may later be suspended by an
        auditor -- transitioning to SUSPENDED and cascading every Quote
        belonging to that vendor in DRAFT or OFFERED status to WITHDRAWN
        -- and a SUSPENDED vendor may be reinstated back to APPROVED."

        Claim: APPROVED -> suspend -> SUSPENDED -> reinstate -> APPROVED.
        """
        v = create_approved_vendor(category="FLORAL")
        sus = api.suspend_vendor(v["id"], auditor_headers)
        sus_data = validate_success(sus)
        assert sus_data["qualification_status"] == "SUSPENDED"
        rein = api.reinstate_vendor(v["id"], auditor_headers)
        rein_data = validate_success(rein)
        assert rein_data["qualification_status"] == "APPROVED"


# ===========================================================================
# §3.2 -- Suspension cascades to OFFERED quotes (forward-looking).
# ===========================================================================
class TestSuspensionCascade:

    def test_suspend_cascades_offered_quote_to_withdrawn(
        self, api, auditor_headers
    ):
        """PRD §3.2: "An APPROVED vendor may later be suspended by an
        auditor -- transitioning to SUSPENDED and cascading every Quote
        belonging to that vendor in DRAFT or OFFERED status to WITHDRAWN."

        Claim: APPROVED vendor + OFFERED quote + suspend -> Quote.status
        == WITHDRAWN.
        """
        v = create_approved_vendor(category="FLORAL")
        vrep = make_vendor_rep_headers(v["id"])
        q_resp = api.create_quote(
            v["id"], create_quote_payload(amount_cents=50_000), vrep,
        )
        quote = validate_success(q_resp, expected_status=201)
        api.offer_quote(v["id"], quote["id"], vrep)
        api.suspend_vendor(v["id"], auditor_headers)

        list_resp = api.list_quotes(v["id"], vrep,
                                    params={"limit": 100})
        from test_helpers import validate_paginated
        data, _meta = validate_paginated(list_resp)
        target = next(q for q in data if q["id"] == quote["id"])
        assert target["status"] == "WITHDRAWN", (
            f"PRD §3.2 cascades OFFERED -> WITHDRAWN on suspend; got "
            f"{target['status']}"
        )


# ===========================================================================
# §3.2 -- Quote lifecycle: DRAFT -> OFFERED preconditions.
# ===========================================================================
class TestQuoteOfferPreconditions:

    def test_offer_requires_approved_vendor(self, api,
                                            vendor_rep_headers_fallback):
        """PRD §3.2: "The vendor representative offers the quote
        (transitioning DRAFT to OFFERED), which requires the vendor's
        qualification_status to be APPROVED (otherwise ERR_VENDOR_NOT_APPROVED,
        HTTP 422)."

        Claim: PENDING_REVIEW vendor + offer -> ERR_VENDOR_NOT_APPROVED / 422.
        """
        v_resp = api.create_vendor(
            create_vendor_payload(category="BAND"),
            vendor_rep_headers_fallback,
        )
        v = validate_success(v_resp, expected_status=201)
        vrep = make_vendor_rep_headers(v["id"])
        q_resp = api.create_quote(
            v["id"], create_quote_payload(amount_cents=10_000), vrep,
        )
        q = validate_success(q_resp, expected_status=201)
        # Vendor never approved -> offer should fail.
        res = api.offer_quote(v["id"], q["id"], vrep)
        validate_error(res, ApiErrorId.ERR_VENDOR_NOT_APPROVED.value)

    def test_offer_requires_clock_strictly_less_than_valid_until(self, api):
        """PRD §3.2: "and the system clock to be strictly less than
        valid_until (otherwise ERR_QUOTE_EXPIRED)."

        Claim: APPROVED vendor + quote whose valid_until == now -1 -> offer
        rejected with ERR_QUOTE_EXPIRED.
        """
        v = create_approved_vendor(category="BAND")
        vrep = make_vendor_rep_headers(v["id"])
        q_resp = api.create_quote(
            v["id"],
            create_quote_payload(
                amount_cents=10_000,
                valid_until=now_seconds() - 1,
            ),
            vrep,
        )
        q = validate_success(q_resp, expected_status=201)
        res = api.offer_quote(v["id"], q["id"], vrep)
        validate_error(res, ApiErrorId.ERR_QUOTE_EXPIRED.value)


# ===========================================================================
# §3.2 -- Quote category copied from vendor.
# ===========================================================================
class TestQuoteCategoryCopy:

    def test_quote_category_copied_from_vendor(self, api):
        """PRD §3.2: "The quote's category is copied from Vendor.category
        at creation time and is not separately modifiable."

        Claim: vendor with category=BAND creates a quote -> quote.category=BAND.
        """
        v = create_approved_vendor(category="BAND")
        vrep = make_vendor_rep_headers(v["id"])
        res = api.create_quote(
            v["id"], create_quote_payload(amount_cents=10_000), vrep,
        )
        q = validate_success(res, expected_status=201)
        assert q["category"] == "BAND"
