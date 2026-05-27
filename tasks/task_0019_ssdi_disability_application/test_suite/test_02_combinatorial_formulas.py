"""Combinatorial formulas: PIA tiered bend points; QC nonlinear age bucket
with lookback gate."""
import pytest
from test_helpers import (
    validate_success, get_success_data, api_client, TEST_USERS,
    set_clock,
    setup_application_awarded,
    setup_application_in_medical_review,
    create_claimant, post_work_credit, post_work_credits_for_years,
    create_application_for_claimant, submit_application,
    make_claimant_headers,
)


# =========================================================================
# Instance: pia_tiered_bend_points_round_per_tier_then_sum
# =========================================================================

class TestPiaTieredBendPointsRoundPerTierThenSum:
    """Asserts the bend-point PIA formula on the BenefitAward."""

    def test_aime_400000_produces_pia_196092(self, api):
        """PRD §3.6: "Two bend points carve AIME into three tiers: the first
        tier is the portion of AIME up to and including 117400 cents (the
        first bend point, $1,174.00), the second tier is the portion of
        AIME above the first bend point up to and including 707900 cents
        (the second bend point, $7,079.00) — equivalently, capped at the
        difference between the two bend points, 590500 cents — and the
        third tier is the portion of AIME strictly above 707900 cents."
        PRD §3.6: "The PIA in cents is the sum of three rounded tier
        contributions: 0.90 of the first tier rounded half up to the
        nearest cent, plus 0.32 of the second tier rounded half up to the
        nearest cent, plus 0.15 of the third tier rounded half up to the
        nearest cent."

        Design: Difficulty/combinatorial_formula/pia_tiered_bend_points_round_per_tier_then_sum
        """
        set_clock("2026-01-15T00:00:00Z")
        # 12 years * 4_800_000 cents → AIME = (12 * 4_800_000) / (12 * 12) = 400000.
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "9999",
                "full_name": "Tier Test",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            application_overrides={
                "alleged_onset_date": "2024-01-01T00:00:00Z",
                "protective_filing_date": "2026-01-15T00:00:00Z",
                "claim_type": "SSDI_ONLY",
            },
            earnings_cents=4_800_000,
            medical_clock_override="2026-04-15T00:00:00Z",
        )
        award = ctx["award"]
        # tier1 = 117400 → 0.9*117400 = 105660 (whole)
        # tier2 = min(400000-117400, 707900-117400) = min(282600, 590500) = 282600
        #       → 0.32*282600 = 90432 (whole)
        # tier3 = 0
        # PIA = 105660 + 90432 + 0 = 196092
        assert award["primary_insurance_amount_cents"] == 196_092, \
            f"Expected PIA=196092 (105660+90432+0), got {award['primary_insurance_amount_cents']}"

    def test_pia_equals_monthly_benefit_for_primary_insured(self, api):
        """PRD §3.6: "The award's `monthly_benefit_cents` equals the
        computed PIA — for a primary insured the monthly cash benefit is
        the PIA itself."

        Design: Difficulty/combinatorial_formula/pia_tiered_bend_points_round_per_tier_then_sum
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_application_awarded(
            claimant_overrides={
                "ssn_last4": "9998",
                "full_name": "PIA Equal MB",
                "date_of_birth": "1980-01-01T00:00:00Z",
                "filing_state": "TX",
            },
            earnings_cents=4_800_000,
            medical_clock_override="2026-04-15T00:00:00Z",
        )
        award = ctx["award"]
        assert award["monthly_benefit_cents"] == award["primary_insurance_amount_cents"], \
            "monthly_benefit_cents must equal primary_insurance_amount_cents"
        assert award["monthly_benefit_cents"] == 196_092


# =========================================================================
# Instance: qc_count_nonlinear_age_bucket_with_lookback_gate
# =========================================================================

class TestQcCountNonlinearAgeBucketWithLookbackGate:
    """Young claimant: passes the age-adjusted total-quarters threshold but
    fails the 20-quarter recent-work gate → NOT_INSURED → DENIED_QC."""

    def test_young_claimant_with_six_recent_quarters_denied_qc(self, api):
        """PRD §3.2: "A claimant is `INSURED` if and only if both the
        total-quarters tally is at least the age-adjusted required total
        AND the recent-quarters tally is at least 20; otherwise the
        claimant is `NOT_INSURED`."
        PRD §3.2: "When `insured_status` resolves to `NOT_INSURED`, the
        server transitions through `QC_REVIEW` to the terminal `DENIED_QC`
        state and increments the `version`."

        Design: Difficulty/combinatorial_formula/qc_count_nonlinear_age_bucket_with_lookback_gate
        """
        set_clock("2026-01-15T00:00:00Z")
        # Age 23 → required total = 6. Has 6 total credits across 2 years,
        # but recent_qc = 6 < 20 → fails the recent-work gate.
        claimant = create_claimant(
            ssn_last4="1010",
            full_name="Young Claim",
            date_of_birth="2002-06-01T00:00:00Z",
            filing_state="TX",
        )
        post_work_credit(claimant["id"], 2024, credits_earned=3, earnings_cents=1_200_000)
        post_work_credit(claimant["id"], 2025, credits_earned=3, earnings_cents=1_200_000)
        app = create_application_for_claimant(
            claimant["id"],
            alleged_onset_date="2025-01-01T00:00:00Z",
            protective_filing_date="2026-01-15T00:00:00Z",
            claim_type="SSDI_ONLY",
        )
        app_submitted = submit_application(app["id"], claimant["id"])
        assert app_submitted["total_qc_at_filing"] == 6
        assert app_submitted["recent_qc_in_lookback"] == 6
        assert app_submitted["insured_status"] == "NOT_INSURED"
        assert app_submitted["status"] == "DENIED_QC"

    def test_qc_tallies_use_integer_arithmetic(self, api):
        """PRD §3.2: "Both tallies use integer arithmetic; there are no
        decimals."
        PRD §3.2: "The `total_qc_at_filing` is the sum of `credits_earned`
        across every `WorkCreditRecord` belonging to this claimant whose
        `year` is on or before the calendar year of the application's
        `filing_date`."

        Design: Difficulty/combinatorial_formula/qc_count_nonlinear_age_bucket_with_lookback_gate
        """
        set_clock("2026-01-15T00:00:00Z")
        claimant = create_claimant(
            ssn_last4="1011",
            full_name="QC Integer",
            date_of_birth="2002-06-01T00:00:00Z",
            filing_state="TX",
        )
        post_work_credit(claimant["id"], 2024, credits_earned=2, earnings_cents=600_000)
        post_work_credit(claimant["id"], 2025, credits_earned=3, earnings_cents=900_000)
        app = create_application_for_claimant(
            claimant["id"],
            alleged_onset_date="2025-01-01T00:00:00Z",
            protective_filing_date="2026-01-15T00:00:00Z",
        )
        app_submitted = submit_application(app["id"], claimant["id"])
        assert isinstance(app_submitted["total_qc_at_filing"], int)
        assert isinstance(app_submitted["recent_qc_in_lookback"], int)
        assert app_submitted["total_qc_at_filing"] == 5
        assert app_submitted["recent_qc_in_lookback"] == 5
