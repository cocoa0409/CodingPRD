"""Shared helpers: id minting, timestamps, datetime parsing, rounding."""
import uuid
import random
import string
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.4)."""
    return str(uuid.uuid4())


def now_iso():
    """ISO 8601 UTC timestamp with three fractional digits (PRD §2.4).

    Used for created_at / updated_at. These are record-keeping stamps, not
    business-time comparisons — PRD §2.5 restricts the *logical clock* to
    business decisions (refund tiers, depart/complete guards), so the audit
    timestamps use real wall-clock time formatted to milliseconds.
    """
    return _fmt_ms(datetime.now(timezone.utc))


def _fmt_ms(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    """Server-generated unique request id starting with req_ (PRD §2.2)."""
    suffix = "".join(random.choices(string.ascii_letters + string.digits, k=20))
    return "req_" + suffix


def request_timestamp():
    return _fmt_ms(datetime.now(timezone.utc))


def round_half_up(value):
    """Round a numeric value half-up to the nearest integer (cents)."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_money(*decimal_factors):
    """Multiply Decimal factors and round half up to whole integer cents."""
    product = Decimal(1)
    for f in decimal_factors:
        product *= Decimal(str(f))
    return int(product.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def parse_datetime(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None if the value cannot be parsed.
    """
    if not isinstance(s, str):
        return None
    raw = s.strip()
    if not raw:
        return None
    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        # try date-only (birth_date may be a bare date)
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
