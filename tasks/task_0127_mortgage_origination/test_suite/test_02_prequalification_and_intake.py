"""Pre-qualification gate (PRD §3.2) and INTAKE-state preconditions
(PRD §3.1).

Covers:
- The three pre-qualification preconditions: credit_score >= 620,
  annual_income_cents > 0, requested_loan_amount <= 4x stated income.
- Pre-qualification DTI variant (PRD §3.7 first variant — falls back
  to stated income).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_loan_application,
    create_borrower,
    create_borrower_and_application,
    create_loan_application,
    pre_qualify,
    validate_error,
    validate_success,
)


# ===========================================================================
# Pre-qualification preconditions — PRD §3.2
# ===========================================================================
def test_pre_qualify_happy_path_intake_to_prequalified(
    api, loan_officer_headers,
):
    """PRD §3.2: "Pre-qualifying an application by a LoanOfficer
    advances status from INTAKE to PRE_QUALIFIED once three conditions
    are satisfied: the borrower's credit_score is at least 620, the
    borrower's annual_income_cents is strictly greater than zero, and
    the requested_loan_amount_cents is no more than four times the
    borrower's annual_income_cents."

    Claim: with credit_score=720, annual_income=$120,000,
    requested=$200,000 (1.67x stated income), pre-qualify succeeds and
    status becomes PRE_QUALIFIED.
    """
    _, app = create_borrower_and_application(headers=loan_officer_headers)
    assert app["status"] == "INTAKE"
    res = api.pre_qualify(app["id"], None, loan_officer_headers)
    pre = validate_success(res, 200)
    assert_loan_application(pre)
    assert pre["status"] == "PRE_QUALIFIED"


@pytest.mark.parametrize("score", [620, 700, 850])
def test_pre_qualify_credit_score_at_or_above_620_accepted(
    api, loan_officer_headers, score,
):
    """PRD §3.2: "the borrower's credit_score is at least 620"

    Claim: credit_score in {620, 700, 850} satisfies the gate.
    Boundary: 620 is the inclusive lower bound.
    """
    borrower = create_borrower(
        credit_score=score, headers=loan_officer_headers,
    )
    app = create_loan_application(
        borrower["id"], headers=loan_officer_headers,
    )
    res = api.pre_qualify(app["id"], None, loan_officer_headers)
    pre = validate_success(res, 200)
    assert pre["status"] == "PRE_QUALIFIED"


@pytest.mark.parametrize("score", [619, 600, 500, 300])
def test_pre_qualify_credit_score_below_620_rejected(
    api, loan_officer_headers, score,
):
    """PRD §3.2: "the borrower's credit_score is at least 620"

    Claim: credit_score < 620 blocks pre-qualification. The PRD prose
    states "Failure of these state-machine preconditions surfaces as
    ERR_INVALID_STATE if the source state itself is wrong, or as an
    ERR_VALIDATION for body-shape issues" — credit_score is a data
    precondition (not source-state, not body-shape), so the PRD does
    not commit to a specific error id for this particular failure.
    We assert the request is rejected with a 4xx status.
    """
    borrower = create_borrower(
        credit_score=score, headers=loan_officer_headers,
    )
    app = create_loan_application(
        borrower["id"], headers=loan_officer_headers,
    )
    res = api.pre_qualify(app["id"], None, loan_officer_headers)
    assert res.status_code >= 400, (
        f"PRD §3.2: pre-qualify with credit_score={score} (< 620) "
        f"must be rejected, got status {res.status_code}"
    )
    # State must remain INTAKE — the failed transition cannot have
    # advanced it.
    got = validate_success(
        api.get_loan_application(app["id"], loan_officer_headers), 200,
    )
    assert got["status"] == "INTAKE"


def test_pre_qualify_requested_at_4x_income_accepted(
    api, loan_officer_headers,
):
    """PRD §3.2: "the requested_loan_amount_cents is no more than four
    times the borrower's annual_income_cents".

    Claim: requested == 4 * annual_income_cents is inclusive ("no more
    than" -> 4x is permitted). With annual_income=$100,000 and
    requested=$400,000, pre-qualify must succeed.
    """
    borrower = create_borrower(
        annual_income_cents=10_000_000,   # $100,000
        headers=loan_officer_headers,
    )
    app = create_loan_application(
        borrower["id"],
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=40_000_000,  # exactly 4x
        headers=loan_officer_headers,
    )
    res = api.pre_qualify(app["id"], None, loan_officer_headers)
    pre = validate_success(res, 200)
    assert pre["status"] == "PRE_QUALIFIED"


def test_pre_qualify_requested_above_4x_income_rejected(
    api, loan_officer_headers,
):
    """PRD §3.2: "the requested_loan_amount_cents is no more than four
    times the borrower's annual_income_cents".

    Claim: requested > 4x stated income blocks pre-qualification. With
    annual_income=$100,000 and requested=$40,000,001 (just above 4x),
    pre-qualify is rejected and status remains INTAKE.
    """
    borrower = create_borrower(
        annual_income_cents=10_000_000,
        headers=loan_officer_headers,
    )
    app = create_loan_application(
        borrower["id"],
        sale_price_cents=40_000_001,
        requested_loan_amount_cents=40_000_001,  # > 4x
        headers=loan_officer_headers,
    )
    res = api.pre_qualify(app["id"], None, loan_officer_headers)
    assert res.status_code >= 400
    got = validate_success(
        api.get_loan_application(app["id"], loan_officer_headers), 200,
    )
    assert got["status"] == "INTAKE"


# ===========================================================================
# Pre-qualification DTI variant — PRD §3.2 + §3.7
# ===========================================================================
def test_pre_qualify_falls_back_to_stated_income(
    api, loan_officer_headers,
):
    """PRD §3.2: "At this transition, the system also computes a
    preliminary dti_ratio using the pre-qualification variant of the
    DTI calculation. Because no IncomeVerification records have been
    verified yet, this preliminary value falls back to the borrower's
    stated annual_income_cents as the income basis"

    Claim: after pre-qualify, dti_ratio is populated and was computed
    from Borrower.annual_income_cents. We check positivity and that
    its value is consistent with the §3.7 formula using stated income.
    The PRD does not uniquely fix dti_ratio's serialised type (the
    is `number`, 4 decimal places ROUND_HALF_UP per §2.8), so we assert
    the numeric value within ±0.0001 of the expected.
    """
    # Stated annual = $120,000 = 12_000_000 cents
    # Requested principal = $200,000 = 20_000_000 cents
    # expected_monthly_income_cents = 12_000_000 / 12 = 1_000_000
    # approx_monthly_payment_cents  = 20_000_000 * 0.0065 = 130_000
    # dti_ratio = 130_000 / 1_000_000 = 0.1300
    _, app = create_borrower_and_application(
        annual_income_cents=12_000_000,
        sale_price_cents=40_000_000,
        requested_loan_amount_cents=20_000_000,
        headers=loan_officer_headers,
    )
    pre = pre_qualify(app["id"], headers=loan_officer_headers)
    assert pre["status"] == "PRE_QUALIFIED"
    dti = pre.get("dti_ratio")
    assert dti is not None, (
        "PRD §3.2: pre-qualify must compute dti_ratio from the "
        "stated-income fallback"
    )
    assert dti == pytest.approx(0.1300, abs=0.0001), (
        f"PRD §3.7 pre-qualification variant: dti_ratio should be "
        f"0.1300 (130,000 / 1,000,000); got {dti}"
    )


# ===========================================================================
# State-machine boundary — INTAKE → WITHDRAWN
# ===========================================================================
def test_withdraw_from_intake_succeeds(api, loan_officer_headers):
    """PRD §3.1: "From INTAKE, two transitions are immediately
    available: pre-qualifying the application advances status to
    PRE_QUALIFIED, and withdrawing it sets status to WITHDRAWN.
    Withdrawal from INTAKE carries no cascades, because no rate lock
    can yet exist."

    Claim: withdrawing from INTAKE sets status=WITHDRAWN.
    """
    _, app = create_borrower_and_application(headers=loan_officer_headers)
    res = api.withdraw_application(app["id"], None, loan_officer_headers)
    out = validate_success(res, 200)
    assert out["status"] == "WITHDRAWN"


def test_pre_qualify_from_pre_qualified_is_invalid_state(
    api, loan_officer_headers,
):
    """PRD §2.10: "State-machine checks (whether the source state
    matches the transition's from) precede business-rule checks."
    PRD §3.2: pre-qualify advances INTAKE → PRE_QUALIFIED; replaying
    the call on an already-PRE_QUALIFIED application has the wrong
    source state.

    Claim: pre-qualify on PRE_QUALIFIED -> ERR_INVALID_STATE (409).
    """
    _, app = create_borrower_and_application(headers=loan_officer_headers)
    pre_qualify(app["id"], headers=loan_officer_headers)
    res = api.pre_qualify(app["id"], None, loan_officer_headers)
    validate_error(
        res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409,
    )
