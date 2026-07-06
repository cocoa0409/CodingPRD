import datetime
from decimal import Decimal, ROUND_HALF_UP

import errors


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.datetime.now(datetime.timezone.utc).microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime."""
    if value is None:
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "missing timestamp")
    if not isinstance(value, str):
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "timestamp must be a string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, "invalid timestamp format")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


def round2(value):
    """Round to 2 decimal places, round-half-up, returning a float."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)


def require(body, field):
    if not isinstance(body, dict) or field not in body or body[field] is None:
        raise errors.ApiError(errors.ERR_INVALID_REQUEST, 400, f"missing required field: {field}")
    return body[field]
