"""Shared helpers: time, envelope, validation, pagination, auth, rounding."""

import uuid
from datetime import datetime, date, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, g

from errors import err_unauthenticated, err_forbidden, err_validation
from store import DB

ROLES = {"RecAdmin", "LeagueCoordinator", "FacilityManager", "Member", "Staff"}

PAGE_DEFAULT_LIMIT = 10
PAGE_MIN_LIMIT = 1
PAGE_MAX_LIMIT = 100


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def now():
    return DB.now()


def today():
    return DB.now().date()


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2026-08-01T00:00:00.000Z."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO 8601 datetime; returns aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    s = value.strip()
    try:
        if s.endswith("Z") or s.endswith("z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def minutes_of_day(dt):
    return dt.hour * 60 + dt.minute + dt.second / 60.0 + dt.microsecond / 60000000.0


def seconds_of_day(dt):
    return dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1000000.0


# ---------------------------------------------------------------------------
# Decimal rounding (round-half-up; never float math for money)
# ---------------------------------------------------------------------------

def rhu_cents(value):
    """Round a Decimal to whole cents, half-up, returning an int."""
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu2(numer, denom):
    """round_half_up(numer/denom, 2) as Decimal."""
    return (Decimal(numer) / Decimal(denom)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def new_request_id():
    return "req_" + uuid.uuid4().hex[:20]


def meta_base():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": fmt_dt(now()),
    }


def envelope_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return body, status


def envelope_list(items, limit, offset, total_count):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return body, 200


def envelope_error(error_id, message, status):
    body = {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return body, status


# ---------------------------------------------------------------------------
# Request body / field validation
# ---------------------------------------------------------------------------

def body_json():
    """Return the request JSON body as a dict; empty/malformed -> {}."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_present(body, field):
    if field not in body or body[field] is None:
        raise err_validation(f"Missing required field: {field}")
    return body[field]


def req_str(body, field):
    v = req_present(body, field)
    if not isinstance(v, str) or not v.strip():
        raise err_validation(f"Field must be a non-empty string: {field}")
    return v


def req_int(body, field):
    v = req_present(body, field)
    if not is_int(v):
        raise err_validation(f"Field must be an integer: {field}")
    return v


def req_enum(body, field, allowed):
    v = req_present(body, field)
    if not isinstance(v, str) or v not in allowed:
        raise err_validation(f"Field {field} must be one of {sorted(allowed)}")
    return v


def req_dt(body, field):
    v = req_present(body, field)
    dt = parse_dt(v)
    if dt is None:
        raise err_validation(f"Field {field} must be an ISO 8601 datetime")
    return dt


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def authenticate():
    """Priority-1 auth check. Runs for every /v1 request."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip():
        raise err_unauthenticated("X-User-ID header missing or empty")
    if role is None or not role.strip():
        raise err_unauthenticated("X-User-Role header missing or empty")
    role = role.strip()
    if role not in ROLES:
        raise err_unauthenticated("X-User-Role is not a declared role")
    g.user_id = user_id.strip()
    g.role = role


def require_role(*roles):
    if g.role not in roles:
        raise err_forbidden()


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_validation("limit must be an integer")
        if is_int(raw_limit):
            limit = raw_limit
        limit = max(PAGE_MIN_LIMIT, min(PAGE_MAX_LIMIT, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_validation("offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def list_response(records, serializer):
    """records: pre-filtered list of dicts with created_at/_seq. Sorts by
    created_at ascending (creation order) and paginates."""
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    limit, offset = pagination_params()
    page = ordered[offset:offset + limit]
    return envelope_list([serializer(r) for r in page], limit, offset, total)


def matches(record, **filters):
    for key, val in filters.items():
        if val is not None and record.get(key) != val:
            return False
    return True


# ---------------------------------------------------------------------------
# Entity plumbing
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    ts = now()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = DB.next_seq()
    return rec


def touch(rec):
    rec["updated_at"] = now()
    rec["version"] += 1
