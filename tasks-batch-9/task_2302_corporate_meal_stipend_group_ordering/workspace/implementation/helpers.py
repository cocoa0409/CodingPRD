"""Auth, request-shape validation and pagination helpers."""

import re
from datetime import datetime, timezone

from flask import request

from errors import ApiError

# PRD §2.1 — the five declared roles.
ROLES = ("PlatformAdmin", "ProgramAdmin", "BenefitsController", "Employee", "Restaurant")

MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


# --------------------------------------------------------------------------
# priority 1 + 2: authentication and role gate
# --------------------------------------------------------------------------
def auth(*allowed_roles):
    """Returns (user_id, role). Raises 401 then 403 per PRD §2.10 ranks 1-2."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if role is None:
        # tolerate the shorter header spelling as an alias
        role = request.headers.get("X-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return user_id, role


# --------------------------------------------------------------------------
# body access
# --------------------------------------------------------------------------
def get_body():
    raw = request.get_json(silent=True)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return raw


def _missing(key):
    raise ApiError("ERR_INVALID_REQUEST", "Missing required field '%s'." % key)


def _bad(key, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (key, why))


_UNSET = object()


def f_string(body, key, required=True, default=None, non_empty=True):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    val = body[key]
    if not isinstance(val, str):
        _bad(key, "must be a string")
    if non_empty and val.strip() == "":
        _bad(key, "must be a non-empty string")
    return val


def f_int(body, key, required=True, default=None, minimum=None, maximum=None):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        _bad(key, "must be an integer")
    if minimum is not None and val < minimum:
        _bad(key, "must be >= %s" % minimum)
    if maximum is not None and val > maximum:
        _bad(key, "must be <= %s" % maximum)
    return val


def f_number(body, key, required=True, default=None, minimum=None, maximum=None,
             exclusive_min=None):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        _bad(key, "must be a number")
    val = float(val)
    if minimum is not None and val < minimum:
        _bad(key, "must be >= %s" % minimum)
    if exclusive_min is not None and val <= exclusive_min:
        _bad(key, "must be > %s" % exclusive_min)
    if maximum is not None and val > maximum:
        _bad(key, "must be <= %s" % maximum)
    return val


def f_bool(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    val = body[key]
    if not isinstance(val, bool):
        _bad(key, "must be a boolean")
    return val


def f_enum(body, key, allowed, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    val = body[key]
    if not isinstance(val, str) or val not in allowed:
        _bad(key, "must be one of %s" % ", ".join(allowed))
    return val


def f_month(body, key, required=True, default=None):
    val = f_string(body, key, required=required, default=default)
    if val is None:
        return None
    if not MONTH_RE.match(val):
        _bad(key, "must match YYYY-MM")
    return val


def parse_dt(value, key):
    if not isinstance(value, str):
        _bad(key, "must be an ISO 8601 UTC datetime string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        _bad(key, "must be an ISO 8601 UTC datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def f_datetime(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    return parse_dt(body[key], key)


def f_lines(body, key="lines", required=True):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return None
    val = body[key]
    if not isinstance(val, list):
        _bad(key, "must be an array")
    if len(val) < 1 or len(val) > 20:
        _bad(key, "must contain between 1 and 20 elements")
    out = []
    for idx, item in enumerate(val):
        if not isinstance(item, dict):
            _bad("%s[%d]" % (key, idx), "must be an object")
        name = f_string(item, "item_name", required=True)
        unit = f_int(item, "unit_price_cents", required=True, minimum=1)
        qty = f_int(item, "quantity", required=True, minimum=1)
        out.append({"item_name": name, "unit_price_cents": unit, "quantity": qty})
    return out


def f_int_array(body, key, required=True, minimum=None, maximum=None, distinct=True,
                non_empty=True):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return None
    val = body[key]
    if not isinstance(val, list):
        _bad(key, "must be an array")
    if non_empty and len(val) == 0:
        _bad(key, "must be a non-empty array")
    for item in val:
        if isinstance(item, bool) or not isinstance(item, int):
            _bad(key, "must contain integers only")
        if minimum is not None and item < minimum:
            _bad(key, "elements must be >= %s" % minimum)
        if maximum is not None and item > maximum:
            _bad(key, "elements must be <= %s" % maximum)
    if distinct and len(set(val)) != len(val):
        _bad(key, "elements must be distinct")
    return list(val)


def f_str_array_upper(body, key, required=True, default=None):
    if key not in body or body[key] is None:
        if required:
            _missing(key)
        return default
    val = body[key]
    if not isinstance(val, list):
        _bad(key, "must be an array")
    if len(val) == 0:
        _bad(key, "must be a non-empty array")
    for item in val:
        if not isinstance(item, str) or item.strip() == "":
            _bad(key, "must contain non-empty strings")
        if item != item.upper():
            _bad(key, "must contain uppercase strings")
    if len(set(val)) != len(val):
        _bad(key, "elements must be distinct")
    return list(val)


# --------------------------------------------------------------------------
# pagination (PRD §2.3)
# --------------------------------------------------------------------------
def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0.")
    return limit, offset


def q_enum(name, allowed):
    val = request.args.get(name)
    if val is None or val == "":
        return None
    if val not in allowed:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return val


def q_str(name):
    val = request.args.get(name)
    if val is None or val == "":
        return None
    return val


def q_month(name):
    val = q_str(name)
    if val is None:
        return None
    if not MONTH_RE.match(val):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must match YYYY-MM." % name)
    return val
