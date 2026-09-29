"""Timestamp formatting, ISO parsing and rounding discipline (PRD §2.4 / §2.6)."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


# --------------------------------------------------------------- timestamps ---
def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def real_now_iso():
    return fmt_dt(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def month_of(dt):
    """YYYY-MM label of an instant."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d" % (dt.year, dt.month)


def add_years(dt, years):
    """Calendar-year addition; a 29-February base clamps back to 28 February."""
    target_year = dt.year + years
    try:
        return dt.replace(year=target_year)
    except ValueError:
        return dt.replace(year=target_year, month=2, day=28)


# ----------------------------------------------------------------- rounding ---
def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def pct_half_up(numerator, denominator):
    """100 * numerator / denominator rounded half up to two decimals."""
    if denominator == 0:
        return Decimal("0.00")
    return round_half_up(Decimal(100) * Decimal(numerator) / Decimal(denominator), 2)


def as_pct(value):
    """Serialise a two-decimal percentage."""
    return float(Decimal(value).quantize(Decimal("0.01")))


def to_decimal(value):
    return Decimal(str(value))


def ceil_div(numerator, denominator):
    """Integer ceiling division that also handles negative numerators."""
    return -((-numerator) // denominator)


def floor_div(numerator, denominator):
    return numerator // denominator
