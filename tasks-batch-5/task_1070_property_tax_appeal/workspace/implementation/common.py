"""Response envelope, error type, auth, body validation, pagination helpers."""

import random
import string

from flask import jsonify, request

from store import db, fmt, next_seq, new_id, now, parse_dt

ROLES = {"FirmAdmin", "Analyst", "Billing", "Client"}


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# --------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": fmt(now())}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def err(error_id, http_status, message):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), http_status


# --------------------------------------------------------------------------
# Auth (PRD §2.1, §2.10)
# --------------------------------------------------------------------------
def require_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or invalid authentication")
    return uid, role


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")


def forbidden_owner():
    raise ApiError("ERR_FORBIDDEN_NOT_OWNER", 403, "resource not owned by caller")


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------
import datetime


def serialize(rec):
    out = {}
    for k, v in rec.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime.datetime):
            out[k] = fmt(v)
        else:
            out[k] = v
    return out


# --------------------------------------------------------------------------
# Record lifecycle helpers
# --------------------------------------------------------------------------
def base_record(with_version=True):
    t = now()
    rec = {"id": new_id(), "created_at": t, "_seq": next_seq()}
    if with_version:
        rec["updated_at"] = t
        rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1


# --------------------------------------------------------------------------
# Body parsing / field validation
# --------------------------------------------------------------------------
def get_body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", 422, "body must be a JSON object")
    return b


def _invalid(msg):
    raise ApiError("ERR_INVALID_REQUEST", 422, msg)


def need(b, key):
    if key not in b or b[key] is None:
        _invalid("missing required field: %s" % key)
    return b[key]


def need_int(b, key):
    v = need(b, key)
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid("field %s must be an integer" % key)
    return v


def need_num(b, key):
    v = need(b, key)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _invalid("field %s must be a number" % key)
    return v


def need_str(b, key):
    v = need(b, key)
    if not isinstance(v, str) or v == "":
        _invalid("field %s must be a non-empty string" % key)
    return v


def need_enum(b, key, allowed):
    v = need_str(b, key)
    if v not in allowed:
        _invalid("field %s must be one of %s" % (key, sorted(allowed)))
    return v


def need_dt(b, key):
    v = need(b, key)
    try:
        return parse_dt(v)
    except Exception:
        _invalid("field %s must be an ISO 8601 datetime" % key)


def opt_int(b, key, default):
    if b.get(key) is None:
        return default
    v = b[key]
    if isinstance(v, bool) or not isinstance(v, int):
        _invalid("field %s must be an integer" % key)
    return v


def opt_num(b, key, default):
    if b.get(key) is None:
        return default
    v = b[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _invalid("field %s must be a number" % key)
    return v


def opt_str(b, key, default):
    if b.get(key) is None:
        return default
    v = b[key]
    if not isinstance(v, str):
        _invalid("field %s must be a string" % key)
    return v


def opt_bool(b, key, default):
    if b.get(key) is None:
        return default
    v = b[key]
    if not isinstance(v, bool):
        _invalid("field %s must be a boolean" % key)
    return v


# --------------------------------------------------------------------------
# Existence
# --------------------------------------------------------------------------
def must_exist(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise ApiError("ERR_NOT_FOUND", 404, "referenced resource does not exist")
    return rec


# --------------------------------------------------------------------------
# Pagination (PRD §2.3) — sort by created_at asc, tie-break on insertion seq
# --------------------------------------------------------------------------
def paginate(items):
    args = request.args
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            _invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            _invalid("limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            _invalid("offset must be an integer")
        if offset < 0:
            _invalid("offset must be >= 0")
    ordered = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": offset + limit < total}
    return [serialize(r) for r in page], pagination
