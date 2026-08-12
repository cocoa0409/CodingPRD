"""Core infrastructure: in-memory store, logical clock, response envelope,
error type, auth extraction, body validation helpers, pagination."""

import re
import uuid
import random
import string
import threading
from datetime import datetime, date, timedelta, timezone

from flask import request

# ----------------------------------------------------------------------------
# In-memory data store (module-level; wiped on every process boot)
# ----------------------------------------------------------------------------


class DB:
    def __init__(self):
        self.clients = {}
        self.family_members = {}
        self.drivers = {}
        self.compliance_docs = {}
        self.rate_cards = {}
        self.standing_rides = {}
        self.rides = {}
        self.assignments = {}
        self.ride_events = {}
        self.invoices = {}
        self.invoice_lines = {}
        self.payments = {}
        self.ops_epoch = 0
        self.seq = 0  # monotonic insertion sequence for stable ordering
        # logical clock: default exactly 2026-05-01T00:00:00Z
        self.clock = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.lock = threading.RLock()


db = DB()


def next_seq():
    db.seq += 1
    return db.seq


def new_id():
    return str(uuid.uuid4())


def now():
    """Current logical time (UTC, tz-aware)."""
    return db.clock


def today():
    return db.clock.date()


# ----------------------------------------------------------------------------
# Timestamp / date formatting and parsing
# ----------------------------------------------------------------------------


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-05-01T00:00:00.000Z"""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_date(d):
    if d is None:
        return None
    if isinstance(d, datetime):
        d = d.date()
    return d.isoformat()


def parse_datetime(s):
    """Parse an ISO 8601 datetime. Returns tz-aware UTC datetime or None."""
    if not isinstance(s, str):
        return None
    txt = s.strip()
    try:
        if txt.endswith("Z") or txt.endswith("z"):
            txt = txt[:-1] + "+00:00"
        dt = datetime.fromisoformat(txt)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Parse a strict YYYY-MM-DD date. Returns date or None."""
    if not isinstance(s, str):
        return None
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", s.strip()):
        return None
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


