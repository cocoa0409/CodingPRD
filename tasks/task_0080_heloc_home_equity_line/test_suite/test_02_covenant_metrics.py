"""Covenant breach metric evaluations: MAX_CLTV on the property, MIN_DSCR's nested
three-input formula, and the strict-> CLTV boundary (Queue A: dual_variant_calc,
combinatorial_formula, boundary_precision_check)."""
from test_helpers import (
    validate_success,
    setup_active_line,
    book_draw,
    TEST_USERS,
)

SERVICER = TEST_USERS["loan_servicer_headers"]


def test_cltv_covenant_breaches_on_property_metric(api):
    """PRD §3.8: "the combined loan-to-value in basis points is the sum of the
    property's senior_lien_balance_cents and the line's current_balance_cents,
    multiplied by 10000, divided by the property's appraised_value_cents, rounded half
    up; the covenant is breached when this figure is strictly greater than the
    threshold_value."

    Balance 90000000, appraised 100000000, senior 0 -> cltv 9000 > 8500 -> BREACHED.

    Design: Difficulty/dual_variant_calc/covenant_cltv_vs_dscr_breach_evaluations
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=12000,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000},
        borrower_overrides={"annual_income_cents": 12000000, "monthly_debt_obligation_cents": 200000},
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 90000000)
    cov = ctx["covenants"]["MAX_CLTV"]
    result = validate_success(api.evaluate_covenant(hl_id, cov["id"], SERVICER))
    assert result["status"] == "BREACHED", f"cltv 9000 > 8500 must breach, got {result['status']}"


def test_dscr_covenant_breaches_on_borrower_metric(api):
    """PRD §3.8: "the debt-service-coverage ratio in basis points is the borrower's
    annual_income_cents multiplied by 10000 and divided by that annual debt service
    (which is positive), rounded half up; the covenant is breached when this ratio is
    strictly less than the threshold_value."

    income 12000000, debt 200000/mo, balance 90000000, APR 1000 -> dscr 10526 < 12000.

    Design: Difficulty/dual_variant_calc/covenant_cltv_vs_dscr_breach_evaluations
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=12000,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000},
        borrower_overrides={"annual_income_cents": 12000000, "monthly_debt_obligation_cents": 200000},
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 90000000)
    cov = ctx["covenants"]["MIN_DSCR"]
    result = validate_success(api.evaluate_covenant(hl_id, cov["id"], SERVICER))
    assert result["status"] == "BREACHED", f"dscr 10526 < 12000 must breach, got {result['status']}"


def test_dscr_nested_three_input_formula(api):
    """PRD §3.8: "the annual debt service is the borrower's monthly_debt_obligation_cents
    multiplied by 12, plus the line's annual interest charge (the current_balance_cents
    multiplied by the line's current_apr_bps divided by 10000, rounded half up); the
    debt-service-coverage ratio in basis points is the borrower's annual_income_cents
    multiplied by 10000 and divided by that annual debt service (which is positive),
    rounded half up; the covenant is breached when this ratio is strictly less than the
    threshold_value."

    income 12000000, debt 200000/mo, balance 90000000, APR 1000 -> dscr 10526 < 12000.

    Design: Difficulty/combinatorial_formula/dscr_nested_formula_three_inputs
    """
    ctx = setup_active_line(
        cltv_threshold=9900,
        dscr_threshold=12000,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000},
        borrower_overrides={"annual_income_cents": 12000000, "monthly_debt_obligation_cents": 200000},
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 90000000)
    cov = ctx["covenants"]["MIN_DSCR"]
    result = validate_success(api.evaluate_covenant(hl_id, cov["id"], SERVICER))
    assert result["status"] == "BREACHED", f"dscr 10526 < 12000 must breach, got {result['status']}"


def test_dscr_evaluation_returns_covenant_resource(api):
    """PRD §3.8: "A LoanServicer evaluates a covenant to test whether its metric crosses
    the threshold." The evaluate response is the Covenant whose metric was tested.

    Design: Difficulty/combinatorial_formula/dscr_nested_formula_three_inputs
    """
    ctx = setup_active_line(
        cltv_threshold=9900,
        dscr_threshold=12000,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 95000000},
        borrower_overrides={"annual_income_cents": 12000000, "monthly_debt_obligation_cents": 200000},
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 90000000)
    cov = ctx["covenants"]["MIN_DSCR"]
    result = validate_success(api.evaluate_covenant(hl_id, cov["id"], SERVICER))
    assert result["id"] == cov["id"]
    assert result["covenant_type"] == "MIN_DSCR"


def test_cltv_exactly_at_threshold_does_not_breach(api):
    """PRD §3.8: "the covenant is breached when this figure is strictly greater than the
    threshold_value."
    PRD §3.8: "on breach, if the line is in DRAW it is transitioned from DRAW to FROZEN
    (a covenant breach freezes the line) ..."

    Balance 85000000, appraised 100000000 -> cltv exactly 8500 == threshold 8500, not
    strictly greater, so no breach occurs and the line is NOT frozen — it remains in DRAW
    and a subsequent draw is still permitted. (Asserting the line state, which the PRD
    uniquely determines, rather than the evaluate call's response shape, which it does
    not pin for a non-crossing metric.)

    Design: Difficulty/boundary_precision_check/cltv_strictly_greater_boundary
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=100,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 90000000},
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 85000000)
    cov = ctx["covenants"]["MAX_CLTV"]
    api.evaluate_covenant(hl_id, cov["id"], SERVICER)
    heloc = validate_success(api.get_heloc(hl_id, SERVICER))
    assert heloc["status"] == "DRAW", (
        f"cltv 8500 == threshold 8500 must NOT breach/freeze, line status is {heloc['status']}"
    )


def test_cltv_one_bps_over_threshold_breaches(api):
    """PRD §3.8: "the covenant is breached when this figure is strictly greater than the
    threshold_value."

    Balance 85000001, appraised 100000000, senior 0 -> cltv round_half_up(850000010000/
    100000000) = 8500 (still not over). Use balance 85010000 -> cltv 8501 > 8500 breach,
    the X+1 side of the strict-> boundary.

    Design: Difficulty/boundary_precision_check/cltv_strictly_greater_boundary
    """
    ctx = setup_active_line(
        cltv_threshold=8500,
        dscr_threshold=100,
        delinquency_threshold=60,
        heloc_overrides={"credit_limit_cents": 90000000},
    )
    hl_id = ctx["heloc"]["id"]
    book_draw(hl_id, 85010000)  # cltv = 8501 > 8500
    cov = ctx["covenants"]["MAX_CLTV"]
    result = validate_success(api.evaluate_covenant(hl_id, cov["id"], SERVICER))
    assert result["status"] == "BREACHED", (
        f"cltv 8501 > 8500 must breach, got {result['status']}"
    )
