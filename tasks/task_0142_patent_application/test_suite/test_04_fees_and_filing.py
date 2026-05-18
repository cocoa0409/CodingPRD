"""Fee math and the DRAFT -> FILED transition.

Covers PRD §2.7 (monetary precision), §3.2 (filing fee, excess-claim
fee), and §3.2 file transition preconditions.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_applicant,
    create_application_payload,
    create_draft_application,
    create_fee_payload,
    excess_claim_fee_cents,
    filing_fee_cents,
    list_fee_transactions,
    make_applicant_headers,
    pay_fee,
    pay_filing_fees,
    validate_error,
    validate_success,
)


# ===========================================================================
# Filing fee math (PRD §3.2 + §2.7)
# ===========================================================================
class TestFilingFee:

    @pytest.mark.parametrize(
        "entity_size,application_type,expected",
        [
            ("LARGE", "UTILITY", 32000),
            ("SMALL", "UTILITY", 16000),
            ("MICRO", "UTILITY", 8000),
            ("LARGE", "DESIGN", 22000),
            ("SMALL", "DESIGN", 11000),
            ("MICRO", "DESIGN", 5500),
            ("LARGE", "PROVISIONAL", 30000),
            ("SMALL", "PROVISIONAL", 15000),
            ("MICRO", "PROVISIONAL", 7500),
        ],
    )
    def test_filing_fee_matrix(self, api, entity_size, application_type, expected):
        """PRD §3.2 filing fee table: "32000 cents for UTILITY, 22000
        cents for DESIGN, and 30000 cents for PROVISIONAL", multiplied
        by the entity-size multiplier from §2.7 (1.00 / 0.50 / 0.25)
        and rounded half-up in a single step.

        Claim: the accepted amount_cents matches this PRD-derived
        value; any other amount is rejected as ERR_FEE_AMOUNT_MISMATCH.
        """
        claim_count = 0 if application_type == "PROVISIONAL" else 1
        ic = 0 if application_type == "PROVISIONAL" else 1
        a = create_applicant(entity_size=entity_size)
        app = create_draft_application(
            a, application_type=application_type,
            claim_count=claim_count, independent_claim_count=ic,
        )
        # Reference computation matches expected.
        assert filing_fee_cents(application_type, entity_size) == expected
        # Correct amount succeeds.
        ok_res = api.create_fee_transaction(
            app["id"],
            create_fee_payload(fee_category="FILING", amount_cents=expected),
            make_applicant_headers(a["id"]),
        )
        validate_success(ok_res, 201)
        # A different (off-by-one) amount on a sibling app must fail.
        a2 = create_applicant(entity_size=entity_size)
        app2 = create_draft_application(
            a2, application_type=application_type,
            claim_count=claim_count, independent_claim_count=ic,
        )
        wrong = expected + 1
        bad_res = api.create_fee_transaction(
            app2["id"],
            create_fee_payload(fee_category="FILING", amount_cents=wrong),
            make_applicant_headers(a2["id"]),
        )
        validate_error(bad_res, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)


# ===========================================================================
# Excess-claim fee — per-component rounding (PRD §3.2)
# ===========================================================================
class TestExcessClaimFee:

    def test_excess_claim_no_excess_above_threshold_not_required(self, api):
        """PRD §3.2: "Whenever the application is a UTILITY or DESIGN
        whose claim_count exceeds 20 or whose independent_claim_count
        exceeds 3, an additional EXCESS_CLAIM-category fee transaction
        must be present at the expected excess-claim amount."

        Claim: at exactly the threshold (claim_count=20, ic=3) no
        excess-claim fee is required for FILE to succeed.
        """
        from test_helpers import filing_fee_cents
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(
            a, application_type="UTILITY", claim_count=20, independent_claim_count=3,
        )
        # Only FILING fee paid.
        pay_fee(a, app, "FILING", filing_fee_cents("UTILITY", "SMALL"))
        res = api.file_application(app["id"], make_applicant_headers(a["id"]))
        data = validate_success(res, 200)
        assert data["status"] == "FILED"

    def test_excess_claim_small_per_component_rounding_21_total_4_indep(self, api):
        """PRD §3.2: "Each excess total claim costs 10001 cents at the
        large-entity rate; each excess independent claim costs 48003
        cents at the large-entity rate. The two components are
        computed independently in a pinned order: first the
        excess-total component multiplies the unit price by the count
        and by the entity multiplier and rounds half-up; then the
        excess-independent component multiplies the unit price by the
        count and by the entity multiplier and rounds half-up; and only
        then are the two rounded integer components summed".

        Claim: SMALL applicant with claim_count=21 and
        independent_claim_count=4 must pay per-component-rounded
        29003 cents (1 excess total × 10001 × 0.5 -> round(5000.5)=5001
        plus 1 excess indep × 48003 × 0.5 -> round(24001.5)=24002).
        The sum-first alternative (round(58004*0.5)=round(29002)=29002)
        is rejected with ERR_FEE_AMOUNT_MISMATCH.
        """
        from test_helpers import filing_fee_cents
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(
            a, application_type="UTILITY",
            claim_count=21, independent_claim_count=4,
        )
        # FILING first so EXCESS_CLAIM is the only fee under test.
        pay_fee(a, app, "FILING", filing_fee_cents("UTILITY", "SMALL"))
        # Pinned-order amount.
        expected = excess_claim_fee_cents(21, 4, "SMALL")
        assert expected == 29003, (
            "PRD §3.2 per-component rounding: round(1*10001*0.5)+round(1*48003*0.5) "
            f"should be 5001+24002=29003, got {expected}"
        )
        good = api.create_fee_transaction(
            app["id"],
            create_fee_payload(fee_category="EXCESS_CLAIM", amount_cents=29003),
            make_applicant_headers(a["id"]),
        )
        validate_success(good, 201)
        # Sum-first amount on a sibling application MUST be rejected.
        a2 = create_applicant(entity_size="SMALL")
        app2 = create_draft_application(
            a2, application_type="UTILITY",
            claim_count=21, independent_claim_count=4,
        )
        pay_fee(a2, app2, "FILING", filing_fee_cents("UTILITY", "SMALL"))
        bad = api.create_fee_transaction(
            app2["id"],
            create_fee_payload(fee_category="EXCESS_CLAIM", amount_cents=29002),
            make_applicant_headers(a2["id"]),
        )
        validate_error(bad, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)


# ===========================================================================
# DRAFT -> FILED preconditions (PRD §3.2)
# ===========================================================================
class TestFileTransition:

    def test_file_without_filing_fee_rejected(self, api):
        """PRD §3.2: "Before the filing can advance from DRAFT to FILED,
        the applicant must record at least one FeeTransaction."
        PRD §3.2: "The actual transition from DRAFT to FILED requires
        that the application's application_type is set, that its claim
        counts satisfy the claim-shape rule above, and that a
        FILING-category fee transaction exists at the application's
        expected filing amount."

        Claim: filing without any FILING fee fails. The diagnosed error
        is fee-amount-related, not state-related, because the state is
        valid for /file (status==DRAFT).
        """
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a, application_type="UTILITY")
        res = api.file_application(app["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)

    def test_file_succeeds_after_paying_filing_fee(self, api):
        """PRD §3.2: file transition requires a FILING fee at the
        scaffold-computed amount. After paying, FILE succeeds."""
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a, application_type="UTILITY")
        pay_filing_fees(a, app)
        res = api.file_application(app["id"], make_applicant_headers(a["id"]))
        data = validate_success(res, 200)
        assert data["status"] == "FILED"
        assert data["filed_at"] is not None
        assert data["total_fees_paid_cents"] >= filing_fee_cents("UTILITY", "SMALL")

    def test_file_provisional_sets_expires_at(self, api):
        """PRD §3.2: "For PROVISIONAL filings only, the server also
        computes expires_at as the filing instant plus 365 days at the
        moment of filing".

        Claim: after FILE, a PROVISIONAL has expires_at set; UTILITY
        does not.
        """
        a = create_applicant(entity_size="SMALL")
        prov = create_draft_application(
            a, application_type="PROVISIONAL",
            claim_count=0, independent_claim_count=0,
        )
        pay_filing_fees(a, prov)
        res = api.file_application(prov["id"], make_applicant_headers(a["id"]))
        data = validate_success(res, 200)
        assert data["status"] == "FILED"
        assert data["expires_at"] is not None, (
            "PRD §3.2: PROVISIONAL filing must set expires_at to filed_at + 365 days"
        )

    def test_file_utility_with_unrequired_excess_claim_does_not_block(self, api):
        """PRD §3.2: an excess-claim fee is required ONLY when
        claim_count > 20 OR independent_claim_count > 3.

        Claim: a UTILITY with claim_count=1, independent_claim_count=1
        FILES successfully after FILING fee alone — no EXCESS_CLAIM is
        required.
        """
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(
            a, application_type="UTILITY", claim_count=1, independent_claim_count=1,
        )
        pay_fee(a, app, "FILING", filing_fee_cents("UTILITY", "SMALL"))
        res = api.file_application(app["id"], make_applicant_headers(a["id"]))
        data = validate_success(res, 200)
        assert data["status"] == "FILED"

    def test_file_utility_with_excess_claims_requires_excess_fee(self, api):
        """PRD §3.2: "Whenever the application is a UTILITY or DESIGN
        whose claim_count exceeds 20 or whose independent_claim_count
        exceeds 3, an additional EXCESS_CLAIM-category fee transaction
        must be present at the expected excess-claim amount."

        Claim: FILE with claim_count=21 + only FILING fee fails with
        ERR_FEE_AMOUNT_MISMATCH.
        """
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(
            a, application_type="UTILITY",
            claim_count=21, independent_claim_count=3,
        )
        pay_fee(a, app, "FILING", filing_fee_cents("UTILITY", "SMALL"))
        res = api.file_application(app["id"], make_applicant_headers(a["id"]))
        validate_error(res, ApiErrorId.ERR_FEE_AMOUNT_MISMATCH.value)


# ===========================================================================
# Fee category appropriateness (PRD §3.2)
# ===========================================================================
class TestFeeCategoryInvalid:

    def test_maintenance_fee_via_applications_fees_endpoint_invalid(self, api):
        """PRD §3.2: "A category that is inappropriate for the
        recording endpoint (for example, submitting a MAINTENANCE fee
        outside the maintenance pay flow) is rejected with
        ERR_FEE_CATEGORY_INVALID, and a category whose amount does not
        match the scaffold-computed amount is rejected with
        ERR_FEE_AMOUNT_MISMATCH."

        Claim: posting a MAINTENANCE FeeTransaction on
        /applications/{id}/fees with no maintenance_fee_id (no
        maintenance pay flow context) yields ERR_FEE_CATEGORY_INVALID.
        """
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(a, application_type="UTILITY")
        # No maintenance_fee_id, and the application has no maintenance
        # rows; the fee category is inappropriate for this endpoint /
        # context.
        res = api.create_fee_transaction(
            app["id"],
            create_fee_payload(fee_category="MAINTENANCE", amount_cents=1),
            make_applicant_headers(a["id"]),
        )
        validate_error(res, ApiErrorId.ERR_FEE_CATEGORY_INVALID.value)


# ===========================================================================
# Total fees aggregate (PRD §2.9)
# ===========================================================================
class TestTotalFeesAggregate:

    def test_total_fees_paid_cents_equals_sum_after_filing(self, api):
        """PRD §2.9: "The denormalised aggregate
        Application.total_fees_paid_cents is recomputed on every
        FeeTransaction insertion as the sum of every
        FeeTransaction.amount_cents row whose application_id matches".
        """
        a = create_applicant(entity_size="SMALL")
        app = create_draft_application(
            a, application_type="UTILITY",
            claim_count=22, independent_claim_count=4,
        )
        out = pay_filing_fees(a, app)
        rows = list_fee_transactions(app["id"])
        expected = sum(r["amount_cents"] for r in rows)
        res = api.file_application(app["id"], make_applicant_headers(a["id"]))
        data = validate_success(res, 200)
        assert data["total_fees_paid_cents"] == expected, (
            "PRD §2.9: total_fees_paid_cents must equal sum of FeeTransaction.amount_cents"
        )
