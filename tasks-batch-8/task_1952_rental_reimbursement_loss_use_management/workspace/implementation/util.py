import re
import secrets
import string
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAX_RATE = Decimal("0.08")
DOCUMENTATION_FEE_CAP_CENTS = 2500
COMPLETION_GRACE_DAYS = 1
RETURN_GRACE_DAYS = 1


def parse_date(value):
    """Parse a strict YYYY-MM-DD calendar date. Returns date or None."""
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime(value):
    """Parse an ISO 8601 datetime; naive values are treated as UTC. Returns aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    t = value.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_ts(dt):
    """ISO 8601 UTC timestamp with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    return iso_ts(datetime.now(timezone.utc))


def request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(16))


def day_tax_cents(charge_cents):
    """Per-day tax: 8% rounded half up to a whole cent, applied before any summation."""
    return int((Decimal(charge_cents) * TAX_RATE).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
