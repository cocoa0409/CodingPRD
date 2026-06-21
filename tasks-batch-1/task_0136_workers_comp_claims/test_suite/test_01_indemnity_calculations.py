"""Indemnity and reserve calculations: TTD/TPD/PPD amounts, the forward-reserve
vs chronological-paid divergence, nested rounding order, and medical drawdowns.

All literal expected values are copied from the design indices (pre-computed).
"""
import pytest

from test_helpers import (
    validate_success,
    get_success_data,
    api_client,
    setup_lost_time_claim,
    setup_reported_claim,
    setup_acknowledged_froi,
    setup_wage_statement,
    setup_reserve,
    read_claim,
    read_reserve,
    TEST_USERS,
)
from test_helpers import factories as f

ADJUSTER = TEST_USERS["claims_adjuster_headers"]


def test_ttd_forward_reserve_diverges_from_chronological_paid(api):
    """PRD §3.4: "The forward-looking reserve and the chronological paid ledger are
    deliberately allowed to diverge: the reserve projects the full expected indemnity
    exposure across projected_weeks at the weekly rate and ignores the waiting-period
    reduction that the paid ledger applies, so for the same disability span the two
    figures differ by exactly the waiting-period amount."
    PRD §3.6: "When the span is more than 7 days but fewer than 14, only the
    days beyond the waiting period count, so the compensable days are the disability
    days minus 7."

    Design: Difficulty/dual_variant_calc/indemnity_forward_reserve_vs_chronological_paid
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    reserve_before = read_reserve(ctx["reserve"]["id"])
    assert reserve_before["indemnity_reserve_cents"] == 1200060, (
        "forward reserve projects 12 weeks * weekly 100005 with no waiting-period reduction"
    )

    pay = validate_success(
        api.create_benefit_payment(f.create_benefit_payment_payload(ctx["claim"]["id"], "TTD"), ADJUSTER),
        201,
    )
    assert pay["amount_cents"] == 42858, (
        "chronological paid amount deducts the 7-day waiting period: 3 compensable days * 14286"
    )

    reserve_after = read_reserve(ctx["reserve"]["id"])
    assert reserve_after["indemnity_reserve_cents"] == 1157202, "1200060 - 42858 drawdown"


def test_forward_reserve_ignores_waiting_period_unlike_paid_ledger(api):
    """PRD §3.4: "the reserve projects the full expected indemnity exposure across
    projected_weeks at the weekly rate and ignores the waiting-period reduction that the paid
    ledger applies, so for the same disability span the two figures differ by exactly the
    waiting-period amount."
    PRD §3.6: "When the span is more than 7 days but fewer than 14, only the days
    beyond the waiting period count, so the compensable days are the disability days minus 7."

    Design: Difficulty/dual_variant_calc/indemnity_forward_reserve_vs_chronological_paid
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    reserve = read_reserve(ctx["reserve"]["id"])
    # forward reserve = weekly 100005 * 12 weeks, NO waiting-period reduction
    assert reserve["indemnity_reserve_cents"] == 1200060

    pay = validate_success(
        api.create_benefit_payment(f.create_benefit_payment_payload(ctx["claim"]["id"], "TTD"), ADJUSTER),
        201,
    )
    # paid ledger applies the 7-day waiting period: only 3 of 10 days compensable
    assert pay["amount_cents"] == 42858
    assert pay["amount_cents"] < reserve["indemnity_reserve_cents"], (
        "the chronological paid amount is strictly below the un-reduced forward reserve"
    )


def test_experience_mod_three_input_nonlinear_clamp_credit(api):
    """PRD §3.12: "the numerator is the actual primary losses, plus W times the actual
    excess losses, plus one-minus-W times the expected excess losses, plus the ballast.
    The denominator is the expected primary losses, plus W times the expected excess
    losses, plus one-minus-W times the expected excess losses, plus the ballast. The raw
    modification factor is the numerator divided by the denominator; the stored mod_factor
    is that raw factor rounded half-up to two decimal places and then clamped to lie
    between 0.75 and 2.00."

    Design: Difficulty/combinatorial_formula/experience_mod_three_input_nonlinear_clamp
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    # claim total_incurred = 2700060 -> Ap=1700000, Ae=1000060
    mod = validate_success(
        api.create_experience_mod(
            f.create_experience_mod_payload(
                ctx["employer"]["id"], 2026, weighting_factor=0.30, ballast_cents=1_000_000,
                expected_primary_cents=1_800_000, expected_excess_cents=1_200_000,
            ),
            TEST_USERS["platform_admin_headers"],
        ),
        201,
    )
    # num = 1700000 + 0.30*1000060 + 0.70*1200000 + 1000000 = 3840018
    # den = 1800000 + 0.30*1200000 + 0.70*1200000 + 1000000 = 4000000 -> 0.9600045 -> 0.96
    assert mod["mod_factor"] == 0.96


def test_experience_mod_clamped_to_ceiling(api):
    """PRD §3.12: "the stored mod_factor is that raw factor rounded half-up to two decimal
    places and then clamped to lie between 0.75 and 2.00."

    Design: Difficulty/combinatorial_formula/experience_mod_three_input_nonlinear_clamp
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    # expected_primary_cents=1, expected_excess_cents=0, ballast 0 -> raw mod ~2000018 -> clamp 2.00
    mod = validate_success(
        api.create_experience_mod(
            f.create_experience_mod_payload(
                ctx["employer"]["id"], 2026, weighting_factor=0.30, ballast_cents=0,
                expected_primary_cents=1, expected_excess_cents=0,
            ),
            TEST_USERS["platform_admin_headers"],
        ),
        201,
    )
    assert mod["mod_factor"] == 2.00


