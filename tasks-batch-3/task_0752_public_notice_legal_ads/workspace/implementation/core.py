"""Cross-cutting concerns: error type, response envelope, auth, body parsing,
serialization, and pagination. All structural names are taken verbatim from the
PRD / SCAFFOLD (headers X-User-ID / X-User-Role; envelope meta/response_type/data;
error data.error_id / data.message; pagination limit/offset/total_count/has_more).
"""
import random
import string

from flask import request, jsonify

from store import fmt_ts, real_now, db

KNOWN_ROLES = {"Advertiser", "Publisher", "ComplianceOfficer", "PlatformAdmin"}


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --------------------------------------------------------------------------
# response envelope (PRD 2.2)
# --------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(pagination=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": fmt_ts(real_now())}
    if pagination:
        m.update(pagination)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, pagination):
    body = {"meta": _meta(pagination), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# auth (PRD 2.1)
# --------------------------------------------------------------------------
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid authentication headers")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role is not permitted for this operation")


# --------------------------------------------------------------------------
# body parsing (ERR_VALIDATION, HTTP 400)
# --------------------------------------------------------------------------
def json_body():
    data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "request body must be a JSON object")
    return data


def _bad(field, why):
    raise ApiError("ERR_VALIDATION", 400, "field '%s' %s" % (field, why))


def req_str(data, field):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    v = data[field]
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_int(data, field):
    if field not in data or data[field] is None:
        _bad(field, "is required")
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "must be an integer")
    return v


def req_enum(data, field, choices):
    v = req_str(data, field)
    if v not in choices:
        _bad(field, "must be one of %s" % sorted(choices))
    return v


def opt_str(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def opt_int(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if isinstance(v, bool) or not isinstance(v, int):
        _bad(field, "must be an integer")
    return v


def opt_bool(data, field, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, bool):
        _bad(field, "must be a boolean")
    return v


def opt_enum(data, field, choices, default=None):
    if field not in data or data[field] is None:
        return default
    v = data[field]
    if not isinstance(v, str) or v not in choices:
        _bad(field, "must be one of %s" % sorted(choices))
    return v


def opt_list(data, field, default=None):
    if field not in data or data[field] is None:
        return default if default is not None else []
    v = data[field]
    if not isinstance(v, list):
        _bad(field, "must be an array")
    return v


# --------------------------------------------------------------------------
# pagination (PRD 2.3)
# --------------------------------------------------------------------------
def _parse_pos_int(raw, field):
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "query param '%s' must be an integer" % field)


def paginate(items):
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        limit = _parse_pos_int(args.get("limit"), "limit")
        if limit < 1:
            limit = 1
        elif limit > 100:
            limit = 100
    if "offset" in args:
        offset = _parse_pos_int(args.get("offset"), "offset")
        if offset < 0:
            offset = 0
    total = len(items)
    window = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, pagination


# --------------------------------------------------------------------------
# serialization
# --------------------------------------------------------------------------
def _clean(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def ser(e):
    return _clean(e)


def ser_account(a):
    from domain import account_balances

    d = _clean(a)
    outstanding, committed = account_balances(a["id"])
    d["outstanding_balance_cents"] = outstanding
    d["committed_balance_cents"] = committed
    return d


def ser_list(items, kind="plain"):
    if kind == "account":
        return [ser_account(i) for i in items]
    return [_clean(i) for i in items]
