"""Shared helpers: UUID, ISO8601 timestamps, parsing, pagination, Decimal math."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

import errors


def new_id():
    return str(uuid.uuid4())


def iso_now():
    """Logical-clock timestamp, ISO 8601 UTC with three fractional digits."""
    import db
    now = db.get_clock()
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def parse_iso(value, field="datetime"):
    """Parse an ISO 8601 datetime. Accepts trailing Z or explicit offset."""
    if not isinstance(value, str):
        raise errors.invalid_request(f"{field} must be an ISO 8601 string")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"{field} is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def require_fields(payload, fields):
    for f in fields:
        if f not in payload or payload[f] is None:
            raise errors.invalid_request(f"missing required field: {f}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise errors.invalid_request(f"bad enum value for {field}: {value!r}")
    return value


def to_decimal(value, field="number"):
    try:
        return Decimal(str(value))
    except Exception:
        raise errors.invalid_request(f"{field} must be a number")


def to_int(value, field="integer"):
    if isinstance(value, bool):
        raise errors.invalid_request(f"{field} must be an integer")
    try:
        if isinstance(value, float) and not value.is_integer():
            raise ValueError
        return int(value)
    except (ValueError, TypeError):
        raise errors.invalid_request(f"{field} must be an integer")


def round_half_up_int(dec):
    """Round a Decimal to integer using ROUND_HALF_UP."""
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(dec):
    return float(dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def get_pagination():
    """Read limit/offset query params per scaffold §1.0 defaults."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            raise errors.invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise errors.invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            raise errors.invalid_request("offset must be an integer")
        if offset < 0:
            raise errors.invalid_request("offset must be >= 0")
    return limit, offset
