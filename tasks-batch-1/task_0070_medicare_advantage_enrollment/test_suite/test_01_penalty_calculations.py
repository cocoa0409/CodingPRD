"""Part D and Part B late-enrollment penalty calculations.

Covers the dual-variant penalty algorithms (Part D dime-rounding vs Part B
full-12-month-period floor) and the per-month / per-period rate boundaries.
"""
from test_helpers import (
    validate_success, set_clock, create_beneficiary,
    setup_active_part_d, create_penalty_assessment_payload, TEST_USERS,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def test_partd_drug_lep_vs_partb_assessment_diverge_same_uncovered_months(api):
    """PRD §3.7: "The raw penalty is one percent of the national base beneficiary
    premium - fixed at 3,470 cents - multiplied by the number of uncovered months.
    That raw amount is then rounded to the nearest dime: divide the raw cents by ten,
    round half up to the nearest whole dime, then multiply back by ten, yielding
    lep_premium_cents as an integer number of cents."
    PRD §3.10: "the penalty is ten percent of the standard Part B premium - fixed at
    17,470 cents - for each full twelve-month period the beneficiary was uncovered"
    PRD §3.10: "Compute the number of full periods by integer-dividing the uncovered
    months by twelve (so thirteen uncovered months yield one full period)."

    Design: Difficulty/dual_variant_calc/partd_lep_drug_enrollment_vs_partb_lep_penalty_assessment
    """
    set_clock("2024-11-01T00:00:00.000Z")
    # Part D drug enrollment LEP: creditable null, anchor=IEP window_end, confirm Jan 2026 -> 13 months.
    ben, _iep, _pdp, pde = setup_active_part_d(confirm_clock="2026-01-15T00:00:00.000Z")
    assert pde["uncovered_months"] == 13
    assert pde["lep_premium_cents"] == 450

    # Part B assessment LEP for the same uncovered_months=13.
    res = api.create_penalty_assessment(
        create_penalty_assessment_payload(ben["id"], "PART_B", 13), COMPLIANCE)
    pa = validate_success(res, 201)
    assert pa["monthly_penalty_cents"] == 1747
    assert pa["monthly_penalty_cents"] != pde["lep_premium_cents"]


def test_partd_lep_from_confirm_vs_from_assessment_variants(api):
    """PRD §3.7: "The raw penalty is one percent of the national base beneficiary
    premium - fixed at 3,470 cents - multiplied by the number of uncovered months.
    That raw amount is then rounded to the nearest dime: divide the raw cents by ten,
    round half up to the nearest whole dime, then multiply back by ten, yielding
    lep_premium_cents as an integer number of cents."
    PRD §3.10: "the penalty uses the same Part D formula as drug confirmation but with
    the caller-supplied uncovered_months taken verbatim rather than computed"

    Design: Difficulty/dual_variant_calc/partd_lep_variant_from_confirm_vs_from_assessment
    """
    set_clock("2024-11-01T00:00:00.000Z")
    ben, _iep, _pdp, pde = setup_active_part_d(confirm_clock="2026-01-15T00:00:00.000Z")
    # from_confirm: derived uncovered_months=13 -> 450c.
    assert pde["lep_premium_cents"] == 450

    # from_assessment: caller supplies uncovered_months=7 verbatim -> 240c.
    res = api.create_penalty_assessment(
        create_penalty_assessment_payload(ben["id"], "PART_D", 7), COMPLIANCE)
    pa = validate_success(res, 201)
    assert pa["monthly_penalty_cents"] == 240


def test_partd_lep_one_uncovered_month_rate_boundary(api):
    """PRD §3.7: "The raw penalty is one percent of the national base beneficiary
    premium - fixed at 3,470 cents - multiplied by the number of uncovered months.
    That raw amount is then rounded to the nearest dime: divide the raw cents by ten,
    round half up to the nearest whole dime, then multiply back by ten, yielding
    lep_premium_cents as an integer number of cents."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_partd_lep_one_uncovered_month_boundary
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="RateB")
    res = api.create_penalty_assessment(
        create_penalty_assessment_payload(ben["id"], "PART_D", 1), COMPLIANCE)
    pa = validate_success(res, 201)
    # 0.01 * 3470 * 1 = 34.70 raw cents; round_half_up(3.47) = 3 dimes -> 30c.
    assert pa["monthly_penalty_cents"] == 30


def test_partb_lep_partial_period_below_twelve_months_is_zero(api):
    """PRD §3.10: "partial twelve-month periods do not count. Compute the number of
    full periods by integer-dividing the uncovered months by twelve (so thirteen
    uncovered months yield one full period)."

    Design: Corner/cross_cutting_complexity_layers/partb_lep_partial_period_below_twelve_months_is_zero
    """
    set_clock("2024-06-01T00:00:00.000Z")
    ben = create_beneficiary(full_name="PartialB")
    res = api.create_penalty_assessment(
        create_penalty_assessment_payload(ben["id"], "PART_B", 11), COMPLIANCE)
    pa = validate_success(res, 201)
    # 11 // 12 = 0 full periods -> 0c.
    assert pa["monthly_penalty_cents"] == 0
