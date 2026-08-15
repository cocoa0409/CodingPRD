"""Shared helpers: error type, response envelope, auth, validation, pagination, time."""
import secrets
from datetime import datetime, timezone
from decimal import Decimal

from flask import request, jsonify


class ApiError(Exception):
    def __init__(self, status, error_id, message):
        super().__init__(message)
        self.status = status
        self.error_id = error_id
        self.message = message


ROLES = ("ClubOfficer", "Member", "EventCoordinator", "EquipmentChair")


# ----- time -----

def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value, field_name):
    if not isinstance(value, str):
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "%s must be an ISO 8601 datetime string" % field_name)
    s = value.strip()
    if s[-1:] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "%s is not a valid ISO 8601 datetime" % field_name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ----- envelope -----

def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": fmt_dt(datetime.now(timezone.utc)),
    }


def success(data, status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ----- auth -----

def actor(allowed_roles=None):
    """Validate X-User-Role / X-User-ID headers, then endpoint role permission."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not uid or role not in ROLES:
        raise ApiError(401, "ERR_UNAUTHENTICATED",
                       "Missing or invalid X-User-Role / X-User-ID headers")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError(403, "ERR_FORBIDDEN", "Role not permitted for this endpoint")
    return uid, role


def forbid(msg="Actor is not the owning Member"):
    raise ApiError(403, "ERR_FORBIDDEN", msg)


# ----- body / field validation -----

def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(400, "ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def field(data, name):
    if name not in data or data[name] is None:
        raise ApiError(400, "ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    return data[name]


def as_str(v, name):
    if not isinstance(v, str):
        raise ApiError(400, "ERR_INVALID_REQUEST", "%s must be a string" % name)
    return v


def as_int(v, name):
    if not isinstance(v, int) or isinstance(v, bool):
        raise ApiError(400, "ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return v


def as_bool(v, name):
    if not isinstance(v, bool):
        raise ApiError(400, "ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        raise ApiError(400, "ERR_INVALID_REQUEST",
                       "%s must be one of %s" % (name, ", ".join(allowed)))
    return v


def as_decimal(v, name):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(400, "ERR_INVALID_REQUEST", "%s must be a number" % name)
    try:
        return Decimal(str(v))
    except Exception:
        raise ApiError(400, "ERR_INVALID_REQUEST", "%s must be a number" % name)


def fk(data, name, table):
    """Body-referenced id existence (priority 4): 404 when a string id does not resolve."""
    v = data.get(name)
    if isinstance(v, str):
        ent = table.get(v)
        if ent is None:
            raise ApiError(404, "ERR_NOT_FOUND",
                           "%s does not reference an existing resource" % name)
        return ent
    return None


# ----- pagination -----

def paginate_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError(400, "ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError(400, "ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError(400, "ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError(400, "ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def sorted_items(table):
    """List responses are sorted by created_at ascending (seq breaks ties)."""
    return sorted(table.values(), key=lambda e: (e["created_at"], e["_seq"]))


def list_response(items, view):
    limit, offset = paginate_params()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return success([view(e) for e in page], 200, pagination)
