"""Penalty/interest accrual, setup-fee tiers, and RCP computation."""
from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    TEST_USERS,
    make_revenue_officer_headers,
    make_case_reviewer_headers,
    create_agreement_payload,
    create_offer_payload,
    setup_account_with_recomputed_period,
    setup_account_with_period_no_recompute,
    propose_agreement,
    approve_agreement,
    submit_offer,
    begin_evaluation,
    get_account_version,
)

OFFICER = TEST_USERS["revenue_officer_headers"]
REVIEWER = TEST_USERS["case_reviewer_headers"]


def test_recompute_penalty_round_per_month_interest_sum_then_round(api):
    """PRD §3.6: "The penalty is then accumulated month by month: for each of the
    elapsed months, multiply the assessed tax by the selected monthly rate, round
    that single-month figure to whole cents using round-half-up, and add it to the
    running total."
    PRD §3.6: "the accrued interest is the assessed tax multiplied by 0.006
    multiplied by the elapsed-months count, with round-half-up applied a single
    time to that product."

    Design: Difficulty/combinatorial_formula/penalty_round_per_month_vs_interest_sum_then_round
    """
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    p = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert p["penalty_accrued_cents"] == 15000, p
    assert p["interest_accrued_cents"] == 18000, p
    assert p["balance_due_cents"] == 1033000, p


def test_recompute_rolls_up_account_total_balance(api):
    """PRD §3.6: "An account's total_balance_cents is the sum of balance_due_cents
    across only those periods whose period_status is ASSESSED or IN_COLLECTION".

    Design: Corner/endpoints/recompute_returns_account_with_updated_balances
    """
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z", mdi_cents=0)
    a = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert a["total_balance_cents"] == 1033000, a


def test_penalty_drops_to_ddia_rate_after_direct_debit_approval(api):
    """PRD §3.4: "If the payment_method is DIRECT_DEBIT, penalty is re-accrued going
    forward at the DDIA-reduced rate (the ddia_reduced variant of §3.6)".
    PRD §3.6: "if the account has an installment agreement with payment_method of
    DIRECT_DEBIT whose status is APPROVED or REINSTATED, the reduced DDIA rate of
    0.0025 per month applies instead (the ddia_reduced variant) — exactly half the
    standard rate".

    Design: Difficulty/dual_variant_calc/penalty_standard_vs_ddia_on_taxperiod
    """
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    before = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert before["penalty_accrued_cents"] == 15000, before

    agr = propose_agreement(
        acct["id"], agreement_type="LONG_TERM", payment_method="DIRECT_DEBIT",
        monthly_payment_cents=200000, term_months=6)
    approve_agreement(acct["id"], agr["id"])

    after = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert after["penalty_accrued_cents"] == 7500, after
    assert after["balance_due_cents"] == 1025500, after


def test_penalty_standard_rate_before_any_agreement(api):
    """PRD §3.6: "the standard rate is 0.005 per month (the standard variant)".

    Design: Difficulty/dual_variant_calc/penalty_standard_vs_ddia_on_taxperiod
    """
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    p = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert p["penalty_accrued_cents"] == 15000, p


def test_setup_fee_standard_manual_long_term(api):
    """PRD §3.7: "Otherwise — a non-low-income, non-short-term, manual agreement —
    the fee is the standard non-DDIA setup fee of 14,900 cents."

    Design: Difficulty/dual_variant_calc/setup_fee_standard_vs_waived_on_agreement
    """
    acct, period, approved = _approved_long_term(api, low_income_flag=False)
    assert approved["setup_fee_cents"] == 14900, approved


def test_setup_fee_waived_for_low_income(api):
    """PRD §3.7: "If the low_income_flag is true, the fee is fully waived at zero
    (the low-income waiver)."

    Design: Difficulty/dual_variant_calc/setup_fee_standard_vs_waived_on_agreement
    """
    acct, period, approved = _approved_long_term(api, low_income_flag=True)
    assert approved["setup_fee_cents"] == 0, approved


