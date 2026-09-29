"""Low-level helpers: ids, timestamps, rounding discipline (PRD 2.4 / 2.5)."""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

UTC = timezone.utc

# --- identifiers ------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def new_id():
    """Server-minted UUID carrying no type prefix (PRD 2.4)."""
    return str(uuid.uuid4())


def new_request_id():
    """Request id for the response envelope; starts with `req_` (PRD 2.2)."""
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# --- timestamps -------------------------------------------------------------


def now_wall():
    return datetime.now(UTC)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.4)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value):
    """Parse an ISO 8601 instant. Returns an aware UTC datetime or raises ValueError."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a timestamp")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def days_between(a, b):
    """Whole elapsed days: floor((b - a) / 86400 seconds) on exact instants (PRD 2.4)."""
    if a is None or b is None:
        return 0
    delta = (b - a).total_seconds()
    return int(delta // 86400)


def plus_days(dt, days):
    return dt + timedelta(days=days)


def minus_days(dt, days):
    return dt - timedelta(days=days)


# --- rounding discipline (PRD 2.5) -----------------------------------------

ZERO = Decimal(0)
ONE = Decimal(1)
Q4 = Decimal("0.0001")


def dec(value):
    """Decimal from an int / float / str / Decimal without float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value):
    """Round a cent-valued real to the nearest whole cent, ties away from zero."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def rhu4(value):
    """Round a fraction half-up to exactly four decimal places."""
    return dec(value).quantize(Q4, rounding=ROUND_HALF_UP)


def jnum(value):
    """JSON representation of a stored fraction."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value
