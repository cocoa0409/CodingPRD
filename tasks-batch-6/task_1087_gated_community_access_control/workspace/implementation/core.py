"""Core infrastructure: in-memory store, logical clock, response envelope,
auth, error handling, and small numeric/temporal helpers.

Every structural name (headers, envelope fields, error ids, pagination params)
is taken verbatim from PRD.md / SCAFFOLD.yaml.
"""
import math
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request, jsonify

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLES = {"CommunityAdmin", "SecurityOfficer", "Resident"}

# ---------------------------------------------------------------------------
# Business constants (SCAFFOLD 1.3)
# ---------------------------------------------------------------------------
GUEST_HOURLY_CENTS = 0
VENDOR_HOURLY_CENTS = 500
OVERSTAY_SURCHARGE_CENTS_PER_HOUR = 2000
OVERAGE_MULTIPLIER = 2
REPEAT_WINDOW_DAYS = 180
DELINQUENT_SURCHARGE_CENTS = 5000
FINE_CAP_CENTS = 50000
LATE_FEE_PCT = Decimal("0.015")
DELINQUENCY_THRESHOLD_CENTS = 25000
PATROL_BUFFER_MINUTES = 60

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------------------
# In-memory store — starts EMPTY on every boot (no seeding).
# ---------------------------------------------------------------------------
class DB:
    def __init__(self):
        self.communities = {}
        self.residents = {}
        self.vehicles = {}
        self.decals = {}
        self.passes = {}
        self.gate_events = {}
        self.amenities = {}
        self.reservations = {}
        self.patrols = {}
        self.incidents = {}
        self.violations = {}
        self.clock = DEFAULT_CLOCK
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = DB()


def now():
    return db.clock


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
# Datetime helpers
# ---------------------------------------------------------------------------
def parse_dt(value):
    if not isinstance(value, str):
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    t = value.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 400, "invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def round_half_up(value):
    """Round a Decimal/number to the nearest whole cent, half-up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hours_ceil(seconds):
    """Ceiling of a span of seconds into whole hours; never negative."""
    if seconds <= 0:
        return 0
    return int(math.ceil(seconds / 3600.0))


def span_seconds(later, earlier):
    return int((later - earlier).total_seconds())


# ---------------------------------------------------------------------------
# Entity base fields (PRD 2.5)
# ---------------------------------------------------------------------------
def base_entity():
    t = now()
    return {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(obj):
    """Any stored-state change refreshes updated_at and bumps version."""
    obj["updated_at"] = now()
    obj["version"] += 1


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(obj):
    out = {}
    for k, v in obj.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            out[k] = fmt_dt(v)
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _request_id(), "api_request_timestamp": fmt_dt(now())}
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, limit, offset, total_count):
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + len(items) < total_count,
    }
    body = {"meta": _meta(meta_extra), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Auth (PRD 2.1)
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
    return uid, role


def forbid(msg="Forbidden"):
    raise ApiError("ERR_UNAUTHORIZED", 403, msg)


# ---------------------------------------------------------------------------
# Existence lookup (PRD 2.9 — left-to-right, resource-specific not-found)
# ---------------------------------------------------------------------------
def lookup(collection, oid, err_id):
    obj = collection.get(oid)
    if obj is None:
        raise ApiError(err_id, 404, f"Not found: {oid}")
    return obj


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    if not request.data:
        return {}
    body = request.get_json(silent=True)
    if body is None:
        raise ApiError("ERR_VALIDATION", 400, "Malformed JSON body")
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "Body must be a JSON object")
    return body


def require(body, field):
    if field not in body or body[field] is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {field}")
    return body[field]


def require_str(body, field):
    v = require(body, field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", 400, f"Field must be a non-empty string: {field}")
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"Field must be a string: {field}")
    return v


def require_enum(body, field, allowed):
    v = require_str(body, field)
    if v not in allowed:
        raise ApiError("ERR_VALIDATION", 400, f"Invalid value for {field}")
    return v


def require_int(body, field, minimum=None, maximum=None):
    v = require(body, field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"Field must be an integer: {field}")
    if minimum is not None and v < minimum:
        raise ApiError("ERR_VALIDATION", 400, f"Field below minimum: {field}")
    if maximum is not None and v > maximum:
        raise ApiError("ERR_VALIDATION", 400, f"Field above maximum: {field}")
    return v


def opt_bool(body, field, default):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"Field must be a boolean: {field}")
    return v


def require_dt(body, field):
    return parse_dt(require(body, field))


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit = args.get("limit", None)
    offset = args.get("offset", None)
    if limit is None:
        limit_v = 10
    else:
        try:
            limit_v = int(limit)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit_v < 1 or limit_v > 100:
            raise ApiError("ERR_VALIDATION", 400, "limit out of range")
    if offset is None:
        offset_v = 0
    else:
        try:
            offset_v = int(offset)
        except (ValueError, TypeError):
            raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset_v < 0:
            raise ApiError("ERR_VALIDATION", 400, "offset out of range")
    return limit_v, offset_v


def paginate(rows):
    """rows: list of stored objects. Sort by created_at asc (stable via _seq)."""
    limit, offset = parse_pagination()
    rows = sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    return [serialize(r) for r in page], limit, offset, total
