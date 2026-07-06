"""Shared helpers: id/timestamp minting, ISO8601 parse/format, half-up rounding."""
import uuid
import secrets
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ERR_INVALID_REQUEST


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def new_gate_code():
    """A scan token distinct from the id (PRD §3.4)."""
    alphabet = string.ascii_uppercase + string.digits
    return "GATE-" + "".join(secrets.choice(alphabet) for _ in range(16))


def new_request_id():
    """Request id starting with req_ (PRD §2.2)."""
    alphabet = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def iso_now(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits.

    e.g. 2026-07-20T03:40:00.000Z (PRD §2.2 / §2.4).
    """
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime string into a tz-aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Raises ERR_INVALID_REQUEST
    on a malformed value.
    """
    if not isinstance(value, str) or not value:
        raise err(ERR_INVALID_REQUEST, "Invalid datetime value.")
    raw = value.strip()
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
    except (ValueError, TypeError):
        raise err(ERR_INVALID_REQUEST, "Invalid datetime value: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def round_half_up(value):
    """Round a numeric value to the nearest whole cent, halves away from zero.

    'rounded half up' (PRD §2.5): a value exactly halfway rounds to the larger
    magnitude. Implemented with Decimal ROUND_HALF_UP to avoid float drift.
    """
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
