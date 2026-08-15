"""Shared helpers: timestamps, decimals, validation primitives, envelopes."""

import random
import string
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from flask import request

from errors import ApiError, raise_error


# ---------------------------------------------------------------- clock
def now_iso():
    """Wall-clock timestamp for meta.api_request_timestamp (3 fractional digits)."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=22))


# ---------------------------------------------------------------- datetime parsing
def parse_dt(value, field):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be an ISO-8601 string")
    s = value.strip()
    try:
        if s.endswith("Z"):
            s2 = s[:-1] + "+00:00"
        else:
            s2 = s
        dt = datetime.fromisoformat(s2)
    except ValueError:
        raise_error("ERR_INVALID_REQUEST", f"{field} is not a valid ISO-8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field):
    if not isinstance(value, str):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be an ISO date string")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise_error("ERR_INVALID_REQUEST", f"{field} is not a valid ISO date")


def fmt_dt(dt):
    """Serialize aware datetime to ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


# ---------------------------------------------------------------- decimals
def dec(value, field):
    """Parse a JSON number into Decimal. Rejects bools and non-numbers."""
    if isinstance(value, bool) or value is None:
        raise_error("ERR_INVALID_REQUEST", f"{field} must be a number")
    if isinstance(value, (int,)):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation:
            raise_error("ERR_INVALID_REQUEST", f"{field} must be a number")
    if isinstance(value, Decimal):
        return value
    raise_error("ERR_INVALID_REQUEST", f"{field} must be a number")


def dec_opt(value, field):
    if value is None:
        return None
    return dec(value, field)


def req_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be an integer")
    return value


def q2(d):
    return Decimal(d).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(d):
    return Decimal(d).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def q0(d):
    return Decimal(d).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def num_out(d):
    """Serialize Decimal as float for JSON (2dp quantities)."""
    if d is None:
        return None
    if not isinstance(d, Decimal):
        return d
    return float(d)


# ---------------------------------------------------------------- request body
ALLOWED_UNKNOWN_CHECK = True


def get_body(allowed_fields, required_fields):
    """Parse JSON body; reject unknown fields, missing required fields."""
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise_error("ERR_INVALID_REQUEST", "Malformed JSON body")
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise_error("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for key in body:
        if key not in allowed_fields:
            raise_error("ERR_INVALID_REQUEST", f"Unknown field: {key}")
    for f in required_fields:
        if f not in body or body[f] is None:
            raise_error("ERR_INVALID_REQUEST", f"Missing required field: {f}")
    return body


def get_body_optional(allowed_fields):
    try:
        body = request.get_json(force=False, silent=True)
    except Exception:
        body = None
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_error("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    for key in body:
        if key not in allowed_fields:
            raise_error("ERR_INVALID_REQUEST", f"Unknown field: {key}")
    return body


def req_enum(value, field, choices):
    if not isinstance(value, str) or value not in choices:
        raise_error("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(choices)}")
    return value


def req_str(value, field):
    if not isinstance(value, str):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be a string")
    return value


def req_bool(value, field):
    if not isinstance(value, bool):
        raise_error("ERR_INVALID_REQUEST", f"{field} must be a boolean")
    return value


# ---------------------------------------------------------------- pagination
def pagination_params():
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_error("ERR_INVALID_REQUEST", "limit out of range")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_error("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise_error("ERR_INVALID_REQUEST", "offset out of range")
    return limit, offset
