"""Time, id, and decimal helpers."""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ERR_VALIDATION


def new_id():
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def iso_z(dt):
    """ISO 8601 UTC with three fractional digits and a Z suffix."""
    d = dt.astimezone(timezone.utc)
    return d.strftime("%Y-%m-%dT%H:%M:%S.") + f"{d.microsecond // 1000:03d}Z"


def parse_dt(value, field):
    """Parse an ISO 8601 datetime; naive values are treated as UTC."""
    if not isinstance(value, str):
        raise err(ERR_VALIDATION, f"Field '{field}' must be an ISO 8601 datetime string", 400)
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        d = datetime.fromisoformat(text)
    except ValueError:
        raise err(ERR_VALIDATION, f"Field '{field}' is not a valid ISO 8601 datetime", 400)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def dec(value):
    """Decimal view of a JSON number (int or float), via str to avoid binary noise."""
    return Decimal(str(value))


def rhu(x):
    """Round half up to whole cents (integer)."""
    if not isinstance(x, Decimal):
        x = Decimal(x)
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
