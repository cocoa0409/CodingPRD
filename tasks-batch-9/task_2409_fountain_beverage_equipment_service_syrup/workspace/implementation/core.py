"""Foundation layer: in-memory store, logical clock, response envelope, auth,
request-shape validation helpers and the validation-priority Ladder.

Every structural name here is taken from PRD.md / SCAFFOLD.yaml:
  auth headers            : X-User-ID, X-User-Role            (PRD 2.1)
  envelope                : meta / response_type / data       (PRD 2.2)
  error body              : error_id / message                (PRD 2.2)
  pagination              : limit / offset / total_count / has_more (PRD 2.3)
  optimistic concurrency  : expected_outlet_version, expected_route_version (PRD 2.8)
  audit triple            : created_at / updated_at / version (PRD 2.5)
"""

import json
import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN
from functools import wraps

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# roles (PRD 2.1 - exactly these six spellings)
# ---------------------------------------------------------------------------
ROLES = (
    "NetworkAdmin",
    "SupplyPlanner",
    "RouteDriver",
    "ServiceTechnician",
    "ComplianceOfficer",
    "OutletManager",
)

# ---------------------------------------------------------------------------
# error catalogue (PRD section 5) - id -> http status
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_OUTLET_OWNERSHIP_REQUIRED": 403,
    "ERR_TECHNICIAN_NOT_ASSIGNED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_OUTLET_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_DISPENSER_UNIT_NOT_FOUND": 404,
    "ERR_SUPPLY_ITEM_NOT_FOUND": 404,
    "ERR_SUPPLY_POSITION_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_ROUTE_STOP_NOT_FOUND": 404,
    "ERR_MAINTENANCE_TASK_NOT_FOUND": 404,
    "ERR_SERVICE_CALL_NOT_FOUND": 404,
    "ERR_VAN_PART_STOCK_NOT_FOUND": 404,
    "ERR_TELEMETRY_READING_NOT_FOUND": 404,
    "ERR_PART_NOT_ON_VAN": 404,
    "ERR_STALE_OUTLET_VERSION": 412,
    "ERR_STALE_ROUTE_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_UNIT_NOT_SERVICEABLE": 409,
    "ERR_ESCALATION_LIMIT_REACHED": 409,
    "ERR_OUTLET_POSTURE_FROZEN": 409,
    "ERR_CALIBRATION_OUT_OF_SPEC": 409,
    "ERR_SANITATION_OVERDUE": 409,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_WAIVER_SEGREGATION_VIOLATION": 409,
    "ERR_OUTLET_AGREEMENT_MISMATCH": 422,
    "ERR_REGION_MISMATCH": 422,
    "ERR_TIMESTAMP_IN_FUTURE": 422,
    "ERR_INVALID_INTERVAL": 422,
    "ERR_TERM_NOT_ELAPSED": 409,
    "ERR_STOP_WINDOW_OVERLAP": 409,
    "ERR_VAN_WINDOW_CONFLICT": 409,
    "ERR_INSUFFICIENT_VAN_PARTS": 409,
    "ERR_CONSUMED_EXCEEDS_RESERVED": 422,
    "ERR_GALLON_INTERVAL_REQUIRED": 422,
    "ERR_GALLON_INTERVAL_NOT_APPLICABLE": 422,
    "ERR_BRIX_MEASUREMENT_REQUIRED": 422,
    "ERR_NO_ELIGIBLE_POSITIONS": 422,
    "ERR_DUPLICATE_ACCOUNT_CODE": 409,
    "ERR_DUPLICATE_SERIAL_NUMBER": 409,
    "ERR_DUPLICATE_SKU_CODE": 409,
    "ERR_DUPLICATE_ROUTE_CODE": 409,
    "ERR_DUPLICATE_SUPPLY_POSITION": 409,
    "ERR_DUPLICATE_VAN_PART": 409,
    "ERR_DUPLICATE_STOP_SEQUENCE": 409,
    "ERR_ALLOCATION_POOL_EXHAUSTED": 409,
    "ERR_ROUTE_CAPACITY_EXCEEDED": 409,
    "ERR_POOL_BELOW_RESERVED": 422,
    "ERR_NO_SHORTFALL_TO_ASSESS": 422,
    "ERR_RECALL_NOT_PERMITTED": 422,
    "ERR_RECALL_EXPOSURE_BELOW_FLOOR": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http = ERROR_HTTP.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").lower().capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


