"""Borrower scoring, risk-grade tiering, APR pricing, and the amortization schedule.

Covers the combinatorial scoring/amortization formulas and the credit-score grade
boundary, plus the corner-design scoring and amortization checks.
"""
import pytest

from test_helpers import (
    validate_success,
    create_borrower, create_application, create_scored_application,
    create_funding_loan,
    UW_SCORER,
)


# =====================================================================
# Rule 2 — combinatorial formula: scoring
# =====================================================================

def test_score_borrower_a_grade_92(api):
    """PRD §3.2: "The four subscores are combined by weight: the DSCR subscore is
    weighted at 0.40, the stability subscore at 0.30, the NSF subscore at 0.20, and
    the account-age subscore at 0.10. Their weighted sum is the `credit_score`,
    rounded to two decimal places using round-half-up."
    PRD §3.2: "the grade is `A` when the score is at least 85"
    PRD §3.2: "grade `A` is priced at `0.0599`"

    Design: Difficulty/combinatorial_formula/score_borrower_nonlinear_min_max_tier_interaction
    """
    borrower, app = create_application()  # A-grade profile by default
    resp = api.score_application(app["id"], UW_SCORER)
    data = validate_success(resp, 200)
    assert data["credit_score"] == 92.0, f"expected 92.0, got {data['credit_score']}"
    assert data["risk_grade"] == "A"
    assert data["offered_apr"] == 0.0599


def test_score_borrower_subscore_floors_and_caps_drive_grade(api):
    """PRD §3.2: "The **NSF subscore** starts at 100.0 and subtracts 15.0 for each
    non-sufficient-funds event, with the result held at a floor of 0.0 so it never
    goes negative."
    PRD §3.2: "and `F` when the score is below 40."

    Design: Difficulty/combinatorial_formula/score_borrower_nonlinear_min_max_tier_interaction
    """
    # rev 300k -> stability 20; debt 2,000,000 -> dscr 0.15 -> dscr_sub 7.5;
    # nsf 6 -> 100-90=10; age 6 -> 10. weighted: 7.5*.4+20*.3+10*.2+10*.1=12.0 -> F.
    borrower, app = create_application(
        plaid_avg_monthly_revenue_cents=300_000,
        plaid_monthly_debt_payment_cents=2_000_000,
        plaid_nsf_count_90d=6,
        plaid_account_age_months=6,
    )
    resp = api.score_application(app["id"], UW_SCORER)
    data = validate_success(resp, 200)
    assert data["credit_score"] == 12.0, f"expected 12.0, got {data['credit_score']}"
    assert data["risk_grade"] == "F"
    assert data["offered_apr"] is None, "grade F must have null offered_apr"


# =====================================================================
# Rule 2 — combinatorial formula: amortization (round-then-subtract)
# =====================================================================

def test_amortization_round_interest_then_subtract_principal(api):
    """PRD §3.5: "For each period, the interest due is the running balance
    multiplied by the monthly rate, rounded to whole cents with round-half-up —
    this rounding happens **before** the principal portion is derived, never after."
    PRD §3.5: "For every period except the last, the principal due is
    `level_payment_cents` minus that period's interest due"

    Design: Difficulty/combinatorial_formula/amortization_round_interest_then_subtract_principal_order
    """
    borrower, app, loan = create_funding_loan()  # principal 1,200,000 apr 0.0599 term 12
    resp = api.get_schedule(loan["id"], UW_SCORER)
    data = validate_success(resp, 200)
    assert data["level_payment_cents"] == 103274, \
        f"expected level_payment 103274, got {data['level_payment_cents']}"
    periods = data["periods"]
    assert periods[0]["interest_due_cents"] == 5990, \
        f"period 1 interest expected 5990, got {periods[0]['interest_due_cents']}"
    assert periods[0]["principal_due_cents"] == 97284, \
        f"period 1 principal expected 97284, got {periods[0]['principal_due_cents']}"


def test_amortization_final_period_absorbs_drift_sum_equals_principal(api):
    """PRD §3.5: "For the final period, the principal due is set to whatever balance
    remains so that rounding drift over the life of the loan is absorbed there"
    PRD §3.5: "The schedule is constructed so that the sum of all periods' principal
    due equals `principal_cents` exactly."

    Design: Difficulty/combinatorial_formula/amortization_round_interest_then_subtract_principal_order
    """
    borrower, app, loan = create_funding_loan()
    resp = api.get_schedule(loan["id"], UW_SCORER)
    data = validate_success(resp, 200)
    periods = data["periods"]
    total_principal = sum(p["principal_due_cents"] for p in periods)
    assert total_principal == 1_200_000, \
        f"sum of principal_due must equal principal 1,200,000, got {total_principal}"


