"""Time, decimal, and request-shape helpers."""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store
from errors import ApiError, ERR_INVALID_REQUEST


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now_iso():
    """Wall-clock timestamp for the meta envelope (request metadata only;
    all business timestamps come from the logical clock)."""
    return fmt_dt(datetime.now(timezone.utc))


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be an ISO 8601 datetime string" % field, 400)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "%s is not a valid ISO 8601 datetime" % field, 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Decimal
# ---------------------------------------------------------------------------

CENT = Decimal("0.01")


def r2(x):
    """Round half up to 2 decimal places."""
    return Decimal(x).quantize(CENT, rounding=ROUND_HALF_UP)


def r0(x):
    """Round half up to an integer (whole cents)."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def dec_to_num(d):
    """JSON-safe number: integral Decimals as int, fractional as float."""
    if d is None:
        return None
    if not isinstance(d, Decimal):
        return d
    if d == d.to_integral_value():
        return int(d)
    return float(d)


# ---------------------------------------------------------------------------
# Entity bookkeeping
# ---------------------------------------------------------------------------

def new_entity(rec):
    """Stamp common system fields on creation (PRD 2.5)."""
    rec["created_at"] = store.logical_now
    rec["updated_at"] = store.logical_now
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    return rec


def touch(rec):
    """Every mutation refreshes updated_at (logical clock) and bumps version."""
    rec["updated_at"] = store.logical_now
    rec["version"] += 1


# ---------------------------------------------------------------------------
# Request body shape validation (evaluation class 5 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object", 400)
    return body


def req_present(body, field):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % field, 400)
    return body[field]


def as_str(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be a string" % field, 400)
    return value


def as_int(value, field):
    if isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be an integer" % field, 400)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    raise ApiError(ERR_INVALID_REQUEST, "%s must be an integer" % field, 400)


def as_num(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be a number" % field, 400)
    return Decimal(str(value))


def as_bool(value, field):
    if not isinstance(value, bool):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be a boolean" % field, 400)
    return value


def as_enum(value, field, allowed):
    if not isinstance(value, str) or value not in allowed:
        raise ApiError(
            ERR_INVALID_REQUEST,
            "%s must be one of %s" % (field, ", ".join(allowed)),
            400,
        )
    return value


def as_list(value, field):
    if not isinstance(value, list):
        raise ApiError(ERR_INVALID_REQUEST, "%s must be an array" % field, 400)
    return value


def check(condition, message):
    if not condition:
        raise ApiError(ERR_INVALID_REQUEST, message, 400)


def pagination_params():
    """PRD 2.3: limit default 10, min 1, max 100; offset default 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            offset = 0
    return limit, offset
