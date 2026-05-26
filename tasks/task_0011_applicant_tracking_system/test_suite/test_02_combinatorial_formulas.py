"""Combinatorial formulas: three-factor referral bonus, nested rounding order on payable."""
import pytest
from test_helpers import (
    api_client, TEST_USERS, set_clock, setup_offer_in_state, extend_offer,
    accept_offer, fetch_background_check_for_offer,
    fetch_referral_bonuses_for_offer,
    start_background_check, resolve_background_check, make_headers,
)


# =========================================================================
# Instance: referral_bonus_estimated_three_factor_conditional
# =========================================================================

class TestReferralBonusEstimatedThreeFactorConditional:
    """Two tests asserting the three-factor multiplicative formula."""

    def test_senior_band_15m_to_20m_with_hispanic_uplift(self, api):
        """PRD §3.6: "`SENIOR` to 400,000 cents (four thousand dollars)"
        PRD §3.6: "a value at or above that threshold but strictly less than
        20,000,000 cents (two hundred thousand dollars) applies a 1.5
        multiplier"
        PRD §3.6: "If the candidate qualifies as underrepresented — that is,
        the candidate's `eeo_ethnicity` is one of `BLACK`, `HISPANIC`,
        `NATIVE`, `PACIFIC`, or `TWO_OR_MORE`, **or** `eeo_disability` is
        true, **or** `eeo_veteran` is true — the raw amount is multiplied by
        1.20 as a diversity uplift."

        Design: Difficulty/combinatorial_formula/referral_bonus_estimated_three_factor_conditional
        """
        set_clock("2026-01-15T00:00:00Z")
        ctx = setup_offer_in_state(
            "EXTENDED",
            budget_cents=500_000_000,
            req_overrides={"target_level": "SENIOR",
                           "base_salary_min_cents": 15_000_000,
                           "base_salary_max_cents": 20_000_000,
                           "openings": 1},
            candidate_referrer_user_id="emp_ref_x",
            cand_overrides={"full_name": "Hispanic Senior",
                            "eeo_ethnicity": "HISPANIC",
                            "eeo_gender": "MALE",
                            "eeo_veteran": False,
                            "eeo_disability": False},
            base_salary_cents=18_000_000,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))

        bonuses = fetch_referral_bonuses_for_offer(offer["id"])
        assert len(bonuses) == 1
        rb = bonuses[0]
        # SENIOR base 400_000 * band_mult 1.5 * uplift 1.2 = 720_000 (exact)
        assert rb["estimated_amount_cents"] == 720_000, \
            f"Expected 720000, got {rb['estimated_amount_cents']}"
        assert rb["status"] == "PENDING_BGC"

    def test_junior_band_below_10m_no_uplift(self, api):
        """PRD §3.6: "`JUNIOR` corresponds to 100,000 cents (one thousand
        dollars)"
        PRD §3.6: "a value strictly less than 10,000,000 cents (one hundred
        thousand dollars) applies a 1.0 multiplier"

        Design: Difficulty/combinatorial_formula/referral_bonus_estimated_three_factor_conditional
        """
        set_clock("2026-01-15T00:00:00Z")
        # Salary 9_999_999 is strictly less than 10_000_000 → band_mult=1.0.
        # Min 5_000_000 keeps the band valid; max must exceed min.
        ctx = setup_offer_in_state(
            "EXTENDED",
            budget_cents=200_000_000,
            req_overrides={"target_level": "JUNIOR",
                           "base_salary_min_cents": 5_000_000,
                           "base_salary_max_cents": 9_999_999,
                           "openings": 1},
            candidate_referrer_user_id="emp_ref_j",
            cand_overrides={"full_name": "Junior White",
                            "eeo_ethnicity": "WHITE",
                            "eeo_gender": "MALE",
                            "eeo_veteran": False,
                            "eeo_disability": False},
            base_salary_cents=9_999_999,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))

        bonuses = fetch_referral_bonuses_for_offer(offer["id"])
        rb = bonuses[0]
        # JUNIOR base 100_000 * band_mult 1.0 * no uplift = 100_000.
        assert rb["estimated_amount_cents"] == 100_000, \
            f"Expected 100000, got {rb['estimated_amount_cents']}"


