"""Request-shape validation helpers (ladder step 5 -> ERR_INVALID_REQUEST)."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    try:
        payload = request.get_json(force=True, silent=True)
    except Exception:  # pragma: no cover - defensive
        payload = None
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def present(data, key):
    return key in data and data[key] is not None


# ---------------------------------------------------------------- strings
def req_str(data, key, min_len=1, max_len=None):
    if key not in data or data[key] is None:
        bad("Field '%s' is required." % key)
    return _check_str(data[key], key, min_len, max_len)


def opt_str(data, key, min_len=1, max_len=None, default=None, allow_null=False):
    if key not in data:
        return default
    if data[key] is None:
        if allow_null:
            return None
        return default
    return _check_str(data[key], key, min_len, max_len)


def _check_str(value, key, min_len, max_len):
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if min_len is not None and min_len >= 1 and not value.strip():
        bad("Field '%s' must not be blank." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long." % key)
    return value


# ---------------------------------------------------------------- integers
def req_int(data, key, lo=None, hi=None):
    if key not in data or data[key] is None:
        bad("Field '%s' is required." % key)
    return _check_int(data[key], key, lo, hi)


def opt_int(data, key, lo=None, hi=None, default=None, allow_null=False):
    if key not in data:
        return default
    if data[key] is None:
        if allow_null:
            return None
        return default
    return _check_int(data[key], key, lo, hi)


def _check_int(value, key, lo, hi):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if lo is not None and value < lo:
        bad("Field '%s' is below its permitted range." % key)
    if hi is not None and value > hi:
        bad("Field '%s' is above its permitted range." % key)
    return value


# ---------------------------------------------------------------- numbers
def req_num(data, key, lo=None, hi=None, exclusive_lo=None):
    if key not in data or data[key] is None:
        bad("Field '%s' is required." % key)
    return _check_num(data[key], key, lo, hi, exclusive_lo)


def opt_num(data, key, lo=None, hi=None, default=None, exclusive_lo=None, allow_null=False):
    if key not in data:
        return default
    if data[key] is None:
        if allow_null:
            return None
        return default
    return _check_num(data[key], key, lo, hi, exclusive_lo)


def _check_num(value, key, lo, hi, exclusive_lo):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        bad("Field '%s' must be a number." % key)
    if isinstance(value, str):
        bad("Field '%s' must be a number." % key)
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % key)
    if not dec.is_finite():
        bad("Field '%s' must be a finite number." % key)
    if lo is not None and dec < Decimal(str(lo)):
        bad("Field '%s' is below its permitted range." % key)
    if exclusive_lo is not None and dec <= Decimal(str(exclusive_lo)):
        bad("Field '%s' is below its permitted range." % key)
    if hi is not None and dec > Decimal(str(hi)):
        bad("Field '%s' is above its permitted range." % key)
    return dec


# ---------------------------------------------------------------- booleans
def req_bool(data, key):
    if key not in data or data[key] is None:
        bad("Field '%s' is required." % key)
    return _check_bool(data[key], key)


def opt_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return _check_bool(data[key], key)


def _check_bool(value, key):
    if not isinstance(value, bool):
        bad("Field '%s' must be a boolean." % key)
    return value


# ---------------------------------------------------------------- enums
def req_enum(data, key, allowed):
    value = req_str(data, key, 1, None)
    if value not in allowed:
        bad("Field '%s' carries an undeclared enum member." % key)
    return value


def opt_enum(data, key, allowed, default=None):
    if key not in data or data[key] is None:
        return default
    value = _check_str(data[key], key, 1, None)
    if value not in allowed:
        bad("Field '%s' carries an undeclared enum member." % key)
    return value


# ---------------------------------------------------------------- dates
def _parse_date(value, key):
    if not isinstance(value, str):
        bad("Field '%s' must be a YYYY-MM-DD date string." % key)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        bad("Field '%s' must be a YYYY-MM-DD date string." % key)
    return parsed


def req_date(data, key):
    if key not in data or data[key] is None:
        bad("Field '%s' is required." % key)
    _parse_date(data[key], key)
    return data[key]


def opt_date(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    _parse_date(data[key], key)
    return data[key]


def parse_instant(value, key):
    """Parse an ISO 8601 instant, returning an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        bad("Field '%s' must be an ISO 8601 timestamp." % key)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        bad("Field '%s' must be an ISO 8601 timestamp." % key)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_instant(data, key):
    if key not in data or data[key] is None:
        bad("Field '%s' is required." % key)
    return parse_instant(data[key], key), data[key]


def req_id(data, key):
    return req_str(data, key, 1, None)


def opt_id(data, key, default=None):
    return opt_str(data, key, 1, None, default)


# ---------------------------------------------------------------- query args
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        limit = _query_int(raw, "limit")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' is outside its permitted range.")
    if "offset" in args:
        raw = args.get("offset")
        offset = _query_int(raw, "offset")
        if offset < 0:
            bad("Query parameter 'offset' must not be negative.")
    return limit, offset


def _query_int(raw, name):
    if raw is None or raw == "":
        bad("Query parameter '%s' must be an integer." % name)
    try:
        return int(raw)
    except (TypeError, ValueError):
        bad("Query parameter '%s' must be an integer." % name)


def q_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def q_enum(name, allowed, default=None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    if value not in allowed:
        bad("Query parameter '%s' carries an undeclared enum member." % name)
    return value


def q_int(name, default=None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    return _query_int(value, name)


def q_bool(name, default=None):
    value = request.args.get(name)
    if value is None or value == "":
        return default
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % name)


def q_date(name, required=False):
    value = request.args.get(name)
    if value is None or value == "":
        if required:
            bad("Query parameter '%s' is required." % name)
        return None
    _parse_date(value, name)
    return value
