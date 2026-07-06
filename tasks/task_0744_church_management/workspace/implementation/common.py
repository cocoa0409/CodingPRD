"""Shared helpers: UUID, timestamps, response envelope, clock, common-fields."""

import uuid
import secrets
import string
from datetime import datetime, timezone, timedelta

from flask import jsonify, request

import db


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_letters + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def wall_now_iso():
    """Wall clock UTC ISO8601 with milliseconds. Used only for meta.api_request_timestamp."""
    dt = datetime.now(timezone.utc)
    ms = dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return ms


def clock_now_iso():
    """Logical clock (§2.6) — used for created_at, updated_at, posted_at, etc."""
    return db.get_clock_iso()


def clock_now_dt():
    """Parse the current logical clock as a UTC datetime."""
    return parse_iso8601(db.get_clock_iso())


def parse_iso8601(v):
    """Parse an ISO8601 datetime string; return an aware UTC datetime.
    Accepts: Z-suffix or +00:00 style; optional fractional seconds.
    """
    if not isinstance(v, str):
        raise ValueError("not-a-string")
    s = v.strip()
    # Normalize trailing Z to +00:00 for fromisoformat compatibility.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(v):
    """Parse an ISO YYYY-MM-DD date string; return a date object."""
    if not isinstance(v, str):
        raise ValueError("not-a-string")
    # Accept only exact YYYY-MM-DD form.
    return datetime.strptime(v, "%Y-%m-%d").date()


def format_iso8601(dt):
    """Format a datetime as ISO8601 UTC with millisecond precision, Z suffix."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---- Common fields (§2.4) --------------------------------------------------


def stamp_common_create(record):
    """Set id/created_at/updated_at/version for a new record. Uses the logical clock."""
    now = db.get_clock_iso()
    record["id"] = record.get("id") or new_id()
    record["created_at"] = now
    record["updated_at"] = now
    record["version"] = 1
    return record


def bump(record):
    """Increment version and refresh updated_at on a mutation (or cascade)."""
    record["updated_at"] = db.get_clock_iso()
    record["version"] = int(record.get("version", 0)) + 1
    return record


# ---- Response envelope -----------------------------------------------------


def success(data, status=200, meta_extra=None):
    is_array = isinstance(data, list)
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if meta_extra:
        meta.update(meta_extra)
    body = {
        "meta": meta,
        "response_type": "array" if is_array else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def error_response(error_id, http_status, message=""):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": wall_now_iso(),
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status


# ---- Auth (§2.1) -----------------------------------------------------------

VALID_ROLES = {"Registrar", "FinanceAdmin", "Coordinator", "Member", "PlatformAdmin"}


def get_role_and_user():
    return request.headers.get("X-User-Role"), request.headers.get("X-User-ID")


def require_role(allowed):
    """Priority-1: auth header present and one of the five declared roles.
    Priority-2: acting role is one of `allowed` (PlatformAdmin is always allowed
    where present; every business endpoint lists it explicitly per PRD §2.1).
    Returns (role, user_id). Raises ApiError on failure."""
    from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

    role, user_id = get_role_and_user()
    if role is None or role not in VALID_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "X-User-Role missing or invalid")
    if role not in allowed:
        raise_err(ERR_FORBIDDEN, f"Role {role} not authorized for this endpoint")
    return role, user_id


# ---- Pagination ------------------------------------------------------------


def get_pagination():
    """Return (limit, offset). Raises ERR_INVALID_REQUEST on out-of-range."""
    from errors import raise_err, ERR_INVALID_REQUEST

    args = request.args
    limit_raw = args.get("limit", "10")
    offset_raw = args.get("offset", "0")
    try:
        limit = int(limit_raw)
        offset = int(offset_raw)
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_REQUEST, "limit must be in [1, 100]")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate_list(records, limit, offset):
    """Sort by created_at ASC (§2.3), paginate, return (page, meta)."""
    sorted_records = sorted(records, key=lambda r: r.get("created_at", ""))
    total = len(sorted_records)
    page = sorted_records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


# ---- Existence helpers -----------------------------------------------------


def must_exist(store, resource_id, label=""):
    from errors import raise_err, ERR_NOT_FOUND

    if resource_id is None or resource_id not in store:
        raise_err(ERR_NOT_FOUND, f"{label} {resource_id!r} not found")
    return store[resource_id]


# ---- JSON body helper ------------------------------------------------------


def get_json_body():
    """Return the JSON body as a dict; on parse failure or non-object, raise ERR_INVALID_REQUEST."""
    from errors import raise_err, ERR_INVALID_REQUEST

    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "body must be a JSON object")
    return body


def add_days_iso(date_str, days):
    """Given YYYY-MM-DD, return a date `days` days later."""
    d = parse_iso_date(date_str)
    return d + timedelta(days=days)
