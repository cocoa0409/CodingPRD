"""ISO 8601 parsing / formatting helpers.

All instants handled by the service are UTC.  Server generated timestamps are
rendered with exactly three fractional digits, per PRD section 2.4.
"""
import re
from datetime import datetime, date, timedelta

_DT_RE = re.compile(
    r'^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?'
    r'(?:[.,](\d{1,9}))?(Z|z|[+-]\d{2}:?\d{2})?$'
)
_DATE_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})$')


def parse_datetime(value):
    """Parse an ISO 8601 UTC instant.  Returns a naive UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second, frac, offset = m.groups()
    try:
        micro = int((frac or '0').ljust(6, '0')[:6])
        dt = datetime(int(year), int(month), int(day), int(hour), int(minute),
                      int(second or 0), micro)
    except ValueError:
        return None
    if offset and offset not in ('Z', 'z'):
        sign = 1 if offset[0] == '+' else -1
        digits = offset[1:].replace(':', '')
        try:
            delta = timedelta(hours=int(digits[:2]), minutes=int(digits[2:4]))
        except ValueError:
            return None
        dt = dt - sign * delta
    return dt


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  Returns a date or None."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_datetime(dt):
    """Render a naive UTC datetime as ISO 8601 with three fractional digits."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def fmt_date(d):
    return d.strftime('%Y-%m-%d')


def utc_now():
    return datetime.utcnow()
