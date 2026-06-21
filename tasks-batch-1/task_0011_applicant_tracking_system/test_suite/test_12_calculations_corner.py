"""Calculations: rounding precision, threshold boundaries, zero-denominator handling."""
import pytest
from test_helpers import (
    api_client, get_success_data, TEST_USERS, set_clock,
    setup_interview_with_feedback, complete_interview,
    setup_offer_in_state, accept_offer,
    fetch_background_check_for_offer, fetch_referral_bonuses_for_offer,
    start_background_check, resolve_background_check,
    create_department, create_diversity_goal, read_diversity_goal,
    make_headers,
)


# =========================================================================
# Instance: interview_recommendation_rounding_to_2dp_half_up
# =========================================================================

def test_interview_recommendation_rounding_to_2dp_half_up(api):
    """PRD §2.6: "Interview aggregate scores are rounded half-up to two
    decimal places."
    PRD §3.5: "Completion recomputes `aggregate_score` as the mean of the
    submitted feedback `score` values, rounded half-up to two decimal
    places, and assigns `recommendation` from that score: ... at least
    3.50 but strictly less than 4.50 yields `HIRE`..."

    Design: Corner/calculations/interview_recommendation_rounding_to_2dp_half_up
    """
    set_clock("2027-06-01T00:00:00Z")
    ctx = setup_interview_with_feedback(
        panel_user_ids=["pp1", "pp2", "pp3"],
        scores=[4, 5, 4],
        scheduled_at="2027-06-02T10:00:00Z",
    )
    intv = complete_interview(ctx["interview"]["id"])
    # mean = 13/3 = 4.3333... → round half-up 2dp = 4.33 → HIRE band.
    assert intv["aggregate_score"] == pytest.approx(4.33, abs=1e-9)
    assert intv["recommendation"] == "HIRE"


# =========================================================================
# Instance: referral_bonus_payable_zero_after_90_day_cutoff
# =========================================================================

def test_referral_bonus_payable_zero_after_90_day_cutoff(api):
    """PRD §3.7: "When the delay exceeds 90 days, the payable is zero."
    PRD §3.7: "The elapsed-day count is the integer floor of the difference
    (in days)."

    Design: Corner/calculations/referral_bonus_payable_zero_after_90_day_cutoff
    """
    set_clock("2027-01-01T00:00:00Z")
    ctx = setup_offer_in_state(
        "EXTENDED",
        req_overrides={"target_level": "MID",
                       "base_salary_min_cents": 10_000_000,
                       "base_salary_max_cents": 15_000_000},
        candidate_referrer_user_id="emp_ref_cut",
        cand_overrides={"full_name": "Cut Cand", "eeo_ethnicity": "WHITE"},
        base_salary_cents=12_000_000,
    )
    cand = ctx["candidate"]
    offer = ctx["offer"]
    accept_offer(offer["id"], candidate_headers=make_headers(cand["id"], "Candidate"))
    # 91 days elapsed → > 90 cutoff.
    set_clock("2027-04-02T00:00:00Z")
    bgc = fetch_background_check_for_offer(offer["id"])
    start_background_check(bgc["id"])
    resolve_background_check(bgc["id"], outcome="PASSED")
    bonuses = fetch_referral_bonuses_for_offer(offer["id"])
    rb = bonuses[0]
    assert rb["payable_amount_cents"] == 0
    assert rb["status"] == "PAYABLE"


# =========================================================================
# Instance: diversity_metric_zero_denominator_returns_zero
# =========================================================================

def test_diversity_metric_zero_denominator_returns_zero(api):
    """PRD §3.1: "When the denominator is zero, `pool_underrepresented_pct`
    is reported as 0.0..."
    PRD §3.1: "With zero hires, `hire_underrepresented_pct` is 0.0..."

    Design: Corner/calculations/diversity_metric_zero_denominator_returns_zero
    """
    dept = create_department(budget_cents=100_000_000)
    goal = create_diversity_goal(dept["id"], target_level="STAFF",
                                 period_year=2027,
                                 target_underrepresented_pct=0.50)
    goal_after = read_diversity_goal(goal["id"])
    assert goal_after["pool_underrepresented_pct"] == pytest.approx(0.0, abs=1e-9)
    assert goal_after["hire_underrepresented_pct"] == pytest.approx(0.0, abs=1e-9)
