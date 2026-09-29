"""Shared primitives: decimal rounding, ISO-8601 handling, id generation."""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Decimal helpers
# ---------------------------------------------------------------------------

D0 = Decimal("0")


def dec(value):
    """Coerce a JSON number / string / Decimal into a Decimal."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise TypeError("bool is not a number")
    return Decimal(str(value))


def _q(places):
    return Decimal(1).scaleb(-places)


def round_half_up(value, places):
    """Round half up (away from zero at the midpoint) to `places` decimals."""
    if value is None:
        return None
    return dec(value).quantize(_q(places), rounding=ROUND_HALF_UP)


def r2(value):
    return round_half_up(value, 2)


def r3(value):
    return round_half_up(value, 3)


def r4(value):
    return round_half_up(value, 4)


def trunc_int(value):
    """Truncate toward zero to a whole number."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_DOWN))


def num(value, places=2):
    """Serialize a Decimal as a JSON number rounded to `places` decimals."""
    if value is None:
        return None
    q = round_half_up(value, places)
    return float(q)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt ]\d{2}:\d{2}(:\d{2})?(\.\d+)?"
    r"([Zz]|[+-]\d{2}:?\d{2})?$"
)


def parse_iso(value):
    """Parse an ISO-8601 instant into a tz-aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _ISO_RE.match(text):
        return None
    text = text.replace(" ", "T").replace("t", "T")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def fmt_iso(value):
    """ISO-8601 UTC with exactly three fractional digits."""
    if value is None:
        return None
    value = value.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year,
        value.month,
        value.day,
        value.hour,
        value.minute,
        value.second,
        value.microsecond // 1000,
    )


def minutes_between(start, end):
    """Length of [start, end) expressed in minutes as a Decimal."""
    seconds = Decimal(str((end - start).total_seconds()))
    return seconds / Decimal("60")


def month_start(when):
    return datetime(when.year, when.month, 1, tzinfo=UTC)


def next_month_start(when):
    if when.month == 12:
        return datetime(when.year + 1, 1, 1, tzinfo=UTC)
    return datetime(when.year, when.month + 1, 1, tzinfo=UTC)


def month_window(period):
    """[start, end) for a YYYY-MM period string."""
    year = int(period[0:4])
    month = int(period[5:7])
    start = datetime(year, month, 1, tzinfo=UTC)
    return start, next_month_start(start)


QUARTER_MONTHS = {
    1: (1, 3),
    2: (4, 6),
    3: (7, 9),
    4: (10, 12),
}


def quarter_window(period):
    """[start, end) for a YYYY-Qn period string."""
    year = int(period[0:4])
    quarter = int(period[6])
    first, last = QUARTER_MONTHS[quarter]
    start = datetime(year, first, 1, tzinfo=UTC)
    if last == 12:
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
    else:
        end = datetime(year, last + 1, 1, tzinfo=UTC)
    return start, end


def month_in_quarter(month_period, quarter_period):
    """True when a YYYY-MM month falls inside a YYYY-Qn quarter."""
    try:
        m_start, _ = month_window(month_period)
    except (ValueError, IndexError):
        return False
    try:
        q_start, q_end = quarter_window(quarter_period)
    except (ValueError, IndexError, KeyError):
        return False
    return q_start <= m_start < q_end


def add_minutes(when, minutes):
    return when + timedelta(minutes=float(minutes))


# ---------------------------------------------------------------------------
# Identity helpers
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))
