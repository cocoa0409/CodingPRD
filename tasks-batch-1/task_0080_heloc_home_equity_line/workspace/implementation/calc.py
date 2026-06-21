"""Core financial calculations: interest accrual, covenant metrics, waterfall,
annual fee, early-closure fee. All money in integer cents, rates in bps."""
from decimal import Decimal, ROUND_HALF_UP

from store import db, parse_iso

DAY_COUNT_BASIS = 365
BPS_SCALE = 10000


def round_half_up(value):
    """Round a numeric (Decimal/int/float) to an integer, half away from zero (up)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def active_prime():
    """Return the active (non-superseded) PRIME IndexRate, or None."""
    candidates = [
        r for r in db.index_rates.values()
        if r["index_name"] == "PRIME" and not r["superseded"]
    ]
    if not candidates:
        return None
    # If multiple, pick the latest effective_date
    return max(candidates, key=lambda r: parse_iso(r["effective_date"]))


def compute_apr_bps(heloc):
    """current_apr_bps = min(active PRIME.rate_bps + margin_bps, rate_ceiling_bps)."""
    prime = active_prime()
    if prime is None:
        return heloc.get("current_apr_bps", 0)
    return min(prime["rate_bps"] + heloc["margin_bps"], heloc["rate_ceiling_bps"])


def daily_rate(apr_bps):
    """Daily rate as a Decimal fraction."""
    return Decimal(apr_bps) / Decimal(BPS_SCALE) / Decimal(DAY_COUNT_BASIS)


def days_between(start_dt, end_dt):
    """Whole days between two aware datetimes (end - start), can be fractional->use total seconds/86400."""
    delta = end_dt - start_dt
    return delta.total_seconds() / 86400.0


def chronological_accrued(heloc, as_of_dt):
    """Replay the ledger chronologically and return accrued interest cents
    from the last-payment anchor up to as_of_dt.

    Events: BOOKED draws (excluded if REVERSED) keyed by requested_at, and
    payments with posted_at <= as_of keyed by posted_at. Ordered by event_ts
    ASC then created_at ASC. Draw raises running principal at requested_at.
    Payment interest portion reduces accrued at posted_at.

    The accrued figure is measured "from the last-payment anchor": i.e. the
    accumulator is reset (interest applied is subtracted) at each payment, and
    we report the residual accrued after the last payment up to as_of.
    """
    apr = heloc.get("current_apr_bps", 0)
    rate = daily_rate(apr)
    heloc_id = heloc["id"]

    events = []
    for d in db.draws.values():
        if d["heloc_id"] != heloc_id:
            continue
        if d["status"] != "BOOKED":
            continue
        ts = parse_iso(d["requested_at"])
        if ts <= as_of_dt:
            events.append((ts, parse_iso(d["created_at"]), "draw", d))
    for p in db.payments.values():
        if p["heloc_id"] != heloc_id:
            continue
        ts = parse_iso(p["posted_at"])
        if ts <= as_of_dt:
            events.append((ts, parse_iso(p["created_at"]), "payment", p))

    events.sort(key=lambda e: (e[0], e[1]))

    running_principal = 0
    accrued = 0
    cursor = None  # current time position

    for ts, _created, kind, obj in events:
        if cursor is not None and ts > cursor:
            days = days_between(cursor, ts)
            if days > 0 and running_principal > 0:
                seg = round_half_up(Decimal(running_principal) * rate * Decimal(str(days)))
                accrued += seg
        cursor = ts if cursor is None else max(cursor, ts)
        if kind == "draw":
            running_principal += obj["amount_cents"]
        else:  # payment
            running_principal -= obj["principal_applied_cents"]
            accrued -= obj["interest_applied_cents"]
            if accrued < 0:
                accrued = 0

    # Final segment from last event/cursor to as_of
    if cursor is not None and as_of_dt > cursor:
        days = days_between(cursor, as_of_dt)
        if days > 0 and running_principal > 0:
            seg = round_half_up(Decimal(running_principal) * rate * Decimal(str(days)))
            accrued += seg

    if accrued < 0:
        accrued = 0
    return accrued


def forward_projected_interest(heloc, as_of_dt):
    """Single forward segment on current_balance_cents from now to as_of."""
    apr = heloc.get("current_apr_bps", 0)
    rate = daily_rate(apr)
    now = db.current_utc
    if as_of_dt <= now:
        return 0
    days = days_between(now, as_of_dt)
    if days <= 0:
        return 0
    principal = heloc.get("current_balance_cents", 0)
    if principal <= 0:
        return 0
    return round_half_up(Decimal(principal) * rate * Decimal(str(days)))


def cltv_bps(heloc, prop):
    numer = (prop["senior_lien_balance_cents"] + heloc["current_balance_cents"]) * BPS_SCALE
    return round_half_up(Decimal(numer) / Decimal(prop["appraised_value_cents"]))


def dscr_bps(heloc, borrower):
    annual_interest = round_half_up(
        Decimal(heloc["current_balance_cents"]) * Decimal(heloc["current_apr_bps"]) / Decimal(BPS_SCALE)
    )
    annual_debt_service = borrower["monthly_debt_obligation_cents"] * 12 + annual_interest
    if annual_debt_service <= 0:
        return None
    return round_half_up(Decimal(borrower["annual_income_cents"]) * BPS_SCALE / Decimal(annual_debt_service))


def covenant_breached(covenant, heloc, prop, borrower):
    """True if the covenant metric crosses its threshold (breach direction)."""
    ctype = covenant["covenant_type"]
    threshold = covenant["threshold_value"]
    if ctype == "MAX_CLTV":
        return cltv_bps(heloc, prop) > threshold
    if ctype == "MIN_DSCR":
        d = dscr_bps(heloc, borrower)
        if d is None:
            return False
        return d < threshold
    if ctype == "MAX_DELINQUENCY_DAYS":
        return heloc["delinquency_days"] > threshold
    return False


def covenant_observed_value(covenant, heloc, prop, borrower):
    ctype = covenant["covenant_type"]
    if ctype == "MAX_CLTV":
        return cltv_bps(heloc, prop)
    if ctype == "MIN_DSCR":
        d = dscr_bps(heloc, borrower)
        return d if d is not None else 0
    if ctype == "MAX_DELINQUENCY_DAYS":
        return heloc["delinquency_days"]
    return 0


def draw_period_end(heloc):
    """origination_date + draw_period_years, using 365-day years."""
    from datetime import timedelta
    orig = parse_iso(heloc["origination_date"])
    return orig + timedelta(days=DAY_COUNT_BASIS * heloc["draw_period_years"])


def early_closure_fee(heloc, clock):
    """Tiered prepayment penalty in cents. clock is aware datetime."""
    draw_end = draw_period_end(heloc)
    if clock >= draw_end:
        return 0
    days_remaining = days_between(clock, draw_end)
    years_remaining = _ceil_years(days_remaining)
    if years_remaining >= 8:
        tier_bps = 200
    elif 4 <= years_remaining <= 7:
        tier_bps = 100
    elif 1 <= years_remaining <= 3:
        tier_bps = 50
    else:
        tier_bps = 0
    if tier_bps == 0:
        return 0
    return round_half_up(Decimal(heloc["credit_limit_cents"]) * tier_bps / Decimal(BPS_SCALE))


def _ceil_years(days):
    """ceil(days / 365) as integer."""
    import math
    return math.ceil(days / 365.0)
