"""Underwriting calculations: dual-variant DSCR, risk rating, maximum sizing.

Implements calculations.dscr_computation, calculations.risk_rating_model,
calculations.maximum_sizing with the pinned evaluation orders from the PRD.
"""
from decimal import Decimal

from db import STORE, now_dt
from errors import raise_err, ERR_NO_SIZEABLE_AMOUNT
from services.exposure import (
    statements_of_app,
    collateral_aggregates,
    borrower_total_exposure_cents,
)
from services.money import (
    round_half_up_cents,
    round_half_up_4dp,
    round_half_up_2dp,
    floor_cents,
)

POLICY_RATE_BPS = 700                      # 7.00% per annum underwriting rate
ADDBACK_CAP_RATIO = Decimal("0.25")
STRESS_REVENUE_HAIRCUT = Decimal("0.15")
DSCR_MIN = Decimal("1.25")
STRESS_DSCR_MIN = Decimal("1.0")
SINGLE_BORROWER_CAP_CENTS = 5000000000     # $50,000,000.00

MAX_LTV = {
    "CRE_TERM": Decimal("0.80"),
    "CRE_CONSTRUCTION": Decimal("0.75"),
    "CI_WORKING_CAPITAL": Decimal("0.60"),
    "EQUIPMENT": Decimal("0.85"),
    "AGRICULTURE": Decimal("0.75"),
}

PRODUCT_TYPES = set(MAX_LTV.keys())


def monthly_rate():
    return Decimal(POLICY_RATE_BPS) / Decimal(10000) / Decimal(12)


def _annuity_factor(term_months):
    r = monthly_rate()
    return Decimal(1) - (Decimal(1) + r) ** (-term_months)


def monthly_payment_cents(principal_cents, term_months):
    r = monthly_rate()
    pmt = Decimal(principal_cents) * r / _annuity_factor(term_months)
    return round_half_up_cents(pmt)


def latest_final_statement(app_id):
    """The FINAL statement with max period_end_date (ties: latest finalized)."""
    finals = [s for s in statements_of_app(app_id) if s['status'] == 'FINAL']
    if not finals:
        return None
    return max(finals, key=lambda s: (s['period_end_date'], s['_seq']))


def compute_dscr(app, stmt):
    """Returns (dscr_standard Decimal4dp, dscr_stress Decimal4dp, cf_standard int)."""
    requested = app['requested_amount_cents']
    term = app['term_months']
    pmt = monthly_payment_cents(requested, term)
    annual_debt_service = pmt * 12 + stmt['existing_annual_debt_service_cents']

    # BANK_STANDARD variant: addbacks capped at 25% of EBITDA (floor to cents).
    addback_cap = floor_cents(Decimal(stmt['ebitda_cents']) * ADDBACK_CAP_RATIO)
    addback_allowed = min(stmt['addbacks_cents'], addback_cap)
    cf_standard = (stmt['ebitda_cents'] + addback_allowed
                   - stmt['distributions_cents'] - stmt['maintenance_capex_cents'])
    dscr_standard = round_half_up_4dp(Decimal(cf_standard) / Decimal(annual_debt_service))

    # REGULATORY_STRESS variant: revenue haircut, addbacks excluded.
    haircut = round_half_up_cents(Decimal(stmt['revenue_cents']) * STRESS_REVENUE_HAIRCUT)
    ebitda_stress = stmt['ebitda_cents'] - haircut
    cf_stress = (ebitda_stress - stmt['distributions_cents']
                 - stmt['maintenance_capex_cents'])
    dscr_stress = round_half_up_4dp(Decimal(cf_stress) / Decimal(annual_debt_service))

    return dscr_standard, dscr_stress, cf_standard


# --- risk rating model ---

def dscr_points(dscr_standard):
    d = Decimal(dscr_standard)
    if d >= Decimal("1.50"):
        return 100
    if d >= Decimal("1.35"):
        return 80
    if d >= Decimal("1.25"):
        return 60
    if d >= Decimal("1.10"):
        return 40
    return 20


