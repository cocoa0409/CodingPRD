import re
import secrets
import string
from datetime import datetime, timezone, time as dtime

from flask import request, jsonify

from errors import ApiError

ROLES = [
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
]

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def new_request_id():
    return "req_" + "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
    )


def wall_ts():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt3(dt):
    """ISO 8601 UTC with three fractional digits (common fields)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_ts(dt):
    """ISO 8601 UTC second precision (timestamps of record)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def ok(data, code=200):
    meta = {"api_request_id": new_request_id(), "api_request_timestamp": wall_ts()}
    return jsonify({"meta": meta, "response_type": "object", "data": data}), code


def ok_list(items, total, limit, offset):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": wall_ts(),
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(items)) < total,
    }
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(error_id, status, message):
    meta = {"api_request_id": new_request_id(), "api_request_timestamp": wall_ts()}
    return (
        jsonify(
            {
                "meta": meta,
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


# ---------------------------------------------------------------------------
# Auth (validation priority 1 and 2)
# ---------------------------------------------------------------------------

def auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        uid is None
        or uid.strip() == ""
        or role is None
        or role.strip() == ""
        or role not in ROLES
    ):
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must both be present and non-empty, "
            "and X-User-Role must be one of the declared roles",
        )
    return uid, role


def require_roles(*allowed):
    uid, role = auth()
    if role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "Role not permitted for this endpoint",
        )
    return uid, role


# ---------------------------------------------------------------------------
# Body parsing / field validation (priority 4)
# ---------------------------------------------------------------------------

def invalid(msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


def body():
    b = request.get_json(silent=True)
    if isinstance(b, dict):
        return b
    return {}


def reject_unknown(b, allowed):
    for k in b:
        if k not in allowed:
            invalid(f"Unexpected or server-managed field in request body: {k}")


def f_str(b, name, required=True, default=None):
    v = b.get(name)
    if v is None:
        if required:
            invalid(f"Missing required field: {name}")
        return default
    if not isinstance(v, str):
        invalid(f"Field {name} must be a string")
    return v


def f_id(b, name):
    """Nullable string id field (absent or explicit null -> None)."""
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        invalid(f"Field {name} must be a string")
    return v


def f_bool(b, name, required=True, default=None):
    v = b.get(name)
    if v is None:
        if required:
            invalid(f"Missing required field: {name}")
        return default
    if not isinstance(v, bool):
        invalid(f"Field {name} must be a boolean")
    return v


def f_int(b, name, required=True, default=None, min_v=None):
    v = b.get(name)
    if v is None:
        if required:
            invalid(f"Missing required field: {name}")
        return default
    if isinstance(v, bool) or not isinstance(v, int):
        invalid(f"Field {name} must be an integer")
    if min_v is not None and v < min_v:
        invalid(f"Field {name} must be >= {min_v}")
    return v


def f_enum(b, name, choices, required=True, default=None):
    v = b.get(name)
    if v is None:
        if required:
            invalid(f"Missing required field: {name}")
        return default
    if not isinstance(v, str) or v not in choices:
        invalid(f"Field {name} must be one of {sorted(choices)}")
    return v


def f_date(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            invalid(f"Missing required field: {name}")
        return None
    if not isinstance(v, str) or not _DATE_RE.match(v):
        invalid(f"Field {name} must be an ISO date (YYYY-MM-DD)")
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except ValueError:
        invalid(f"Field {name} must be a valid ISO date (YYYY-MM-DD)")


def f_dt(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            invalid(f"Missing required field: {name}")
        return None
    if not isinstance(v, str):
        invalid(f"Field {name} must be an ISO 8601 timestamp")
    dt = parse_dt(v)
    if dt is None:
        invalid(f"Field {name} must be a valid ISO 8601 timestamp")
    return dt


def f_list_str(b, name, required=True):
    v = b.get(name)
    if v is None:
        if required:
            invalid(f"Missing required field: {name}")
        return []
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        invalid(f"Field {name} must be an array of strings")
    return list(v)


# ---------------------------------------------------------------------------
# Datetime / date parsing
# ---------------------------------------------------------------------------

def parse_dt(s):
    """Parse ISO 8601 timestamp to aware UTC datetime truncated to seconds."""
    if not isinstance(s, str):
        return None
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def end_of_day(d):
    return datetime.combine(d, dtime(23, 59, 59), tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Pagination (limit/offset; defaults 10/0; clamped to [1,100] / >=0)
# ---------------------------------------------------------------------------

def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            invalid("Query parameter limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid("Query parameter offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(records, serializer):
    """records: list of entity dicts; sorts by created_at asc (insertion order
    tiebreak), applies limit/offset, returns the Flask response."""
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset : offset + limit]
    return ok_list([serializer(r) for r in page], total, limit, offset)