def require(condition, error_id, message=None):
    if not condition:
        raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# logical clock + in-memory store (PRD 2.4 / 2.5)
# ---------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    """Pure in-memory storage.  Nothing is seeded: every row is created by a
    declared endpoint.  A fresh process therefore starts completely empty."""

    def __init__(self):
        self.outlets = {}
        self.agreements = {}
        self.units = {}
        self.supply_items = {}
        self.readings = {}
        self.positions = {}
        self.routes = {}
        self.stops = {}
        self.tasks = {}
        self.calls = {}
        self.van_stocks = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()
LOCK = threading.RLock()


def now():
    """The logical clock.  Never wall-clock time (PRD 2.4)."""
    return db.clock


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.2 / 2.5)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_flex(dt):
    """ISO 8601 UTC, fractional part only when non-zero.  Used for the clock
    echo so that `{current_utc}` reads back the instant the caller supplied."""
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(raw):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# rounding helpers (PRD 2.7)
# ---------------------------------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def floor_div_units(value, step):
    """floor(value / step) * step for integer unit counts."""
    return (int(value) // int(step)) * int(step)


def ceil_int(value):
    d = D(value)
    i = int(d.to_integral_value(rounding=ROUND_DOWN))
    if d > i:
        i += 1
    return i


def num_out(value):
    """Serialise a Decimal/number field as a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


# ---------------------------------------------------------------------------
# mutation bookkeeping (PRD 2.5 / 2.10)
#   "Every resource touched anywhere along a cascade is a mutated resource:
#    its updated_at is refreshed and its version advances by one, exactly
#    once per request."
# ---------------------------------------------------------------------------
def touch(entity):
    if entity is None:
        return
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    key = id(entity) if "id" not in entity else entity["id"]
    if key in touched:
        return
    touched.add(key)
    entity["updated_at"] = iso_ms(now())
    entity["version"] = entity.get("version", 1) + 1


def stamp_new(entity):
    """Common fields of a freshly created resource (version starts at 1)."""
    entity["created_at"] = iso_ms(now())
    entity["updated_at"] = entity["created_at"]
    entity["version"] = 1
    entity["_seq"] = db.next_seq()
    if not hasattr(g, "touched"):
        g.touched = set()
    g.touched.add(entity["id"])
    return entity


