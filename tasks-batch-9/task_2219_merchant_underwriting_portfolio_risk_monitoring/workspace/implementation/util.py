"""Low-level helpers: ids, timestamps, date arithmetic and rounding discipline.

PRD 2.5: money is integer cents, rates are integer basis points, rounding is
half up and happens only where the document says it happens.
"""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def new_id():
    """Server-minted UUID with no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_ts():
    return iso_ts(datetime.now(timezone.utc))


def parse_dt(value):
    """Parse an ISO 8601 instant. Raises ValueError on malformed input."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict YYYY-MM-DD date. Raises ValueError on malformed input."""
    if not isinstance(value, str) or not ISO_DATE_RE.match(value.strip()):
        raise ValueError("malformed date")
    return date.fromisoformat(value.strip())


def fmt_date(d):
    return d.isoformat()


def date_plus(date_str, days):
    return fmt_date(parse_date(date_str) + timedelta(days=days))


def date_minus(date_str, days):
    return fmt_date(parse_date(date_str) - timedelta(days=days))


def days_between(a_str, b_str):
    """b - a in whole calendar days."""
    return (parse_date(b_str) - parse_date(a_str)).days


def rhu_div(numerator, denominator):
    """round_half_up(numerator / denominator) with exact integer arithmetic.

    Only ever called with a non-negative numerator and a positive denominator in
    this domain, which makes (2n + d) // (2d) an exact half-up rounding.
    """
    numerator = int(numerator)
    denominator = int(denominator)
    if denominator == 0:
        raise ZeroDivisionError
    if numerator >= 0:
        return (2 * numerator + denominator) // (2 * denominator)
    # Symmetric fallback (unused by the specified formulas).
    return -((2 * (-numerator) + denominator) // (2 * denominator))


def ceil_div(numerator, denominator):
    """Round the quotient UP to the next whole number."""
    return -((-int(numerator)) // int(denominator))
