"""Formatters, request-body validators, and pagination parameter parsing."""

from datetime import date, datetime, timezone

from flask import request

from errors import ApiError, ERR_VALIDATION


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def fmt_date(d):
    """ISO date YYYY-MM-DD (or None)."""
    if d is None:
        return None
    return d.isoformat()


def fmt_dt(dt):
    """ISO 8601 UTC datetime at seconds precision with Z suffix (or None)."""
    if dt is None:
        return None
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond:06d}".rstrip("0") + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_ts(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Request body and field validators (schema tier -> ERR_VALIDATION 400)
# ---------------------------------------------------------------------------

def body_dict():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_VALIDATION, 400, "Request body must be a JSON object.")
    return data


def _missing(name):
    raise ApiError(ERR_VALIDATION, 400, f"Missing required field: {name}.")


def req_string(d, name):
    v = d.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, f"Field {name} must be a string.")
    return v


def opt_string(d, name):
    v = d.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, f"Field {name} must be a string.")
    return v


def _check_int(v, name, minimum):
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_VALIDATION, 400, f"Field {name} must be an integer.")
    if minimum is not None and v < minimum:
        raise ApiError(ERR_VALIDATION, 400, f"Field {name} must be >= {minimum}.")
    return v


def req_int(d, name, minimum=None):
    v = d.get(name)
    if v is None:
        _missing(name)
    return _check_int(v, name, minimum)


def opt_int(d, name, minimum=None):
    if name not in d or d[name] is None:
        return None
    return _check_int(d[name], name, minimum)


def req_bool(d, name):
    v = d.get(name)
    if v is None:
        _missing(name)
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, 400, f"Field {name} must be a boolean.")
    return v


def req_enum(d, name, allowed):
    v = req_string(d, name)
    if v not in allowed:
        raise ApiError(ERR_VALIDATION, 400, f"Field {name} must be one of {sorted(allowed)}.")
    return v


def parse_date_value(v, name):
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, f"Field {name} must be an ISO date string.")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ApiError(ERR_VALIDATION, 400, f"Field {name} must be a valid ISO date (YYYY-MM-DD).")


def req_date(d, name):
    v = d.get(name)
    if v is None:
        _missing(name)
    return parse_date_value(v, name)


def opt_date(d, name):
    """Optional date; explicit null is allowed and yields None."""
    if name not in d or d[name] is None:
        return None
    return parse_date_value(d[name], name)


def parse_datetime_value(v, name):
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, 400, f"Field {name} must be an ISO 8601 datetime string.")
    s = v
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_VALIDATION, 400, f"Field {name} must be a valid ISO 8601 datetime.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_datetime(d, name):
    v = d.get(name)
    if v is None:
        _missing(name)
    return parse_datetime_value(v, name)


# ---------------------------------------------------------------------------
# Pagination (limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------

def pagination_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "Query parameter limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, 400, "Query parameter limit must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, 400, "Query parameter offset must be an integer.")
        if offset < 0:
            raise ApiError(ERR_VALIDATION, 400, "Query parameter offset must be >= 0.")
    return limit, offset
