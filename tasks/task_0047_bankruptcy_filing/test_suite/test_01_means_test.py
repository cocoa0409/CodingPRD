"""Means test computation: annualization, disposable income, the two screens,
and the at-median / above-median boundary.

PRD §3.2 governs every assertion in this file.
"""
import pytest

from test_helpers import (
    api_client, validate_success, assert_means_test, assert_case,
    create_means_test_payload,
    register_debtor, open_case, submit_means_test,
    make_debtor_headers,
)


def test_means_test_at_median_passes_outright(api):
    """PRD §3.2: "if the annualized income is less than or equal to the median
    annual income, the result is PRESUMPTION_OK and the debtor passes outright.
    Income exactly equal to the median passes on this screen".

    Design: Difficulty/dual_variant_calc/means_test_at_median_vs_above_median_variant
    """
    debtor = register_debtor(full_name="At Median Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    headers = make_debtor_headers(debtor["id"])

    res = api.create_means_test(create_means_test_payload(
        case["id"], cmi_monthly_cents=500000, monthly_expenses_cents=300000,
        median_annual_income_cents=6000000), headers)
    mt = validate_success(res, 201)
    assert_means_test(mt)
    assert mt["annualized_cmi_cents"] == 6000000
    assert mt["disposable_monthly_cents"] == 200000
    assert mt["result"] == "PRESUMPTION_OK"

    case_after = validate_success(api.get_case(case["id"], headers), 200)
    assert_case(case_after)
    assert case_after["means_test_result"] == "PRESUMPTION_OK"


def test_means_test_one_cent_above_median_with_high_disposable_is_abuse(api):
    """PRD §3.2: "income even one cent above it falls through to the second
    screen." And: "If that sixty-month projection is at least the abuse floor,
    the result is PRESUMPTION_ABUSE". This is the above-median variant that
    contrasts with the at-median PRESUMPTION_OK on the same boundary.

    Design: Difficulty/dual_variant_calc/means_test_at_median_vs_above_median_variant
    """
    debtor = register_debtor(full_name="Above Median Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    headers = make_debtor_headers(debtor["id"])

    # cmi 600000 -> annualized 7,200,000 > median 6,000,000; disposable 300,000;
    # 300,000 * 60 = 18,000,000 >= 1,500,000 -> PRESUMPTION_ABUSE.
    res = api.create_means_test(create_means_test_payload(
        case["id"], cmi_monthly_cents=600000, monthly_expenses_cents=300000,
        median_annual_income_cents=6000000), headers)
    mt = validate_success(res, 201)
    assert mt["annualized_cmi_cents"] == 7200000
    assert mt["result"] == "PRESUMPTION_ABUSE"


def test_means_test_above_median_high_disposable_is_abuse(api):
    """PRD §3.2: "If that sixty-month projection is at least the abuse floor, the
    result is PRESUMPTION_ABUSE; otherwise the result is PRESUMPTION_OK."

    Design: Difficulty/combinatorial_formula/means_test_three_input_nested_branch_mode_a
    """
    debtor = register_debtor(full_name="Abuse Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    headers = make_debtor_headers(debtor["id"])

    res = api.create_means_test(create_means_test_payload(
        case["id"], cmi_monthly_cents=600000, monthly_expenses_cents=300000,
        median_annual_income_cents=6000000), headers)
    mt = validate_success(res, 201)
    assert_means_test(mt)
    # annualized 7,200,000 > median; disposable 300,000 * 60 = 18,000,000 >= 1,500,000.
    assert mt["annualized_cmi_cents"] == 7200000
    assert mt["disposable_monthly_cents"] == 300000
    assert mt["result"] == "PRESUMPTION_ABUSE"


def test_means_test_three_input_else_branch_low_disposable_is_ok(api):
    """PRD §3.2: "If that sixty-month projection is at least the abuse floor, the
    result is PRESUMPTION_ABUSE; otherwise the result is PRESUMPTION_OK." This
    exercises the nested conditional's else branch: above median but the 60-month
    disposable projection falls below the abuse floor.

    Design: Difficulty/combinatorial_formula/means_test_three_input_nested_branch_mode_a
    """
    debtor = register_debtor(full_name="Else Branch Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    headers = make_debtor_headers(debtor["id"])

    # annualized 7,200,000 > median; disposable 20,000; 20,000 * 60 = 1,200,000
    # < 1,500,000 floor -> PRESUMPTION_OK on the else branch.
    res = api.create_means_test(create_means_test_payload(
        case["id"], cmi_monthly_cents=600000, monthly_expenses_cents=580000,
        median_annual_income_cents=6000000), headers)
    mt = validate_success(res, 201)
    assert mt["annualized_cmi_cents"] == 7200000
    assert mt["disposable_monthly_cents"] == 20000
    assert mt["result"] == "PRESUMPTION_OK"


def test_means_test_one_cent_above_median_crosses_to_disposable_screen(api):
    """PRD §3.2: "income even one cent above it falls through to the second
    screen." And: "If that sixty-month projection is at least the abuse floor,
    the result is PRESUMPTION_ABUSE; otherwise the result is PRESUMPTION_OK."

    Design: Difficulty/boundary_precision_check/means_test_one_cent_above_median_crosses_to_disposable_screen
    """
    debtor = register_debtor(full_name="Bound Above Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    headers = make_debtor_headers(debtor["id"])

    # cmi 500001 -> annualized 6,000,012 (one cent-times-12 above median);
    # disposable 20,001 * 60 = 1,200,060 < 1,500,000 floor -> still PRESUMPTION_OK.
    res = api.create_means_test(create_means_test_payload(
        case["id"], cmi_monthly_cents=500001, monthly_expenses_cents=480000,
        median_annual_income_cents=6000000), headers)
    mt = validate_success(res, 201)
    assert mt["annualized_cmi_cents"] == 6000012
    assert mt["disposable_monthly_cents"] == 20001
    assert mt["result"] == "PRESUMPTION_OK"


def test_means_test_exactly_at_median_is_the_passing_boundary(api):
    """PRD §3.2: "Income exactly equal to the median passes on this screen; income
    even one cent above it falls through to the second screen." The at-median
    value is the X side of the <= boundary that the one-cent-above test crosses.

    Design: Difficulty/boundary_precision_check/means_test_one_cent_above_median_crosses_to_disposable_screen
    """
    debtor = register_debtor(full_name="Exactly At Median Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    headers = make_debtor_headers(debtor["id"])

    # cmi 500000 -> annualized exactly 6,000,000 == median; high disposable is
    # irrelevant because the income screen passes outright at the boundary.
    res = api.create_means_test(create_means_test_payload(
        case["id"], cmi_monthly_cents=500000, monthly_expenses_cents=0,
        median_annual_income_cents=6000000), headers)
    mt = validate_success(res, 201)
    assert mt["annualized_cmi_cents"] == 6000000
    assert mt["result"] == "PRESUMPTION_OK"


def test_means_test_below_median_passes_regardless_of_disposable(api):
    """PRD §3.2: "if the annualized income is less than or equal to the median
    annual income, the result is PRESUMPTION_OK and the debtor passes outright."

    Design: Corner/calculations/means_test_below_median_passes_regardless_of_disposable
    """
    debtor = register_debtor(full_name="Below Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    headers = make_debtor_headers(debtor["id"])

    # annualized 4,800,000 < 6,000,000 median; disposable is high but the income
    # screen passes outright, so the disposable screen is never reached.
    res = api.create_means_test(create_means_test_payload(
        case["id"], cmi_monthly_cents=400000, monthly_expenses_cents=0,
        median_annual_income_cents=6000000), headers)
    mt = validate_success(res, 201)
    assert mt["annualized_cmi_cents"] == 4800000
    assert mt["disposable_monthly_cents"] == 400000
    assert mt["result"] == "PRESUMPTION_OK"


def test_means_test_disposable_floored_at_zero(api):
    """PRD §3.2: "monthly disposable income ... as the current monthly income
    minus the allowed monthly expenses, but never below zero — if expenses meet
    or exceed income, disposable income is zero."

    Design: Corner/calculations/means_test_disposable_floored_at_zero_when_expenses_exceed_income
    """
    debtor = register_debtor(full_name="Floor Debtor")
    case = open_case(debtor, filed_chapter="CHAPTER_13")
    headers = make_debtor_headers(debtor["id"])

    res = api.create_means_test(create_means_test_payload(
        case["id"], cmi_monthly_cents=300000, monthly_expenses_cents=350000,
        median_annual_income_cents=6000000), headers)
    mt = validate_success(res, 201)
    assert mt["disposable_monthly_cents"] == 0
    assert mt["result"] == "PRESUMPTION_OK"
