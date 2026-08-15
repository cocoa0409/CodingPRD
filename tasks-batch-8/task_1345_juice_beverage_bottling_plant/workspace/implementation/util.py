"""Response envelope, auth, payload parsing, pagination, serialization."""
import re
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from errors import err
from store import db

ROLES = {
    "PlantManager", "FinanceClerk", "ProductDeveloper", "LabelComplianceReviewer",
    "BlendOperator", "QAInspector", "ProductionPlanner", "WarehouseLead",
    "CustomerServiceRep", "CustomerContact",
}


# ---------------------------------------------------------------- envelope
def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": "req_" + uuid.uuid4().hex[:20],
            "api_request_timestamp": ts}


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(items)) < total
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


# ---------------------------------------------------------------- auth
def auth_ctx():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or not uid.strip() or not role.strip():
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-ID and X-User-Role headers must be present and non-empty")
    if role not in ROLES:
        raise err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                  "X-User-Role names an unrecognized role")
    return uid, role


def require_roles(*roles):
    uid, role = auth_ctx()
    if role not in roles:
        raise err("ERR_INSUFFICIENT_PERMISSIONS",
                  f"Role {role} is not authorized for this operation")
    return uid, role


def require_any():
    uid, role = auth_ctx()
    return uid, role


# ---------------------------------------------------------------- parsing
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def req_field(data, name, kind):
    if name not in data or data[name] is None:
        raise err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    v = data[name]
    if kind == "str" and not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    if kind == "int" and not _is_int(v):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if kind == "num" and not _is_num(v):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be a number")
    if kind == "list" and not isinstance(v, list):
        raise err("ERR_INVALID_REQUEST", f"Field {name} must be an array")
    if kind == "datetime":
        if not isinstance(v, str):
            raise err("ERR_INVALID_REQUEST", f"Field {name} must be an ISO 8601 string")
        return parse_datetime(v)
    if kind == "date":
        if not isinstance(v, str):
            raise err("ERR_INVALID_REQUEST", f"Field {name} must be a YYYY-MM-DD string")
        return parse_date(v)
    return v


def opt_field(data, name, kind, default=None):
    if name not in data or data[name] is None:
        return default
    return req_field(data, name, kind)


def req_enum(data, name, allowed):
    v = req_field(data, name, "str")
    if v not in allowed:
        raise err("ERR_INVALID_REQUEST",
                  f"Field {name} must be one of {sorted(allowed)}")
    return v


def req_enum_list(data, name, allowed):
    vals = req_field(data, name, "list")
    for v in vals:
        if not isinstance(v, str) or v not in allowed:
            raise err("ERR_INVALID_REQUEST",
                      f"Field {name} entries must be one of {sorted(allowed)}")
    return list(vals)


def parse_datetime(s):
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Invalid ISO 8601 datetime: {s}")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s.strip()):
        raise err("ERR_INVALID_REQUEST", f"Invalid YYYY-MM-DD date: {s}")
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise err("ERR_INVALID_REQUEST", f"Invalid calendar date: {s}")


# ---------------------------------------------------------------- pagination
def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "offset must be an integer")
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(items, serializer):
    """items: full filtered collection of entity dicts. Returns response."""
    limit, offset = pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(e) for e in page], limit, offset, total)


# ---------------------------------------------------------------- serialization
def pub(entity):
    """Strip internal fields (underscore-prefixed) for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}
