from decimal import Decimal, ROUND_HALF_UP
from datetime import date


def round_half_up(numerator, denominator):
    """round_half_up(numerator / denominator) to nearest whole integer."""
    q = (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)


COMPLEXITY_BP = {"LOW": 10000, "MEDIUM": 11500, "HIGH": 13000}

TIER1_MAX = 500
TIER2_MAX = 1500
BASE_CENTS = 50000
RATE1_CENTS = 40
RATE2_CENTS = 30

MATCH_TOLERANCE_CENTS = 100
BLOCKING_PENALTY = 8


def parse_iso_date(s):
    y, m, d = s.split("-")
    return date(int(y), int(m), int(d))


def period_month_count(period_start, period_end):
    start = parse_iso_date(period_start)
    end = parse_iso_date(period_end)
    return (end.year - start.year) * 12 + (end.month - start.month) + 1


def scope_volume_estimate(month_count, monthly_txn_rate, complexity_tier):
    complexity_bp = COMPLEXITY_BP[complexity_tier]
    raw = month_count * monthly_txn_rate * complexity_bp
    return raw // 10000  # integer floor


def fixed_price_quote(estimated_txn_volume):
    vol = estimated_txn_volume
    if vol <= TIER1_MAX:
        return BASE_CENTS
    elif vol <= TIER2_MAX:
        return BASE_CENTS + (vol - TIER1_MAX) * RATE1_CENTS
    else:
        return (
            BASE_CENTS
            + (TIER2_MAX - TIER1_MAX) * RATE1_CENTS
            + (vol - TIER2_MAX) * RATE2_CENTS
        )


def phase_billing_split(fixed_price, phases_sorted):
    """phases_sorted: list of phase dicts ordered by phase_index ASC.
    Returns dict phase_id -> amount_cents."""
    result = {}
    running = 0
    for i, ph in enumerate(phases_sorted):
        if i < len(phases_sorted) - 1:
            amt = round_half_up(fixed_price * ph["weight_bp"], 10000)
            result[ph["id"]] = amt
            running += amt
        else:
            result[ph["id"]] = fixed_price - running
    return result


def readiness_score(reconciled_account_count, total_account_count, open_blocking_exception_count):
    if total_account_count == 0:
        base = 0
    else:
        base = (100 * reconciled_account_count) // total_account_count
    score = base - (open_blocking_exception_count * BLOCKING_PENALTY)
    return max(0, min(100, score))


def recon_difference(statement, account_book_balance):
    reconciled_bank = (
        statement["ending_balance_cents"]
        + statement["deposits_in_transit_cents"]
        - statement["outstanding_checks_cents"]
    )
    return reconciled_bank - account_book_balance


def service_proration(monthly_fee_cents, conversion_date):
    import calendar

    d = parse_iso_date(conversion_date)
    days_in_month = calendar.monthrange(d.year, d.month)[1]
    day = d.day
    remaining_days = days_in_month - day + 1
    return round_half_up(monthly_fee_cents * remaining_days, days_in_month)
