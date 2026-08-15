"""Shared helpers: envelope, auth, time, decimal math, field validation."""

import re
import uuid
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

from db import store
from errors import (
    ApiError, ERR_VALIDATION, ERR_UNAUTHENTICATED, ERR_FORBIDDEN,
)

ROLES = {
    "PlatformAdmin", "Dispatcher", "Customer", "Technician",
    "QualityAuditor", "ComplianceOfficer",
}

# ----------------------------------------------------------------------------
# Response envelope
# ----------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": iso_dt(store.clock),
    }


def respond(data, code=200, response_type="object", pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def respond_list(items, total_count, limit, offset, code=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return respond(items, code=code, response_type="array", pagination=pagination)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------

def caller():
    """Authenticate: X-User-Role must be present and a declared role."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED,
                       "X-User-Role header missing or not a declared role")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN,
                       "Role %s is not permitted for this endpoint" % role)


def forbid(msg="Ownership check failed"):
    raise ApiError(ERR_FORBIDDEN, msg)


# ----------------------------------------------------------------------------
# Time helpers (logical clock)
# ----------------------------------------------------------------------------

def now():
    return store.clock


def clock_date():
    return store.clock.date()


def iso_dt(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_d(d):
    return d.strftime("%Y-%m-%d")


def parse_dt(value, field):
    if not isinstance(value, str):
        raise ApiError(ERR_VALIDATION, "%s must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(ERR_VALIDATION, "%s is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PERIOD_RE = re.compile(r"^\d{4}-\d{2}$")


def parse_date(value, field):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        raise ApiError(ERR_VALIDATION, "%s must be a YYYY-MM-DD date" % field)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ApiError(ERR_VALIDATION, "%s is not a valid calendar date" % field)


def parse_period(value, field):
    if not isinstance(value, str) or not _PERIOD_RE.match(value):
        raise ApiError(ERR_VALIDATION, "%s must be a YYYY-MM period" % field)
    year, month = int(value[:4]), int(value[5:7])
    if not 1 <= month <= 12:
        raise ApiError(ERR_VALIDATION, "%s is not a valid month" % field)
    return value


# ----------------------------------------------------------------------------
# Decimal / rounding helpers
# ----------------------------------------------------------------------------

def round_half_up_cents(x):
    """Round a Decimal to integer cents, half-up."""
    return int(Decimal(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


GAL_Q = Decimal("0.1")


def gal_round(x):
    """Round gallons to one decimal place."""
    return Decimal(x).quantize(GAL_Q, rounding=ROUND_HALF_UP)


def gal_num(x):
    """Serialize a gallons Decimal as a JSON number."""
    d = gal_round(x)
    f = float(d)
    return f


# ----------------------------------------------------------------------------
# Body validation helpers
# ----------------------------------------------------------------------------

def get_body():
    body = request.get_json(force=True, silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_VALIDATION, "Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, "%s is required and must be a string" % field)
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise ApiError(ERR_VALIDATION, "%s must be a string" % field)
    return v


def req_int(body, field):
    v = body.get(field)
    if not _is_int(v):
        raise ApiError(ERR_VALIDATION, "%s is required and must be an integer" % field)
    return v


def opt_int(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not _is_int(v):
        raise ApiError(ERR_VALIDATION, "%s must be an integer" % field)
    return v


def req_num(body, field):
    v = body.get(field)
    if not _is_num(v):
        raise ApiError(ERR_VALIDATION, "%s is required and must be a number" % field)
    return v


def opt_num(body, field, default=None):
    if field not in body or body.get(field) is None:
        return default
    v = body.get(field)
    if not _is_num(v):
        raise ApiError(ERR_VALIDATION, "%s must be a number" % field)
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, "%s is required and must be a boolean" % field)
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise ApiError(ERR_VALIDATION, "%s must be a boolean" % field)
    return v


def req_enum(body, field, members):
    v = body.get(field)
    if not isinstance(v, str) or v not in members:
        raise ApiError(ERR_VALIDATION,
                       "%s must be one of %s" % (field, sorted(members)))
    return v


def opt_enum(body, field, members, default):
    if field not in body or body.get(field) is None:
        return default
    return req_enum(body, field, members)


def req_str_list(body, field):
    v = body.get(field)
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise ApiError(ERR_VALIDATION,
                       "%s is required and must be a list of strings" % field)
    return v


# ----------------------------------------------------------------------------
# Pagination
# ----------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError(ERR_VALIDATION, "limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(records, serializer, sort_key=None):
    """Sort, filter (already applied by caller), paginate, respond."""
    if sort_key is None:
        sort_key = lambda r: (r["created_at_sort"], r["_seq"])
    ordered = sorted(records, key=sort_key)
    total = len(ordered)
    limit, offset = pagination_params()
    page = ordered[offset:offset + limit]
    return respond_list([serializer(r) for r in page], total, limit, offset)


# ----------------------------------------------------------------------------
# Record helpers
# ----------------------------------------------------------------------------

def stamp_new(rec):
    rec["id"] = str(uuid.uuid4())
    rec["created_at"] = store.clock
    rec["updated_at"] = store.clock
    rec["version"] = 1
    rec["_seq"] = store.next_seq()
    rec["created_at_sort"] = store.clock
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD 2.4/2.10)."""
    rec["version"] += 1
    rec["updated_at"] = store.clock
