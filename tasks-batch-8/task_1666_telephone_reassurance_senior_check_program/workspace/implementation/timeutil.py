"""Logical-clock, ISO-8601 and HH:MM helpers."""
import re
from datetime import datetime, date, timezone, timedelta

from db import now

DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-]\d{2}:?\d{2})?$"
)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
HM_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")

WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(s):
    if not isinstance(s, str):
        return None
    m = DT_RE.match(s)
    if not m:
        return None
    y, mo, d, h, mi, se = (int(x) for x in m.groups()[:6])
    micro = 0
    if m.group(7):
        micro = int(m.group(7)[1:][:6].ljust(6, "0"))
    tzs = m.group(8)
    try:
        if tzs and tzs not in ("Z", "z"):
            sign = 1 if tzs[0] == "+" else -1
            tzd = tzs[1:].replace(":", "")
            tz = timezone(sign * timedelta(hours=int(tzd[:2]), minutes=int(tzd[2:])))
        else:
            tz = timezone.utc
        return datetime(y, mo, d, h, mi, se, micro, tzinfo=tz).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_month(s):
    if not isinstance(s, str):
        return None
    m = MONTH_RE.match(s)
    if not m:
        return None
    y, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12):
        return None
    return (y, mo)


def parse_hm(s):
    """HH:MM 24h -> minutes since midnight, or None."""
    if not isinstance(s, str):
        return None
    m = HM_RE.match(s)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2))


def fmt_hm(minutes):
    return "%02d:%02d" % (minutes // 60, minutes % 60)


def hm_valid(s):
    return parse_hm(s) is not None


def iso_week_key(d):
    iso = d.isocalendar()
    return (iso[0], iso[1])


def weekday_of(d):
    return WEEKDAYS[d.weekday()]


def month_bounds(year, month):
    first = date(year, month, 1)
    if month == 12:
        nxt = date(year + 1, 1, 1)
    else:
        nxt = date(year, month + 1, 1)
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = datetime(nxt.year, nxt.month, 1, tzinfo=timezone.utc)
    return first, nxt, start, end


def today():
    return now().date()