def sort_rows(rows):
    """Default list ordering: created_at ascending (PRD 2.3).  The secondary
    _seq key keeps insertion order deterministic when the logical clock has
    not moved between two creations."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), status


def ok_list(page, limit, offset, total):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(page)) < total,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


def error_body(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


# ---------------------------------------------------------------------------
# rung 1 + rung 2: authentication and authorization (PRD 2.6)
# ---------------------------------------------------------------------------
def endpoint(roles):
    allowed = tuple(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(**kwargs):
            with LOCK:
                g.touched = set()
                user_id = request.headers.get("X-User-ID")
                role = request.headers.get("X-User-Role")
                # rung 1 - authentication
                require(
                    bool(user_id) and bool(role) and role in ROLES,
                    "ERR_UNAUTHENTICATED",
                    "X-User-ID and X-User-Role headers are required.",
                )
                # rung 2 - authorization
                require(role in allowed, "ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
                g.user_id = user_id
                g.role = role
                return fn(**kwargs)

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# the validation priority ladder (PRD 2.6)
#
# Handlers register their checks with the rung number the PRD assigns them;
# Ladder.run() executes them in ascending rung order, so the *first* failure
# in PRD order always wins no matter what order the handler wrote them in.
# Registration order breaks ties inside one rung (left-to-right path ids,
# declared body-reference order, ...).
# ---------------------------------------------------------------------------
class Ladder:
    def __init__(self):
        self._checks = []

    def add(self, rung, fn):
        self._checks.append((rung, len(self._checks), fn))
        return self

    def run(self):
        for _rung, _order, fn in sorted(self._checks, key=lambda t: (t[0], t[1])):
            fn()


# ---------------------------------------------------------------------------
# rung 3 helpers: request shape
# ---------------------------------------------------------------------------
def body():
    raw = request.get_data()
    if raw is None or len(raw) == 0:
        return {}
    try:
        parsed = json.loads(raw)
    except Exception:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def present(payload, key):
    return key in payload and payload[key] is not None


def _missing(key):
    fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)


def f_str(payload, key, required=False, default=None, enum=None, allow_empty=False):
    if not present(payload, key):
        if required:
            _missing(key)
        return default
    value = payload[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % key)
    if not allow_empty and value == "":
        fail("ERR_INVALID_REQUEST", "Field '%s' must not be empty." % key)
    if enum is not None and value not in enum:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (key, ", ".join(enum)))
    return value


def f_bool(payload, key, required=False, default=None):
    if not present(payload, key):
        if required:
            _missing(key)
        return default
    value = payload[key]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % key)
    return value


def f_int(payload, key, required=False, default=None, ge=None, gt=None, le=None):
    if not present(payload, key):
        if required:
            _missing(key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % key)
    _range(key, value, ge, gt, le)
    return value


def f_num(payload, key, required=False, default=None, ge=None, gt=None, le=None):
    if not present(payload, key):
        if required:
            _missing(key)
        return default
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a number." % key)
    _range(key, value, ge, gt, le)
    return value


def _range(key, value, ge, gt, le):
    if ge is not None and value < ge:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be >= %s." % (key, ge))
    if gt is not None and value <= gt:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be > %s." % (key, gt))
    if le is not None and value > le:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be <= %s." % (key, le))


def f_dt(payload, key, required=False):
    """Returns (raw_string, datetime) or (None, None)."""
    if not present(payload, key):
        if required:
            _missing(key)
        return None, None
    value = payload[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 timestamp string." % key)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is not a valid ISO 8601 timestamp." % key)
    return value, parsed


def f_str_list(payload, key, required=False):
    if not present(payload, key):
        if required:
            _missing(key)
        return None
    value = payload[key]
    if not isinstance(value, list):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an array." % key)
    for member in value:
        if not isinstance(member, str) or member == "":
            fail("ERR_INVALID_REQUEST", "Field '%s' must contain identifier strings." % key)
    return value


def interval_ok(start_dt, end_dt):
    """rung 21 - every submitted interval end bound strictly after its start."""
    if start_dt is None or end_dt is None:
        return
    require(end_dt > start_dt, "ERR_INVALID_INTERVAL", "Interval end must be strictly after its start.")


# ---------------------------------------------------------------------------
# pagination + query helpers (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer between 1 and 100.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if "offset" in args and args.get("offset") != "":
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be a non-negative integer.")
    return limit, offset


def q_str(key, enum=None):
    if key not in request.args:
        return None
    value = request.args.get(key)
    if value == "":
        return None
    if enum is not None and value not in enum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (key, ", ".join(enum)))
    return value


def q_dt(key):
    if key not in request.args:
        return None
    value = request.args.get(key)
    if value == "":
        return None
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is not a valid ISO 8601 timestamp." % key)
    return parsed


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset : offset + limit], total


# ---------------------------------------------------------------------------
# rung 4 / rung 5 existence lookups
# ---------------------------------------------------------------------------
def get_outlet(oid):
    row = db.outlets.get(oid)
    require(row is not None, "ERR_OUTLET_NOT_FOUND", "Outlet %s does not exist." % oid)
    return row


def get_agreement(aid):
    row = db.agreements.get(aid)
    require(row is not None, "ERR_AGREEMENT_NOT_FOUND", "Placement agreement %s does not exist." % aid)
    return row


def get_unit(uid):
    row = db.units.get(uid)
    require(row is not None, "ERR_DISPENSER_UNIT_NOT_FOUND", "Dispenser unit %s does not exist." % uid)
    return row


def get_item(iid):
    row = db.supply_items.get(iid)
    require(row is not None, "ERR_SUPPLY_ITEM_NOT_FOUND", "Supply item %s does not exist." % iid)
    return row


def get_position(pid):
    row = db.positions.get(pid)
    require(row is not None, "ERR_SUPPLY_POSITION_NOT_FOUND", "Supply position %s does not exist." % pid)
    return row


def get_route(rid):
    row = db.routes.get(rid)
    require(row is not None, "ERR_ROUTE_NOT_FOUND", "Replenishment route %s does not exist." % rid)
    return row


def get_stop(sid):
    row = db.stops.get(sid)
    require(row is not None, "ERR_ROUTE_STOP_NOT_FOUND", "Route stop %s does not exist." % sid)
    return row


def get_task(tid):
    row = db.tasks.get(tid)
    require(row is not None, "ERR_MAINTENANCE_TASK_NOT_FOUND", "Maintenance task %s does not exist." % tid)
    return row


def get_call(cid):
    row = db.calls.get(cid)
    require(row is not None, "ERR_SERVICE_CALL_NOT_FOUND", "Service call %s does not exist." % cid)
    return row


def get_van_stock(vid):
    row = db.van_stocks.get(vid)
    require(row is not None, "ERR_VAN_PART_STOCK_NOT_FOUND", "Van part stock %s does not exist." % vid)
    return row


def get_reading(rid):
    row = db.readings.get(rid)
    require(row is not None, "ERR_TELEMETRY_READING_NOT_FOUND", "Telemetry reading %s does not exist." % rid)
    return row


# ---------------------------------------------------------------------------
# rung 6: outlet ownership (PRD 2.1 / 2.6)
# ---------------------------------------------------------------------------
def require_outlet_ownership(outlet_id):
    if g.role != "OutletManager":
        return
    require(
        g.user_id == outlet_id,
        "ERR_OUTLET_OWNERSHIP_REQUIRED",
        "An OutletManager may only act on its own outlet.",
    )


# ---------------------------------------------------------------------------
# enum vocabularies
# ---------------------------------------------------------------------------
THROUGHPUT_TIERS = ("SMALL", "MEDIUM", "LARGE")
OUTLET_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
SERVICE_POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "SHORTFALL_REVIEW", "RECALL_PENDING", "TERMINATED", "EXPIRED")
EXPOSURE_VARIANTS = ("BOOK_VALUE", "REPLACEMENT_RISK")
UNIT_STATUSES = ("IN_SERVICE", "SERVICE_HOLD", "RECALL_STAGED", "RETURNED")
CALIBRATION_STATUSES = ("UNVERIFIED", "IN_SPEC", "OUT_OF_SPEC")
SUPPLY_FORMS = ("CARTRIDGE", "BAG_IN_BOX")
TELEMETRY_SOURCES = ("TELEMETRY", "MANUAL_AUDIT")
FORECAST_VARIANTS = ("TRAILING_ACTUAL", "THROUGHPUT_PROJECTED")
ALERT_LEVELS = ("NONE", "LOW", "CRITICAL")
ROUTE_STATUSES = ("PLANNED", "DISPATCHED", "COMPLETED", "CANCELLED")
STOP_STATUSES = ("PENDING", "ARRIVED", "SERVED", "SKIPPED")
SKIP_REASONS = ("OUTLET_CLOSED", "POSTURE_FROZEN", "ACCESS_DENIED")
TASK_TYPES = ("PREVENTIVE", "BRIX_CALIBRATION", "SANITATION", "FILTER_CHANGE")
TASK_STATUSES = ("SCHEDULED", "DUE", "OVERDUE", "COMPLETED", "WAIVED")
BREACH_KINDS = ("DATE", "GALLON")
SYMPTOM_CODES = ("NO_POUR", "OFF_RATIO", "LEAK", "CO2_LOW", "ICE_FAULT")
SEVERITIES = ("ROUTINE", "URGENT", "CRITICAL")
CALL_STATUSES = ("OPEN", "DISPATCHED", "ON_SITE", "RESOLVED", "ESCALATED", "CANCELLED")
RESOLUTION_CODES = ("PART_REPLACED", "CALIBRATED", "CLEANED", "NO_FAULT_FOUND")

__all__ = [name for name in dir() if not name.startswith("__")]
