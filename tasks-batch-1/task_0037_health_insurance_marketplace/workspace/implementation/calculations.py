from decimal import Decimal, ROUND_HALF_UP
from datetime import date, timedelta
import calendar

FILING_THRESHOLD_CENTS = 1460000   # $14,600
FPL_BASE_CENTS = 1500000           # $15,000 for size 1
FPL_ADDL_CENTS = 530000            # +$5,300 per additional person
CAP_RATE = Decimal("0.085")
SEP_WINDOW_DAYS = 60
REGULAR_CUTOFF_DAY = 15


def round_half_up(value, places):
    """value: Decimal or number; places: number of decimal places."""
    q = Decimal(1).scaleb(-places)  # e.g. places=2 -> 0.01, places=0 -> 1
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def member_is_countable_income(member):
    return not (
        member["tax_filing_status"] == "DEPENDENT_NONFILER"
        and member["annual_income_cents"] < FILING_THRESHOLD_CENTS
    )


def compute_household_magi(members):
    """Returns (household_magi_cents, countable_size)."""
    magi = 0
    for m in members:
        if member_is_countable_income(m):
            magi += m["annual_income_cents"]
    countable_size = sum(1 for m in members if m.get("applies_for_coverage", True))
    return magi, countable_size


def fpl_annual_cents(countable_size):
    if countable_size <= 0:
        return 0
    return FPL_BASE_CENTS + FPL_ADDL_CENTS * (countable_size - 1)


def compute_fpl_percent(household_magi_cents, countable_size):
    if countable_size == 0:
        return Decimal("0.00")
    fpl_annual = fpl_annual_cents(countable_size)
    pct = Decimal(household_magi_cents) / Decimal(fpl_annual) * Decimal(100)
    return round_half_up(pct, 2)


def applicable_percentage(fpl_percent):
    """fpl_percent: Decimal. Returns Decimal rounded to 6 dp."""
    p = Decimal(fpl_percent)
    if p <= Decimal("150.0"):
        ap = Decimal("0.0")
    elif p <= Decimal("200.0"):
        ap = Decimal("0.0") + (p - 150) / (200 - 150) * (Decimal("0.02") - Decimal("0.0"))
    elif p <= Decimal("250.0"):
        ap = Decimal("0.02") + (p - 200) / (250 - 200) * (Decimal("0.04") - Decimal("0.02"))
    elif p <= Decimal("300.0"):
        ap = Decimal("0.04") + (p - 250) / (300 - 250) * (Decimal("0.06") - Decimal("0.04"))
    elif p <= Decimal("400.0"):
        ap = Decimal("0.06") + (p - 300) / (400 - 300) * (Decimal("0.085") - Decimal("0.06"))
    else:
        ap = CAP_RATE
    return round_half_up(ap, 6)


def compute_max_aptc(household_magi_cents, applicable_pct, benchmark_cents):
    monthly_contribution = round_half_up(
        Decimal(household_magi_cents) * Decimal(applicable_pct) / Decimal(12), 0
    )
    max_aptc = max(Decimal(0), Decimal(benchmark_cents) - monthly_contribution)
    return int(max_aptc)


def compute_csr_tier(fpl_percent):
    p = Decimal(fpl_percent)
    if Decimal("100.0") <= p <= Decimal("150.0"):
        return "CSR94"
    elif p <= Decimal("200.0"):
        return "CSR87"
    elif p <= Decimal("250.0"):
        return "CSR73"
    else:
        return "NONE"


def compute_sep_window_close(event_date_str):
    d = date.fromisoformat(event_date_str)
    close = d + timedelta(days=SEP_WINDOW_DAYS)
    return close.isoformat()


def compute_applied_aptc(elected, max_aptc, gross_premium):
    return min(elected, max_aptc, gross_premium)


def _first_of_following_month(d):
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def _add_one_month(d):
    # d is a first-of-month date here
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    return date(d.year, d.month + 1, 1)


def compute_effective_date(submitted_at_date, enrollment_window, sep_event_type, sep_event_date):
    """submitted_at_date: date (UTC date portion). Returns YYYY-MM-DD string."""
    sub = submitted_at_date
    if enrollment_window == "OEP":
        return _first_of_following_month(sub).isoformat()
    # SEP
    ev = sep_event_type
    if ev in ("BIRTH", "ADOPTION"):
        return sep_event_date  # retroactive to event date (already YYYY-MM-DD)
    elif ev in ("MARRIAGE", "PERMANENT_MOVE"):
        return _first_of_following_month(sub).isoformat()
    elif ev == "LOSS_OF_COVERAGE":
        base = _first_of_following_month(sub)
        if sub.day <= REGULAR_CUTOFF_DAY:
            return base.isoformat()
        else:
            return _add_one_month(base).isoformat()
    # fallback (should not happen)
    return _first_of_following_month(sub).isoformat()


def compute_first_month_proration(net_premium_cents, effective_date_str):
    d = date.fromisoformat(effective_date_str)
    eff_day = d.day
    if eff_day == 1:
        return net_premium_cents
    days_in_month = calendar.monthrange(d.year, d.month)[1]
    cov_days = days_in_month - eff_day + 1
    daily = Decimal(net_premium_cents) / Decimal(days_in_month)
    return int(round_half_up(daily * Decimal(cov_days), 0))


def compute_reconciliation(applied_aptc_monthly, months_enrolled,
                           actual_annual_magi_cents, countable_size, benchmark_cents):
    advanced_total = applied_aptc_monthly * months_enrolled

    actual_fpl = compute_fpl_percent(actual_annual_magi_cents, countable_size)
    actual_ap = applicable_percentage(actual_fpl)
    actual_monthly_contribution = round_half_up(
        Decimal(actual_annual_magi_cents) * Decimal(actual_ap) / Decimal(12), 0
    )
    allowed_monthly = max(Decimal(0), Decimal(benchmark_cents) - actual_monthly_contribution)
    allowed_total = int(allowed_monthly) * months_enrolled
    settlement = advanced_total - allowed_total
    return advanced_total, allowed_total, settlement
