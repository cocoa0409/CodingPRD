"""Shared helpers: id/timestamp generation, timestamp parsing, rounding,
and request field-shape validation (ERR_INVALID_REQUEST, 400)."""

import re
import secrets
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from errors import err_invalid


def new_id() -> str:
    """Server-minted UUID with no type prefix."""
    return str(uuid.uuid4())


def new_request_id() -> str:
    """Request id starting with 'req_' followed by random alphanumerics."""
    alphabet = string.ascii_letters + string.digits
    suffix = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"req_{suffix}"


def now_timestamp() -> str:
    """ISO 8601 UTC timestamp with exactly three fractional digits (wall clock)."""
    now = datetime.now(timezone.utc)
    base = now.strftime("%Y-%m-%dT%H:%M:%S")
    ms = now.microsecond // 1000
    return f"{base}.{ms:03d}Z"


def round_half_up(value) -> int:
    """Round a Decimal (or numeric) to integer cents, half away from zero."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


_TS_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d+)?(Z|[+-]\d{2}:\d{2})$"
)


def parse_dt(value):
    """Parse an ISO 8601 UTC instant into an aware datetime.

    Returns None when the value is not a well-formed timestamp (callers then
    treat the field as malformed for the field-shape stage)."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not _TS_RE.match(text):
        return None
    iso = text
    if iso.endswith("Z"):
        iso = iso[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def render_like(template: str, dt: datetime) -> str:
    """Render dt as an ISO 8601 string preserving the style of `template`
    (fractional-second digit count and Z vs numeric offset)."""
    m = _TS_RE.match(template)
    if not m:
        base = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return f"{base}Z"
    frac = m.group(5) or ""
    tz = m.group(6)
    if tz == "Z":
        local = dt.astimezone(timezone.utc)
        suffix = "Z"
    else:
        sign = 1 if tz[0] == "+" else -1
        oh, om = int(tz[1:3]), int(tz[4:6])
        from datetime import timedelta, timezone as _tz

        off = _tz(sign * timedelta(hours=oh, minutes=om))
        local = dt.astimezone(off)
        suffix = tz
    base = local.strftime("%Y-%m-%dT%H:%M:%S")
    if frac:
        digits = len(frac) - 1
        us = f"{local.microsecond:06d}"
        frac_str = "." + (us + "000000")[:digits]
    else:
        frac_str = ""
    return base + frac_str + suffix


# ---- Request body field-shape validation (all raise ERR_INVALID_REQUEST) ----


def body_of(request) -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def require_field(body: dict, field: str):
    if field not in body or body[field] is None:
        raise err_invalid(f"Missing required field '{field}'")
    return body[field]


def require_string(body: dict, field: str) -> str:
    value = require_field(body, field)
    if not isinstance(value, str) or value == "":
        raise err_invalid(f"Field '{field}' must be a non-empty string")
    return value


def optional_string(body: dict, field: str):
    value = body.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise err_invalid(f"Field '{field}' must be a non-empty string when provided")
    return value


def require_enum(body: dict, field: str, allowed) -> str:
    value = require_field(body, field)
    if not isinstance(value, str) or value not in allowed:
        raise err_invalid(f"Field '{field}' must be one of {sorted(allowed)}")
    return value


def require_int(body: dict, field: str, minimum=None, maximum=None) -> int:
    value = require_field(body, field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid(f"Field '{field}' must be an integer")
    if minimum is not None and value < minimum:
        raise err_invalid(f"Field '{field}' must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err_invalid(f"Field '{field}' must be <= {maximum}")
    return value


def optional_int(body: dict, field: str, default=None, minimum=None, maximum=None):
    value = body.get(field)
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise err_invalid(f"Field '{field}' must be an integer")
    if minimum is not None and value < minimum:
        raise err_invalid(f"Field '{field}' must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise err_invalid(f"Field '{field}' must be <= {maximum}")
    return value


def require_timestamp(body: dict, field: str) -> str:
    value = require_field(body, field)
    if parse_dt(value) is None:
        raise err_invalid(f"Field '{field}' must be an ISO 8601 UTC timestamp")
    return value