# =====================================================================
# Rule 6 — boundary precision: grade threshold exactly 70 is grade B (inclusive)
# =====================================================================

def test_credit_score_exactly_70_is_grade_b_inclusive(api):
    """PRD §3.2: "otherwise `B` when the score is at least 70"
    PRD §3.2: "grade `B` at `0.0899`"

    Design: Difficulty/boundary_precision_check/grade_threshold_exact_70_is_grade_b_inclusive
    """
    # rev 2,000,000 -> stability 80; debt 2,000,000 -> dscr 1.0 -> dscr_sub 50;
    # nsf 0 -> 100; age 36 -> 60. weighted: 50*.4+80*.3+100*.2+60*.1=70.0 -> B.
    borrower, app = create_application(
        plaid_avg_monthly_revenue_cents=2_000_000,
        plaid_monthly_debt_payment_cents=2_000_000,
        plaid_nsf_count_90d=0,
        plaid_account_age_months=36,
    )
    resp = api.score_application(app["id"], UW_SCORER)
    data = validate_success(resp, 200)
    assert data["credit_score"] == 70.0, f"expected exactly 70.0, got {data['credit_score']}"
    assert data["risk_grade"] == "B", "score of exactly 70 must be grade B (inclusive lower bound)"
    assert data["offered_apr"] == 0.0899


def test_credit_score_just_below_70_is_grade_c(api):
    """PRD §3.2: "otherwise `B` when the score is at least 70; otherwise `C` when the
    score is at least 55"
    PRD §3.2: "grade `C` at `0.1299`"

    Design: Difficulty/boundary_precision_check/grade_threshold_exact_70_is_grade_b_inclusive
    """
    # rev 2,000,000 -> stability 80; debt 2,000,000 -> dscr 1.0 -> dscr_sub 50;
    # nsf 0 -> 100; age 35 -> 35/60*100=58.333. weighted = 69.83 -> just below 70 -> C.
    borrower, app = create_application(
        plaid_avg_monthly_revenue_cents=2_000_000,
        plaid_monthly_debt_payment_cents=2_000_000,
        plaid_nsf_count_90d=0,
        plaid_account_age_months=35,
    )
    resp = api.score_application(app["id"], UW_SCORER)
    data = validate_success(resp, 200)
    assert data["credit_score"] == 69.83, f"expected 69.83, got {data['credit_score']}"
    assert data["risk_grade"] == "C", "score of 69.83 (just under 70) must be grade C"
    assert data["offered_apr"] == 0.1299


def test_grade_c_borrower_apr_1299(api):
    """PRD §3.2: "otherwise `C` when the score is at least 55"
    PRD §3.2: "grade `C` at `0.1299`"

    Design: Corner/calculations/grade_c_borrower_apr_1299
    """
    # rev 1,500,000 -> stability 60; debt 1,000,000 -> dscr 1.5 -> dscr_sub 75;
    # nsf 2 -> 100-30=70; age 24 -> 40. weighted: 75*.4+60*.3+70*.2+40*.1=66.0 -> C.
    borrower, app = create_application(
        plaid_avg_monthly_revenue_cents=1_500_000,
        plaid_monthly_debt_payment_cents=1_000_000,
        plaid_nsf_count_90d=2,
        plaid_account_age_months=24,
    )
    resp = api.score_application(app["id"], UW_SCORER)
    data = validate_success(resp, 200)
    assert data["credit_score"] == 66.0, f"expected 66.0, got {data['credit_score']}"
    assert data["risk_grade"] == "C"
    assert data["offered_apr"] == 0.1299


# =====================================================================
# Corner — entities: computed fields null before scoring
# =====================================================================

def test_application_computed_fields_null_before_scoring(api):
    """PRD §3.1: "The `credit_score` is the weighted score in the range 0 to 100
    and is `null` until the application is scored."
    PRD §3.1: "A freshly submitted application begins in `SUBMITTED` status"

    Design: Corner/entities/loan_application_computed_fields_null_before_scoring
    """
    borrower, app = create_application()
    assert app["status"] == "SUBMITTED"
    assert app["credit_score"] is None
    assert app["risk_grade"] is None
    assert app["offered_apr"] is None


def test_application_system_fields_server_controlled(api):
    """PRD §3.1: "A freshly submitted application begins in `SUBMITTED` status"
    PRD §3.1: "A fourth field, `scored_by_user_id`, records the `X-User-ID` of the
    underwriter who performed the scoring and is `null` until that point."

    Design: Corner/entities/borrower_id_system_field_ignored_on_application_create
    """
    borrower, app = create_application()
    assert app["status"] == "SUBMITTED", "status is system-controlled"
    assert app["scored_by_user_id"] is None, "scored_by_user_id is null until scoring"
