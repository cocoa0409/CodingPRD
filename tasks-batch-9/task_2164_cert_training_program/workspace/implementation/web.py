"""Response envelope, authentication/RBAC, pagination and payload validation."""
from __future__ import annotations

from decimal import Decimal

from flask import jsonify, request

from errors import ApiError, bad_request
from store import serialize, serialize_many, sorted_rows
from util import D, has_max_decimals, parse_iso, request_id, wall_now_iso

ROLES = (
    "ProgramCoordinator",
    "Instructor",
    "SkillsEvaluator",
    "LogisticsOfficer",
    "EmergencyManager",
    "Trainee",
    "Auditor",
)
ALL_ROLES = ROLES

MISSING = object()


# --------------------------------------------------------------------------
# Envelope (PRD 2.2)
# --------------------------------------------------------------------------
def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def ok_row(row, status=200):
    return ok(serialize(row), status)


def ok_list(rows, limit, offset, total_count):
    payload = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(rows) < total_count,
        }),
        "response_type": "array",
        "data": serialize_many(rows),
    }
    return jsonify(payload), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# Auth (PRD 2.1) — checks 1 and 2 of the ordering in PRD 2.6
# --------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    return user_id, role


def require(*allowed):
    user_id, role = authenticate()
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not invoke this endpoint." % role)
    return user_id, role


def require_any():
    return require(*ALL_ROLES)


# --------------------------------------------------------------------------
# Path / FK resolution
# --------------------------------------------------------------------------
def resolve(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row


# --------------------------------------------------------------------------
# Body validation (PRD 2.6 step 4)
# --------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise bad_request("Request body must be a JSON object.")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def f_str(data, name, required=True, default=None, min_len=None, nullable=False):
    if name not in data:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    value = data[name]
    if value is None:
        if nullable:
            return None
        raise bad_request("Field '%s' must be a string." % name)
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        raise bad_request("Field '%s' must be at least %d characters." % (name, min_len))
    return value


def f_int(data, name, required=True, default=None, min_val=None, max_val=None):
    if name not in data:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    value = data[name]
    if not _is_int(value):
        raise bad_request("Field '%s' must be an integer." % name)
    if min_val is not None and value < min_val:
        raise bad_request("Field '%s' must be >= %s." % (name, min_val))
    if max_val is not None and value > max_val:
        raise bad_request("Field '%s' must be <= %s." % (name, max_val))
    return value


def f_num(data, name, required=True, default=None, min_val=None, max_val=None,
          gt=None, max_decimals=None):
    if name not in data:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return None if default is None else D(default)
    value = data[name]
    if not _is_num(value):
        raise bad_request("Field '%s' must be a number." % name)
    dec = D(value)
    if gt is not None and not dec > D(gt):
        raise bad_request("Field '%s' must be greater than %s." % (name, gt))
    if min_val is not None and dec < D(min_val):
        raise bad_request("Field '%s' must be >= %s." % (name, min_val))
    if max_val is not None and dec > D(max_val):
        raise bad_request("Field '%s' must be <= %s." % (name, max_val))
    if max_decimals is not None and not has_max_decimals(dec, max_decimals):
        raise bad_request("Field '%s' carries at most %d decimal place(s)." % (name, max_decimals))
    return dec


def f_bool(data, name, required=True, default=None):
    if name not in data:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean." % name)
    return value


def f_enum(data, name, choices, required=True, default=None):
    if name not in data:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default
    value = data[name]
    if not isinstance(value, str) or value not in choices:
        raise bad_request("Field '%s' must be one of %s." % (name, ", ".join(choices)))
    return value


def f_dt(data, name, required=True, default=None):
    """Returns (raw_string, datetime).  Input datetimes are echoed verbatim."""
    if name not in data:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return default, None
    value = data[name]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO 8601 UTC datetime string." % name)
    try:
        parsed = parse_iso(value)
    except ValueError:
        raise bad_request("Field '%s' must be a well-formed ISO 8601 UTC datetime." % name)
    return value, parsed


def f_id(data, name, required=True, nullable=False, present=None):
    """A foreign-key reference field: string id, optionally nullable."""
    if name not in data:
        if required:
            raise bad_request("Field '%s' is required." % name)
        return MISSING if present else None
    value = data[name]
    if value is None:
        if nullable:
            return None
        raise bad_request("Field '%s' must be a string identifier." % name)
    if not isinstance(value, str) or not value:
        raise bad_request("Field '%s' must be a string identifier." % name)
    return value


# --------------------------------------------------------------------------
# Pagination + filtering (PRD 2.3)
# --------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except Exception:
            raise bad_request("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            raise bad_request("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except Exception:
            raise bad_request("Query parameter 'offset' must be an integer.")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be >= 0.")
    return limit, offset


def q_enum(name, choices):
    if name not in request.args:
        return None
    value = request.args.get(name)
    if value not in choices:
        raise bad_request("Query parameter '%s' must be one of %s." % (name, ", ".join(choices)))
    return value


def q_str(name):
    if name not in request.args:
        return None
    return request.args.get(name)


def q_bool(name):
    if name not in request.args:
        return None
    value = str(request.args.get(name)).strip().lower()
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    raise bad_request("Query parameter '%s' must be a boolean." % name)


def paginate(rows):
    limit, offset = pagination()
    rows = sorted_rows(rows)
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list(page, limit, offset, total)
