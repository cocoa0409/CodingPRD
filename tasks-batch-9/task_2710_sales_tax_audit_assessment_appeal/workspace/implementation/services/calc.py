"""Pure arithmetic: constants and the seven calculation rules (SCAFFOLD 1.3)."""
from decimal import ROUND_HALF_UP, Decimal

# ---------------------------------------------------------------- constants
STATE_SALES_TAX_RATE_BP = 625
ANNUAL_INTEREST_RATE_BP = 800
DAYS_PER_YEAR = 365
SMALL_BALANCE_THRESHOLD_CENTS = 5000
COLLECTION_FEE_BP = 1000
MIN_OIC_BP = 2000
PROTEST_WINDOW_DAYS = 60
ESCALATION_WINDOW_DAYS = 30
STATUTE_BASE_DAYS = 1095
EXPIRING_SOON_DAYS = 90
MAX_NEGOTIATION_ROUNDS = 3
DELINQUENCY_BP_PER_PERIOD = 2500
MAGNITUDE_CAP_CENTS = 5000000000
NEUTRAL_PRIOR_BP = 3500
FMV_STEPDOWN_MONTHS = 6

ABATEMENT_POINTS = {
    "FIRST_TIME_COMPLIANT": 40,
    "RELIANCE_ON_WRITTEN_ADVICE": 35,
    "RECORDS_LOST_IN_DISASTER": 25,
    "SUBSTANTIAL_COOPERATION": 20,
}
MAX_ABATEMENT_PCT = 100
DELINQUENT_ABATEMENT_CAP_PCT = 50

FORUM_LADDER = ("INFORMAL_CONFERENCE", "ADMINISTRATIVE_APPEAL", "TAX_TRIBUNAL")
LIVE_AUDIT_STATUSES = ("PLANNED", "SCOPED", "FIELDWORK", "REVIEW_COMPLETE", "ASSESSED")


