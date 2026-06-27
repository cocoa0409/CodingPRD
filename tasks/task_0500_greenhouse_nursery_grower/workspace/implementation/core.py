"""Foundation: in-memory store, logical clock, response envelope, errors, auth, validation helpers."""
import os
import re
import uuid
import random
import string
from datetime import datetime, timedelta, timezone

from flask import request, jsonify, g

# ---------------------------------------------------------------------------
# Error catalogue
# ---------------------------------------------------------------------------
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN = ("ERR_FORBIDDEN", 403)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 422)
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)
ERR_DUPLICATE_CULTIVAR = ("ERR_DUPLICATE_CULTIVAR", 409)
ERR_VARIETY_NOT_ACTIVE = ("ERR_VARIETY_NOT_ACTIVE", 409)
ERR_VARIETY_IN_USE = ("ERR_VARIETY_IN_USE", 409)
ERR_ZONE_NOT_OPEN = ("ERR_ZONE_NOT_OPEN", 409)
ERR_ZONE_NOT_EMPTY = ("ERR_ZONE_NOT_EMPTY", 409)
ERR_CLIMATE_MISMATCH = ("ERR_CLIMATE_MISMATCH", 409)
ERR_INVALID_STARTED_COUNT = ("ERR_INVALID_STARTED_COUNT", 422)
ERR_ZONE_CAPACITY_EXCEEDED = ("ERR_ZONE_CAPACITY_EXCEEDED", 409)
ERR_ZONE_TIGHT_FILL_CAP = ("ERR_ZONE_TIGHT_FILL_CAP", 409)
ERR_GROW_CYCLE_INCOMPLETE = ("ERR_GROW_CYCLE_INCOMPLETE", 409)
ERR_NO_GRADE_MEASUREMENT = ("ERR_NO_GRADE_MEASUREMENT", 409)
ERR_GRADE_BELOW_SPEC = ("ERR_GRADE_BELOW_SPEC", 409)
ERR_LIVE_PCT_BELOW_SPEC = ("ERR_LIVE_PCT_BELOW_SPEC", 409)
ERR_BATCH_HAS_COMMITMENTS = ("ERR_BATCH_HAS_COMMITMENTS", 409)
ERR_BATCH_NOT_SALEABLE = ("ERR_BATCH_NOT_SALEABLE", 409)
ERR_EMPTY_ORDER = ("ERR_EMPTY_ORDER", 409)
ERR_BROKER_ON_HOLD = ("ERR_BROKER_ON_HOLD", 409)
ERR_INSUFFICIENT_AVAILABILITY = ("ERR_INSUFFICIENT_AVAILABILITY", 409)
ERR_INSUFFICIENT_LIVE_STOCK = ("ERR_INSUFFICIENT_LIVE_STOCK", 409)
ERR_CREDIT_LIMIT_EXCEEDED = ("ERR_CREDIT_LIMIT_EXCEEDED", 402)
ERR_ORDER_NOT_FULFILLABLE = ("ERR_ORDER_NOT_FULFILLABLE", 409)
ERR_ORDER_HAS_SHIPMENT = ("ERR_ORDER_HAS_SHIPMENT", 409)
ERR_ORDER_ALREADY_CLOSED = ("ERR_ORDER_ALREADY_CLOSED", 409)
ERR_PHYTO_REQUIRED = ("ERR_PHYTO_REQUIRED", 409)
ERR_PHYTO_INVALID = ("ERR_PHYTO_INVALID", 409)
ERR_PHYTO_EXPIRED = ("ERR_PHYTO_EXPIRED", 409)
ERR_PHYTO_DESTINATION_MISMATCH = ("ERR_PHYTO_DESTINATION_MISMATCH", 409)


class ApiError(Exception):
    def __init__(self, err, message=None):
        self.error_id = err[0]
        self.http_status = err[1]
        self.message = message or err[0]
        super().__init__(self.message)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
CLOCK_DEFAULT = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.current = CLOCK_DEFAULT

    def now(self):
        return self.current

    def now_iso(self):
        return to_iso(self.current)

    def set(self, dt):
        self.current = dt


