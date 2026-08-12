"""Shared helpers: errors, envelope, auth, pagination, datetime, validators."""
import secrets
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from store import db

ALL_ROLES = (
    "FestivalDirector",
    "VendorManager",
    "OperationsLead",
    "HealthInspector",
    "SustainabilityOfficer",
    "FinanceLead",
    "Vendor",
)


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(10),
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }


def success(data, code=200, response_type="object", pagination=None):
    body = {"meta": _meta(), "response_type": response_type, "data": data}
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), code


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Datetime
# ---------------------------------------------------------------------------

def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits (system timestamps)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def fmt_dt(dt):
    """Canonical ISO 8601 UTC for client-supplied instants and the clock.

    Omits the fractional part when it is zero so the startup clock renders
    exactly as 2026-05-01T00:00:00Z.
    """
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        frac = f"{dt.microsecond:06d}".rstrip("0")
        return f"{base}.{frac}Z"
    return base + "Z"


def parse_dt(value, field):
    if not isinstance(value, str) or not value.strip():
        err("ERR_INVALID_REQUEST", 400, f"Field '{field}' must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        err("ERR_INVALID_REQUEST", 400, f"Field '{field}' must be an ISO 8601 datetime string")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Auth / roles
# ---------------------------------------------------------------------------

def ctx():
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role:
        err("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
            "X-User-ID and X-User-Role headers are required and must be non-empty")
    return uid, role


def require_role(*roles):
    uid, role = ctx()
    if role not in roles:
        err("ERR_FORBIDDEN_FOR_ROLE", 403, f"Role '{role}' is not permitted for this endpoint")
    return uid, role


# ---------------------------------------------------------------------------
# Body / field validators
# ---------------------------------------------------------------------------

def body_json():
    raw = request.get_data()
    if not raw:
        return {}
    b = request.get_json(silent=True)
    if b is None:
        err("ERR_INVALID_REQUEST", 400, "Request body must be valid JSON")
    if not isinstance(b, dict):
        err("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return b


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or not v.strip():
        err("ERR_INVALID_REQUEST", 400, f"Field '{name}' is required and must be a non-empty string")
    return v


def opt_str(b, name):
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        err("ERR_INVALID_REQUEST", 400, f"Field '{name}' must be a string")
    return v


def req_int(b, name, min_v=None, max_v=None):
    v = b.get(name)
    if not _is_int(v):
        err("ERR_INVALID_REQUEST", 400, f"Field '{name}' is required and must be an integer")
    if min_v is not None and v < min_v:
        err("ERR_INVALID_REQUEST", 400, f"Field '{name}' must be >= {min_v}")
    if max_v is not None and v > max_v:
        err("ERR_INVALID_REQUEST", 400, f"Field '{name}' must be <= {max_v}")
    return v


def opt_int(b, name, min_v=None, max_v=None):
    v = b.get(name)
    if v is None:
        return None
    if not _is_int(v):
        err("ERR_INVALID_REQUEST", 400, f"Field '{name}' must be an integer")
    if min_v is not None and v < min_v:
        err("ERR_INVALID_REQUEST", 400, f"Field '{name}' must be >= {min_v}")
    if max_v is not None and v > max_v:
        err("ERR_INVALID_REQUEST", 400, f"Field '{name}' must be <= {max_v}")
    return v


def req_bool(b, name):
    v = b.get(name)
    if not isinstance(v, bool):
        err("ERR_INVALID_REQUEST", 400, f"Field '{name}' is required and must be a boolean")
    return v


def req_enum(b, name, allowed):
    v = b.get(name)
    if not isinstance(v, str) or v not in allowed:
        err("ERR_INVALID_REQUEST", 400,
            f"Field '{name}' is required and must be one of {sorted(allowed)}")
    return v


def opt_enum(b, name, allowed):
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        err("ERR_INVALID_REQUEST", 400, f"Field '{name}' must be one of {sorted(allowed)}")
    return v


def req_dt(b, name):
    return parse_dt(b.get(name), name)


# ---------------------------------------------------------------------------
# Existence / records
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def stamp_new(rec):
    rec["created_at"] = db.clock
    rec["updated_at"] = db.clock
    rec["version"] = 1
    return rec


def touch(rec):
    rec["updated_at"] = db.clock
    rec["version"] = rec.get("version", 1) + 1
    return rec


def get_or_404(collection, rid, error_id, label):
    rec = collection.get(rid) if isinstance(rid, str) else None
    if rec is None:
        err(error_id, 404, f"{label} '{rid}' does not exist")
    return rec


# ---------------------------------------------------------------------------
# Pagination / list helpers
# ---------------------------------------------------------------------------

def paginate_list(items):
    """items must already be filtered and sorted; applies limit/offset."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "Query parameter 'limit' must be an integer")
        if isinstance(limit, bool) or limit < 1 or limit > 100:
            err("ERR_INVALID_REQUEST", 400, "Query parameter 'limit' must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            err("ERR_INVALID_REQUEST", 400, "Query parameter 'offset' must be an integer")
        if isinstance(offset, bool) or offset < 0:
            err("ERR_INVALID_REQUEST", 400, "Query parameter 'offset' must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def list_response(records, serializer, filters):
    """filters: mapping of query-param name -> record key."""
    items = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    out = []
    for rec in items:
        ok = True
        for q, key in filters.items():
            v = request.args.get(q)
            if v is not None and str(rec.get(key)) != v:
                ok = False
                break
        if ok:
            out.append(rec)
    page, pagination = paginate_list(out)
    return success([serializer(r) for r in page], 200, "array", pagination)
