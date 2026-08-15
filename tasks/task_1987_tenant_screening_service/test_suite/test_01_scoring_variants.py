"""Difficulty queue A tests: dual-variant calculations and decision-table composition."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    create_and_resolve_income_verification,
    create_applicant,
    create_application,
    create_guarantor_payload,
    create_jurisdiction_rule,
    evaluate_guarantor_payload,
    get_application,
    get_guarantor,
    make_landlord_headers,
    record_searches_payload,
    run_record_searches,
    score_application,
    setup_landlord_with_criteria,
    setup_submitted_application,
    submit_application,
    verify_identity,
    consent_application,
)
from test_helpers import TEST_USERS

SCREENER = TEST_USERS["screener_headers"]


class TestSoiAdjustedRatioVsStandardRatio:
    def test_soi_variant_passes_when_voucher_reduces_rent(self):
        """PRD §3.6: "The **source-of-income-adjusted variant** applies when the
        covering jurisdiction rule's `source_of_income_protected` is true, the
        application carries a positive `voucher_monthly_amount_cents`, and the
        pinned criteria's `accepts_voucher_income` is true. Only the tenant's
        share of rent is tested: the applicable rent is `monthly_rent_cents`
        minus `voucher_monthly_amount_cents`, and when that difference is zero
        or negative, affordability passes automatically; otherwise the same
        multiplier threshold is applied to the reduced rent."

        Design: Difficulty/dual_variant_calc/soi_adjusted_ratio_vs_standard_ratio
        """
        landlord, _ = setup_landlord_with_criteria(
            jurisdiction_rule={
                "state_code": "CA",
                "source_of_income_protected": True,
                "portable_report_acceptance_required": True,
            },
            criteria_overrides={"accepts_voucher_income": True},
        )
        applicant = create_applicant(residence_state="CA")
        app = create_application(
            landlord,
            applicant,
            unit_state_code="CA",
            monthly_rent_cents=200000,
            stated_monthly_income_cents=500000,
            voucher_monthly_amount_cents=100000,
        )
        consent_application(app, applicant)
        verify_identity(app)
        app = submit_application(app, landlord)
        run_record_searches(app)
        create_and_resolve_income_verification(app, 500000)
        scored = score_application(app)
        assert scored["affordability_passes"] is True, (
            "SOI variant: applicable rent 100000, threshold 300000, 500000 >= 300000"
        )
        assert scored["recommendation"] == "RECOMMEND_APPROVE"

    def test_standard_variant_applies_without_soi_rule(self):
        """PRD §3.6: "In the **standard variant**, the pass threshold is the
        pinned criteria's `income_multiplier` times the application's
        `monthly_rent_cents`, rounded half-up to integer cents; the application
        passes when `verified_income_cents` is not null and is at least the
        threshold — income exactly equal to the threshold passes."

        Design: Difficulty/dual_variant_calc/soi_adjusted_ratio_vs_standard_ratio
        """
        landlord, _ = setup_landlord_with_criteria(
            criteria_overrides={"accepts_voucher_income": True},
        )
        applicant = create_applicant(residence_state="TX")
        app = create_application(
            landlord,
            applicant,
            unit_state_code="TX",
            monthly_rent_cents=200000,
            stated_monthly_income_cents=500000,
            voucher_monthly_amount_cents=100000,
        )
        consent_application(app, applicant)
        verify_identity(app)
        app = submit_application(app, landlord)
        run_record_searches(app)
        create_and_resolve_income_verification(app, 500000)
        scored = score_application(app)
        assert scored["affordability_passes"] is False, (
            "standard variant: threshold 600000, 500000 < 600000"
        )
        assert scored["recommendation"] == "RECOMMEND_DENY"


class TestGuarantorPolicyCombinedVsIndependent:
    def _setup_guarantor(self, guarantor_policy):
        landlord, _ = setup_landlord_with_criteria(
            criteria_overrides={"guarantor_policy": guarantor_policy},
        )
        applicant = create_applicant(residence_state="TX")
        app, applicant = setup_submitted_application(
            landlord,
            applicant,
            unit_state_code="TX",
            monthly_rent_cents=200000,
            stated_monthly_income_cents=400000,
        )
        create_and_resolve_income_verification(app, 400000)
        resp = api_client.create_guarantor(
            app["id"],
            create_guarantor_payload(full_name="Gill G", stated_monthly_income_cents=300000),
            make_landlord_headers(landlord["id"]),
        )
        guarantor = resp.json()["data"]
        return guarantor

    def test_combined_allowed_pools_applicant_and_guarantor_income(self):
        """PRD §3.5: "Under `COMBINED_ALLOWED`, the applicant's verified income
        — the income verification's `verified_monthly_income_cents` when it is
        `VERIFIED`, and zero otherwise — is pooled with the guarantor's verified
        income, and the combined sum must reach the product of the criteria's
        ordinary `income_multiplier` and the `monthly_rent_cents`, rounded
        half-up to integer cents."

        Design: Difficulty/dual_variant_calc/guarantor_policy_combined_vs_independent
        """
        guarantor = self._setup_guarantor("COMBINED_ALLOWED")
        resp = api_client.evaluate_guarantor(
            guarantor["id"], evaluate_guarantor_payload(300000, 720), SCREENER
        )
        data = resp.json()["data"]
        assert data["status"] == "APPROVED", "400000 + 300000 = 700000 >= 600000"
        assert data["qualification_policy_used"] == "COMBINED_ALLOWED"

    def test_independent_only_ignores_applicant_income(self):
        """PRD §3.5: "Under `INDEPENDENT_ONLY`, the guarantor qualifies when
        their verified income alone reaches the product of the criteria's
        `guarantor_income_multiplier` and the application's `monthly_rent_cents`,
        rounded half-up to integer cents. The applicant's income is ignored
        entirely in this variant."

        Design: Difficulty/dual_variant_calc/guarantor_policy_combined_vs_independent
        """
        guarantor = self._setup_guarantor("INDEPENDENT_ONLY")
        resp = api_client.evaluate_guarantor(
            guarantor["id"], evaluate_guarantor_payload(300000, 720), SCREENER
        )
        data = resp.json()["data"]
        assert data["status"] == "DECLINED", "300000 < round_half_up(4.0 * 200000) = 800000"
        assert data["qualification_policy_used"] == "INDEPENDENT_ONLY"


class TestRecommendationDecisionTableGuarantorRescue:
    def _setup_application(self, landlord, with_guarantor):
        applicant = create_applicant(residence_state="TX")
        app = create_application(
            landlord,
            applicant,
            unit_state_code="TX",
            monthly_rent_cents=200000,
            stated_monthly_income_cents=400000,
        )
        consent_application(app, applicant)
        verify_identity(app)
        app = submit_application(app, landlord)
        run_record_searches(app, credit_score=700)
        create_and_resolve_income_verification(app, 400000)
        if with_guarantor:
            resp = api_client.create_guarantor(
                app["id"],
                create_guarantor_payload(full_name="Gill G", stated_monthly_income_cents=300000),
                make_landlord_headers(landlord["id"]),
            )
            g = resp.json()["data"]
            api_client.evaluate_guarantor(g["id"], evaluate_guarantor_payload(300000, 720), SCREENER)
        return app

    def test_approved_guarantor_lands_on_conditional_branch(self):
        """PRD §3.6: "Fifth, the existence of an `APPROVED` guarantor on the
        application recommends a conditional outcome."

        Design: Difficulty/combinatorial_formula/recommendation_decision_table_guarantor_rescue
        """
        landlord, _ = setup_landlord_with_criteria(
            criteria_overrides={"guarantor_policy": "COMBINED_ALLOWED"},
        )
        app = self._setup_application(landlord, with_guarantor=True)
        scored = score_application(app)
        assert scored["affordability_passes"] is False, "400000 < 600000"
        assert scored["recommendation"] == "RECOMMEND_CONDITIONAL", (
            "branch 5: APPROVED guarantor exists"
        )

    def test_no_guarantor_falls_through_to_deny(self):
        """PRD §3.6: "The `recommendation` is then read from a pinned decision table, evaluated in order with the first matching branch winning."
        PRD §3.6: "Anything else recommends denial."

        Design: Difficulty/combinatorial_formula/recommendation_decision_table_guarantor_rescue
        """
        landlord, _ = setup_landlord_with_criteria()
        app = self._setup_application(landlord, with_guarantor=False)
        scored = score_application(app)
        assert scored["affordability_passes"] is False
        assert scored["recommendation"] == "RECOMMEND_DENY", "branch 6: fall-through"
