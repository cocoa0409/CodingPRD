"""Response envelope, errors, auth, and request-body validation helpers."""
import secrets

from flask import g, jsonify, request

import db

ROLES = {
    "PlatformAdmin",
    "CaseManager",
    "ConflictAnalyst",
    "CredentialAnalyst",
    "BillingReviewer",
    "Expert",
}

MISSING = object()


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# ---------------------------------------------------------------- envelope
def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": db.wall_now_iso(),
    }


def ok(data, status=200, response_type="object", pagination=None):
    m = _meta()
    if pagination is not None:
        m.update(pagination)
    return jsonify({"meta": m, "response_type": response_type, "data": data}), status


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------- errors
def bad_request(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def forbidden(msg="role not permitted for this operation"):
    raise ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="resource not found"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def conflict_err(error_id, msg):
    raise ApiError(error_id, 409, msg)


def unprocessable(error_id, msg):
    raise ApiError(error_id, 422, msg)


# ---------------------------------------------------------------- auth
def authenticate():
    """before_request: X-User-ID + X-User-Role mandatory; role must be declared."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "missing or invalid X-User-ID / X-User-Role headers",
        )
    g.user_id = uid
    g.user_role = role


def require_role(*roles):
    if g.user_role not in roles:
        forbidden()


# ---------------------------------------------------------------- body parsing
def body_dict():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        bad_request("request body must be a JSON object")
    return data


def optional_body():
    """Body optional for the endpoint; returns {} when absent/not an object."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _type_err(name):
    bad_request("field '%s' is missing or has an invalid type" % name)


def req_str(d, name):
    v = d.get(name, MISSING)
    if not isinstance(v, str):
        _type_err(name)
    return v


def opt_str(d, name, default=None):
    v = d.get(name, MISSING)
    if v is MISSING:
        return default
    if not isinstance(v, str):
        _type_err(name)
    return v


def _check_int(name, v, minimum, maximum):
    if isinstance(v, bool) or not isinstance(v, int):
        _type_err(name)
    if minimum is not None and v < minimum:
        bad_request("field '%s' is below its minimum" % name)
    if maximum is not None and v > maximum:
        bad_request("field '%s' exceeds its maximum" % name)
    return v


def req_int(d, name, minimum=None, maximum=None):
    v = d.get(name, MISSING)
    if v is MISSING:
        _type_err(name)
    return _check_int(name, v, minimum, maximum)


def opt_int(d, name, default=None, minimum=None, maximum=None):
    v = d.get(name, MISSING)
    if v is MISSING:
        return default
    return _check_int(name, v, minimum, maximum)


def _check_num(name, v, gt, ge, le):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _type_err(name)
    f = float(v)
    if gt is not None and not f > gt:
        bad_request("field '%s' must be > %s" % (name, gt))
    if ge is not None and not f >= ge:
        bad_request("field '%s' must be >= %s" % (name, ge))
    if le is not None and not f <= le:
        bad_request("field '%s' must be <= %s" % (name, le))
    return f


def req_num(d, name, gt=None, ge=None, le=None):
    v = d.get(name, MISSING)
    if v is MISSING:
        _type_err(name)
    return _check_num(name, v, gt, ge, le)


def opt_num_nullable(d, name, ge=None, le=None):
    """Optional numeric field that may be explicitly null."""
    if name not in d or d[name] is None:
        return None
    return _check_num(name, d[name], None, ge, le)


def req_enum(d, name, choices):
    v = d.get(name, MISSING)
    if not isinstance(v, str) or v not in choices:
        bad_request("field '%s' must be one of %s" % (name, sorted(choices)))
    return v


def req_dt(d, name):
    v = req_str(d, name)
    try:
        db.parse_iso(v)
    except Exception:
        bad_request("field '%s' must be an ISO 8601 datetime" % name)
    return v


def opt_bool(d, name, default=False):
    v = d.get(name, MISSING)
    if v is MISSING:
        return default
    if not isinstance(v, bool):
        _type_err(name)
    return v


def req_str_list(d, name):
    v = d.get(name, MISSING)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        _type_err(name)
    return v


# ---------------------------------------------------------------- pagination
def pagination_params():
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit, offset = 10, 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            bad_request("limit must be an integer")
        if limit < 1 or limit > 100:
            bad_request("limit must be between 1 and 100")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            bad_request("offset must be an integer")
        if offset < 0:
            bad_request("offset must be >= 0")
    return limit, offset


def list_ok(records, limit, offset):
    """Sorted by created_at ascending; meta carries the pagination fields."""
    recs = sorted(records, key=lambda r: (r["created_at"], r.get("_seq", 0)))
    total = len(recs)
    page = recs[offset:offset + limit]
    return ok(
        page,
        200,
        "array",
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(page) < total,
        },
    )


# ---------------------------------------------------------------- lookups
def get_or_404(store, rid, what="resource"):
    rec = store.get(rid)
    if rec is None:
        not_found("%s not found" % what)
    return rec
