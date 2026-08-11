"""Response envelope, time helpers, pagination, structural validators, auth."""

import random
import string
from datetime import datetime, timezone, date
from functools import wraps

from flask import request, g, jsonify

from db import db, new_id
from errors import (
    ApiError, raise_err,
    ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
)

ROLE_NAMES = ("Provider", "Nurse", "CaregiverRole")


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_ts(s):
    """Parse an ISO 8601 timestamp to an aware UTC datetime. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        raise ValueError("bad timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse an ISO 8601 date. Raises ValueError."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    try:
        return date.fromisoformat(s)
    except Exception:
        raise ValueError("bad date")


def now_ts():
    return fmt_ts(db.now())


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD response_envelope / PRD §2.2)
# ---------------------------------------------------------------------------

def _meta():
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=16))
    return {
        "api_request_id": rid,
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, page_meta):
    m = _meta()
    m.update(page_meta)
    body = {"meta": m, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(error_id, status, message):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------

def stamp_new(rec, common=True):
    rec["id"] = new_id()
    rec["created_at"] = now_ts()
    rec["_seq"] = db.next_seq()
    if common:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and increments version (PRD §2.5)."""
    rec["updated_at"] = now_ts()
    rec["version"] = rec.get("version", 0) + 1


def pub(rec):
    """Public view: strip internal underscore-prefixed fields."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def sort_created(items):
    return sorted(items, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------

def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_INVALID_REQUEST, "limit out of range [1, 100]")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise_err(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, validations priority 1-2)
# ---------------------------------------------------------------------------

def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            uid = request.headers.get("X-User-ID")
            if not role or role not in ROLE_NAMES:
                raise_err(ERR_UNAUTHENTICATED, "missing or unknown X-User-Role header")
            if not uid:
                raise_err(ERR_UNAUTHENTICATED, "missing X-User-ID header")
            if role == "CaregiverRole" and uid not in db.caregivers:
                raise_err(ERR_UNAUTHENTICATED, "unknown caregiver identity")
            if role not in roles:
                raise_err(ERR_UNAUTHORIZED, "role not permitted on this endpoint")
            g.user_role = role
            g.user_id = uid
            return fn(*args, **kwargs)
        return wrapper
    return deco


# ---------------------------------------------------------------------------
# Existence + body helpers (validations priority 3, 22)
# ---------------------------------------------------------------------------

def get_or_404(coll, rid, what="resource"):
    if not isinstance(rid, str) or rid not in coll:
        raise_err(ERR_NOT_FOUND, f"{what} not found")
    return coll[rid]


def body():
    b = request.get_json(silent=True)
    if b is None:
        b = {}
    if not isinstance(b, dict):
        raise_err(ERR_INVALID_REQUEST, "request body must be a JSON object")
    return b


# ---------------------------------------------------------------------------
# Structural validators (priority 22 — checked last per PRD §2.9)
# ---------------------------------------------------------------------------

def need(b, field):
    if field not in b or b[field] is None:
        raise_err(ERR_INVALID_REQUEST, f"missing required field: {field}")
    return b[field]


def need_str(b, field):
    v = need(b, field)
    if not isinstance(v, str) or v == "":
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be a non-empty string")
    return v


def need_int(b, field):
    v = need(b, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be an integer")
    return v


def need_num(b, field):
    v = need(b, field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be a number")
    return v


def need_bool(b, field):
    v = need(b, field)
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be a boolean")
    return v


def opt_bool(b, field, default=False):
    if field not in b or b[field] is None:
        return default
    v = b[field]
    if not isinstance(v, bool):
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be a boolean")
    return v


def need_enum(b, field, allowed):
    v = need(b, field)
    if not isinstance(v, str) or v not in allowed:
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be one of {sorted(allowed)}")
    return v


def need_ts(b, field):
    v = need(b, field)
    try:
        return parse_ts(v)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be an ISO 8601 timestamp")


def need_date(b, field):
    v = need(b, field)
    try:
        return parse_date(v)
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be an ISO 8601 date")


def opt_ts(b, field):
    if field not in b or b[field] is None:
        return None
    try:
        return parse_ts(b[field])
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be an ISO 8601 timestamp")


def opt_date(b, field):
    if field not in b or b[field] is None:
        return None
    try:
        return parse_date(b[field])
    except ValueError:
        raise_err(ERR_INVALID_REQUEST, f"field {field} must be an ISO 8601 date")