def test_ttd_daily_rate_rounds_before_multiply(api):
    """PRD §3.6: "the daily rate is the controlling weekly rate divided by 7, rounded
    half-up." PRD §3.6: "The amount is the daily rate multiplied by the compensable days,
    rounded half-up."

    Design: Difficulty/combinatorial_formula/ttd_daily_rounding_order_then_sum
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    pay = validate_success(
        api.create_benefit_payment(f.create_benefit_payment_payload(ctx["claim"]["id"], "TTD"), ADJUSTER),
        201,
    )
    # round(100005/7)=14286; 14286*3=42858 (NOT round(100005/7*3)=42859)
    assert pay["amount_cents"] == 42858


def test_ttd_amount_for_high_compensable_count(api):
    """PRD §3.6: "the daily rate is the controlling weekly rate divided by 7, rounded
    half-up." PRD §3.6: "When the span reaches 14 days or more, the waiting period is paid
    retroactively and every disability day is compensable. The amount is the daily rate
    multiplied by the compensable days, rounded half-up."

    Design: Difficulty/combinatorial_formula/ttd_daily_rounding_order_then_sum
    """
    ctx = setup_lost_time_claim(disability_days=14, projected_weeks=15, average_weekly_wage_cents=150_000)
    pay = validate_success(
        api.create_benefit_payment(f.create_benefit_payment_payload(ctx["claim"]["id"], "TTD"), ADJUSTER),
        201,
    )
    # 14 compensable days * round(100005/7)=14286 -> 200004
    assert pay["amount_cents"] == 200004


def test_ttd_retroactive_at_14_day_boundary(api):
    """PRD §3.6: "When the span reaches 14 days or more, the waiting period is paid
    retroactively and every disability day is compensable. The amount is the daily rate
    multiplied by the compensable days, rounded half-up."

    Design: Difficulty/boundary_precision_check/ttd_retroactive_waiting_period_at_14_days
    """
    ctx = setup_lost_time_claim(disability_days=14, projected_weeks=15, average_weekly_wage_cents=150_000)
    pay = validate_success(
        api.create_benefit_payment(f.create_benefit_payment_payload(ctx["claim"]["id"], "TTD"), ADJUSTER),
        201,
    )
    assert pay["amount_cents"] == 200004, "all 14 days compensable at the >=14 boundary"


def test_ttd_below_retro_boundary_excludes_waiting_period(api):
    """PRD §3.6: "When the span is more than 7 days but fewer than 14, only the
    days beyond the waiting period count, so the compensable days are the disability days
    minus 7."

    Design: Difficulty/boundary_precision_check/ttd_retroactive_waiting_period_at_14_days
    """
    ctx = setup_lost_time_claim(disability_days=13, projected_weeks=15, average_weekly_wage_cents=150_000)
    pay = validate_success(
        api.create_benefit_payment(f.create_benefit_payment_payload(ctx["claim"]["id"], "TTD"), ADJUSTER),
        201,
    )
    # 13 days -> compensable 6 -> 6 * 14286 = 85716
    assert pay["amount_cents"] == 85716, "below the 14-day boundary only (13-7)=6 days are compensable"


def test_ttd_rate_capped_at_saww_for_high_earner(api):
    """PRD §3.5: "That raw rate is then capped: the cap is the state average weekly wage of
    120,000 cents multiplied by the maximum-compensation percentage of 1.00 (again rounded
    half-up), and the rate is the smaller of the raw rate and the cap."

    Design: Corner/calculations/ttd_rate_capped_at_saww_for_high_earner
    """
    ctx = setup_reported_claim(gross_wages_cents=13_000_000, weeks_worked=52)
    ws, _ = setup_wage_statement(ctx["claim"]["id"], ctx["claim_version"], average_weekly_wage_cents=250_000)
    assert ws["ttd_weekly_rate_cents"] == 120000, "raw 166675 capped at SAWW 120000"


def test_ttd_rate_floored_at_statutory_minimum_for_low_earner(api):
    """PRD §3.5: "Finally the capped value is floored at the statutory minimum of 15,000
    cents — the weekly rate is the larger of the capped figure and that minimum."

    Design: Corner/calculations/ttd_rate_floored_for_low_earner
    """
    ctx = setup_reported_claim(gross_wages_cents=1_000_000, weeks_worked=52)
    ws, _ = setup_wage_statement(ctx["claim"]["id"], ctx["claim_version"], average_weekly_wage_cents=19_231)
    assert ws["ttd_weekly_rate_cents"] == 15000, "raw 12820 floored at MIN_TTD 15000"


def test_tpd_light_duty_wage_offset_amount(api):
    """PRD §3.6: "The weekly wage loss is the claim worker's average weekly wage minus those
    light-duty earnings; if that loss is zero or negative, the amount is 0. Otherwise the
    amount is the wage loss multiplied by the partial replacement fraction of 0.6667 and
    rounded half-up, but capped so it never exceeds the controlling temporary-total weekly
    rate."

    Design: Corner/calculations/tpd_light_duty_wage_offset_amount
    """
    ctx = setup_lost_time_claim(disability_days=10, projected_weeks=12, average_weekly_wage_cents=150_000)
    pay = validate_success(
        api.create_benefit_payment(
            f.create_benefit_payment_payload(ctx["claim"]["id"], "TPD", light_duty_weekly_cents=90_000),
            ADJUSTER,
        ),
        201,
    )
    # round((150000-90000)*0.6667)=round(40002)=40002, below TTD weekly cap 100005
    assert pay["amount_cents"] == 40002
    claim = read_claim(ctx["claim"]["id"])
    assert claim["claim_class"] == "LOST_TIME", "first temporary-disability payment flips claim_class"


def test_ppd_award_from_finalized_rating(api):
    """PRD §3.6: "The award covers a number of weeks equal to the rating's finalized_pct
    multiplied by 3.0 weeks per percentage point, and the amount is that week count
    multiplied by the controlling weekly rate, rounded half-up."

    Design: Corner/calculations/ppd_award_from_finalized_rating
    """
    ctx = setup_lost_time_claim(
        disability_days=10, severity_tier="SEVERE", projected_weeks=60, average_weekly_wage_cents=150_000
    )
    rating = get_success_data(
        api.create_impairment_rating(
            f.create_impairment_rating_payload(ctx["claim"]["id"], 15, "IME"),
            TEST_USERS["medical_reviewer_headers"],
        )
    )
    get_success_data(api.finalize_impairment_rating(rating["id"], TEST_USERS["medical_reviewer_headers"]))
    pay = validate_success(
        api.create_benefit_payment(
            f.create_benefit_payment_payload(ctx["claim"]["id"], "PPD", impairment_rating_id=rating["id"]),
            ADJUSTER,
        ),
        201,
    )
    # 15 * 3 * 100005 = 4500225
    assert pay["amount_cents"] == 4500225


def test_medical_payment_draws_down_medical_reserve(api):
    """PRD §3.7: "A medical payment supplies an amount_cents and draws down the medical
    side: medical_paid_cents rises by that amount and medical_reserve_cents falls by the
    same amount (floored at zero). As with indemnity, the total incurred is recomputed and
    the conserved invariant holds — money moves between the outstanding-medical and
    paid-medical columns without changing the total."

    Design: Corner/calculations/medical_payment_draws_down_medical_reserve
    """
    ctx = setup_reported_claim()
    claim_id = ctx["claim"]["id"]
    setup_acknowledged_froi(claim_id)
    ws, v1 = setup_wage_statement(claim_id, ctx["claim_version"], average_weekly_wage_cents=150_000)
    reserve = setup_reserve(claim_id, severity_tier="MODERATE", projected_weeks=12)

    updated = validate_success(
        api.create_medical_payment(reserve["id"], f.create_medical_payment_payload(500_000), ADJUSTER),
        201,
    )
    assert updated["medical_paid_cents"] == 500000
    assert updated["medical_reserve_cents"] == 1000000
    assert updated["total_incurred_cents"] == 2700060, "total unchanged by the medical drawdown"
