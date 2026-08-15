"""Time helpers, money rounding, interval overlap, recurrence expansion.

All deadline/expiry/window rules read the server logical clock (db.CLOCK_NOW) —
never the host wall clock. Timestamps are ISO 8601 UTC with three fractional
digits. Money is integer cents with ROUND_HALF_UP at the pinned steps only.
"""
import math
import re
from datetime import datetime, timedelta, timezone, time as dtime
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

import db

DEFAULT_TZ = "America/Los_Angeles"

# Open-ended windows (e.g., a policy's null effective_to) compare as +infinity.
FAR_FUTURE = datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone.utc)

DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def iso_z(dt):
    """Format an aware UTC datetime as ISO 8601 with exactly 3 fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"


def clock_now():
    return db.CLOCK_NOW


def clock_iso():
    return iso_z(db.CLOCK_NOW)


def parse_iso(value):
    """Parse an ISO 8601 datetime to an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str) or not DATETIME_RE.match(value.strip()):
        raise ValueError("not an ISO 8601 datetime")
    s = value.strip().replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def try_parse_iso(value):
    try:
        return parse_iso(value)
    except (ValueError, TypeError):
        return None


def tz_for_site(site):
    name = (site or {}).get("rental_timezone") or DEFAULT_TZ
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo(DEFAULT_TZ)


def overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: each begins strictly before the other ends."""
    return a_start < b_end and b_start < a_end


def round_half_up_cents(value):
    """Round a Decimal/float/int monetary value to integer cents, half-up."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hours_2dp(td):
    """Express a timedelta in hours carried to two decimal places (half-up)."""
    d = Decimal(str(td.total_seconds())) / Decimal("3600")
    return float(d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def site_local_date(dt, tz):
    return dt.astimezone(tz).date()


def whole_days_between(earlier, later, tz):
    """Whole calendar days between two instants, on site-local dates."""
    return (site_local_date(later, tz) - site_local_date(earlier, tz)).days


def compute_wo_flags(scheduled_start, scheduled_end, tz):
    """after_hours: any minute of [start, end) outside 07:00-18:00 Mon-Fri local.
    weekend: any minute on Sat/Sun local. Both may be true at once."""
    after_hours = False
    weekend = False
    t = scheduled_start
    while t < scheduled_end:
        local = t.astimezone(tz)
        wd = local.weekday()  # Mon=0 .. Sun=6
        if wd >= 5:
            weekend = True
            after_hours = True  # Sat/Sun is outside the Mon-Fri business window
        else:
            lt = local.time()
            if lt < dtime(7, 0) or lt >= dtime(18, 0):
                after_hours = True
        if after_hours and weekend:
            break
        t += timedelta(minutes=1)
    return after_hours, weekend


WEEKDAYS = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}

RECURRENCE_RE = re.compile(
    r"^WEEKLY:(MON|TUE|WED|THU|FRI|SAT|SUN):(\d{2}):(\d{2})-(\d{2}):(\d{2})$"
)


def parse_recurrence(rule):
    """'WEEKLY:SAT:18:00-21:00' -> (weekday, start_time, end_time) or None."""
    if not isinstance(rule, str):
        return None
    m = RECURRENCE_RE.match(rule.strip())
    if not m:
        return None
    wd = WEEKDAYS[m.group(1)]
    sh, sm, eh, em = (int(m.group(i)) for i in range(2, 6))
    if sh > 23 or eh > 23 or sm > 59 or em > 59:
        return None
    start_t = dtime(sh, sm)
    end_t = dtime(eh, em)
    if end_t <= start_t:
        return None
    return wd, start_t, end_t


def expand_occurrences(rule, season_start, season_end, tz):
    """Expand a weekly recurrence across [season_start, season_end] (inclusive
    local dates) in chronological order. Returns [(start_utc, end_utc), ...]."""
    parsed = parse_recurrence(rule)
    if parsed is None:
        return None
    wd, start_t, end_t = parsed
    start_date = season_start.astimezone(tz).date()
    end_date = season_end.astimezone(tz).date()
    out = []
    d = start_date
    while d <= end_date:
        if d.weekday() == wd:
            occ_start = datetime.combine(d, start_t, tzinfo=tz).astimezone(timezone.utc)
            occ_end = datetime.combine(d, end_t, tzinfo=tz).astimezone(timezone.utc)
            out.append((occ_start, occ_end))
        d += timedelta(days=1)
    return out


def ceil_div_30(minutes):
    """Whole 30-minute blocks, any partial block rounding up."""
    return int(math.ceil(minutes / 30.0))
