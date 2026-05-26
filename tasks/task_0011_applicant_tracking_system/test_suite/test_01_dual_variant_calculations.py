"""Dual-variant calculations: estimated vs payable referral bonus, pool vs hire diversity."""
import pytest
from test_helpers import (
    validate_success, get_success_data, api_client, TEST_USERS,
    set_clock, setup_offer_in_state, extend_offer, accept_offer,
    fetch_background_check_for_offer, fetch_referral_bonuses_for_offer,
    start_background_check, resolve_background_check,
    setup_approved_req_with_screened_app,
    create_diversity_goal, read_diversity_goal,
    create_candidate, create_application, screen_application,
    create_offer, fully_approve_offer,
    make_headers,
)


# =========================================================================
# Instance: referral_bonus_estimated_vs_payable_diverge_on_60_day_delay
# =========================================================================

class TestReferralBonusEstimatedVsPayableDivergeOn60DayDelay:
    """Two tests for the same instance, both pinned to verbatim PRD prose."""

    def test_estimated_amount_captured_at_accept_uses_zero_day_baseline(self, api):
        """PRD §3.7: "the estimate captured at offer acceptance implicitly
        assumes a delay of zero days and always returns the baseline, while
        the payable captured at background-check clearance uses the actual
        elapsed delay and may produce a strictly smaller integer when
        clearance is slow."
        PRD §3.6: "`MID` to 200,000 cents (two thousand dollars)" and "a value
        at or above that threshold but strictly less than 15,000,000 cents
        (one hundred fifty thousand dollars) applies a 1.25 multiplier".

        Design: Difficulty/dual_variant_calc/referral_bonus_estimated_vs_payable_diverge_on_60_day_delay
        """
        set_clock("2026-01-01T00:00:00Z")
        # MID requisition + REFERRAL candidate (no diversity uplift), salary in 10M..15M band.
        ctx = setup_offer_in_state(
            "EXTENDED",
            req_overrides={"target_level": "MID",
                           "base_salary_min_cents": 10_000_000,
                           "base_salary_max_cents": 18_000_000,
                           "openings": 1},
            candidate_referrer_user_id="emp_referrer_1",
            cand_overrides={"eeo_ethnicity": "WHITE", "eeo_gender": "FEMALE",
                            "eeo_veteran": False, "eeo_disability": False},
            base_salary_cents=12_000_000,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))

        bonuses = fetch_referral_bonuses_for_offer(offer["id"])
        assert len(bonuses) == 1, "Exactly one ReferralBonus created on REFERRAL accept"
        rb = bonuses[0]
        # MID base_cents=200_000 * band_mult 1.25 * uplift 1.0 = 250_000
        assert rb["estimated_amount_cents"] == 250_000, \
            f"Expected 250000, got {rb['estimated_amount_cents']}"
        assert rb["status"] == "PENDING_BGC"
        assert rb["payable_amount_cents"] is None

    def test_payable_at_60_day_delay_decays_by_quarter(self, api):
        """PRD §3.7: "When the delay is more than 30 but at most 60 days, the
        payable is the baseline multiplied by 0.75 and rounded half-up to
        integer cents."
        PRD §3.7: "The elapsed-day count is the integer floor of the
        difference (in days)."

        Design: Difficulty/dual_variant_calc/referral_bonus_estimated_vs_payable_diverge_on_60_day_delay
        """
        set_clock("2026-01-01T00:00:00Z")
        ctx = setup_offer_in_state(
            "EXTENDED",
            req_overrides={"target_level": "MID",
                           "base_salary_min_cents": 10_000_000,
                           "base_salary_max_cents": 18_000_000},
            candidate_referrer_user_id="emp_referrer_1",
            cand_overrides={"eeo_ethnicity": "WHITE", "eeo_gender": "FEMALE",
                            "eeo_veteran": False, "eeo_disability": False},
            base_salary_cents=12_000_000,
        )
        cand = ctx["candidate"]
        offer = ctx["offer"]
        accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))

        # Advance to 60 days after accept → elapsed delay = 60 days (integer floor),
        # within "more than 30 but at most 60 days" band → 0.75 × baseline.
        set_clock("2026-03-02T00:00:00Z")
        bgc = fetch_background_check_for_offer(offer["id"])
        start_background_check(bgc["id"])
        resolve_background_check(bgc["id"], outcome="PASSED")

        bonuses = fetch_referral_bonuses_for_offer(offer["id"])
        rb = bonuses[0]
        # baseline = 250_000; payable = round_half_up(250_000 * 0.75) = 187_500
        assert rb["payable_amount_cents"] == 187_500, \
            f"Expected payable=187500 (0.75 * baseline 250000), got {rb['payable_amount_cents']}"
        # Conservation: estimated stays as captured baseline (0-day assumption).
        assert rb["estimated_amount_cents"] == 250_000
        assert rb["status"] == "PAYABLE"


# =========================================================================
# Instance: diversity_pool_vs_hire_diverge_on_same_goal
# =========================================================================

