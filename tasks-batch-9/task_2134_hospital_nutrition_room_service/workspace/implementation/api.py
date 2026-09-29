"""Response envelope, authentication/RBAC, and request-shape validators.

Every structural name here is taken from PRD section 2.2 / 2.3 / 2.1 and the
scaffold's response_envelope block: meta / api_request_id /
api_request_timestamp / response_type / data / error_id / message, and the
pagination fields limit / offset / total_count / has_more.
"""

import random
import string
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from functools import wraps

from flask import g, jsonify, request

import store
from errors import ApiError

ROLES = ("Physician", "Dietitian", "DietClerk", "TrayAide", "NutritionManager")
ALL_ROLES = list(ROLES)

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0

MISSING = object()


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------
def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def _request_timestamp():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def _meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": _request_timestamp()}


def ok(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data or {}}), code


def created(data):
    return ok(data, 201)


def ok_list(rows, total, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC (validation ladder steps 1 and 2)
# ---------------------------------------------------------------------------
def require(*roles):
    allowed = list(roles) if roles else ALL_ROLES

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def actor():
    return g.user_id


# ---------------------------------------------------------------------------
# Request body helpers (validation ladder step 4)
# ---------------------------------------------------------------------------
def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(cache=True)
    if not raw:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _present(b, key):
    return key in b and b[key] is not None


def req_str(b, key, min_len=1, max_len=None):
    if key not in b or b[key] is None:
        bad("Field '%s' is required." % key)
    value = b[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long." % key)
    return value


def opt_str(b, key, default=None, min_len=None, max_len=None):
    if key not in b:
        return default
    value = b[key]
    if value is None:
        return None
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' is too long." % key)
    return value


def _check_int(value, key):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    return value


def req_int(b, key, lo=None, hi=None):
    if key not in b or b[key] is None:
        bad("Field '%s' is required." % key)
    value = _check_int(b[key], key)
    if lo is not None and value < lo:
        bad("Field '%s' is below its minimum." % key)
    if hi is not None and value > hi:
        bad("Field '%s' is above its maximum." % key)
    return value


def opt_int(b, key, default=None, lo=None, hi=None):
    if key not in b:
        return default
    if b[key] is None:
        return None
    value = _check_int(b[key], key)
    if lo is not None and value < lo:
        bad("Field '%s' is below its minimum." % key)
    if hi is not None and value > hi:
        bad("Field '%s' is above its maximum." % key)
    return value


def _check_num(value, key):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("Field '%s' must be a number." % key)
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        bad("Field '%s' must be a number." % key)


def req_num(b, key, lo=None, hi=None):
    if key not in b or b[key] is None:
        bad("Field '%s' is required." % key)
    value = _check_num(b[key], key)
    if lo is not None and value < Decimal(str(lo)):
        bad("Field '%s' is below its minimum." % key)
    if hi is not None and value > Decimal(str(hi)):
        bad("Field '%s' is above its maximum." % key)
    return value


def opt_num(b, key, default=None, lo=None, hi=None):
    if key not in b:
        return default
    if b[key] is None:
        return None
    value = _check_num(b[key], key)
    if lo is not None and value < Decimal(str(lo)):
        bad("Field '%s' is below its minimum." % key)
    if hi is not None and value > Decimal(str(hi)):
        bad("Field '%s' is above its maximum." % key)
    return value


def req_enum(b, key, allowed):
    value = req_str(b, key)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(b, key, allowed, default=None, nullable=False):
    if key not in b:
        return default
    value = b[key]
    if value is None:
        if nullable:
            return None
        return default
    if not isinstance(value, str) or value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_bool(b, key, default=None):
    if key not in b or b[key] is None:
        return default
    if not isinstance(b[key], bool):
        bad("Field '%s' must be a boolean." % key)
    return b[key]


def opt_str_list(b, key, default=None):
    if key not in b or b[key] is None:
        return list(default) if default is not None else []
    value = b[key]
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        bad("Field '%s' must be an array of strings." % key)
    return list(value)


def req_dt(b, key):
    value = req_str(b, key)
    parsed = store.parse_iso(value)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 timestamp." % key)
    return parsed


def req_date(b, key):
    value = req_str(b, key)
    if store.parse_date(value) is None:
        bad("Field '%s' must be a YYYY-MM-DD calendar date." % key)
    return value


def req_id(b, key):
    """A body reference: shape-checked here, resolved later at ladder step 5."""
    return req_str(b, key)


def opt_id(b, key):
    if key not in b or b[key] is None:
        return None
    if not isinstance(b[key], str) or not b[key]:
        bad("Field '%s' must be a string identifier." % key)
    return b[key]


# ---------------------------------------------------------------------------
# Query string helpers
# ---------------------------------------------------------------------------
def pagination():
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be zero or greater.")
    return limit, offset


def q_enum(key, allowed):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def q_str(key):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    return value


def q_bool(key):
    value = request.args.get(key)
    if value is None or value == "":
        return None
    lowered = value.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter '%s' must be a boolean." % key)


def paged(rows, serializer):
    limit, offset = pagination()
    ordered = store.sort_rows(rows)
    total = len(ordered)
    page = ordered[offset: offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)


def filtered(rows, filters):
    """filters: list of (value, key) pairs; a None value means 'no filter'."""
    out = []
    for row in rows:
        keep = True
        for value, key in filters:
            if value is None:
                continue
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out
