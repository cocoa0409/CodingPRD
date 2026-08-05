"""Incentive summary: provisional vs final payout and per-award bonus rounding."""
from test_helpers import (
    validate_success, TEST_USERS,
    setup_completed_enrollment, setup_seven_day_achieved,
)

CM = TEST_USERS["case_manager_headers"]


def test_completed_enrollment_final_payout_adds_bonus(api):
    """PRD §3.8: "once the enrollment is `COMPLETED` — the thirty-day
    continuous-abstinence endpoint reached — the payout is final and equals
    `provisional_earned_cents` plus `completion_bonus_cents`."
    PRD §3.8: "The `provisional_earned_cents` is the sum of `amount_cents` over the
    enrollment's awards in `EARNED` or `PAID` status, with `FORFEITED` awards excluded."

    Design: Difficulty/dual_variant_calc/incentive_provisional_vs_final_payout
    """
    ctx = setup_completed_enrollment(api, budget=100000, cpd=10)
    summary = validate_success(api.get_incentive_summary(ctx["enrollment_id"], CM))
    assert summary["provisional_earned_cents"] == 10000
    assert summary["completion_bonus_cents"] == 751
    assert summary["final_payout_cents"] == 10751


def test_provisional_payout_before_completion_has_no_bonus(api):
    """PRD §3.8: "while the enrollment is not yet `COMPLETED` the payout is
    provisional and equals `provisional_earned_cents` with no completion bonus".

    Design: Difficulty/dual_variant_calc/incentive_provisional_vs_final_payout
    """
    # Seven-day achieved but not yet 30-day completed: awards 1000+1500+2500 = 5000 EARNED.
    ctx = setup_seven_day_achieved(api, budget=100000, cpd=10)
    summary = validate_success(api.get_incentive_summary(ctx["enrollment_id"], CM))
    assert summary["provisional_earned_cents"] == 5000
    assert summary["completion_bonus_cents"] == 0
    assert summary["final_payout_cents"] == 5000


def test_completion_bonus_rounds_per_award_before_summing(api):
    """PRD §2.7: "The completion bonus multiplies each award amount by
    `COMPLETION_BONUS_RATE` (0.075) and rounds each product to the nearest cent,
    half up, **before** summing — the rounding is applied per award, not to the
    aggregate."

    Design: Difficulty/combinatorial_formula/completion_bonus_per_award_rounding_order
    """
    # Awards 1000/1500/2500/5000: per-award round_half_up(0.075*amt) = 75+113+188+375 = 751.
    # A sum-then-round implementation would instead yield 750.
    ctx = setup_completed_enrollment(api, budget=100000, cpd=10)
    summary = validate_success(api.get_incentive_summary(ctx["enrollment_id"], CM))
    assert summary["completion_bonus_cents"] == 751
    assert summary["completion_bonus_cents"] != 750


def test_completion_bonus_folds_into_final_payout(api):
    """PRD §3.8: "once the enrollment is `COMPLETED` — the thirty-day
    continuous-abstinence endpoint reached — the payout is final and equals
    `provisional_earned_cents` plus `completion_bonus_cents`."

    Design: Difficulty/combinatorial_formula/completion_bonus_per_award_rounding_order
    """
    ctx = setup_completed_enrollment(api, budget=100000, cpd=10)
    summary = validate_success(api.get_incentive_summary(ctx["enrollment_id"], CM))
    assert summary["final_payout_cents"] == summary["provisional_earned_cents"] + summary["completion_bonus_cents"]
    assert summary["final_payout_cents"] == 10751
