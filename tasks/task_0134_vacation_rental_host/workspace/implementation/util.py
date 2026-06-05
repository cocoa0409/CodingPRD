"""Shared helpers: ids, timestamps, money rounding, date parsing."""
import random
import string
import uuid
from datetime import datetime, timezone, date
from decimal import Decimal, ROUND_HALF_UP

from errors import err


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """Request id starting with req_ (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def iso_now(dt):
    """Format a datetime as ISO 8601 UTC with three fractional digits (PRD §2.4)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_utc():
    return datetime.now(timezone.utc)


def round_half_up(value):
    """Round a Decimal/number to the nearest whole cent, half rounds up (PRD §2.5)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round to 2 decimal places, half rounds up (risk score, PRD §3.5)."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def parse_datetime(raw, error_id="ERR_INVALID_DATE_RANGE"):
    """Parse an ISO 8601 date or datetime. Raises the given error on malformed input."""
    if not isinstance(raw, str) or not raw.strip():
        raise err(error_id, "malformed date")
    s = raw.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Try plain date (YYYY-MM-DD)
        try:
            d = date.fromisoformat(raw.strip())
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        except ValueError:
            raise err(error_id, "malformed date")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_lenient(raw):
    """Parse an ISO instant for the clock; raises ERR_VALIDATION on failure."""
    return parse_datetime(raw, error_id="ERR_VALIDATION")


def date_only(dt):
    """Return the date() portion of a parsed datetime (calendar dates are day-granular)."""
    return dt.date()
