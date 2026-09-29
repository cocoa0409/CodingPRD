"""Core infrastructure: in-memory store, logical clock, response envelope,
error catalogue, auth, validation helpers and numeric primitives.

Every structural name in this module (header names, envelope field names,
pagination parameter names, error ids) is taken verbatim from PRD.md §2 and
SCAFFOLD.yaml.
"""

import json
import math
import random
import string
import threading
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction

from flask import Response, g, request

# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------

FACILITY_ADMIN = "FacilityAdmin"
INBOUND_COORDINATOR = "InboundCoordinator"
SORT_SUPERVISOR = "SortSupervisor"
LABOR_PLANNER = "LaborPlanner"
OPS_MANAGER = "OpsManager"
WORKER = "Worker"

OPERATOR_ROLES = [
    FACILITY_ADMIN,
    INBOUND_COORDINATOR,
    SORT_SUPERVISOR,
    LABOR_PLANNER,
    OPS_MANAGER,
]
ALL_ROLES = OPERATOR_ROLES + [WORKER]
ROLE_SET = set(ALL_ROLES)

# --------------------------------------------------------------------------
# Error catalogue (PRD §5)
# --------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_SORT_CENTER_NOT_FOUND": 404,
    "ERR_FACILITY_RESOURCE_NOT_FOUND": 404,
    "ERR_TRAILER_APPOINTMENT_NOT_FOUND": 404,
    "ERR_SHIFT_PLAN_NOT_FOUND": 404,
    "ERR_LABOR_RESOURCE_NOT_FOUND": 404,
    "ERR_OUTBOUND_RESOURCE_NOT_FOUND": 404,
    "ERR_NOT_ASSIGNMENT_OWNER": 403,
    "ERR_INVALID_TIME_WINDOW": 422,
    "ERR_DUPLICATE_FACILITY_RESOURCE": 409,
    "ERR_DUPLICATE_TRAILER_CODE": 409,
    "ERR_INVALID_APPOINTMENT_STATE": 409,
    "ERR_INVALID_SHIFT_PLAN_STATE": 409,
    "ERR_INVALID_LOAD_STATE": 409,
    "ERR_INVALID_ASSIGNMENT_STATE": 409,
    "ERR_INVALID_EXCEPTION_STATE": 409,
    "ERR_STALE_CHUTE_VERSION": 412,
    "ERR_STALE_CENTER_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_CENTER_FROZEN": 409,
    "ERR_LINE_HEADCOUNT_EXCEEDED": 422,
    "ERR_ERGONOMIC_ROTATION_REQUIRED": 422,
    "ERR_WORKER_NOT_CLEARED": 409,
    "ERR_DOOR_OUT_OF_SERVICE": 409,
    "ERR_DOOR_WINDOW_CONFLICT": 409,
    "ERR_CHUTE_CONCURRENCY_EXCEEDED": 409,
    "ERR_JAM_RETRY_LIMIT_REACHED": 409,
    "ERR_TRAILER_CUBE_EXCEEDED": 422,
    "ERR_EXCEPTION_COUNT_EXCEEDS_SOURCE": 422,
    "ERR_LOAD_NOT_SEALED": 409,
    "ERR_DISPATCH_CUT_PASSED": 422,
    "ERR_LANE_NOT_ASSIGNED_TO_CHUTE": 409,
    "ERR_WORKER_CENTER_MISMATCH": 409,
    "ERR_NO_ELIGIBLE_CHUTE": 422,
    "ERR_FLEX_POOL_EXHAUSTED": 409,
    "ERR_LABOR_BUDGET_EXCEEDED": 402,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _DEFAULT_MESSAGES.get(error_id, error_id)


