"""Envelope, auth, parsing, and pagination helpers (names per scaffold §1.0/§1.4)."""
import re
import uuid
from datetime import datetime, timezone

from flask import request, jsonify

from store import db
from errors import ApiError

ALL_ROLES = ["HrisAnalyst", "DataSteward", "ChangeApprover", "IntegrationOperator", "SecurityAdmin"]


def new_id():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + uuid.uuid4().hex[:24]


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_clock(dt):
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def clock_date():
    return db.clock.date()


def ok(data, code=200, is_list=False, pagination=None):
    meta = {"api_request_id": new_req_id(), "api_request_timestamp": fmt_ts(db.clock)}
    if pagination is not None:
        meta.update(pagination)
    return jsonify({
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }), code


def error_body(error_id, message):
    return {
        "meta": {"api_request_id": new_req_id(), "api_request_timestamp": fmt_ts(db.clock)},
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def auth(roles):
    uid = request.headers.get("X-User-ID", "")
    role = request.headers.get("X-User-Role", "")
    if not uid or not uid.strip() or not role or not role.strip():
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "X-User-ID and X-User-Role headers must be present and non-empty")
    if role not in roles:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       "Role not permitted for this endpoint")
    return uid


def body():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "JSON object body required")
    return b


def inv(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def req_field(b, name):
    if name not in b or b[name] is None:
        raise inv("Missing required field: %s" % name)
    return b[name]


def parse_date_val(v, what="date"):
    if not isinstance(v, str):
        raise inv("Invalid %s" % what)
    try:
        return datetime.strptime(v.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise inv("Invalid %s: %r" % (what, v))


def parse_int_val(v, what="integer"):
    if isinstance(v, bool):
        raise inv("Invalid %s" % what)
    if isinstance(v, int):
        return v
    if isinstance(v, str) and re.fullmatch(r"-?\d+", v.strip()):
        return int(v.strip())
    raise inv("Invalid %s: %r" % (what, v))


def parse_instant(v):
    if not isinstance(v, str):
        raise inv("Invalid ISO 8601 instant")
    s = v.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        raise inv("Invalid ISO 8601 instant: %r" % v)


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise inv("limit must be an integer")
        if limit < 1:
            raise inv("limit must be >= 1")
        if limit > 100:
            limit = 100
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise inv("offset must be an integer")
        if offset < 0:
            raise inv("offset must be >= 0")
    return limit, offset


def sorted_items(coll):
    """List default sort: created_at ascending, insertion order breaks ties."""
    return sorted(coll, key=lambda e: (e["created_at"], e["_seq"]))


def list_page(items, serializer):
    limit, offset = pagination_params()
    items = sorted_items(list(items))
    total = len(items)
    page = items[offset:offset + limit]
    return ok([serializer(i) for i in page], is_list=True, pagination={
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })


def new_entity(coll):
    """Common system fields for a fresh resource (id/created_at/updated_at/version)."""
    eid = new_id()
    return {
        "id": eid,
        "_seq": next(db.seq),
        "created_at": db.clock,
        "updated_at": db.clock,
        "version": 1,
    }