def rhu(numerator, denominator=1):
    """Integer division rounded half up (never float)."""
    quotient = Decimal(int(numerator)) / Decimal(int(denominator))
    return int(quotient.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ------------------------------------------------------- taxpayer_risk_score
def variance_bp(reported_total, matched_total):
    if reported_total == 0:
        return 0
    delta = abs(reported_total - matched_total)
    return min(10000, rhu(delta * 10000, reported_total))


def delinquency_bp(delinquent_period_count):
    return min(10000, int(delinquent_period_count) * DELINQUENCY_BP_PER_PERIOD)


def magnitude_bp(gross_receipts_annual_cents):
    capped = min(int(gross_receipts_annual_cents), MAGNITUDE_CAP_CENTS)
    return min(10000, rhu(capped * 10000, MAGNITUDE_CAP_CENTS))


def prior_audit_bp(prior_audit_error_rate_bp):
    if prior_audit_error_rate_bp is None:
        return NEUTRAL_PRIOR_BP
    return min(10000, int(prior_audit_error_rate_bp))


def screening_score(v_bp, d_bp):
    return rhu(60 * v_bp + 40 * d_bp, 1000)


def full_score(v_bp, d_bp, i_bp, m_bp, p_bp):
    return rhu(35 * v_bp + 20 * d_bp + 20 * i_bp + 15 * m_bp + 10 * p_bp, 1000)


# ---------------------------------------------------------- sample_projection
def sample_error_rate_bp(sum_err, sum_base):
    if sum_base == 0:
        return 0
    return rhu(sum_err * 10000, sum_base)


def project(methodology, sum_err, sum_base, n, population_base_cents, population_units):
    rate = sample_error_rate_bp(sum_err, sum_base)
    if methodology == "MEAN_PER_UNIT":
        mean_unit_error = rhu(sum_err, n) if n else 0
        projected = mean_unit_error * int(population_units)
    else:
        projected = rhu(int(population_base_cents) * rate, 10000)
    return rate, projected


def unit_error_amount(error_class, exempt_sale_amount_cents, declared_error_amount_cents):
    if error_class in ("PENDING", "NO_ERROR"):
        return 0
    if error_class == "CERTIFICATE_DEFECT":
        return rhu(int(exempt_sale_amount_cents) * STATE_SALES_TAX_RATE_BP, 10000)
    return int(declared_error_amount_cents or 0)


def tax_on(amount_cents):
    return rhu(int(amount_cents) * STATE_SALES_TAX_RATE_BP, 10000)


# ---------------------------------------------------------- use_tax_liability
def use_tax_row(asset_class, purchase_price_cents, in_state_usage_pct_bp,
                first_use_outside_state, months_used_outside_state,
                fair_market_value_at_entry_cents, tax_paid_other_state_cents):
    """Returns (taxable_basis, gross, credit, due). FMV presence is validated by caller."""
    if asset_class == "CONSUMABLE":
        basis = int(purchase_price_cents)
    elif asset_class == "EXEMPT_MANUFACTURING":
        basis = 0
    else:
        if first_use_outside_state and int(months_used_outside_state or 0) >= FMV_STEPDOWN_MONTHS:
            base = int(fair_market_value_at_entry_cents)
        else:
            base = int(purchase_price_cents)
        basis = rhu(base * int(in_state_usage_pct_bp), 10000)
    gross = rhu(basis * STATE_SALES_TAX_RATE_BP, 10000)
    credit = min(int(tax_paid_other_state_cents or 0), gross)
    return basis, gross, credit, gross - credit


def needs_fmv(asset_class, first_use_outside_state, months_used_outside_state):
    return (
        asset_class == "CAPITAL_ASSET"
        and bool(first_use_outside_state)
        and int(months_used_outside_state or 0) >= FMV_STEPDOWN_MONTHS
    )


# ------------------------------------------------- assessment_liability_rollup
def penalty_rate(fraud_indicator, tax_deficiency_cents):
    if fraud_indicator:
        return 5000
    if tax_deficiency_cents > 1000000000:
        return 2500
    if tax_deficiency_cents > 100000000:
        return 1500
    if tax_deficiency_cents > 1000000:
        return 1000
    return 500


def rollup(projected, certificate, use_tax, fraud_indicator, interest_days):
    """The five-step rollup. Returns the eight computed money figures."""
    tax = int(projected) + int(certificate) + int(use_tax)
    rate_bp = penalty_rate(fraud_indicator, tax)
    penalty = rhu(tax * rate_bp, 10000)
    interest = rhu((tax + penalty) * ANNUAL_INTEREST_RATE_BP * int(interest_days),
                   10000 * DAYS_PER_YEAR)
    provisional = tax + penalty + interest
    if provisional <= SMALL_BALANCE_THRESHOLD_CENTS:
        waived = True
        penalty = 0
        interest = rhu(tax * ANNUAL_INTEREST_RATE_BP * int(interest_days),
                       10000 * DAYS_PER_YEAR)
    else:
        waived = False
    total_due = tax + penalty + interest
    return {
        "tax_deficiency_cents": tax,
        "penalty_rate_bp": rate_bp,
        "penalty_cents": penalty,
        "interest_days": int(interest_days),
        "interest_cents": interest,
        "provisional_total_due_cents": provisional,
        "penalty_waived_small_balance": waived,
        "total_due_cents": total_due,
    }


# ----------------------------------------------------------- penalty_abatement
def abatement_pct(factors, delinquent):
    points = 0
    for name in ABATEMENT_POINTS:
        if name in factors:
            points += ABATEMENT_POINTS[name]
    pct = min(MAX_ABATEMENT_PCT, points)
    if delinquent:
        pct = min(pct, DELINQUENT_ABATEMENT_CAP_PCT)
    return pct


def collection_fee(balance_due_cents):
    return -rhu(int(balance_due_cents) * COLLECTION_FEE_BP, 10000)
