"""Monetary, scheduling, and scoring calculations.

All money is in integer USD cents. We use Decimal + ROUND_HALF_UP for the
per-component half-up rounding the PRD pins (§2.8).
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    from backports.zoneinfo import ZoneInfo  # type: ignore


TAX_BPS = 875                # 8.75%
SHADOW_PACKAGE_RATE = 9000   # cents
DEFAULT_LIST_PRICE = 12000   # cents
SLOT_DURATION_MIN = 60
DAILY_CAP_MIN = 480
WEEKLY_CAP_MIN = 1800
REST_INTERVAL_MIN = 15


def round_half_up(amount) -> int:
    """Half-up rounding to the nearest integer cent."""
    if isinstance(amount, int):
        return amount
    if isinstance(amount, float):
        amount = Decimal(str(amount))
    if not isinstance(amount, Decimal):
        amount = Decimal(amount)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Settlement charge
# ---------------------------------------------------------------------------

def settlement_charge_breakdown(*, list_price_cents: int, payment_mode: str,
                                revenue_share_bps: int) -> dict:
    """Return the four-component breakdown for a CHARGE row."""
    lp = Decimal(int(list_price_cents))
    rs = Decimal(int(revenue_share_bps))
    if payment_mode == "PACKAGE":
        gross = 0
        tax = 0
        cs = round_half_up(Decimal(SHADOW_PACKAGE_RATE) * rs / Decimal(10000))
        ps = -cs
        return {
            "gross_amount_cents": gross,
            "tax_cents": tax,
            "counselor_share_cents": cs,
            "platform_share_cents": ps,
        }
    # PAY_PER_SESSION
    gross = int(list_price_cents)
    tax = round_half_up(lp * Decimal(TAX_BPS) / Decimal(10000))
    cs = round_half_up(lp * rs / Decimal(10000))
    ps = gross - cs
    return {
        "gross_amount_cents": gross,
        "tax_cents": tax,
        "counselor_share_cents": cs,
        "platform_share_cents": ps,
    }


# ---------------------------------------------------------------------------
# Refund
# ---------------------------------------------------------------------------

def appointment_refund(*, list_price_cents: int, revenue_share_bps: int,
                       cancellation_reason: str, hours_to_start: float) -> dict:
    """Return refund_state and four signed components (negative on REFUND row).

    Threshold rule:
      * COUNSELOR_CANCEL or CRISIS_HANDOVER -> FULL_REFUNDED
      * CLIENT_CANCEL: hours >= 24 -> FULL; >= 2 -> PARTIAL (50%); else NON_REFUNDABLE
    """
    lp = Decimal(int(list_price_cents))
    rs = Decimal(int(revenue_share_bps))

    if cancellation_reason in ("COUNSELOR_CANCEL", "CRISIS_HANDOVER"):
        refund_state = "FULL_REFUNDED"
        refund_gross = int(list_price_cents)
    elif cancellation_reason == "CLIENT_CANCEL":
        if hours_to_start >= 24:
            refund_state = "FULL_REFUNDED"
            refund_gross = int(list_price_cents)
        elif hours_to_start >= 2:
            refund_state = "PARTIAL_REFUNDED"
            refund_gross = round_half_up(lp * Decimal("0.50"))
        else:
            refund_state = "NON_REFUNDABLE"
            refund_gross = 0
    else:
        refund_state = "NON_REFUNDABLE"
        refund_gross = 0

    if refund_gross == 0:
        return {
            "refund_state": refund_state,
            "gross_amount_cents": 0,
            "tax_cents": 0,
            "counselor_share_cents": 0,
            "platform_share_cents": 0,
        }

    rg = Decimal(refund_gross)
    tax = round_half_up(rg * Decimal(TAX_BPS) / Decimal(10000))
    cs = round_half_up(rg * rs / Decimal(10000))
    ps = refund_gross - cs

    return {
        "refund_state": refund_state,
        # On the REFUND ledger row these are stored as negatives (caller flips signs)
        "gross_amount_cents": refund_gross,
        "tax_cents": tax,
        "counselor_share_cents": cs,
        "platform_share_cents": ps,
    }


def forward_refund_estimate(hours_to_start: float) -> str:
    """Strict > comparisons for forecast; PARTIAL at exactly 24.0 hours."""
    if hours_to_start > 24:
        return "FULL_REFUNDED"
    if hours_to_start > 2:
        return "PARTIAL_REFUNDED"
    return "NON_REFUNDABLE"


# ---------------------------------------------------------------------------
# Slot scheduling invariants
# ---------------------------------------------------------------------------

def overlaps_half_open(a_start: datetime, a_end: datetime,
                        b_start: datetime, b_end: datetime) -> bool:
    """Half-open interval overlap: [a_start, a_end) ∩ [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


def gap_minutes(slot_start: datetime, slot_end: datetime,
                proposed_start: datetime, proposed_end: datetime) -> int:
    """Return the absolute minutes between two non-overlapping intervals."""
    if proposed_start >= slot_end:
        delta = (proposed_start - slot_end).total_seconds() / 60
    elif slot_start >= proposed_end:
        delta = (slot_start - proposed_end).total_seconds() / 60
    else:
        return 0
    return int(round(delta))


def split_minutes_by_local_day(start_at: datetime, end_at: datetime,
                                tz_name: str) -> dict:
    """Split the (start, end) interval into local-day buckets.

    Returns: {date_str_in_local_tz: minutes}
    """
    tz = ZoneInfo(tz_name)
    local_start = start_at.astimezone(tz)
    local_end = end_at.astimezone(tz)
    buckets: dict = {}
    cursor = local_start
    while cursor < local_end:
        # Walk to the end of the local day or to local_end, whichever comes first
        next_midnight = (cursor.replace(hour=0, minute=0, second=0, microsecond=0)
                         + timedelta(days=1))
        chunk_end = min(next_midnight, local_end)
        date_key = cursor.date().isoformat()
        minutes = int((chunk_end - cursor).total_seconds() / 60)
        buckets[date_key] = buckets.get(date_key, 0) + minutes
        cursor = chunk_end
    return buckets


def iso_week_key(dt: datetime, tz_name: str) -> str:
    tz = ZoneInfo(tz_name)
    local = dt.astimezone(tz)
    iso = local.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def split_minutes_by_iso_week(start_at: datetime, end_at: datetime,
                              tz_name: str) -> dict:
    """Split (start, end) by ISO week, in counselor's tz, returning minutes per week."""
    tz = ZoneInfo(tz_name)
    local_start = start_at.astimezone(tz)
    local_end = end_at.astimezone(tz)
    buckets: dict = {}
    cursor = local_start
    while cursor < local_end:
        # End of current ISO week (next Monday 00:00 local time)
        weekday = cursor.isoweekday()  # Monday=1..Sunday=7
        days_until_monday = 8 - weekday  # if Mon -> 7
        next_week_start = (cursor.replace(hour=0, minute=0, second=0, microsecond=0)
                           + timedelta(days=days_until_monday))
        chunk_end = min(next_week_start, local_end)
        key = iso_week_key(cursor, tz_name)
        minutes = int((chunk_end - cursor).total_seconds() / 60)
        buckets[key] = buckets.get(key, 0) + minutes
        cursor = chunk_end
    return buckets


# ---------------------------------------------------------------------------
# Risk flag
# ---------------------------------------------------------------------------

def compute_risk_score(incidents: list, now_dt: datetime) -> int:
    """Score per PRD §3.7 over a 90-day lookback.

    incidents: list of crisis-incident dicts with parsed datetimes.
    Returns the integer score (used by callers to derive risk_flag).
    """
    lookback = now_dt - timedelta(days=90)
    relevant = []
    for inc in incidents:
        created_at = inc["_created_at_dt"]
        status = inc["status"]
        if status != "RESOLVED":
            if created_at >= lookback:
                relevant.append(inc)
        else:
            fc = inc.get("_follow_up_completed_at_dt")
            if fc is not None and fc >= lookback:
                relevant.append(inc)
    relevant.sort(key=lambda x: (x["_created_at_dt"], x["id"]))
    score = 0
    for inc in relevant:
        sev = inc.get("severity")
        if sev == "HIGH":
            score += 5
        elif sev == "MEDIUM":
            score += 3
        else:
            score += 1
        if inc.get("detection_source") == "COUNSELOR_TRIGGERED":
            score += 1
    return score


def risk_flag_for_score(score: int) -> str:
    if score >= 8:
        return "ACUTE"
    if score >= 4:
        return "ELEVATED"
    return "NONE"


def round_half_to_even(n: int) -> int:
    """Round an integer score to the nearest even integer with ties to even.

    Implementation: divide by 2, round half-to-even to integer, then multiply
    by 2.  For an integer N: N/2 has fractional part 0.0 (N even) or 0.5
    (N odd); ROUND_HALF_EVEN on 0.5 picks the even neighbour, so 1 -> 0,
    3 -> 4, 5 -> 4, 7 -> 8, etc.
    """
    half = Decimal(int(n)) / Decimal(2)
    rounded = int(half.quantize(Decimal("1"), rounding="ROUND_HALF_EVEN"))
    return rounded * 2