# ----------------------------------------------------------------------------
# Errors
# ----------------------------------------------------------------------------


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err_invalid(msg="Invalid request"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_unauthenticated(msg="Missing or unrecognized authentication headers"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_unauthorized_role(msg="Role not permitted for this operation"):
    return ApiError("ERR_UNAUTHORIZED_ROLE", 403, msg)


def err_forbidden(msg="Caller does not own the target resource"):
    return ApiError("ERR_FORBIDDEN_OWNERSHIP", 403, msg)


def err_family_access(msg="Family member access level insufficient or membership revoked"):
    return ApiError("ERR_FAMILY_ACCESS_INSUFFICIENT", 403, msg)


def err_not_found(msg="Referenced resource does not exist"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


# ----------------------------------------------------------------------------
# Response envelope
# ----------------------------------------------------------------------------


def make_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def ok(data, status=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": make_request_id(),
        "api_request_timestamp": fmt_ts(now()),
    }
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data,
    }
    return body, status


def error_body(error_id, message):
    return {
        "meta": {
            "api_request_id": make_request_id(),
            "api_request_timestamp": fmt_ts(now()),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ----------------------------------------------------------------------------
# Pagination
# ----------------------------------------------------------------------------


def parse_pagination():
    """Parse limit/offset query params. Raises ApiError(ERR_INVALID_REQUEST)."""
    qs = request.args
    raw_limit = qs.get("limit")
    raw_offset = qs.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err_invalid("limit must be an integer")
        if str(raw_limit).strip() != str(limit) and not re.fullmatch(r"[+-]?\d+", str(raw_limit).strip()):
            raise err_invalid("limit must be an integer")
        if limit < 1 or limit > 100:
            raise err_invalid("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err_invalid("offset must be an integer")
        if not re.fullmatch(r"[+-]?\d+", str(raw_offset).strip()):
            raise err_invalid("offset must be an integer")
        if offset < 0:
            raise err_invalid("offset must be non-negative")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


# ----------------------------------------------------------------------------
# Auth / caller context
# ----------------------------------------------------------------------------

ROLES = {
    "PlatformAdmin",
    "Coordinator",
    "ComplianceOfficer",
    "BillingAdmin",
    "Client",
    "FamilyMember",
    "Driver",
}


class Caller:
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id


def get_caller():
    """Priority 2: authentication. Returns Caller or raises ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or user_id is None or user_id == "":
        raise err_unauthenticated()
    if role not in ROLES:
        raise err_unauthenticated("Unrecognized X-User-Role")
    return Caller(role, user_id)


def require_role(caller, allowed):
    """Priority 3: role gate."""
    if caller.role not in allowed:
        raise err_unauthorized_role()


def family_member_of(caller):
    """Resolve the FamilyMember row for a FamilyMember caller (or None)."""
    return db.family_members.get(caller.user_id)


def check_family_active(caller):
    """Member row must exist and be ACTIVE; used before tier checks."""
    member = family_member_of(caller)
    if member is None:
        raise err_forbidden("Family member not recognized")
    if member["status"] != "ACTIVE":
        raise err_family_access("Family membership is revoked")
    return member


def require_family_tier(caller, tiers):
    member = check_family_active(caller)
    if member["access_level"] not in tiers:
        raise err_family_access("Family member access tier does not permit this action")
    return member


# ----------------------------------------------------------------------------
# Body validation
# ----------------------------------------------------------------------------


def get_body():
    """Return parsed JSON object body; {} when absent. Malformed -> 400."""
    if not request.data:
        return {}
    try:
        body = request.get_json(force=True, silent=False)
    except Exception:
        raise err_invalid("Request body is not valid JSON")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise err_invalid("Request body must be a JSON object")
    return body


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def field_str(body, name, required=False, allow_empty=True):
    if name not in body or body[name] is None:
        if required:
            raise err_invalid(f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, str):
        raise err_invalid(f"Field {name} must be a string")
    if not allow_empty and v == "":
        raise err_invalid(f"Field {name} must be a non-empty string")
    return v


def field_int(body, name, required=False, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        if required:
            raise err_invalid(f"Missing required field: {name}")
        return None
    v = body[name]
    if not _is_int(v):
        raise err_invalid(f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        raise err_invalid(f"Field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        raise err_invalid(f"Field {name} must be <= {maximum}")
    return v


def field_bool(body, name, required=False):
    if name not in body or body[name] is None:
        if required:
            raise err_invalid(f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, bool):
        raise err_invalid(f"Field {name} must be a boolean")
    return v


def field_enum(body, name, values, required=False):
    if name not in body or body[name] is None:
        if required:
            raise err_invalid(f"Missing required field: {name}")
        return None
    v = body[name]
    if not isinstance(v, str) or v not in values:
        raise err_invalid(f"Field {name} must be one of {sorted(values)}")
    return v


def field_date(body, name, required=False):
    if name not in body or body[name] is None:
        if required:
            raise err_invalid(f"Missing required field: {name}")
        return None
    d = parse_date(body[name])
    if d is None:
        raise err_invalid(f"Field {name} must be a YYYY-MM-DD date")
    return d


def field_datetime(body, name, required=False):
    if name not in body or body[name] is None:
        if required:
            raise err_invalid(f"Missing required field: {name}")
        return None
    dt = parse_datetime(body[name])
    if dt is None:
        raise err_invalid(f"Field {name} must be an ISO 8601 datetime")
    return dt


# ----------------------------------------------------------------------------
# Common record helpers
# ----------------------------------------------------------------------------


def stamp_new(rec):
    ts = now()
    rec["id"] = new_id()
    rec["created_at"] = ts
    rec["updated_at"] = ts
    rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Mutate: refresh updated_at and increment version."""
    rec["updated_at"] = now()
    rec["version"] += 1


def sort_created(items):
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