class TestDiversityPoolVsHireDivergeOnSameGoal:
    """Two tests for the same instance, both pinned to verbatim PRD prose."""

    def test_pool_metric_counts_distinct_non_withdrawn_candidates(self, api):
        """PRD §3.1: "Take every candidate who has at least one application against
        any requisition belonging to the goal's department whose `target_level`
        matches the goal's stratum, where the application's `created_at` falls
        in the goal's `period_year` (UTC) and the application's `status` is
        not `WITHDRAWN`."
        PRD §3.1: "The numerator is the count of those candidates whose
        `eeo_ethnicity` is one of `BLACK`, `HISPANIC`, `NATIVE`, `PACIFIC`,
        or `TWO_OR_MORE`, **or** whose `eeo_disability` flag is true, **or**
        whose `eeo_veteran` flag is true."

        Design: Difficulty/dual_variant_calc/diversity_pool_vs_hire_diverge_on_same_goal
        """
        set_clock("2026-02-01T00:00:00Z")
        dept, req, _, _ = setup_approved_req_with_screened_app(
            req_overrides={"target_level": "MID",
                           "base_salary_min_cents": 10_000_000,
                           "base_salary_max_cents": 18_000_000,
                           "openings": 1},
            cand_overrides={"full_name": "C0 ignored", "eeo_ethnicity": "WHITE"},
        )
        # Above seeded one WHITE candidate already; ignore it for clarity by creating
        # a brand-new department to scope the goal cleanly.
        # Build a clean second department where we control the population exactly.
        from test_helpers import create_department, create_approved_requisition

        d2 = create_department(budget_cents=200_000_000)
        _, r2 = create_approved_requisition(
            department_id=d2["id"],
            req_overrides={"target_level": "MID",
                           "base_salary_min_cents": 10_000_000,
                           "base_salary_max_cents": 18_000_000},
        )
        goal = create_diversity_goal(d2["id"], target_level="MID",
                                     period_year=2026,
                                     target_underrepresented_pct=0.50)
        # Two candidates: C1 BLACK (underrepresented), C2 WHITE.
        c1 = create_candidate(full_name="C1 Black", eeo_ethnicity="BLACK",
                              eeo_gender="FEMALE", eeo_veteran=False,
                              eeo_disability=False)
        c2 = create_candidate(full_name="C2 White", eeo_ethnicity="WHITE",
                              eeo_gender="MALE", eeo_veteran=False,
                              eeo_disability=False)
        create_application(c1["id"], r2["id"])
        a2 = create_application(c2["id"], r2["id"])
        screen_application(a2["id"])

        goal_after = read_diversity_goal(goal["id"])
        # pool denom = 2 (both applications, neither WITHDRAWN); numer = 1 (C1).
        assert goal_after["pool_underrepresented_pct"] == pytest.approx(0.5, abs=1e-4), \
            f"Expected pool_underrepresented_pct=0.5, got {goal_after['pool_underrepresented_pct']}"

    def test_hire_metric_diverges_from_pool_when_only_non_underrepresented_hired(self, api):
        """PRD §3.1: "The hire metric uses the same underrepresented predicate but
        restricts the cohort to applications whose `status` is `HIRED` and whose
        `updated_at` year (UTC) matches the goal's `period_year`."
        PRD §3.1: "With zero hires, `hire_underrepresented_pct` is 0.0; otherwise
        it is numerator over denominator rounded half-up to four decimal places."

        Design: Difficulty/dual_variant_calc/diversity_pool_vs_hire_diverge_on_same_goal
        """
        set_clock("2026-02-01T00:00:00Z")
        from test_helpers import create_department, create_approved_requisition

        d = create_department(budget_cents=200_000_000)
        _, r = create_approved_requisition(
            department_id=d["id"],
            req_overrides={"target_level": "MID",
                           "base_salary_min_cents": 10_000_000,
                           "base_salary_max_cents": 18_000_000,
                           "openings": 1},
        )
        goal = create_diversity_goal(d["id"], target_level="MID", period_year=2026,
                                     target_underrepresented_pct=0.50)
        c1 = create_candidate(full_name="C1 Black", eeo_ethnicity="BLACK")
        c2 = create_candidate(full_name="C2 White", eeo_ethnicity="WHITE")
        create_application(c1["id"], r["id"])
        a2 = create_application(c2["id"], r["id"])
        screen_application(a2["id"])
        # Drive C2 (WHITE) through to HIRED.
        offer = create_offer(a2["id"], base_salary_cents=12_000_000)
        offer = fully_approve_offer(offer["id"])
        extend_offer(offer["id"])
        accept_offer(offer["id"], candidate_headers=make_headers(c2["id"], "Candidate"))

        goal_after = read_diversity_goal(goal["id"])
        # hires = {C2 (WHITE)} → 1 hire, 0 underrepresented → hire_pct = 0.0.
        assert goal_after["hire_underrepresented_pct"] == pytest.approx(0.0, abs=1e-4), \
            f"Expected hire_underrepresented_pct=0.0, got {goal_after['hire_underrepresented_pct']}"
        # pool still counts C1 + C2 since neither application is WITHDRAWN.
        # C1 = BLACK (underrepresented) → numer=1, denom=2 → pool_pct=0.5.
        assert goal_after["pool_underrepresented_pct"] == pytest.approx(0.5, abs=1e-4), \
            f"Expected pool_underrepresented_pct=0.5, got {goal_after['pool_underrepresented_pct']}"
        # Divergence on the SAME goal row.
        assert goal_after["pool_underrepresented_pct"] != goal_after["hire_underrepresented_pct"]
