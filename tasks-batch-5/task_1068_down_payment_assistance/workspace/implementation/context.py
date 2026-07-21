"""Request context helpers: auth, body access, field validation, lookups."""
from decimal import Decimal
from datetime import datetime, timezone

from flask import request

import store
from errors import ApiError

VALID_ROLES = {
    "Anonymous", "Applicant", "CaseManager",
    "ProgramAdmin", "ClosingCoordinator", "Servicer",
}


# ----------------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------------
def authenticate(allowed_roles):
    """Enforce header presence/validity (401) then role authorization (403).

    Returns (user_id, role).
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role '%s' may not perform this operation." % role)
    return uid, role


# ----------------------------------------------------------------------------
# Body
# ----------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


# ----------------------------------------------------------------------------
# Existence lookups (raise the resource-specific NOT_FOUND)
# ----------------------------------------------------------------------------
_NOT_FOUND = {
    "program": "ERR_PROGRAM_NOT_FOUND",
    "applicant": "ERR_APPLICANT_NOT_FOUND",
    "application": "ERR_APPLICATION_NOT_FOUND",
    "property": "ERR_PROPERTY_NOT_FOUND",
    "session": "ERR_SESSION_NOT_FOUND",
    "enrollment": "ERR_ENROLLMENT_NOT_FOUND",
    "certificate": "ERR_CERTIFICATE_NOT_FOUND",
    "award": "ERR_AWARD_NOT_FOUND",
    "funding_source": "ERR_FUNDING_SOURCE_NOT_FOUND",
    "allocation": "ERR_ALLOCATION_NOT_FOUND",
    "closing": "ERR_CLOSING_NOT_FOUND",
    "servicing": "ERR_SERVICING_NOT_FOUND",
}


def lookup(kind, rid):
    coll = store.COLLECTIONS[kind]
    rec = coll.get(rid)
    if rec is None:
        raise ApiError(_NOT_FOUND[kind], "%s not found." % kind)
    return rec


# ----------------------------------------------------------------------------
# Field validation (ERR_INVALID_REQUEST)
# ----------------------------------------------------------------------------
def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg)


def require(data, field):
    if field not in data or data[field] is None:
        _bad("Missing required field: %s" % field)
    return data[field]


def req_str(data, field):
    v = require(data, field)
    if not isinstance(v, str) or v == "":
        _bad("Field %s must be a non-empty string." % field)
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = require(data, field)
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field %s must be an integer." % field)
    if minimum is not None and v < minimum:
        _bad("Field %s must be >= %s." % (field, minimum))
    if maximum is not None and v > maximum:
        _bad("Field %s must be <= %s." % (field, maximum))
    return v


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data[field] is None:
        return default
    return req_int(data, field, minimum, maximum)


def req_enum(data, field, members):
    v = require(data, field)
    if v not in members:
        _bad("Field %s must be one of %s." % (field, sorted(members)))
    return v


def opt_enum(data, field, members, default=None):
    if field not in data or data[field] is None:
        return default
    return req_enum(data, field, members)


def opt_bool(data, field, default):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        _bad("Field %s must be a boolean." % field)
    return v


def req_datetime(data, field):
    v = require(data, field)
    if not isinstance(v, str):
        _bad("Field %s must be an ISO-8601 datetime string." % field)
    return v, parse_dt(v)


def parse_dt(s):
    try:
        s2 = s.strip()
        if s2.endswith("Z"):
            s2 = s2[:-1] + "+00:00"
        dt = datetime.fromisoformat(s2)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Invalid datetime: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----------------------------------------------------------------------------
# Pagination + list filtering
# ----------------------------------------------------------------------------
def pagination_params():
    args = request.args

    def parse(name, default, lo, hi):
        raw = args.get(name)
        if raw is None or raw == "":
            return default
        try:
            val = int(raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % name)
        if lo is not None and val < lo:
            val = lo
        if hi is not None and val > hi:
            val = hi
        return val

    limit = parse("limit", 10, 1, 100)
    offset = parse("offset", 0, 0, None)
    return limit, offset


def paginate(records, limit, offset, filters=None):
    items = list(records)
    if filters:
        for key, val in filters.items():
            if val is not None:
                items = [r for r in items if r.get(key) == val]
    items.sort(key=lambda r: r["_seq"])
    total = len(items)
    page = items[offset:offset + limit]
    return page, total


def query_filter(name):
    v = request.args.get(name)
    return v if v not in (None, "") else None
