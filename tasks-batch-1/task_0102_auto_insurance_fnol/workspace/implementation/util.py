"""Shared helpers: ISO8601 formatting/parsing, ids, rounding (Decimal-based)."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err


def new_uuid():
    return str(uuid.uuid4())


def new_request_id():
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def format_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits and trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime.

    Accepts a trailing Z or an explicit offset. Raises ERR_INVALID_REQUEST
    on a value that is not a parseable instant.
    """
    if not isinstance(value, str) or not value:
        raise err("ERR_INVALID_REQUEST", "invalid datetime")
    raw = value.strip()
    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        dt = None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw, fmt)
                break
            except ValueError:
                dt = None
        if dt is None:
            raise err("ERR_INVALID_REQUEST", "invalid datetime: %s" % value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ratio_round4(numerator, denominator):
    """numerator / denominator rounded to 4 decimal places, round-half-up.

    Returns a float for JSON serialization; the rounding is exact via Decimal.
    """
    q = (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
        Decimal("0.0001"), rounding=ROUND_HALF_UP
    )
    return float(q)


def pct_recovery(demand_cents, fault_pct):
    """demand_cents * (100 - fault_pct) / 100, rounded half-up to whole cents.

    Rounding is applied exactly once at the end (PRD §2.6). Uses Decimal to
    avoid IEEE-754 error.
    """
    product = (Decimal(int(demand_cents)) * Decimal(100 - int(fault_pct))) / Decimal(100)
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
