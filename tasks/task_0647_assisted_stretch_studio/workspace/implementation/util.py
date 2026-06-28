"""Shared helpers: time parsing/comparison, pagination, decimal rounding, validation."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from errors import err, ERR_VALIDATION
from db import store


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def parse_iso(s):
    """Parse an ISO 8601 instant into a timezone-aware UTC datetime.

    Accepts trailing 'Z' or explicit offset. Raises ERR_VALIDATION on garbage.
    """
    if not isinstance(s, str):
        raise err(ERR_VALIDATION, "Invalid datetime value.")
    raw = s.strip()
    try:
        normalized = raw
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        raise err(ERR_VALIDATION, f"Invalid ISO 8601 datetime: {s!r}.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_clock():
    """Current logical-clock instant as a tz-aware UTC datetime."""
    return parse_iso(store.clock["current_utc"])


def minute_of_day(dt):
    return dt.hour * 60 + dt.minute


# ---------------------------------------------------------------------------
# Decimal money rounding (round-half-up, whole cents)
# ---------------------------------------------------------------------------
def round_half_up_cents(value):
    """Round a Decimal/number to a whole integer cents value, round-half-up."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Request body / field validation
# ---------------------------------------------------------------------------
def get_json_body():
    """Parse JSON body; tolerate empty body as {} for action endpoints."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err(ERR_VALIDATION, "Malformed JSON body.")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err(ERR_VALIDATION, "Request body must be a JSON object.")
    return body


def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err(ERR_VALIDATION, f"Missing required field: {n}.")


def require_str(body, name):
    require_fields(body, [name])
    v = body[name]
    if not isinstance(v, str) or v == "":
        raise err(ERR_VALIDATION, f"Field {name} must be a non-empty string.")
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        raise err(ERR_VALIDATION, f"Field {name} must be a string.")
    return v


def require_int(body, name, minimum=None, maximum=None):
    require_fields(body, [name])
    return _coerce_int(body[name], name, minimum, maximum)


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return _coerce_int(body[name], name, minimum, maximum)


def _coerce_int(v, name, minimum, maximum):
    # Reject bools (subclass of int) and non-integers.
    if isinstance(v, bool) or not isinstance(v, int):
        raise err(ERR_VALIDATION, f"Field {name} must be an integer.")
    if minimum is not None and v < minimum:
        raise err(ERR_VALIDATION, f"Field {name} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise err(ERR_VALIDATION, f"Field {name} must be <= {maximum}.")
    return v


def require_number(body, name, minimum=None, maximum=None):
    require_fields(body, [name])
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err(ERR_VALIDATION, f"Field {name} must be a number.")
    if minimum is not None and v < minimum:
        raise err(ERR_VALIDATION, f"Field {name} must be >= {minimum}.")
    if maximum is not None and v > maximum:
        raise err(ERR_VALIDATION, f"Field {name} must be <= {maximum}.")
    return v


def opt_number(body, name, default=None, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    return require_number(body, name, minimum, maximum)


def require_bool(body, name):
    require_fields(body, [name])
    v = body[name]
    if not isinstance(v, bool):
        raise err(ERR_VALIDATION, f"Field {name} must be a boolean.")
    return v


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise err(ERR_VALIDATION, f"Field {name} must be a boolean.")
    return v


def require_enum(body, name, choices):
    v = require_str(body, name)
    if v not in choices:
        raise err(ERR_VALIDATION, f"Field {name} must be one of {sorted(choices)}.")
    return v


# ---------------------------------------------------------------------------
# Pagination (scaffold §1.0 / PRD §2.3)
# ---------------------------------------------------------------------------
PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100
PAGE_DEFAULT_OFFSET = 0


def parse_pagination():
    limit = _parse_query_int("limit", PAGE_DEFAULT_LIMIT)
    offset = _parse_query_int("offset", PAGE_DEFAULT_OFFSET)
    if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
        raise err(ERR_VALIDATION, "limit out of range.")
    if offset < 0:
        raise err(ERR_VALIDATION, "offset must be >= 0.")
    return limit, offset


def _parse_query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        # Reject floats / non-integer strings.
        if raw.strip().lstrip("-").isdigit() is False:
            raise ValueError
        return int(raw)
    except (ValueError, TypeError):
        raise err(ERR_VALIDATION, f"{name} must be an integer.")


def paginate(items, limit, offset):
    """Sort by created_at asc (tie-break by creation seq) then slice."""
    ordered = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    total = len(ordered)
    window = ordered[offset:offset + limit]
    return window, total


def days_ceiling(start_dt, end_dt):
    """Ceiling of a span to whole days. ceil((end-start)/1day)."""
    total = (end_dt - start_dt).total_seconds()
    if total <= 0:
        return 0
    day = 86400.0
    import math
    return int(math.ceil(total / day))