_DEFAULT_MESSAGES = {
    "ERR_UNAUTHENTICATED": "X-User-ID and X-User-Role headers are required and the role must be recognized.",
    "ERR_FORBIDDEN_ROLE": "The acting role is not authorized for this operation.",
    "ERR_INVALID_REQUEST": "The request body or query is malformed.",
    "ERR_SORT_CENTER_NOT_FOUND": "The named sort center does not exist.",
    "ERR_FACILITY_RESOURCE_NOT_FOUND": "A referenced dock door, sort chute, destination lane or chute assignment does not exist.",
    "ERR_TRAILER_APPOINTMENT_NOT_FOUND": "The referenced trailer appointment does not exist.",
    "ERR_SHIFT_PLAN_NOT_FOUND": "The referenced shift plan does not exist.",
    "ERR_LABOR_RESOURCE_NOT_FOUND": "The referenced worker or staff assignment does not exist.",
    "ERR_OUTBOUND_RESOURCE_NOT_FOUND": "The referenced outbound load or package exception does not exist.",
    "ERR_NOT_ASSIGNMENT_OWNER": "The acting worker does not own this staff assignment.",
    "ERR_INVALID_TIME_WINDOW": "The supplied time window or instant is not valid.",
    "ERR_DUPLICATE_FACILITY_RESOURCE": "The value is already in use within its owning scope.",
    "ERR_DUPLICATE_TRAILER_CODE": "The trailer code is already in use at this sort center.",
    "ERR_INVALID_APPOINTMENT_STATE": "The trailer appointment is not in a state that permits this transition.",
    "ERR_INVALID_SHIFT_PLAN_STATE": "The shift plan is not in a state that permits this operation.",
    "ERR_INVALID_LOAD_STATE": "The outbound load is not in a state that permits this transition.",
    "ERR_INVALID_ASSIGNMENT_STATE": "The staff assignment is not in a state that permits this transition.",
    "ERR_INVALID_EXCEPTION_STATE": "The record is not open.",
    "ERR_STALE_CHUTE_VERSION": "expected_chute_version does not match the current sort chute version.",
    "ERR_STALE_CENTER_VERSION": "expected_center_version does not match the current sort center version.",
    "ERR_SEGREGATION_OF_DUTIES": "The submitting operator may not approve or reject the plan.",
    "ERR_CENTER_FROZEN": "The sort center is FROZEN and refuses this operation.",
    "ERR_LINE_HEADCOUNT_EXCEEDED": "The line headcount ceiling would be exceeded.",
    "ERR_ERGONOMIC_ROTATION_REQUIRED": "The worker requires ergonomic rotation or injury clearance.",
    "ERR_WORKER_NOT_CLEARED": "The worker is not in a state that permits this operation.",
    "ERR_DOOR_OUT_OF_SERVICE": "The dock door is out of service or of the wrong kind.",
    "ERR_DOOR_WINDOW_CONFLICT": "The requested window conflicts with another appointment on this door.",
    "ERR_CHUTE_CONCURRENCY_EXCEEDED": "The chute would hold too many simultaneous destinations.",
    "ERR_JAM_RETRY_LIMIT_REACHED": "The jam retry limit has been reached on this appointment.",
    "ERR_TRAILER_CUBE_EXCEEDED": "The scanned batch would exceed the trailer's cube.",
    "ERR_EXCEPTION_COUNT_EXCEEDS_SOURCE": "The exception package count exceeds the source pool.",
    "ERR_LOAD_NOT_SEALED": "The outbound load is not sealed.",
    "ERR_DISPATCH_CUT_PASSED": "The dispatch cut time has passed.",
    "ERR_LANE_NOT_ASSIGNED_TO_CHUTE": "The destination lane has never been mapped to a chute.",
    "ERR_WORKER_CENTER_MISMATCH": "A referenced resource belongs to a different sort center.",
    "ERR_NO_ELIGIBLE_CHUTE": "No eligible chute can take the re-laned packages.",
    "ERR_FLEX_POOL_EXHAUSTED": "The flex pool cannot cover the required draw.",
    "ERR_LABOR_BUDGET_EXCEEDED": "The priced shift exceeds the plan's labor budget.",
}

# --------------------------------------------------------------------------
# Numeric primitives (PRD §2.9 — all rounding is round half up)
# --------------------------------------------------------------------------


def to_fraction(value):
    if isinstance(value, Fraction):
        return value
    if isinstance(value, Decimal):
        return Fraction(value)
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, float):
        return Fraction(str(value))
    raise TypeError("unsupported numeric type %r" % (type(value),))


def q(value, places):
    """Round half up to `places` decimal places, exactly, returning a Decimal."""
    fr = to_fraction(value)
    scale = 10 ** places
    scaled = fr * scale
    if scaled >= 0:
        whole = math.floor(scaled + Fraction(1, 2))
    else:
        whole = -math.floor(-scaled + Fraction(1, 2))
    return Decimal(whole).scaleb(-places)


def qi(value):
    """Round half up to a whole integer."""
    return int(q(value, 0))


# --------------------------------------------------------------------------
# In-memory store and logical clock (PRD §2.4)
# --------------------------------------------------------------------------

CLOCK_DEFAULT_RAW = "2026-08-01T00:00:00Z"


