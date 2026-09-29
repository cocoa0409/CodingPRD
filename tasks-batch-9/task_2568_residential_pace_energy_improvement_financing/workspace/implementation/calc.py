"""The twelve program calculations (PRD 2.5, 3.1-3.9).

All money is integer cents, all ratios integer basis points, all rounding is
half up unless a rule explicitly names truncation.
"""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

getcontext().prec = 60

# --- pinned program constants ------------------------------------------------
SIR_DISCOUNT_BPS = 300
ADMIN_FEE_BPS = 250
COUNTY_RECORDING_FEE_CENTS = 9500
ANNUAL_SERVICING_FEE_CENTS = 4000
PAYOFF_ADMIN_FEE_CENTS = 7500
PENALTY_BASE_BPS = 1000
PENALTY_PER_MONTH_BPS = 150
PENALTY_CAP_BPS = 2400
PENALTY_CAP_REFERRED_BPS = 3000
LIEN_REFERRAL_FEE_CENTS = 15000
CLTV_CAP_BPS = 9700
PTV_CAP_BPS = 1500
EQUITY_FLOOR_BPS = 1000
SIR_FLOOR_BPS = 10000
APPRAISAL_FRESH_DAYS = 180
CONSENT_WINDOW_DAYS = 30
QUOTE_GOOD_THROUGH_DAYS = 30
QUOTE_BUFFER_DAYS = 5
TRAILING_WINDOW_DAYS = 730
DUE_MONTH = 12
DUE_DAY = 10

PROGRAM_HOLIDAYS = frozenset(
    ("2026-09-07", "2026-11-26", "2026-12-25", "2027-01-01", "2027-07-03")
)

SEVERITY_DEDUCTION_BPS = {"MINOR": 300, "MAJOR": 800, "SEVERE": 2000}
UPHELD_COMPLAINT_STATUSES = ("REMEDY_ORDERED", "CLOSED_REMEDIED", "ESCALATED_RECOURSE")

ONE = Decimal(1)
BPS = Decimal(10000)


def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# --- 1. present_value_annuity_factor ----------------------------------------
def annuity_factor(rate_bps, years):
    """Quantized to ten decimal places, half up, BEFORE it is used anywhere."""
    rate = Decimal(int(rate_bps)) / BPS
    factor = (ONE - (ONE + rate) ** (-int(years))) / rate
    return factor.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)


# --- 2. savings_to_investment_ratio -----------------------------------------
def pv_savings_cents(annual_savings_cents, useful_life_years):
    factor = annuity_factor(SIR_DISCOUNT_BPS, useful_life_years)
    return round_half_up(Decimal(int(annual_savings_cents)) * factor)


def sir_bps(pv_cents, installed_cost_cents):
    if int(installed_cost_cents) == 0:
        return 0
    return round_half_up(Decimal(int(pv_cents)) * BPS / Decimal(int(installed_cost_cents)))


def portfolio_sir_bps(total_pv_cents, total_cost_cents):
    if int(total_cost_cents) == 0:
        return None
    return round_half_up(Decimal(int(total_pv_cents)) * BPS / Decimal(int(total_cost_cents)))


# --- 3. combined_lien_to_value_ratio ----------------------------------------
def cltv_bps(senior_lien_balance_cents, committed_pace_principal_cents, requested_principal_cents, basis_value_cents):
    if int(basis_value_cents) == 0:
        return None
    numerator = (
        int(senior_lien_balance_cents)
        + int(committed_pace_principal_cents)
        + int(requested_principal_cents)
    )
    return round_half_up(Decimal(numerator) * BPS / Decimal(int(basis_value_cents)))


def ptv_bps(requested_principal_cents, assessed_value_cents):
    if int(assessed_value_cents) == 0:
        return None
    return round_half_up(
        Decimal(int(requested_principal_cents)) * BPS / Decimal(int(assessed_value_cents))
    )


def equity_ratio_bps(senior_lien_balance_cents, assessed_value_cents):
    """Round FIRST, then subtract from 10000 (PRD 3.1)."""
    if int(assessed_value_cents) == 0:
        return 10000
    ratio = round_half_up(
        Decimal(int(senior_lien_balance_cents)) * BPS / Decimal(int(assessed_value_cents))
    )
    return 10000 - ratio


# --- 4. weighted_average_useful_life ----------------------------------------
def weighted_useful_life_years(pairs):
    """pairs = [(installed_cost_cents, useful_life_years), ...]; floored."""
    total_cost = sum(int(cost) for cost, _ in pairs)
    if total_cost == 0:
        return None
    weighted = sum(int(cost) * int(life) for cost, life in pairs)
    return int(Decimal(weighted) / Decimal(total_cost))


