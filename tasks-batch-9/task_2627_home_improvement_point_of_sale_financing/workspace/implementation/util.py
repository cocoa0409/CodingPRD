"""Pure helpers: exact integer rounding, date/instant formatting, month math."""
import calendar
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INSTANT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def rhu(num, den):
    """round_half_up(num/den) on exact integers; ties go away from zero."""
    num = int(num)
    den = int(den)
    if den == 0:
        raise ZeroDivisionError("round_half_up by zero")
    if den < 0:
        num, den = -num, -den
    if num >= 0:
        return (2 * num + den) // (2 * den)
    return -((-2 * num + den) // (2 * den))


def fmt_dt(dt):
    """ISO 8601 UTC instant with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    return d.isoformat()


def parse_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def parse_instant(s):
    if not isinstance(s, str) or not INSTANT_RE.match(s):
        return None
    try:
        return datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S.%f%z") \
            if "." in s else datetime.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None


def add_months(d, n):
    n = int(n)
    total = (d.year * 12) + (d.month - 1) + n
    y = total // 12
    m = total % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return date(y, m, day)


def whole_months_between(start, end):
    """Largest n >= 0 such that add_months(start, n) <= end (0 when end < start)."""
    if end < start:
        return 0
    n = 0
    while n < 2400 and add_months(start, n + 1) <= end:
        n += 1
    return n


def days_between(a, b):
    return (b - a).days


def midnight(d):
    return datetime(d.year, d.month, d.day, tzinfo=UTC)
