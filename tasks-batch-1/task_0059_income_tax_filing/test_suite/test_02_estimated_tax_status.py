"""Estimated-tax status projection: safe-harbor selection, coverage, penalty, on_time.

Translates difficulty queue A dual_variant_calc (safe harbor instance) and corner
queue B endpoint instances for the estimated-tax-status read.
"""
from test_helpers import (
    validate_success,
    make_taxpayer_headers,
    create_taxpayer_payload, create_tax_return_payload,
    create_income_document_payload, create_estimated_tax_payment_payload,
)


def _new_taxpayer(api, **tp_overrides):
    resp = api.create_taxpayer(create_taxpayer_payload(**tp_overrides),
                               make_taxpayer_headers("bootstrap"))
    return validate_success(resp, 201)


def _open_return(api, tp_id, **ret_overrides):
    resp = api.create_tax_return(create_tax_return_payload(tp_id, **ret_overrides),
                                 make_taxpayer_headers(tp_id))
    return validate_success(resp, 201)


# =====================================================================
# dual_variant_calc / estimated_tax_safe_harbor_current_vs_prior_year
# =====================================================================

def test_prior_year_safe_harbor_governs(api):
    """PRD §3.7: "The prior-year safe harbor is the taxpayer's
    `prior_year_total_tax_cents` multiplied by a rate, rounded down: that rate is one
    hundred percent normally, but one hundred ten percent when the taxpayer's
    `prior_year_agi_cents` is strictly greater than fifteen million cents ($150,000.00
    prior-year AGI)."
    PRD §3.7: "The required annual amount is the smaller of the current-year and
    prior-year figures; when the current-year figure is the lesser (or equal), the
    current-year safe harbor governs, and when the prior-year figure is strictly
    smaller, the prior-year safe harbor governs — identical current-year figures can
    yield a different required amount, and therefore a different penalty, depending on
    which harbor binds."
    PRD §3.7: "The penalty is eight percent of that shortfall, rounded down to the
    nearest cent."

    Design: Difficulty/dual_variant_calc/estimated_tax_safe_harbor_current_vs_prior_year
    """
    tp = _new_taxpayer(api, filing_status="SINGLE",
                       prior_year_agi_cents=5_000_000,
                       prior_year_total_tax_cents=1_000_000)
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=10_000_000,
                                                  federal_withholding_cents=0), h), 201)
    validate_success(api.create_estimated_tax_payment(
        create_estimated_tax_payment_payload(
            ret["id"], quarter="Q1", amount_cents=500_000,
            paid_on="2025-04-10T00:00:00Z",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-04-01T00:00:00Z"), h), 201)
    validate_success(api.compute_tax_return(ret["id"], h), 200)
    status = validate_success(api.get_estimated_tax_status(ret["id"], h), 200)
    # prior-year 100% of 1,000,000 = 1,000,000 < current 90% of 1,375,300 = 1,237,770
    assert status["required_annual_cents"] == 1_000_000
    assert status["shortfall_cents"] == 500_000
    assert status["penalty_cents"] == 40_000


def test_current_year_safe_harbor_governs(api):
    """PRD §3.7: "The current-year safe harbor is ninety percent of the return's
    `tax_after_credits_cents`, rounded down to the nearest cent."
    PRD §3.7: "The required annual amount is the smaller of the current-year and
    prior-year figures; when the current-year figure is the lesser (or equal), the
    current-year safe harbor governs, and when the prior-year figure is strictly
    smaller, the prior-year safe harbor governs — identical current-year figures can
    yield a different required amount, and therefore a different penalty, depending on
    which harbor binds."
    PRD §3.7: "Coverage is the sum of `amount_cents` over only the estimated payments
    whose `on_time` flag is true, plus the sum of `federal_withholding_cents` over all
    income documents (withholding is always treated as timely)."

    Design: Difficulty/dual_variant_calc/estimated_tax_safe_harbor_current_vs_prior_year
    """
    tp = _new_taxpayer(api, filing_status="SINGLE",
                       prior_year_agi_cents=5_000_000,
                       prior_year_total_tax_cents=5_000_000)
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=10_000_000,
                                                  federal_withholding_cents=0), h), 201)
    validate_success(api.create_estimated_tax_payment(
        create_estimated_tax_payment_payload(
            ret["id"], quarter="Q1", amount_cents=500_000,
            paid_on="2025-04-10T00:00:00Z",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-04-01T00:00:00Z"), h), 201)
    validate_success(api.compute_tax_return(ret["id"], h), 200)
    status = validate_success(api.get_estimated_tax_status(ret["id"], h), 200)
    # current 90% of 1,375,300 = 1,237,770 < prior 5,000,000
    assert status["required_annual_cents"] == 1_237_770
    assert status["penalty_cents"] == 59_021


# =====================================================================
# Corner B / endpoints
# =====================================================================

def test_estimated_tax_status_current_year_figures(api):
    """PRD §3.7: "The current-year safe harbor is ninety percent of the return's
    `tax_after_credits_cents`, rounded down to the nearest cent."
    PRD §3.7: "The shortfall is the required annual amount minus the coverage, floored
    at 0. The penalty is eight percent of that shortfall, rounded down to the nearest
    cent."

    Design: Corner/endpoints/estimated_tax_status_computed_read
    """
    tp = _new_taxpayer(api, filing_status="SINGLE",
                       prior_year_agi_cents=5_000_000,
                       prior_year_total_tax_cents=5_000_000)
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE", deduction_method="STANDARD")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=10_000_000,
                                                  federal_withholding_cents=0), h), 201)
    validate_success(api.create_estimated_tax_payment(
        create_estimated_tax_payment_payload(
            ret["id"], quarter="Q1", amount_cents=500_000,
            paid_on="2025-04-10T00:00:00Z",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-04-01T00:00:00Z"), h), 201)
    validate_success(api.compute_tax_return(ret["id"], h), 200)
    status = validate_success(api.get_estimated_tax_status(ret["id"], h), 200)
    assert status["required_annual_cents"] == 1_237_770
    assert status["penalty_cents"] == 59_021


def test_late_estimated_payment_marked_not_on_time(api):
    """PRD §3.4: "each payment's `on_time` flag is computed: it is true when `paid_on`
    is on or before the statutory due date for its quarter, and false otherwise."
    PRD §3.4: "The due dates are fixed: Q1 is due at the final instant of April 15, 2025
    (UTC); Q2 at the final instant of June 16, 2025; Q3 at the final instant of
    September 15, 2025; and Q4 at the final instant of January 15, 2026."

    Design: Corner/endpoints/late_estimated_payment_not_counted_on_time
    """
    tp = _new_taxpayer(api, filing_status="SINGLE")
    h = make_taxpayer_headers(tp["id"])
    ret = _open_return(api, tp["id"], filing_status="SINGLE")
    validate_success(api.create_income_document(
        ret["id"], create_income_document_payload(box_amount_cents=8_000_000), h), 201)
    payment = validate_success(api.create_estimated_tax_payment(
        create_estimated_tax_payment_payload(
            ret["id"], quarter="Q1", amount_cents=100_000,
            paid_on="2025-05-01T00:00:00Z",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-04-01T00:00:00Z"), h), 201)
    assert payment["on_time"] is False