def leverage_points(stmt):
    assets = stmt['total_assets_cents']
    if assets <= 0:
        return 20
    ratio = round_half_up_4dp(Decimal(stmt['total_liabilities_cents']) / Decimal(assets))
    if ratio <= Decimal("0.50"):
        return 100
    if ratio <= Decimal("0.65"):
        return 80
    if ratio <= Decimal("0.75"):
        return 60
    if ratio <= Decimal("0.85"):
        return 40
    return 20


def coverage_points(total_eligible_cents, requested_amount_cents):
    if requested_amount_cents <= 0:
        return 25
    ratio = Decimal(total_eligible_cents) / Decimal(requested_amount_cents)
    if ratio >= Decimal("1.25"):
        return 100
    if ratio >= Decimal("1.00"):
        return 75
    if ratio >= Decimal("0.75"):
        return 50
    return 25


def tenure_points(borrower):
    """Whole years elapsed between relationship_since and the logical clock date."""
    since = borrower['relationship_since']  # date object
    now = now_dt().date()
    years = now.year - since.year
    if (now.month, now.day) < (since.month, since.day):
        years -= 1
    if years >= 10:
        return 100
    if years >= 5:
        return 75
    if years >= 2:
        return 50
    return 25


def score_to_rating(score):
    s = Decimal(score)
    for threshold, rating in ((90, 1), (80, 2), (70, 3), (60, 4), (50, 5),
                              (40, 6), (30, 7), (20, 8), (10, 9)):
        if s >= Decimal(threshold):
            return rating
    return 10


def compute_risk_rating(app, stmt, borrower, basis):
    dp = dscr_points(app['dscr_standard'])
    lp = leverage_points(stmt)
    tp = tenure_points(borrower)
    if basis == 'FULL':
        total_appraised, total_eligible, _ = collateral_aggregates(app['id'])
        cp = coverage_points(total_eligible, app['requested_amount_cents'])
        score = round_half_up_2dp(
            Decimal("0.40") * dp + Decimal("0.30") * lp
            + Decimal("0.20") * cp + Decimal("0.10") * tp)
    else:  # PROVISIONAL: coverage excluded, weights renormalized
        score = round_half_up_2dp(
            (Decimal("0.40") * dp + Decimal("0.30") * lp + Decimal("0.10") * tp)
            / Decimal("0.80"))
    return score_to_rating(score)


# --- maximum sizing (pinned order, no iteration back) ---

def compute_maximum_sizing(app, stmt, borrower):
    """Returns proposed_amount_cents or raises ERR_NO_SIZEABLE_AMOUNT."""
    # (1) DSCR principal cap from the already-computed standard cash flow.
    _, _, cf_standard = compute_dscr(app, stmt)
    max_annual_proposed_ds = (
        floor_cents(Decimal(cf_standard) / DSCR_MIN)
        - stmt['existing_annual_debt_service_cents'])
    if max_annual_proposed_ds <= 0:
        raise_err(ERR_NO_SIZEABLE_AMOUNT,
                  "Sizing yields no sizeable amount: maximum annual proposed debt service is not positive.")
    pmt_max = Decimal(max_annual_proposed_ds) / Decimal(12)
    dscr_max = floor_cents(pmt_max * _annuity_factor(app['term_months']) / monthly_rate())

    # (2) LTV principal cap.
    total_appraised, _, _ = collateral_aggregates(app['id'])
    ltv_max = floor_cents(Decimal(total_appraised) * MAX_LTV[app['product_type']])

    # (3) Single-borrower cap headroom.
    cap_headroom = SINGLE_BORROWER_CAP_CENTS - borrower_total_exposure_cents(borrower['id'])

    # (4) Proposed amount.
    proposed = min(app['requested_amount_cents'], dscr_max, ltv_max, cap_headroom)
    if proposed <= 0:
        raise_err(ERR_NO_SIZEABLE_AMOUNT,
                  "Sizing yields no sizeable amount: proposed amount is not positive.")
    return proposed