# =========================================================================
# Instance: referral_bonus_payable_nested_rounding_order
# =========================================================================

class TestReferralBonusPayableNestedRoundingOrder:
    """Two tests asserting the recompute-baseline-then-decay order."""

    def test_staff_underrepresented_baseline_at_zero_days(self, api):
        """PRD §3.7: "When the delay is at most 30 days, the payable equals
        the baseline."
        PRD §3.6: "`STAFF` to 600,000 cents (six thousand dollars)" and
        "a value at or above that threshold but strictly less than 20,000,000
        cents (two hundred thousand dollars) applies a 1.5 multiplier"
        PRD §3.6: "If the candidate qualifies as underrepresented ... the
        raw amount is multiplied by 1.20 as a diversity uplift."

        Design: Difficulty/combinatorial_formula/referral_bonus_payable_nested_rounding_order
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "EXTENDED",
            budget_cents=500_000_000,
            req_overrides={"target_level": "STAFF",
                           "base_salary_min_cents": 15_000_000,
                           "base_salary_max_cents": 20_000_000},
            candidate_referrer_user_id="emp_ref_y",
            cand_overrides={"full_name": "Black Staff",
                            "eeo_ethnicity": "BLACK",
                            "eeo_gender": "FEMALE",
                            "eeo_veteran": False,
                            "eeo_disability": False},
            base_salary_cents=18_000_000,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))

        # Resolve BGC immediately (delay 0) → payable == baseline.
        bgc = fetch_background_check_for_offer(offer["id"])
        start_background_check(bgc["id"])
        resolve_background_check(bgc["id"], outcome="PASSED")
        bonuses = fetch_referral_bonuses_for_offer(offer["id"])
        rb = bonuses[0]
        # baseline = 600_000 * 1.5 * 1.2 = 1_080_000 (exact).
        assert rb["estimated_amount_cents"] == 1_080_000
        assert rb["payable_amount_cents"] == 1_080_000, \
            f"Expected payable=baseline=1080000, got {rb['payable_amount_cents']}"
        assert rb["status"] == "PAYABLE"

    def test_staff_underrepresented_60_day_delay_decay_pinned_order(self, api):
        """PRD §3.7: "When the delay is more than 30 but at most 60 days, the
        payable is the baseline multiplied by 0.75 and rounded half-up to
        integer cents."
        PRD §3.7: "The recomputation re-runs the estimated-bonus formula
        against the current state of the offer, candidate, and requisition
        to produce a baseline, then applies a decay that depends on the
        elapsed time between the offer's acceptance and the background
        check's `completed_at`."

        Design: Difficulty/combinatorial_formula/referral_bonus_payable_nested_rounding_order
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "EXTENDED",
            budget_cents=500_000_000,
            req_overrides={"target_level": "STAFF",
                           "base_salary_min_cents": 15_000_000,
                           "base_salary_max_cents": 20_000_000},
            candidate_referrer_user_id="emp_ref_y2",
            cand_overrides={"full_name": "Black Staff2",
                            "eeo_ethnicity": "BLACK",
                            "eeo_gender": "FEMALE"},
            base_salary_cents=18_000_000,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))

        # 50-day delay falls in (30, 60] → multiplier 0.75.
        set_clock("2026-02-20T00:00:00Z")
        bgc = fetch_background_check_for_offer(offer["id"])
        start_background_check(bgc["id"])
        resolve_background_check(bgc["id"], outcome="PASSED")
        bonuses = fetch_referral_bonuses_for_offer(offer["id"])
        rb = bonuses[0]
        # baseline 1_080_000 then *0.75 = 810_000 (exact integer).
        assert rb["payable_amount_cents"] == 810_000, \
            f"Expected payable=810000 (1080000*0.75), got {rb['payable_amount_cents']}"
