"""Error catalog, response envelope, auth/authorization helpers, validators."""
from datetime import datetime
from flask import request, jsonify, g

import store

# ---------------------------------------------------------------------------
# Error catalog (error_id -> http status)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_TENANT_NOT_FOUND": 404,
    "ERR_LANDLORD_NOT_FOUND": 404,
    "ERR_PLAN_NOT_FOUND": 404,
    "ERR_ENROLLMENT_NOT_FOUND": 404,
    "ERR_LEASE_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_REPORTED_ITEM_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_BACK_REPORT_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_ALREADY_VERIFIED": 409,
    "ERR_LEASE_NOT_VERIFIED": 409,
    "ERR_ITEM_NOT_DISPUTABLE": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_LEASE_DATE_OVERLAP": 409,
    "ERR_PERIOD_ALREADY_COVERED": 409,
    "ERR_BACK_REPORT_LIMIT_EXCEEDED": 422,
    "ERR_BACK_REPORT_MONTHS_INVALID": 422,
    "ERR_ENROLLMENT_INACTIVE": 402,
    "ERR_INVOICE_UNPAID": 402,
    "ERR_CLOCK_BEFORE_CURRENT": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = ERROR_HTTP.get(error_id, 400)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    m = {
        "api_request_id": store.new_request_id(),
        "api_request_timestamp": store.fmt_dt(store.clock_now()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Serialization: format internal datetimes, drop private keys
# ---------------------------------------------------------------------------
def serialize(entity):
    out = {}
    for k, v in entity.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = store.fmt_dt(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def paginate(items):
    """items: already-sorted list of entity dicts. Returns (page, pagination_meta)."""
    args = request.args
    limit = _parse_int_param(args.get("limit"), 10)
    offset = _parse_int_param(args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination


def _parse_int_param(raw, default):
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise ApiError("ERR_INVALID_REQUEST", "invalid pagination parameter")


def sort_key(e):
    return (e["created_at"], e["_seq"])


def sorted_list(collection, predicate=None):
    items = [e for e in collection.values() if (predicate is None or predicate(e))]
    items.sort(key=sort_key)
    return items


# ---------------------------------------------------------------------------
# Auth / authorization
# ---------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in store.KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "missing or invalid credentials")
    g.user_id = uid
    g.role = role
    return uid, role


def authorize(allowed_roles):
    uid, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "role not permitted for this operation")
    return uid, role


def require_tenant_owner(role, uid, owner_tenant_id):
    if role == "Tenant" and owner_tenant_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", "not the owning tenant")


def require_landlord_owner(role, uid, landlord_id):
    if role == "Landlord" and landlord_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", "not the owning landlord")


# ---------------------------------------------------------------------------
# Body / field validators (raise ApiError ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "body must be a JSON object")
    return data


def require_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", "missing or invalid field: " + field)
    return v


def require_present(body, field):
    if field not in body or body.get(field) is None:
        raise ApiError("ERR_INVALID_REQUEST", "missing field: " + field)
    return body.get(field)


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", "missing or non-integer field: " + field)
    return v


def require_enum(body, field, choices):
    v = body.get(field)
    if v not in choices:
        raise ApiError("ERR_INVALID_REQUEST", "invalid enum for field: " + field)
    return v


def require_month(body, field):
    v = body.get(field)
    if not isinstance(v, str) or not _valid_month(v):
        raise ApiError("ERR_INVALID_REQUEST", "invalid YYYY-MM month: " + field)
    return v


def require_iso(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime: " + field)
    try:
        return store.parse_dt(v)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime: " + field)


def optional_iso(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime: " + field)
    try:
        return store.parse_dt(v)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "invalid datetime: " + field)


def optional_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", "invalid field: " + field)
    return v


def _valid_month(s):
    import re
    return bool(re.match(r"^\d{4}-(0[1-9]|1[0-2])$", s))


def month_index(s):
    y, m = s.split("-")
    return int(y) * 12 + int(m)


def current_month_str():
    now = store.clock_now()
    return "{:04d}-{:02d}".format(now.year, now.month)
