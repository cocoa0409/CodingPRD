"""Time / numeric helpers shared across the implementation."""

import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    # normalise fractional second digit counts that fromisoformat rejects
    m = re.match(r"^(.*?\.)(\d+)(.*)$", text)
    if m and len(m.group(2)) not in (3, 6):
        frac = (m.group(2) + "000000")[:6]
        text = m.group(1) + frac + m.group(3)
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date; returns None when unparseable."""
    if not isinstance(value, str) or not DATE_RE.match(value.strip()):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def whole_minutes(start, end):
    """Whole minutes between two instants, truncated toward zero."""
    return int(math.trunc((end - start).total_seconds() / 60.0))


def add_days(dt, days):
    return dt + timedelta(days=days)


def dec(value):
    """Exact Decimal for a JSON-sourced number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    """Half-up rounding to `places` decimal places, returned as a Decimal."""
    quantum = Decimal(1).scaleb(-places)
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def num(value):
    """Render a Decimal for JSON as a float (never a string)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def ceil_div(a, b):
    return -((-a) // b)
