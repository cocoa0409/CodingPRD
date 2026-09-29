"""Shared primitives: timestamps, decimal rounding, interval helpers."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc


# --- timestamps -------------------------------------------------------------

def format_dt(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.4)."""
    if value is None:
        return None
    value = value.astimezone(UTC)
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def parse_dt(raw):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def add_days(value, days):
    return value + timedelta(days=int(days))


# --- decimals ---------------------------------------------------------------

def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places=0):
    """round half up to `places` decimal places."""
    quant = Decimal(1) if places == 0 else Decimal(1).scaleb(-places)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def cents(value):
    """Round a money expression to whole cents, half up, returning an int."""
    return int(round_half_up(value, 0))


def pct(value):
    """Round a percentage to two decimal places, half up."""
    return round_half_up(value, 2)


# --- intervals --------------------------------------------------------------

def half_open_overlap(a_start, a_end, b_start, b_end):
    """[a_start, a_end) intersects [b_start, b_end)?"""
    return a_start < b_end and b_start < a_end


def closed_contains(start, end, moment):
    return start <= moment <= end


def half_open_contains(start, end, moment):
    return start <= moment < end


def band_overlap(a_min, a_max, b_min, b_max):
    """Half-open case-volume bands; None means unbounded above."""
    a_hi = a_max if a_max is not None else float("inf")
    b_hi = b_max if b_max is not None else float("inf")
    return a_min < b_hi and b_min < a_hi
