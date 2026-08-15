"""Response envelope, auth header extraction, body validation, pagination,
and ISO-8601 datetime helpers — all field names per SCAFFOLD/PRD §2."""

import random
import string
import uuid
from datetime import date, datetime, timezone

from flask import jsonify, request

from errors import (err_unauthenticated, err_unauthorized_role, err_validation,
                    err_not_found, err_forbidden_ownership)
from store import DB

ALL_ROLES = [
    "PUBLIC", "FESTIVAL_ADMIN", "FILMMAKER", "PROGRAMMER", "PROGRAM_CHAIR",
    "FESTIVAL_DIRECTOR", "SCHEDULING_OPS", "TRAVEL_COORDINATOR", "JUROR",
    "AWARDS_ADMIN",
]
AUTHENTICATED_ROLES = [r for r in ALL_ROLES if r != "PUBLIC"]


# ---------------------------------------------------------------- timestamps
def now():
    """The single logical clock; never the wall clock."""
    return DB.clock


def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value, field="timestamp"):
    if not isinstance(value, str):
        raise err_validation("Field '%s' must be an ISO 8601 datetime string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise err_validation("Field '%s' is not a valid ISO 8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value, field="date"):
    if not isinstance(value, str):
        raise err_validation("Field '%s' must be an ISO 8601 date string" % field)
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise err_validation("Field '%s' is not a valid ISO 8601 date" % field)


def new_id():
    return str(uuid.uuid4())


# ------------------------------------------------------------------ envelope
def _meta_base(pagination=None):
    meta = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=22)),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta_base(pagination),
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------- auth
def auth():
    """Step 1 of §2.9: both headers present and role declared."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise err_unauthenticated()
    return uid, role


def require_role(role, roles):
    """Step 2 of §2.9."""
    if role not in roles:
        raise err_unauthorized_role()


def check_ownership(cond):
    """Step 4 of §2.9 (entity-backed ownership)."""
    if not cond:
        raise err_forbidden_ownership()


def get_or_404(table, rid):
    rec = table.get(rid)
    if rec is None:
        raise err_not_found()
    return rec


# ---------------------------------------------------------------------- body
def get_body():
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err_validation("Request body must be valid JSON")
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def _present(body, field):
    return field in body and body[field] is not None


def v_str(body, field, required=True):
    if not _present(body, field):
        if required:
            raise err_validation("Missing required field: %s" % field)
        return None
    if not isinstance(body[field], str) or body[field] == "":
        raise err_validation("Field '%s' must be a non-empty string" % field)
    return body[field]


def v_int(body, field, required=True, min_v=None, max_v=None):
    if not _present(body, field):
        if required:
            raise err_validation("Missing required field: %s" % field)
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("Field '%s' must be an integer" % field)
    if min_v is not None and v < min_v:
        raise err_validation("Field '%s' is below its minimum" % field)
    if max_v is not None and v > max_v:
        raise err_validation("Field '%s' exceeds its maximum" % field)
    return v


def v_num(body, field, required=True):
    if not _present(body, field):
        if required:
            raise err_validation("Missing required field: %s" % field)
        return None
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise err_validation("Field '%s' must be a number" % field)
    return v


def v_bool(body, field, required=True):
    if not _present(body, field):
        if required:
            raise err_validation("Missing required field: %s" % field)
        return None
    if not isinstance(body[field], bool):
        raise err_validation("Field '%s' must be a boolean" % field)
    return body[field]


def v_enum(body, field, values, required=True):
    v = v_str(body, field, required)
    if v is None:
        return None
    if v not in values:
        raise err_validation("Field '%s' must be one of %s" % (field, values))
    return v


def v_arr(body, field, required=True, item_enum=None):
    if not _present(body, field):
        if required:
            raise err_validation("Missing required field: %s" % field)
        return None
    v = body[field]
    if not isinstance(v, list):
        raise err_validation("Field '%s' must be an array" % field)
    if item_enum is not None:
        for item in v:
            if item not in item_enum:
                raise err_validation("Field '%s' contains an invalid value" % field)
    return v


def v_dt(body, field, required=True):
    if not _present(body, field):
        if required:
            raise err_validation("Missing required field: %s" % field)
        return None
    return parse_dt(body[field], field)


def v_date(body, field, required=True):
    if not _present(body, field):
        if required:
            raise err_validation("Missing required field: %s" % field)
        return None
    return parse_date(body[field], field)


# ---------------------------------------------------------------- pagination
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit, offset = 10, 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def paginate(items):
    """Items must already be sorted. Returns (page, pagination-meta)."""
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


def created_key(rec):
    """created_at ASC ordering with a deterministic creation-order tiebreak."""
    return (rec["created_at"], rec["_seq"])
