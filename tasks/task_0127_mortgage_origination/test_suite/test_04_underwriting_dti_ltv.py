"""Submission to underwriting and the DTI/LTV recompute on the
PRE_QUALIFIED → UNDERWRITING transition (PRD §3.7).

Covers difficulty design instance:
  - dti_prequal_vs_underwriting_variants (difficulty:
    dual_variant_calc/dti_prequal_vs_underwriting_variants)
  - ltv_sale_price_vs_appraised_value_basis (difficulty:
    dual_variant_calc/ltv_sale_price_vs_appraised_value_basis)
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    api_client,
    assert_loan_application,
    create_and_pre_qualify,
    create_and_verify_asset,
    create_and_verify_income,
    create_borrower_and_application,
    get_loan_application,
    issue_loan_estimate,
    order_and_complete_appraisal,
    order_and_complete_title_search,
    setup_application_ready_for_underwriting,
    submit_underwriting,
    submit_underwriting_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# submit-underwriting precondition gate — PRD §3.7
# ===========================================================================
def test_submit_underwriting_happy_path_advances_state(
    api, loan_officer_headers,
):
    """PRD §3.7: "Submitting an application to underwriting moves
    status from PRE_QUALIFIED to UNDERWRITING. The transition is gated
    on five preconditions: at least one IncomeVerification is VERIFIED
    for this application, at least one AssetVerification is VERIFIED,
    an Appraisal is COMPLETED, a TitleSearch is either CLEAR or
    RESOLVED, and an initial LOAN_ESTIMATE Disclosure exists in either
    ISSUED or ACKNOWLEDGED."

    Claim: when all five preconditions are met, /submit-underwriting
    sets status=UNDERWRITING and assigns compliance_reviewer_id.
    """
    _, app, _, _ = setup_application_ready_for_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
    )
    res = api.submit_underwriting(
        app["id"],
        submit_underwriting_payload(compliance_reviewer_id="co-001"),
        loan_officer_headers,
    )
    out = validate_success(res, 200)
    assert_loan_application(out)
    assert out["status"] == "UNDERWRITING"
    assert out.get("compliance_reviewer_id") == "co-001"


def test_submit_underwriting_missing_income_verification_blocked(
    api, loan_officer_headers,
):
    """PRD §3.7: "If any of the five is missing, the request is
    rejected with ERR_MISSING_DEPENDENCIES."

    Claim: skip the IncomeVerification step — submit -> 409
    ERR_MISSING_DEPENDENCIES. Application stays PRE_QUALIFIED.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    # Provide everything EXCEPT a verified income.
    create_and_verify_asset(app["id"], headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"], appraised_value_cents=40_000_000,
        headers=loan_officer_headers,
    )
    order_and_complete_title_search(
        app["id"], defects_found=[], headers=loan_officer_headers,
    )
    issue_loan_estimate(app["id"], headers=loan_officer_headers)
    res = api.submit_underwriting(
        app["id"],
        submit_underwriting_payload(compliance_reviewer_id="co-001"),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_DEPENDENCIES.value,
        expected_status=409,
    )


def test_submit_underwriting_missing_asset_verification_blocked(
    api, loan_officer_headers,
):
    """PRD §3.7 ERR_MISSING_DEPENDENCIES.

    Claim: skip AssetVerification -> ERR_MISSING_DEPENDENCIES.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    create_and_verify_income(app["id"], headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"], appraised_value_cents=40_000_000,
        headers=loan_officer_headers,
    )
    order_and_complete_title_search(
        app["id"], defects_found=[], headers=loan_officer_headers,
    )
    issue_loan_estimate(app["id"], headers=loan_officer_headers)
    res = api.submit_underwriting(
        app["id"],
        submit_underwriting_payload(compliance_reviewer_id="co-001"),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_DEPENDENCIES.value,
        expected_status=409,
    )


def test_submit_underwriting_missing_loan_estimate_blocked(
    api, loan_officer_headers,
):
    """PRD §3.7 ERR_MISSING_DEPENDENCIES — missing initial LE.

    Claim: omit the LOAN_ESTIMATE step -> ERR_MISSING_DEPENDENCIES.
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(headers=loan_officer_headers)
    create_and_verify_income(app["id"], headers=loan_officer_headers)
    create_and_verify_asset(app["id"], headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"], appraised_value_cents=40_000_000,
        headers=loan_officer_headers,
    )
    order_and_complete_title_search(
        app["id"], defects_found=[], headers=loan_officer_headers,
    )
    res = api.submit_underwriting(
        app["id"],
        submit_underwriting_payload(compliance_reviewer_id="co-001"),
        loan_officer_headers,
    )
    validate_error(
        res,
        ApiErrorId.ERR_MISSING_DEPENDENCIES.value,
        expected_status=409,
    )


