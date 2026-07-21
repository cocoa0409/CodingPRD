"""Core shared infrastructure: in-memory store, logical clock, response
envelope, auth, errors, and small helpers.  All structural names (headers,
envelope fields, pagination params, error ids) are taken verbatim from the
scaffold / PRD.
"""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
ROLES = {"DeskExaminer", "FieldAdjuster", "QAReviewer", "LicensingAdmin", "BillingManager"}

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id

# ---------------------------------------------------------------------------
# Logical clock (single source of "now" for business rules)
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {"clock": DEFAULT_CLOCK, "seq": 0}


def current_clock():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def next_seq():
    _state["seq"] += 1
    return _state["seq"]


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime.  Raises ValueError
    on anything that is not a well-formed datetime string."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# In-memory store — empty on every boot, never seeded.
# ---------------------------------------------------------------------------
COLLECTIONS = [
    "adjusters", "licenses", "cat_events", "deployments", "claims",
    "assignments", "inspections", "estimates", "reports", "time_entries",
    "fee_schedules", "fee_bills", "payments",
]

DB = {name: {} for name in COLLECTIONS}


def new_id():
    return str(uuid.uuid4())


def base_record(with_version=True):
    now = iso(current_clock())
    rec = {"id": new_id(), "created_at": now, "_seq": next_seq()}
    if with_version:
        rec["updated_at"] = now
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump updated_at + version on a mutable resource (cascade-safe)."""
    if "version" in rec:
        rec["updated_at"] = iso(current_clock())
        rec["version"] += 1


def fetch(collection, rid, not_found_error):
    rec = DB[collection].get(rid)
    if rec is None:
        raise ApiError(not_found_error, 404)
    return rec


def serialize(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require_ctx(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400)
    if role not in allowed_roles:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403)
    return uid, role


ALL_ROLES = ROLES  # every role may call every read endpoint


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {
        "api_request_id": _req_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }
    if extra:
        m.update(extra)
    return m


def respond(data, status=200, response_type="object", pagination=None):
    body = {"meta": _meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


def respond_object(rec, status=200):
    return respond(serialize(rec), status=status, response_type="object")


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Pagination + list helpers
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    raw_limit = args.get("limit", None)
    raw_offset = args.get("offset", None)
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit out of range")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset out of range")
    return limit, offset


def list_response(collection, filters=None):
    """Filter, order by created_at asc (stable by insertion seq), paginate."""
    limit, offset = parse_pagination()
    items = list(DB[collection].values())
    if filters:
        for field, val in filters.items():
            if val is not None:
                items = [r for r in items if str(r.get(field)) == str(val)]
    items.sort(key=lambda r: (r["created_at"], r["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    data = [serialize(r) for r in page]
    return respond(data, status=200, response_type="array", pagination=pagination)


# ---------------------------------------------------------------------------
# Body helpers / validation
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if body.get(f) is None:
            raise ApiError("ERR_INVALID_REQUEST", 400, "missing field: %s" % f)


def require_enum(value, allowed, field):
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid %s" % field)


def require_str(value, field):
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid %s" % field)


def require_int(value, field, minimum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid %s" % field)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid %s" % field)
    return value


# ---------------------------------------------------------------------------
# Rounding helpers (money)
# ---------------------------------------------------------------------------
def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def floor_dec(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_FLOOR))
