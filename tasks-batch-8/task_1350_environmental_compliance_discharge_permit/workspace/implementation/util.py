"""Shared helpers: timestamps, rounding, ids, request parsing."""

import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err, ERR_INVALID_REQUEST

ISO_Z_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def new_id():
    return str(uuid.uuid4())


def now_iso():
    """Logical clock now rendered as ISO 8601 UTC with 3 fractional digits."""
    return iso_format(datetime_now())


def datetime_now():
    from db import clock
    return clock.now()


def iso_format(dt):
    """Render a datetime as ISO 8601 UTC with exactly 3 fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def parse_iso(value, field="timestamp"):
    """Parse an ISO 8601 timestamp string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise err(ERR_INVALID_REQUEST, 400, f"{field} must be an ISO 8601 string")
    m = ISO_Z_RE.match(value.strip())
    if not m:
        raise err(ERR_INVALID_REQUEST, 400, f"{field} must be a valid ISO 8601 timestamp")
    try:
        v = value.strip()
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise err(ERR_INVALID_REQUEST, 400, f"{field} must be a valid ISO 8601 timestamp")


def dec(value):
    """Convert numeric input to Decimal without float artifacts where avoidable."""
    if isinstance(value, bool):
        raise err(ERR_INVALID_REQUEST, 400, "numeric field must be a number")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:
            raise err(ERR_INVALID_REQUEST, 400, "numeric field must be a number")
    raise err(ERR_INVALID_REQUEST, 400, "numeric field must be a number")


def round_half_up(value, places):
    """Round a Decimal to `places` decimal places, ROUND_HALF_UP."""
    q = Decimal(1).scaleb(-places)  # 10^-places
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def num_out(value):
    """Serialize a Decimal to int if whole, else float."""
    if value is None:
        return None
    d = Decimal(value)
    if d == d.to_integral_value():
        return int(d)
    return float(d)


def require_fields(payload, fields):
    for f in fields:
        if f not in payload or payload[f] is None:
            raise err(ERR_INVALID_REQUEST, 400, f"Missing required field: {f}")


def get_body():
    """Fetch the JSON request body as a dict ({} when empty)."""
    from flask import request
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_INVALID_REQUEST, 400, "Request body must be valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def check_enum(value, allowed, field):
    if value not in allowed:
        raise err(ERR_INVALID_REQUEST, 400, f"{field} must be one of {sorted(allowed)}")
    return value