# ===========================================================================
# Segregation of duties at submit-underwriting — PRD §3.7
# ===========================================================================
def test_submit_underwriting_sod_compliance_equals_loan_officer_rejected(
    api, loan_officer_headers,
):
    """PRD §3.7: "The supplied value must not equal the application's
    assigned_loan_officer_id — segregation of duties is enforced at
    this moment of assignment."

    Claim: compliance_reviewer_id == assigned_loan_officer_id -> the
    request is rejected. PRD §3.7 names this violation as a SoD
    enforcement at assignment but does not commit to one specific
    error_id beyond the SoD theme. We assert rejection with 4xx.
    """
    _, app, _, _ = setup_application_ready_for_underwriting(
        clock_anchor="2026-03-02T10:00:00.000Z",
        assigned_loan_officer_id="lo-001",
    )
    res = api.submit_underwriting(
        app["id"],
        submit_underwriting_payload(compliance_reviewer_id="lo-001"),
        loan_officer_headers,
    )
    assert res.status_code >= 400


# ===========================================================================
# DTI calculation — PRD §3.7
# difficulty: dual_variant_calc/dti_prequal_vs_underwriting_variants
# ===========================================================================
def test_dti_prequal_uses_stated_income_then_underwriting_uses_verified(
    api, loan_officer_headers,
):
    """PRD §3.7: "The pre-qualification variant is used at the INTAKE
    → PRE_QUALIFIED transition. Because no income verifications have
    been recorded yet, if the aggregated effective income is zero, the
    system falls back to the borrower's stated annual_income_cents."
    PRD §3.7: "The underwriting variant is used at the PRE_QUALIFIED
    → UNDERWRITING transition and again as a gate at conditional
    approval. It does not fall back to the borrower's stated figure"

    Claim: with stated annual = $120,000 and verified = $96,000 ($80%
    of stated), pre-qualify produces dti=0.1300 (uses 12_000_000),
    submit-underwriting recomputes dti=0.1625 (uses 9_600_000).
      pre-qual:    130000 / 1000000     = 0.1300
      underwriting:130000 / 800000      = 0.1625

    # difficulty: dual_variant_calc/dti_prequal_vs_underwriting_variants
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        annual_income_cents=12_000_000,
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    assert app["dti_ratio"] == pytest.approx(0.1300, abs=0.0001), (
        "Pre-qualification DTI must use stated income fallback "
        "(PRD §3.7)"
    )

    # Now drive to UNDERWRITING with one VERIFIED income of $96,000.
    create_and_verify_income(
        app["id"],
        documented_annual_cents=9_600_000,
        headers=loan_officer_headers,
    )
    create_and_verify_asset(app["id"], headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"], appraised_value_cents=40_000_000,
        headers=loan_officer_headers,
    )
    order_and_complete_title_search(
        app["id"], defects_found=[], headers=loan_officer_headers,
    )
    issue_loan_estimate(app["id"], headers=loan_officer_headers)
    submit_underwriting(app["id"], headers=loan_officer_headers)
    after = get_loan_application(
        app["id"], headers=loan_officer_headers,
    )
    assert after["status"] == "UNDERWRITING"
    assert after["dti_ratio"] == pytest.approx(0.1625, abs=0.0001), (
        "Underwriting DTI must use only verified income aggregate "
        "(PRD §3.7). Expected 0.1625 (130,000 / 800,000); got "
        f"{after['dti_ratio']}."
    )
    assert after["dti_ratio"] != app["dti_ratio"], (
        "PRD §3.7: the two variants must produce different ratios "
        "on the same row when stated and verified incomes differ."
    )


def test_dti_prequal_distinct_from_underwriting_on_same_row(
    api, loan_officer_headers,
):
    """PRD §3.7 dual-variant rule: same Borrower data + same
    LoanApplication, two different DTI ratios depending on which
    variant runs.

    # difficulty: dual_variant_calc/dti_prequal_vs_underwriting_variants
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        annual_income_cents=12_000_000,
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    pre_dti = app["dti_ratio"]
    create_and_verify_income(
        app["id"], documented_annual_cents=9_600_000,
        headers=loan_officer_headers,
    )
    create_and_verify_asset(app["id"], headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"], appraised_value_cents=40_000_000,
        headers=loan_officer_headers,
    )
    order_and_complete_title_search(
        app["id"], defects_found=[], headers=loan_officer_headers,
    )
    issue_loan_estimate(app["id"], headers=loan_officer_headers)
    submit_underwriting(app["id"], headers=loan_officer_headers)
    after = get_loan_application(
        app["id"], headers=loan_officer_headers,
    )
    underw_dti = after["dti_ratio"]
    assert pre_dti is not None and underw_dti is not None
    assert pre_dti != underw_dti, (
        "PRD §3.7: pre-qualification and underwriting variants must "
        "yield different ratios when stated and verified incomes "
        f"differ. Got pre={pre_dti}, underwriting={underw_dti}."
    )