class Store:
    def __init__(self):
        self.sort_centers = {}
        self.dock_doors = {}
        self.sort_chutes = {}
        self.destination_lanes = {}
        self.chute_assignments = {}
        self.trailer_appointments = {}
        self.shift_plans = {}
        self.workers = {}
        self.staff_assignments = {}
        self.outbound_loads = {}
        self.package_exceptions = {}
        self.injury_reports = {}
        self.seq = 0
        self.clock_dt = parse_dt(CLOCK_DEFAULT_RAW)
        self.clock_raw = CLOCK_DEFAULT_RAW


request_lock = threading.RLock()


def clock_dt():
    return db.clock_dt


def clock_raw():
    return db.clock_raw


def clock_date():
    return db.clock_dt.date()


# --------------------------------------------------------------------------
# Timestamps
# --------------------------------------------------------------------------


def parse_dt(value):
    """Parse an RFC 3339 / ISO 8601 instant. Returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("z") or s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(s)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD §2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


def wall_now_str():
    return fmt_dt(datetime.now(timezone.utc))


def parse_date_only(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except Exception:
        return None


# The single in-memory store for this process. Always empty at import time.
db = Store()


# --------------------------------------------------------------------------
# Entities: common fields, dirty tracking (PRD §2.4, §2.10)
# --------------------------------------------------------------------------


def new_entity(kind, fields):
    db.seq += 1
    stamp = wall_now_str()
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["created_at"] = stamp
    row["updated_at"] = stamp
    row["version"] = 1
    row["_seq"] = db.seq
    row["_kind"] = kind
    return row


def touch(row):
    """Mark a row as mutated by this request; version/updated_at settle once."""
    if row is None:
        return
    bag = getattr(g, "_touched", None)
    if bag is None:
        bag = {}
        g._touched = bag
    bag[id(row)] = row


def finalize():
    bag = getattr(g, "_touched", None)
    if not bag:
        return
    stamp = wall_now_str()
    for row in bag.values():
        row["version"] = row["version"] + 1
        row["updated_at"] = stamp
    g._touched = {}


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------


def _json_default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, Fraction):
        return float(obj)
    raise TypeError("not JSON serializable: %r" % (obj,))


def serialize(row):
    out = {k: v for k, v in row.items() if not k.startswith("_")}
    if row.get("_kind") == "Worker":
        out["tenure_days"] = worker_tenure_days(row)
    return out


def worker_tenure_days(worker):
    hire = worker.get("_hire_date")
    if hire is None:
        return 0
    return (clock_date() - hire).days


# --------------------------------------------------------------------------
# Response envelope (PRD §2.2)
# --------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": wall_now_str(),
    }
    if extra:
        meta.update(extra)
    return meta


def _json(payload, status):
    return Response(
        json.dumps(payload, default=_json_default),
        status=status,
        mimetype="application/json",
    )


def respond_object(data, status=200):
    finalize()
    return _json({"meta": _meta(), "response_type": "object", "data": data}, status)


def respond_entity(row, status=200):
    # finalize() first: version/updated_at must be settled before the snapshot.
    finalize()
    return respond_object(serialize(row), status)


def respond_list(rows, total, limit, offset):
    finalize()
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + len(rows) < total,
        }
    )
    return _json(
        {
            "meta": meta,
            "response_type": "array",
            "data": [serialize(r) for r in rows],
        },
        200,
    )


def respond_error(error_id, message, status):
    return _json(
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )


# --------------------------------------------------------------------------
# Auth (PRD §2.1, validation priorities 1 and 2)
# --------------------------------------------------------------------------


def authorize(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLE_SET:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.role = role
    return user_id, role


# --------------------------------------------------------------------------
# Body / query validation (validation priority 3)
# --------------------------------------------------------------------------


def body_dict():
    raw = request.get_data(cache=True)
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _bad(field, why):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, why))


def present(body, key):
    return key in body and body[key] is not None


def req_str(body, key, min_len=1, max_len=None):
    if not present(body, key):
        _bad(key, "is required")
    value = body[key]
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if len(value) < min_len:
        _bad(key, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(key, "must be at most %d characters" % max_len)
    return value


def opt_str(body, key, default=None, min_len=1, max_len=None):
    if not present(body, key):
        return default
    return req_str(body, key, min_len=min_len, max_len=max_len)


def req_int(body, key, min_value=None, max_value=None):
    if not present(body, key):
        _bad(key, "is required")
    return _as_int(body[key], key, min_value, max_value)


def opt_int(body, key, default=None, min_value=None, max_value=None):
    if not present(body, key):
        return default
    return _as_int(body[key], key, min_value, max_value)


def _as_int(value, key, min_value, max_value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(key, "must be an integer")
    if min_value is not None and value < min_value:
        _bad(key, "must be >= %s" % min_value)
    if max_value is not None and value > max_value:
        _bad(key, "must be <= %s" % max_value)
    return value


def req_num(body, key, min_value=None, max_value=None, exclusive_min=False, places=None):
    if not present(body, key):
        _bad(key, "is required")
    return _as_num(body[key], key, min_value, max_value, exclusive_min, places)


def opt_num(body, key, default=None, min_value=None, max_value=None,
            exclusive_min=False, places=None):
    if not present(body, key):
        return default
    return _as_num(body[key], key, min_value, max_value, exclusive_min, places)


def _as_num(value, key, min_value, max_value, exclusive_min, places):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(key, "must be a number")
    dec = Decimal(str(value))
    if min_value is not None:
        if exclusive_min:
            if dec <= Decimal(str(min_value)):
                _bad(key, "must be greater than %s" % min_value)
        elif dec < Decimal(str(min_value)):
            _bad(key, "must be >= %s" % min_value)
    if max_value is not None and dec > Decimal(str(max_value)):
        _bad(key, "must be <= %s" % max_value)
    if places is not None:
        dec = q(dec, places)
    return dec


def req_enum(body, key, allowed):
    value = req_str(body, key)
    if value not in allowed:
        _bad(key, "must be one of %s" % ", ".join(sorted(allowed)))
    return value


def opt_enum(body, key, allowed, default=None):
    if not present(body, key):
        return default
    return req_enum(body, key, allowed)


def req_bool(body, key, default=False):
    if not present(body, key):
        return default
    value = body[key]
    if not isinstance(value, bool):
        _bad(key, "must be a boolean")
    return value


def req_id(body, key):
    if not present(body, key):
        _bad(key, "is required")
    value = body[key]
    if not isinstance(value, str) or not value:
        _bad(key, "must be a non-empty string")
    return value


def opt_id(body, key):
    if not present(body, key):
        return None
    value = body[key]
    if not isinstance(value, str) or not value:
        _bad(key, "must be a non-empty string")
    return value


def pagination():
    """PRD §2.3 — limit default 10 (1..100), offset default 0 (>= 0)."""
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except Exception:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0.")
    return limit, offset


def filter_enum(name, allowed):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    if value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "%s filter is not a recognized value." % name)
    return value


def filter_bool(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    low = value.strip().lower()
    if low in ("true", "1"):
        return True
    if low in ("false", "0"):
        return False
    raise ApiError("ERR_INVALID_REQUEST", "%s filter must be a boolean." % name)


def paginate(rows, limit, offset):
    ordered = sorted(rows, key=lambda r: r["_seq"])
    total = len(ordered)
    return ordered[offset:offset + limit], total


# --------------------------------------------------------------------------
# Existence lookups (validation priorities 4..9)
# --------------------------------------------------------------------------


def get_center(center_id):
    row = db.sort_centers.get(center_id) if isinstance(center_id, str) else None
    if row is None:
        raise ApiError("ERR_SORT_CENTER_NOT_FOUND")
    return row


def get_facility(collection, resource_id):
    row = collection.get(resource_id) if isinstance(resource_id, str) else None
    if row is None:
        raise ApiError("ERR_FACILITY_RESOURCE_NOT_FOUND")
    return row


def get_appointment(appointment_id):
    row = db.trailer_appointments.get(appointment_id) if isinstance(appointment_id, str) else None
    if row is None:
        raise ApiError("ERR_TRAILER_APPOINTMENT_NOT_FOUND")
    return row


def get_shift_plan(plan_id):
    row = db.shift_plans.get(plan_id) if isinstance(plan_id, str) else None
    if row is None:
        raise ApiError("ERR_SHIFT_PLAN_NOT_FOUND")
    return row


def get_labor(collection, resource_id):
    row = collection.get(resource_id) if isinstance(resource_id, str) else None
    if row is None:
        raise ApiError("ERR_LABOR_RESOURCE_NOT_FOUND")
    return row


def get_outbound(collection, resource_id):
    row = collection.get(resource_id) if isinstance(resource_id, str) else None
    if row is None:
        raise ApiError("ERR_OUTBOUND_RESOURCE_NOT_FOUND")
    return row
