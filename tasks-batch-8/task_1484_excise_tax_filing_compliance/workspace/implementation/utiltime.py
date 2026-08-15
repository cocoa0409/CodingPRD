"""Logical-clock formatting/parsing, period-key arithmetic, rounding helpers."""
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from store import DB

MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")
QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


# ---------------------------------------------------------------- clock
def now_dt():
    return DB.clock


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z"""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    return fmt_dt(DB.clock)


def parse_dt(value):
    """Parse an ISO 8601 datetime (accepts trailing Z, offsets, fractional
    seconds, and date-only). Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------- rounding
def rhu(value):
    """Round half-up to whole cents (integer)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu_div_1000(millicents_product):
    """round_half_up(product_of_millicents / 1000) -> whole cents int."""
    return int((Decimal(millicents_product) / Decimal(1000)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------- periods
def valid_month_key(key):
    m = MONTH_RE.match(key) if isinstance(key, str) else None
    return bool(m) and 1 <= int(m.group(2)) <= 12


def valid_quarter_key(key):
    return bool(QUARTER_RE.match(key)) if isinstance(key, str) else False


def valid_period_key(key, frequency):
    if frequency == "MONTHLY":
        return valid_month_key(key)
    return valid_quarter_key(key)


def period_of_date(frequency, dt):
    if frequency == "MONTHLY":
        return f"{dt.year:04d}-{dt.month:02d}"
    q = (dt.month - 1) // 3 + 1
    return f"{dt.year:04d}-Q{q}"


def _add_months(year, month, delta):
    idx = (year * 12 + (month - 1)) + delta
    return idx // 12, idx % 12 + 1


def _last_day_of_month(year, month):
    ny, nm = _add_months(year, month, 1)
    return datetime(ny, nm, 1, tzinfo=timezone.utc) - timedelta(days=1)


def period_bounds(period, frequency):
    """Return (start_dt inclusive, end_dt inclusive date-at-midnight)."""
    if frequency == "MONTHLY":
        m = MONTH_RE.match(period)
        y, mo = int(m.group(1)), int(m.group(2))
        start = datetime(y, mo, 1, tzinfo=timezone.utc)
        end = _last_day_of_month(y, mo)
        return start, end
    m = QUARTER_RE.match(period)
    y, q = int(m.group(1)), int(m.group(2))
    start_month = (q - 1) * 3 + 1
    start = datetime(y, start_month, 1, tzinfo=timezone.utc)
    ey, em = _add_months(y, start_month, 2)
    end = _last_day_of_month(ey, em)
    return start, end


def period_end_exclusive(period, frequency):
    """First instant after the period."""
    _start, end = period_bounds(period, frequency)
    return end + timedelta(days=1)


def prev_period(period, frequency):
    if frequency == "MONTHLY":
        m = MONTH_RE.match(period)
        y, mo = _add_months(int(m.group(1)), int(m.group(2)), -1)
        return f"{y:04d}-{mo:02d}"
    m = QUARTER_RE.match(period)
    y, q = int(m.group(1)), int(m.group(2))
    if q == 1:
        return f"{y - 1:04d}-Q4"
    return f"{y:04d}-Q{q - 1}"


def period_month_buckets(period, frequency):
    """Month buckets (YYYY-MM) covered by a period key."""
    if frequency == "MONTHLY":
        return [period]
    m = QUARTER_RE.match(period)
    y, q = int(m.group(1)), int(m.group(2))
    start_month = (q - 1) * 3 + 1
    out = []
    for i in range(3):
        yy, mm = _add_months(y, start_month, i)
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def month_bucket_range(start_key, end_key):
    """Inclusive list of YYYY-MM buckets from start to end (assumes valid)."""
    sm = MONTH_RE.match(start_key)
    em = MONTH_RE.match(end_key)
    y, mo = int(sm.group(1)), int(sm.group(2))
    ey, emo = int(em.group(1)), int(em.group(2))
    out = []
    while (y, mo) <= (ey, emo):
        out.append(f"{y:04d}-{mo:02d}")
        y, mo = _add_months(y, mo, 1)
    return out


def month_bucket_index(key):
    m = MONTH_RE.match(key)
    return int(m.group(1)) * 12 + int(m.group(2))


# ---------------------------------------------------------------- date math
def due_date_for_return(period, frequency):
    """First day of month after period end + 24 days (25th of next month)."""
    _start, end = period_bounds(period, frequency)
    ny, nm = _add_months(end.year, end.month, 1)
    return datetime(ny, nm, 1, tzinfo=timezone.utc) + timedelta(days=24)


def add_years_safe(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return dt.replace(year=dt.year + years, day=28)


def add_days(dt, days):
    return dt + timedelta(days=days)


def months_ago(dt, months):
    y, m = _add_months(dt.year, dt.month, -months)
    day = min(dt.day, _last_day_of_month(y, m).day)
    return dt.replace(year=y, month=m, day=day)
