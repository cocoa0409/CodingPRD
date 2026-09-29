"""Time, id and arithmetic helpers (PRD §2.4, §2.7)."""

import calendar
import random
import re
import string
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def new_id():
    """UUID identifier with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_dt():
    return datetime.now(timezone.utc)


def now_iso():
    return fmt_dt(now_dt())


def parse_datetime(value):
    """Parse an ISO 8601 datetime string. Returns aware UTC datetime or None."""
    if not isinstance(value, str) or not _DT_RE.match(value.strip()):
        return None
    raw = value.strip()
    txt = raw.replace(" ", "T").replace("t", "T")
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date string. Returns date or None."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def fmt_date(d):
    return d.isoformat() if d is not None else None


def utc_date(dt):
    return dt.astimezone(timezone.utc).date()


def round_half_up(value, places):
    """Half-up rounding (a value exactly on the half rounds away from zero)."""
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def round_half_up_int(value):
    return int(round_half_up(value, 0))


def floor_int(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_FLOOR))


def dec(value):
    """Exact Decimal from an int/float/str without binary float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def add_months(d, months):
    """Calendar-month add with the day clamped to the last day of the target month."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month = divmod(total, 12)
    month += 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last))


def whole_minutes(start_dt, end_dt):
    """Whole minutes between two instants, or None when not a whole number."""
    seconds = (end_dt - start_dt).total_seconds()
    if seconds != int(seconds):
        return None
    total = int(seconds)
    if total % 60 != 0:
        return None
    return total // 60


def num_out(value):
    """Serialise a Decimal/number for JSON without float artefacts."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value