clock = Clock()


def to_iso(dt):
    """ISO 8601 UTC with three fractional digits and trailing Z."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % (dt.microsecond // 1000)


def parse_iso(s):
    """Parse an ISO 8601 instant into an aware UTC datetime. Raises ValueError on failure."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.varieties = {}
        self.zones = {}
        self.batches = {}
        self.input_logs = {}
        self.brokers = {}
        self.availability = {}
        self.orders = {}
        self.order_lines = {}
        self.shipments = {}
        self.phyto_certs = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_id():
    return str(uuid.uuid4())


def common_create(entity, versioned=True):
    """Populate id / created_at / (updated_at / version) / _seq on a freshly built record."""
    entity["id"] = new_id()
    entity["created_at"] = clock.now_iso()
    entity["_seq"] = store.next_seq()
    if versioned:
        entity["updated_at"] = entity["created_at"]
        entity["version"] = 1
    return entity


def touch(entity):
    """Record a mutation: refresh updated_at, bump version."""
    entity["updated_at"] = clock.now_iso()
    entity["version"] = entity.get("version", 1) + 1


def public(entity):
    """Strip internal-only keys for output."""
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def get_or_404(coll, _id):
    e = coll.get(_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND, "Resource not found")
    return e


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(extra=None):
    rid = "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))
    m = {"api_request_id": rid, "api_request_timestamp": clock.now_iso()}
    if extra:
        m.update(extra)
    return m


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": public(data) if data is not None else {}}
    return jsonify(body), status


def ok_empty(status=200):
    body = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(body), status


def ok_list(items, limit, offset, total):
    has_more = (offset + len(items)) < total
    meta_extra = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    body = {
        "meta": _meta(meta_extra),
        "response_type": "array",
        "data": [public(i) for i in items],
    }
    return jsonify(body), 200


def error_response(err_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
KNOWN_ROLES = {"GrowerManager", "ProductionTech", "SalesCoordinator", "Broker"}


def require(roles):
    """Validate auth headers (401) and role permission (403). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, "Missing or invalid authentication headers")
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN, "Role %s is not permitted for this operation" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


# ---------------------------------------------------------------------------
# Body / field validation helpers (ERR_INVALID_REQUEST on failure)
# ---------------------------------------------------------------------------
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return data


def req_str(body, field, allow_empty=False):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    v = body[field]
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a string" % field)
    if not allow_empty and v.strip() == "":
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must not be empty" % field)
    return v


def req_int(body, field, minimum=None, maximum=None):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, minimum))
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be <= %s" % (field, maximum))
    return v


def req_number(body, field, minimum=None, maximum=None, exclusive_min=None):
    if field not in body or body[field] is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: %s" % field)
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, minimum))
    if exclusive_min is not None and v <= exclusive_min:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be > %s" % (field, exclusive_min))
    if maximum is not None and v > maximum:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be <= %s" % (field, maximum))
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be one of %s" % (field, sorted(allowed)))
    return v


def opt_bool(body, field, default=False):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a boolean" % field)
    return v


def opt_number(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a number" % field)
    return v


def opt_int(body, field, default=0, minimum=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an integer" % field)
    if minimum is not None and v < minimum:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be >= %s" % (field, minimum))
    return v


def opt_str(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    v = body[field]
    if not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be a string" % field)
    return v


def req_datetime(body, field):
    v = req_str(body, field)
    try:
        parse_iso(v)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, "Field %s must be an ISO 8601 datetime" % field)
    return v


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        try:
            limit = int(args["limit"])
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args:
        try:
            offset = int(args["offset"])
        except (ValueError, TypeError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


def paginate(rows):
    """Sort by creation order, apply current request pagination, return (page, limit, offset, total)."""
    limit, offset = pagination()
    rows = sorted(rows, key=lambda r: r["_seq"])
    total = len(rows)
    page = rows[offset:offset + limit]
    return page, limit, offset, total
