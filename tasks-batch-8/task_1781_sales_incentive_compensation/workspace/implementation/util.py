"""Shared helpers: ids, timestamps, rounding, serialization."""
import random
import string
import uuid
from datetime import datetime, timezone


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def now_ts() -> str:
    """ISO 8601 UTC timestamp with three fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def round_half_up_int(numer, denom) -> int:
    """round_half_up(numer/denom) to an integer — ties away from zero.

    Uses exact integer arithmetic. For positive numer: floor((2n+d)/(2d)).
    """
    numer = int(numer)
    denom = int(denom)
    if denom == 0:
        raise ZeroDivisionError("denominator must be nonzero")
    if numer >= 0:
        return (2 * numer + denom) // (2 * denom)
    return -((2 * (-numer) + denom) // (2 * denom))


def serialize(entity):
    """Strip internal fields (underscore-prefixed) from entity for API response."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def new_entity(fields):
    """Create a new entity with common system fields."""
    ts = now_ts()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        **fields,
    }


def touch(entity):
    """Increment version and refresh updated_at on modification."""
    entity["updated_at"] = now_ts()
    entity["version"] = entity.get("version", 0) + 1
