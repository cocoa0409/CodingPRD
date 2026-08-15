"""Response envelope, auth context, body validation, pagination helpers."""
import random
import string
from datetime import date, datetime, timezone

from flask import jsonify, request

from db import now_iso
from errors import ApiError

ROLES = {
    "DistrictProgramAdmin",
    "FarmManager",
    "KitchenManager",
    "ClaimsCoordinator",
    "StateGrantAuditor",
}


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=22))


def meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": now_iso()}


def ok_object(rec, status=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": rec}), status


def ok_list(items, limit, offset, total):
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + limit) < total
    return jsonify({"meta": m, "response_type": "array", "data": items}), 200


def ok_empty(status=200):
    return jsonify({"meta": meta(), "response_type": "object", "data": {}}), status


def error_response(err):
    return jsonify({
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.status


def ctx():
    """Priority 1: user-context headers."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and role must be a recognized role",
            400,
        )
    return uid, role


def require_role(role, *allowed):
    """Priority 2: endpoint role permission."""
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", "Role %s is not permitted for this endpoint" % role, 403)


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object", 400)
    return data


def _bad(msg):
    raise ApiError("ERR_INVALID_REQUEST", msg, 400)


def req_field(b, k):
    if k not in b or b[k] is None:
        _bad("Missing required field: %s" % k)
    return b[k]


def req_str(b, k):
    v = req_field(b, k)
    if not isinstance(v, str) or v == "":
        _bad("Field %s must be a non-empty string" % k)
    return v


def opt_str(b, k):
    if k not in b or b[k] is None:
        return None
    v = b[k]
    if not isinstance(v, str) or v == "":
        _bad("Field %s must be a non-empty string" % k)
    return v


def _check_int(v, k, mn, mx):
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field %s must be an integer" % k)
    if mn is not None and v < mn:
        _bad("Field %s is below the allowed minimum" % k)
    if mx is not None and v > mx:
        _bad("Field %s exceeds the allowed maximum" % k)
    return v


def req_int(b, k, mn=None, mx=None):
    return _check_int(req_field(b, k), k, mn, mx)


def opt_int(b, k, mn=None, mx=None):
    if k not in b or b[k] is None:
        return None
    return _check_int(b[k], k, mn, mx)


def _check_number(v, k, mn, mx):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("Field %s must be a number" % k)
    if mn is not None and v < mn:
        _bad("Field %s is below the allowed minimum" % k)
    if mx is not None and v > mx:
        _bad("Field %s exceeds the allowed maximum" % k)
    return v


def req_number(b, k, mn=None, mx=None):
    return _check_number(req_field(b, k), k, mn, mx)


def req_enum(b, k, allowed):
    v = req_field(b, k)
    if not isinstance(v, str) or v not in allowed:
        _bad("Field %s must be one of %s" % (k, sorted(allowed)))
    return v


def opt_enum(b, k, allowed, default=None):
    if k not in b or b[k] is None:
        return default
    v = b[k]
    if not isinstance(v, str) or v not in allowed:
        _bad("Field %s must be one of %s" % (k, sorted(allowed)))
    return v


def parse_date(v, k="date"):
    if not isinstance(v, str):
        _bad("Field %s must be an ISO date string (YYYY-MM-DD)" % k)
    try:
        if len(v) != 10 or v[4] != "-" or v[7] != "-":
            raise ValueError
        return date(int(v[0:4]), int(v[5:7]), int(v[8:10]))
    except ValueError:
        _bad("Field %s must be a valid YYYY-MM-DD date" % k)


def req_date(b, k):
    return parse_date(req_field(b, k), k)


def parse_iso8601(v, k="to_iso8601"):
    if not isinstance(v, str):
        _bad("Field %s must be an ISO 8601 timestamp string" % k)
    try:
        t = v.strip()
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        _bad("Field %s must be a valid ISO 8601 timestamp" % k)


def parse_month(v, k="month"):
    if not isinstance(v, str):
        _bad("Field %s must be a YYYY-MM month string" % k)
    try:
        if len(v) != 7 or v[4] != "-":
            raise ValueError
        y, m = int(v[0:4]), int(v[5:7])
        if m < 1 or m > 12:
            raise ValueError
        return y, m
    except ValueError:
        _bad("Field %s must be a valid YYYY-MM month" % k)


def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
        if limit < 1 or limit > 100:
            _bad("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
        if offset < 0:
            _bad("offset must be >= 0")
    return limit, offset


def list_response(records, serializer, filters):
    """filters: {query_param: record_key_or_callable}. Sorted by created_at asc."""
    items = sorted(records, key=lambda r: r["_seq"])
    out = []
    for rec in items:
        match = True
        for param, key in filters.items():
            v = request.args.get(param)
            if v is None:
                continue
            rv = rec[key] if isinstance(key, str) else key(rec)
            if isinstance(rv, bool):
                if str(rv).lower() != v.lower():
                    match = False
                    break
            elif isinstance(rv, int):
                try:
                    cmp_v = int(v)
                except (TypeError, ValueError):
                    _bad("Filter %s must be an integer" % param)
                if rv != cmp_v:
                    match = False
                    break
            else:
                if str(rv) != v:
                    match = False
                    break
        if match:
            out.append(rec)
    limit, offset = pagination()
    total = len(out)
    page = out[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)