# ===========================================================================
# LTV calculation — PRD §3.7
# difficulty: dual_variant_calc/ltv_sale_price_vs_appraised_value_basis
# ===========================================================================
def test_ltv_uses_appraised_when_below_sale_price(api, loan_officer_headers):
    """PRD §3.7: "The value basis is the minimum of the application's
    sale_price_cents and the latest completed Appraisal's
    appraised_value_cents — the lender treats the lower of contract
    price and appraised value as the secured value."

    Claim: sale=$400,000, appraised=$380,000, principal=$360,000 ->
    ltv = 360000/380000 = 0.9474 (uses appraised as the basis).

    # difficulty: dual_variant_calc/ltv_sale_price_vs_appraised_value_basis
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        annual_income_cents=20_000_000,
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=36_000_000,
        headers=loan_officer_headers,
    )
    create_and_verify_income(
        app["id"],
        documented_annual_cents=20_000_000,
        headers=loan_officer_headers,
    )
    create_and_verify_asset(app["id"], headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"], appraised_value_cents=38_000_000,
        headers=loan_officer_headers,
    )
    order_and_complete_title_search(
        app["id"], defects_found=[], headers=loan_officer_headers,
    )
    issue_loan_estimate(app["id"], headers=loan_officer_headers)
    submit_underwriting(app["id"], headers=loan_officer_headers)
    after = get_loan_application(
        app["id"], headers=loan_officer_headers,
    )
    assert after["ltv_ratio"] == pytest.approx(0.9474, abs=0.0001), (
        "PRD §3.7: ltv = principal/min(sale,appraised); with "
        "sale=400000000c, appraised=38_000_000c, principal=36_000_000c "
        f"expected 0.9474, got {after['ltv_ratio']}."
    )
    assert after["pmi_required"] is True, (
        "PRD §3.7: ltv > 0.80 (0.9474) implies pmi_required true."
    )


def test_ltv_uses_sale_price_when_appraised_above(api, loan_officer_headers):
    """PRD §3.7: "the lower of contract price and appraised value as
    the secured value."

    Claim: sale=$400,000, appraised=$410,000, principal=$360,000 ->
    ltv = 360000/400000 = 0.9000 (sale_price is the basis).

    # difficulty: dual_variant_calc/ltv_sale_price_vs_appraised_value_basis
    """
    advance_clock("2026-03-02T10:00:00.000Z")
    _, app = create_and_pre_qualify(
        annual_income_cents=20_000_000,
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=36_000_000,
        headers=loan_officer_headers,
    )
    create_and_verify_income(
        app["id"],
        documented_annual_cents=20_000_000,
        headers=loan_officer_headers,
    )
    create_and_verify_asset(app["id"], headers=loan_officer_headers)
    order_and_complete_appraisal(
        app["id"], appraised_value_cents=41_000_000,
        headers=loan_officer_headers,
    )
    order_and_complete_title_search(
        app["id"], defects_found=[], headers=loan_officer_headers,
    )
    issue_loan_estimate(app["id"], headers=loan_officer_headers)
    submit_underwriting(app["id"], headers=loan_officer_headers)
    after = get_loan_application(
        app["id"], headers=loan_officer_headers,
    )
    assert after["ltv_ratio"] == pytest.approx(0.9000, abs=0.0001), (
        "PRD §3.7: with appraised > sale_price, ltv = "
        "principal/sale_price. Expected 0.9000, got "
        f"{after['ltv_ratio']}."
    )
    # NOTE: PRD §3.7 only commits to recomputing pmi_required on appraisal
    # completion when appraised_value < sale_price (§2.6 / §3.4 L97), on
    # APPROVE (§3.8 L194), and at clear-to-close (§3.7 L188). It does NOT
    # say submit-underwriting recomputes pmi_required. So with appraised
    # >= sale_price the appraisal-completion cascade leaves pmi_required
    # alone, and submit-underwriting need not set it. Asserting
    # pmi_required is True here is not PRD-derivable.
