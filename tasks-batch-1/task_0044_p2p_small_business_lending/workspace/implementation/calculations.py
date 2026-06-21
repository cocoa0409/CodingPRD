"""Pure calculation routines (SCAFFOLD §1.3 / PRD §3).

All monetary quantities are integer cents. Fractional cents are rounded with
round-half-up via decimal.Decimal. Never use float for the rounded results.
"""
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR


def round_half_up(value, decimals=0):
    """Round value (number or Decimal) to the given number of decimals, round-half-up."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    quant = Decimal(1).scaleb(-decimals)  # e.g. decimals=0 -> Decimal('1'); 2 -> Decimal('0.01')
    return d.quantize(quant, rounding=ROUND_HALF_UP)


# --- score_borrower -----------------------------------------------------------

W_DSCR = Decimal("0.40")
W_STAB = Decimal("0.30")
W_NSF = Decimal("0.20")
W_AGE = Decimal("0.10")
DSCR_FULL_RATIO = Decimal("2.0")
NSF_PENALTY_PER_EVENT = Decimal("15.0")
AGE_FULL_MONTHS = Decimal("60")


def score_borrower(avg_monthly_revenue_cents, monthly_debt_payment_cents,
                   nsf_count_90d, account_age_months):
    """Return (credit_score Decimal rounded to 2 dp, risk_grade string)."""
    revenue = Decimal(avg_monthly_revenue_cents)
    debt = Decimal(monthly_debt_payment_cents)
    nsf = Decimal(nsf_count_90d)
    age = Decimal(account_age_months)

    if monthly_debt_payment_cents == 0:
        dscr = Decimal("3.0")
    else:
        dscr = revenue / debt

    dscr_sub = (dscr / DSCR_FULL_RATIO) * Decimal("100.0")
    if dscr_sub > Decimal("100.0"):
        dscr_sub = Decimal("100.0")

    if avg_monthly_revenue_cents >= 5000000:
        stability_sub = Decimal("100.0")
    elif avg_monthly_revenue_cents >= 2000000:
        stability_sub = Decimal("80.0")
    elif avg_monthly_revenue_cents >= 1000000:
        stability_sub = Decimal("60.0")
    elif avg_monthly_revenue_cents >= 500000:
        stability_sub = Decimal("40.0")
    else:
        stability_sub = Decimal("20.0")

    nsf_sub = Decimal("100.0") - nsf * NSF_PENALTY_PER_EVENT
    if nsf_sub < Decimal("0.0"):
        nsf_sub = Decimal("0.0")

    age_sub = (age / AGE_FULL_MONTHS) * Decimal("100.0")
    if age_sub > Decimal("100.0"):
        age_sub = Decimal("100.0")

    raw = dscr_sub * W_DSCR + stability_sub * W_STAB + nsf_sub * W_NSF + age_sub * W_AGE
    credit_score = round_half_up(raw, 2)

    risk_grade = grade_for_score(credit_score)
    return credit_score, risk_grade


def grade_for_score(credit_score):
    cs = credit_score if isinstance(credit_score, Decimal) else Decimal(str(credit_score))
    if cs >= Decimal("85"):
        return "A"
    if cs >= Decimal("70"):
        return "B"
    if cs >= Decimal("55"):
        return "C"
    if cs >= Decimal("40"):
        return "D"
    return "F"


# --- apr_for_grade ------------------------------------------------------------

APR_BY_GRADE = {
    "A": Decimal("0.0599"),
    "B": Decimal("0.0899"),
    "C": Decimal("0.1299"),
    "D": Decimal("0.1799"),
    "F": None,
}


def apr_for_grade(risk_grade):
    return APR_BY_GRADE.get(risk_grade)


# --- amortization_schedule ----------------------------------------------------

def amortization_schedule(principal_cents, apr, term_months):
    """Return (level_payment_cents int, periods list).

    apr is a Decimal fraction (or None — only when grade F, but loans never
    originate from F, so apr is always a real fraction here).
    periods: list of dicts {period_index, interest_due_cents, principal_due_cents, payment_cents}.
    """
    principal = Decimal(principal_cents)
    rate = (apr if isinstance(apr, Decimal) else Decimal(str(apr))) / Decimal(12)

    if rate == 0:
        level_raw = principal / Decimal(term_months)
    else:
        one_plus = Decimal(1) + rate
        factor = one_plus ** term_months
        level_raw = principal * (rate * factor) / (factor - Decimal(1))

    level_payment_cents = int(round_half_up(level_raw, 0))

    periods = []
    balance = int(principal_cents)
    for m in range(1, term_months + 1):
        interest_due = int(round_half_up(Decimal(balance) * rate, 0))
        if m < term_months:
            principal_due = level_payment_cents - interest_due
            payment = level_payment_cents
        else:
            principal_due = balance
            payment = principal_due + interest_due
        periods.append({
            "period_index": m,
            "interest_due_cents": interest_due,
            "principal_due_cents": principal_due,
            "payment_cents": payment,
        })
        balance = balance - principal_due

    return level_payment_cents, periods


# --- compute_servicing_fee ----------------------------------------------------

SERVICING_FEE_PCT = Decimal("0.01")


def compute_servicing_fee(interest_bucket_cents):
    """Return (platform_fee_cents, net_interest_to_investors_cents)."""
    fee = int(round_half_up(Decimal(interest_bucket_cents) * SERVICING_FEE_PCT, 0))
    net = interest_bucket_cents - fee
    return fee, net


# --- compute_late_fee ---------------------------------------------------------

LATE_FEE_PCT = Decimal("0.05")
LATE_FEE_FLOOR_CENTS = 2500


def compute_late_fee(level_payment_cents):
    pct_part = int(round_half_up(Decimal(level_payment_cents) * LATE_FEE_PCT, 0))
    return max(LATE_FEE_FLOOR_CENTS, pct_part)


# --- largest-remainder distribution -------------------------------------------

def distribute_largest_remainder(bucket_cents, weights):
    """Distribute bucket_cents across recipients by weight using the
    largest-remainder method.

    weights: list of (key, weight_cents, tiebreak_seq) tuples. The raw share is
    bucket_cents * weight / total_weight. Each recipient receives floor(raw);
    leftover cents are handed out one each, ranked by fractional part DESC then
    tiebreak_seq ASC.

    Returns {key: amount_cents}. If total weight is 0 or bucket is 0, every
    recipient gets 0.
    """
    result = {key: 0 for (key, _w, _t) in weights}
    if bucket_cents <= 0:
        return result
    total_weight = sum(w for (_k, w, _t) in weights)
    if total_weight <= 0:
        return result

    bucket = Decimal(bucket_cents)
    total = Decimal(total_weight)

    floors = {}
    fracs = []
    allocated = 0
    for (key, weight, tiebreak) in weights:
        raw = bucket * Decimal(weight) / total
        fl = int(raw.to_integral_value(rounding=ROUND_FLOOR))
        floors[key] = fl
        allocated += fl
        frac = raw - Decimal(fl)
        fracs.append((key, frac, tiebreak))

    remainder = bucket_cents - allocated
    # Rank by fractional part DESC, then tiebreak (creation sequence) ASC.
    fracs.sort(key=lambda t: (-t[1], t[2]))
    for i in range(remainder):
        key = fracs[i][0]
        floors[key] += 1

    return floors