def _approved_long_term(api, low_income_flag):
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    agr = propose_agreement(
        acct["id"], agreement_type="LONG_TERM", payment_method="MANUAL",
        monthly_payment_cents=200000, term_months=6, low_income_flag=low_income_flag)
    approved = approve_agreement(acct["id"], agr["id"])
    return acct, period, approved


def test_rcp_long_tier_multiplier_caps_at_60(api):
    """PRD §3.9: "Otherwise the multiplier is 60 (capped at five years of income).
    The future-income component is monthly_disposable_income_cents multiplied by
    that multiplier, and rcp_cents is net_realizable_equity_cents plus that
    future-income component."

    Design: Difficulty/combinatorial_formula/rcp_tiered_multiplier_selection
    """
    # csed 2034-01-15, clock 2024-04-15 -> remaining ~118 months -> MULT_LONG 60
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z", mdi_cents=300000)
    offer = submit_offer(acct["id"], 18500000, net_realizable_equity_cents=500000)
    offer = begin_evaluation(offer["id"])
    assert offer["rcp_cents"] == 18500000, offer
    assert offer["status"] == "EVALUATING", offer


def test_rcp_mid_tier_multiplier_24(api):
    """PRD §3.9: "If they are at most 60, the multiplier is 24."

    Design: Corner/calculations/rcp_mid_tier_multiplier_boundary
    """
    # assessment 2018-05-24 -> csed 2028-05-24; clock 2024-04-15 -> ~50 months -> MULT_MID 24
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2018-05-24T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z", mdi_cents=300000, tax_year=2017)
    offer = submit_offer(acct["id"], 7700000, net_realizable_equity_cents=500000)
    offer = begin_evaluation(offer["id"])
    assert offer["rcp_cents"] == 7700000, offer


def test_tax_period_create_computes_csed_and_initial_balance(api):
    """PRD §3.1: "its csed_date is computed as the assessment date plus the base
    statute window of 3,653 days — ten years including two leap days — with no
    suspension days yet folded in."
    PRD §3.1: "On creation the period's period_status is ASSESSED; its
    balance_due_cents starts equal to the assessed tax".

    Design: Corner/entities/tax_period_create_computes_csed_and_initial_balance
    """
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=500000, assessment_date="2010-01-15T00:00:00.000Z",
        clock=None, tax_year=2009)
    p = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    assert p["csed_date"][:10] == "2020-01-16", p
    assert p["period_status"] == "ASSESSED", p
    assert p["balance_due_cents"] == 500000, p


def test_rcp_tier_selection_sets_evaluating_status(api):
    """PRD §3.9: "Beginning evaluation computes the Reasonable Collection Potential
    into rcp_cents ... recomputes the account's collection_status to OIC_PENDING, and
    increments the offer's version."

    Design: Difficulty/combinatorial_formula/rcp_tiered_multiplier_selection
    """
    acct, period = setup_account_with_period_no_recompute(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z", mdi_cents=300000)
    offer = submit_offer(acct["id"], 18500000, net_realizable_equity_cents=500000)
    evaluating = begin_evaluation(offer["id"])
    assert evaluating["status"] == "EVALUATING", evaluating
    a = validate_success(api.get_tax_account(acct["id"], OFFICER), 200)
    assert a["collection_status"] == "OIC_PENDING", a


def test_penalty_and_interest_diverge_in_rounding_order(api):
    """PRD §3.6: "The accrued penalty is the sum of those per-month rounded amounts —
    that is, round-per-month-then-sum."
    PRD §3.6: "Note the deliberate contrast with penalty: interest is sum-then-round
    (one rounding at the end), whereas penalty is round-per-month-then-sum."

    Design: Difficulty/combinatorial_formula/penalty_round_per_month_vs_interest_sum_then_round
    """
    acct, period = setup_account_with_recomputed_period(
        assessed_tax_cents=1000000, assessment_date="2024-01-15T00:00:00.000Z",
        clock="2024-04-15T00:00:00.000Z")
    p = validate_success(api.get_tax_period(period["id"], OFFICER), 200)
    # 3 months: penalty = 3 * round(1000000*0.005) = 15000; interest = round(1000000*0.006*3) = 18000
    assert p["penalty_accrued_cents"] == 15000, p
    assert p["interest_accrued_cents"] == 18000, p
