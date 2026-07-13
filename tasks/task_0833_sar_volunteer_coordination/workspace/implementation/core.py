"""Request-level helpers: envelope, auth, body validation, pagination."""
import random
import string

from flask import request, jsonify

import store
from errors import ApiError

ROLES = {"Coordinator", "IncidentCommander", "FinanceOfficer", "Member"}


# --- Response envelope ---------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": store.now_iso()}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --- Auth ----------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")


def auth(allowed):
    """Authenticate then authorize against the allowed role set."""
    uid, role = authenticate()
    authorize(role, allowed)
    return uid, role


# --- Path existence ------------------------------------------------------
def get_or_404(collection, rid):
    rec = collection.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND")
    return rec


# --- Body / field validation (all failures -> ERR_VALIDATION 422) --------
def body_json():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION")
    return data


def _fail():
    raise ApiError("ERR_VALIDATION")


def _present(d, k):
    return k in d and d[k] is not None


def vstr(d, k, required=True, default=None):
    if not _present(d, k):
        if required:
            _fail()
        return default
    v = d[k]
    if not isinstance(v, str) or v == "":
        _fail()
    return v


def venum(d, k, choices, required=True, default=None):
    if not _present(d, k):
        if required:
            _fail()
        return default
    v = d[k]
    if v not in choices:
        _fail()
    return v


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def vnum(d, k, required=True, default=None, gt=None, ge=None):
    if not _present(d, k):
        if required:
            _fail()
        return default
    v = d[k]
    if not _is_number(v):
        _fail()
    if gt is not None and not (v > gt):
        _fail()
    if ge is not None and not (v >= ge):
        _fail()
    return v


def vint(d, k, required=True, default=None, gt=None, ge=None):
    if not _present(d, k):
        if required:
            _fail()
        return default
    v = d[k]
    if not isinstance(v, int) or isinstance(v, bool):
        _fail()
    if gt is not None and not (v > gt):
        _fail()
    if ge is not None and not (v >= ge):
        _fail()
    return v


def vbool(d, k, required=True, default=None):
    if not _present(d, k):
        if required:
            _fail()
        return default
    v = d[k]
    if not isinstance(v, bool):
        _fail()
    return v


def vdt(d, k, required=True, default=None):
    """Validate a datetime string is parseable; return the raw string."""
    if not _present(d, k):
        if required:
            _fail()
        return default
    v = d[k]
    if not isinstance(v, str):
        _fail()
    try:
        store.parse_dt(v)
    except Exception:
        _fail()
    return v


def varray_enum(d, k, choices, required=False, default=None):
    if not _present(d, k):
        if required:
            _fail()
        return default if default is not None else []
    v = d[k]
    if not isinstance(v, list):
        _fail()
    for item in v:
        if item not in choices:
            _fail()
    return v


def vfk(d, k, collection, required=True, default=None):
    """Validate a foreign-key body field references an existing record.

    Missing FK references are body errors (422), NOT path-existence (404)."""
    if not _present(d, k):
        if required:
            _fail()
        return default
    v = d[k]
    if not isinstance(v, str) or v not in collection:
        _fail()
    return v


# --- Pagination ----------------------------------------------------------
def pagination_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (ValueError, TypeError):
            limit = 10
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (ValueError, TypeError):
            offset = 0
        if offset < 0:
            offset = 0
    return limit, offset


def paginate_and_respond(records, serialize_fn, filters):
    """records: iterable of raw records; filters: list of (query_param, field_name).

    Filtering is applied to the *serialized* view so computed fields (status,
    etc.) filter correctly. Results are sorted by creation order (created_at asc).
    """
    ordered = sorted(records, key=lambda r: r["_seq"])
    serialized = [serialize_fn(r) for r in ordered]
    for param, field in filters:
        val = request.args.get(param)
        if val is not None:
            serialized = [s for s in serialized if str(s.get(field)) == val]
    limit, offset = pagination_params()
    total = len(serialized)
    page = serialized[offset:offset + limit]
    return ok_list(page, limit, offset, total)
