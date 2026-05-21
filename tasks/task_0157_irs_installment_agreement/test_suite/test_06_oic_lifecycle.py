"""Offer in Compromise lifecycle: deposit, submit, take-up, decide
(accept / reject), withdraw. PRD §3.8 and the segregation-of-duties
rule from PRD §2.8.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_offer_in_compromise,
    create_draft_oic,
    create_offer_in_compromise_payload,
    create_taxpayer,
    create_tax_liability,
    decide_offer_in_compromise_payload,
    get_offer_in_compromise,
    get_tax_liability,
    make_oic_officer_headers,
    make_taxpayer_headers,
    pay_oic_deposit,
    setup_oic_under_review,
    submit_oic,
    take_up_oic,
    validate_error,
    validate_success,
)


class TestOICDraft:

    def test_draft_oic_returns_201_and_in_draft(self, api):
        """PRD §3.8: "The offer is created in status DRAFT."

        Claim: a freshly drafted OIC has status == DRAFT.
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=2_000_000,
        )
        payload = create_offer_in_compromise_payload(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000,
            schedule_months=5,
        )
        resp = api.create_offer_in_compromise(
            payload, make_taxpayer_headers(taxpayer["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert_offer_in_compromise(data)
        assert data["status"] == "DRAFT"


class TestOICSubmit:

    def test_submit_without_deposit_rejected(self, api):
        """PRD §3.8: "It requires that a Payment of payment_kind
        OIC_DEPOSIT exists for the offer with amount_cents at least
        equal to twenty percent of offer_amount_cents, rounded up to
        the next whole cent (the standard non-refundable 20% deposit).
        A deposit that falls short is rejected with
        ERR_DEPOSIT_INSUFFICIENT."

        Claim: submit with no deposit at all → ERR_DEPOSIT_INSUFFICIENT.
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=2_000_000,
        )
        oic = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000,
            schedule_months=5,
        )
        resp = api.submit_offer_in_compromise(
            oic["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT.value)

    def test_submit_with_short_deposit_rejected(self, api):
        """PRD §3.8: "A deposit that falls short is rejected with
        ERR_DEPOSIT_INSUFFICIENT."

        Claim: 20% of 1_500_000 = 300_000; a 299_999 deposit is
        rejected.
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=2_000_000,
        )
        oic = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000,
            schedule_months=5,
        )
        pay_oic_deposit(taxpayer["id"], oic["id"], 299_999)
        resp = api.submit_offer_in_compromise(
            oic["id"], make_taxpayer_headers(taxpayer["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DEPOSIT_INSUFFICIENT.value)

    def test_submit_with_exact_20pct_deposit_succeeds(self, api):
        """PRD §3.8: "amount_cents at least equal to twenty percent of
        offer_amount_cents."

        Claim: 20% deposit (exactly) succeeds; OIC.status == SUBMITTED.
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=2_000_000,
        )
        oic = create_draft_oic(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000,
            schedule_months=5,
        )
        pay_oic_deposit(taxpayer["id"], oic["id"], 300_000)
        submitted = submit_oic(taxpayer["id"], oic["id"])
        assert submitted["status"] == "SUBMITTED"


class TestSegregationOfDuties:

    def test_same_officer_take_up_then_decide_rejected(self, api):
        """PRD §2.8: "Within the Offer in Compromise pipeline, the
        `OICOfficer` who takes up a submitted offer cannot be the same
        operator who later issues the accept or reject decision; a
        mismatched decision attempt is rejected with
        `ERR_SEGREGATION_OF_DUTIES`."

        Claim: take-up by OICO_X, decide by OICO_X →
        ERR_SEGREGATION_OF_DUTIES.

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_oic_decide
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=1_000_000,
        )
        oic = setup_oic_under_review(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_000_000,
            schedule_months=5,
            deposit_cents=200_000,
            take_up_officer_id="oic-officer-same",
        )
        resp = api.decide_offer_in_compromise(
            oic["id"],
            decide_offer_in_compromise_payload("ACCEPT"),
            make_oic_officer_headers("oic-officer-same"),
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    def test_segregation_wins_over_below_rcp(self, api):
        """PRD §2.10 + §2.8: priority 8 (ERR_SEGREGATION_OF_DUTIES) runs
        before priority 18 (ERR_OIC_BELOW_RCP). When both conditions
        hold, segregation is reported.

        PRD §2.10: "After that come the segregation-of-duties checks at
        priorities 8 and 9 (both ERR_SEGREGATION_OF_DUTIES) ... the
        business-constraint band at priorities 13–19 (DDIA requirement,
        short-term gating, long-term gating, PPIA gating, OIC deposit,
        OIC RCP, lien withdrawal eligibility)."

        Claim: same-officer decide with offer < rcp →
        ERR_SEGREGATION_OF_DUTIES (not ERR_OIC_BELOW_RCP).

        # difficulty: priority_pair_validation_conflict/business_safety_vs_business_constraint_oic_decide
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=200_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=2_000_000,
        )
        # rcp for schedule 5 months = MDI * 12 = 2_400_000; offer of
        # 1_000_000 is below rcp.
        oic = setup_oic_under_review(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_000_000,
            schedule_months=5,
            deposit_cents=200_000,
            take_up_officer_id="oic-officer-A",
        )
        resp = api.decide_offer_in_compromise(
            oic["id"],
            decide_offer_in_compromise_payload("ACCEPT"),
            make_oic_officer_headers("oic-officer-A"),  # same officer
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)


class TestDifferentOfficerCanDecide:

    def test_different_officer_can_accept_with_offer_at_rcp(self, api):
        """PRD §3.8: "On an accept, every covered liability transitions
        to IN_COMPROMISE."
        PRD §2.8: "the `OICOfficer` who takes up a submitted offer
        cannot be the same operator who later issues the accept or
        reject decision."

        Claim: distinct take-up and decide officers, offer >= rcp →
        ACCEPT succeeds and OIC.status == ACCEPTED.
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=30_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=1_500_000,
        )
        # rcp for schedule 5 = MDI * 12 = 360_000; offer 1_500_000 > rcp.
        oic = setup_oic_under_review(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000,
            schedule_months=5,
            deposit_cents=300_000,
            take_up_officer_id="oic-officer-A",
        )
        resp = api.decide_offer_in_compromise(
            oic["id"],
            decide_offer_in_compromise_payload("ACCEPT"),
            make_oic_officer_headers("oic-officer-B"),
        )
        data = validate_success(resp)
        assert data["status"] == "ACCEPTED"

    def test_accept_transitions_covered_liability_to_in_compromise(self, api):
        """PRD §3.8: "On an accept, every covered liability transitions
        to IN_COMPROMISE."

        Claim: post-accept, covered liability is IN_COMPROMISE.
        """
        taxpayer = create_taxpayer(monthly_disposable_income_cents=30_000)
        liability = create_tax_liability(
            taxpayer["id"], original_assessed_amount_cents=1_500_000,
        )
        oic = setup_oic_under_review(
            taxpayer["id"], [liability["id"]],
            offer_amount_cents=1_500_000,
            schedule_months=5,
            deposit_cents=300_000,
            take_up_officer_id="oic-officer-A",
        )
        api.decide_offer_in_compromise(
            oic["id"],
            decide_offer_in_compromise_payload("ACCEPT"),
            make_oic_officer_headers("oic-officer-B"),
        )
        refreshed = get_tax_liability(liability["id"])
        assert refreshed["status"] == "IN_COMPROMISE"