# --- 5. financed_amount_composition -----------------------------------------
def financed_amount_composition(principal_cents):
    principal = int(principal_cents)
    admin_fee = round_half_up(Decimal(principal) * Decimal(ADMIN_FEE_BPS) / BPS)
    recording = COUNTY_RECORDING_FEE_CENTS
    return {
        "principal_cents": principal,
        "admin_fee_cents": admin_fee,
        "county_recording_fee_cents": recording,
        "financed_amount_cents": principal + admin_fee + recording,
        "contractor_payable_cents": principal,
    }


# --- 6. level_payment_amortization_schedule ---------------------------------
def level_payment_cents(financed_amount_cents, apr_bps, term_years):
    factor = annuity_factor(apr_bps, term_years)
    return round_half_up(Decimal(int(financed_amount_cents)) / factor)


def amortization_schedule(original_principal_cents, annual_installment_cents, apr_bps, term_years, first_tax_year):
    rate = Decimal(int(apr_bps)) / BPS
    balance = int(original_principal_cents)
    lines = []
    for index in range(1, int(term_years) + 1):
        interest = round_half_up(Decimal(balance) * rate)
        if index == int(term_years):
            principal = balance
        else:
            principal = int(annual_installment_cents) - interest
        servicing = ANNUAL_SERVICING_FEE_CENTS
        tax_year = int(first_tax_year) + index - 1
        lines.append(
            {
                "tax_year": tax_year,
                "sequence": index,
                "due_on": "%04d-%02d-%02d" % (tax_year, DUE_MONTH, DUE_DAY),
                "principal_cents": principal,
                "interest_cents": interest,
                "servicing_fee_cents": servicing,
                "total_due_cents": principal + interest + servicing,
            }
        )
        balance -= principal
    return lines


# --- 7. delinquency_penalty_accrual -----------------------------------------
def delinquency_penalty(total_due_cents, due_on, effective_date, already_referred):
    days_past_due = (effective_date - due_on).days
    months_past_due = days_past_due // 30
    if months_past_due < 0:
        months_past_due = 0
    raw_bps = PENALTY_BASE_BPS + PENALTY_PER_MONTH_BPS * months_past_due
    cap_bps = PENALTY_CAP_REFERRED_BPS if already_referred else PENALTY_CAP_BPS
    applied_bps = raw_bps if raw_bps < cap_bps else cap_bps
    penalty = round_half_up(Decimal(int(total_due_cents)) * Decimal(applied_bps) / BPS)
    if already_referred:
        penalty += LIEN_REFERRAL_FEE_CENTS
    return penalty, months_past_due


# --- 8. payoff_quote_composition --------------------------------------------
def payoff_quote(principal_balance_cents, apr_bps, interest_accrual_from, closing_date):
    principal = int(principal_balance_cents)
    days_accrued = (closing_date - interest_accrual_from).days
    accrued_interest = round_half_up(
        Decimal(principal)
        * Decimal(int(apr_bps))
        / BPS
        * Decimal(days_accrued)
        / Decimal(365)
    )
    admin_fee = PAYOFF_ADMIN_FEE_CENTS
    base = principal + accrued_interest + admin_fee
    if base < 1000000:
        premium_bps = 0
    elif base < 5000000:
        premium_bps = 200
    else:
        premium_bps = 350
    premium = round_half_up(Decimal(base) * Decimal(premium_bps) / BPS)
    return {
        "payoff_principal_cents": principal,
        "days_accrued": days_accrued,
        "accrued_interest_cents": accrued_interest,
        "payoff_admin_fee_cents": admin_fee,
        "base_payoff_cents": base,
        "prepayment_premium_bps": premium_bps,
        "prepayment_premium_cents": premium,
        "payoff_total_cents": base + premium,
    }


# --- 9. contractor_workmanship_score ---------------------------------------
def workmanship_score(deduction_severities):
    total = sum(SEVERITY_DEDUCTION_BPS.get(item, 0) for item in deduction_severities)
    score = 10000 - total
    return score if score > 0 else 0


# --- 11. rescission_window_expiry ------------------------------------------
def rescission_expiry(signed_at):
    """Three counted program business days after the signing date; the window
    closes at 00:00:00Z of the day after the third counted day."""
    cursor = signed_at.date()
    counted = 0
    while counted < 3:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() < 5 and cursor.isoformat() not in PROGRAM_HOLIDAYS:
            counted += 1
    expiry_day = cursor + timedelta(days=1)
    return datetime(expiry_day.year, expiry_day.month, expiry_day.day, tzinfo=timezone.utc)


def date_from_iso(text):
    if not text:
        return None
    return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
