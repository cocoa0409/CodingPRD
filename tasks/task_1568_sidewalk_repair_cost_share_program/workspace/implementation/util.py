"""Shared low-level utilities: ids, timestamps, parsing, rounding."""
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Wall-clock UTC timestamp with exactly three fractional digits."""
    n = datetime.now(timezone.utc)
    return n.strftime('%Y-%m-%dT%H:%M:%S.') + f'{n.microsecond // 1000:03d}Z'


_FRAC_RE = re.compile(r'\.\d+')


def parse_dt(s):
    """Parse an ISO-8601 datetime string to an aware UTC datetime; None on failure."""
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip()
    if t.endswith(('Z', 'z')):
        t = t[:-1] + '+00:00'
    m = _FRAC_RE.search(t)
    if m and len(m.group(0)) > 7:  # more than 6 fractional digits -> truncate
        t = t[:m.start()] + m.group(0)[:7] + t[m.end():]
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a strict YYYY-MM-DD date string; None on failure."""
    if not isinstance(s, str):
        return None
    try:
        return datetime.strptime(s.strip(), '%Y-%m-%d').date()
    except ValueError:
        return None


def fmt_dt(dt):
    """Render a logical-clock datetime: no fraction when zero, else 3 digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}Z'
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')


def dec(x):
    """Exact Decimal from a JSON number."""
    return Decimal(str(x))


def rhu(d):
    """Round half-up to whole cents (integer)."""
    return int(Decimal(d).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def rhu1(d):
    """Round half-up to one decimal place (float)."""
    return float(Decimal(d).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def add_days(dt, days):
    return dt + timedelta(days=days)
