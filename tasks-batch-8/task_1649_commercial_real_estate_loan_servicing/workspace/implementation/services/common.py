"""Shared helpers: timestamps, decimal money math, date arithmetic, parsing."""
import calendar
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import db
import errors


def now_iso():
    return db.fmt_ts(db.get_clock())


def touch(entity):
    entity["updated_at"] = now_iso()
    entity["version"] += 1


def stamp_new(entity):
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1


def round_cents(value):
    """Round a Decimal/float to integer cents, round-half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_ratio_4dp(numerator, denominator):
    q = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(q)


def parse_dt(value, field="timestamp"):
    """Parse ISO 8601 datetime. Accepts trailing Z or offset; date-only treated as UTC midnight."""
    if not isinstance(value, str):
        raise errors.invalid_request(f"{field} must be an ISO 8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise errors.invalid_request(f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def days_between(later, earlier):
    """Whole days from earlier to later (floor of elapsed seconds / 86400)."""
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


def add_months_clamped(dt, months):
    """Add calendar months; clamp day to target month's last day."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    day = min(dt.day, last_day)
    return dt.replace(year=year, month=month, day=day)


def quarter_of(dt):
    """Return (qstart, qend) datetimes of the calendar quarter containing dt (UTC)."""
    q = (dt.month - 1) // 3
    start = datetime(dt.year, q * 3 + 1, 1, tzinfo=timezone.utc)
    end_month = q * 3 + 3
    last_day = calendar.monthrange(dt.year, end_month)[1]
    end = datetime(dt.year, end_month, last_day, 23, 59, 59, 999000, tzinfo=timezone.utc)
    return start, end


def is_full_quarter(period_start, period_end):
    """period must equal exactly one full calendar quarter [Qstart, Qend] inclusive."""
    qs, qe = quarter_of(period_start)
    # Compare at date granularity: quarter start 00:00:00, quarter end last day.
    ps_ok = (
        period_start.year == qs.year
        and period_start.month == qs.month
        and period_start.day == qs.day
        and period_start.hour == 0
        and period_start.minute == 0
        and period_start.second == 0
        and period_start.microsecond == 0
    )
    pe_ok = (
        period_end.year == qe.year
        and period_end.month == qe.month
        and period_end.day == qe.day
    )
    return ps_ok and pe_ok


def quarter_label(period_start):
    q = (period_start.month - 1) // 3 + 1
    return f"{period_start.year}Q{q}"


def months_between(later, earlier):
    """Whole months between two datetimes (approximation: 30.4375 days/month is NOT used;
    instead compute calendar month difference adjusted by day)."""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return months


def within_months(dt, ref, months):
    """True iff dt is within `months` calendar months before ref (dt >= ref - months)."""
    return dt >= add_months_clamped(ref, -months)
