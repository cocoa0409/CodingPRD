"""Foundation layer: error catalogue, response envelope, auth, in-memory store,
logical clock, validation primitives and rounding helpers.

Every structural name in this module is taken verbatim from PRD.md
(sections 2.1 - 2.7) and SCAFFOLD.yaml `response_envelope`.
"""

import itertools
import random
import re
import string
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from functools import lru_cache

from flask import jsonify, request, g

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLE_FLEET_PLANNER = "FleetPlanner"
ROLE_TRANSPORT_MANAGER = "TransportManager"
ROLE_DRIVER = "Driver"
ROLE_PAYROLL_ANALYST = "PayrollAnalyst"
ROLE_SAFETY_MANAGER = "SafetyManager"
ROLE_MAINTENANCE_COORDINATOR = "MaintenanceCoordinator"

ALL_ROLES = [
    ROLE_FLEET_PLANNER,
    ROLE_TRANSPORT_MANAGER,
    ROLE_DRIVER,
    ROLE_PAYROLL_ANALYST,
    ROLE_SAFETY_MANAGER,
    ROLE_MAINTENANCE_COORDINATOR,
]

# ---------------------------------------------------------------------------
# Error catalogue (PRD section 5) -- error_id -> HTTP status
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_DRIVER_SCOPE_VIOLATION": 403,
    "ERR_PARENT_MISMATCH": 403,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_DOMICILE_NOT_FOUND": 404,
    "ERR_PAY_PLAN_NOT_FOUND": 404,
    "ERR_DRIVER_NOT_FOUND": 404,
    "ERR_TRACTOR_NOT_FOUND": 404,
    "ERR_TRAILER_NOT_FOUND": 404,
    "ERR_ORDER_NOT_FOUND": 404,
    "ERR_TRIP_NOT_FOUND": 404,
    "ERR_TRIP_STOP_NOT_FOUND": 404,
    "ERR_OFFER_NOT_FOUND": 404,
    "ERR_WORK_ORDER_NOT_FOUND": 404,
    "ERR_STATEMENT_NOT_FOUND": 404,
    "ERR_POSTING_NOT_FOUND": 404,
    "ERR_BID_NOT_FOUND": 404,
    "ERR_EVENT_NOT_FOUND": 404,
    "ERR_INVALID_REQUEST": 400,
    "ERR_DUPLICATE_CODE": 422,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_TRIP_NOT_DRAFT": 409,
    "ERR_TRIP_NOT_STAFFED": 409,
    "ERR_TRIP_HAS_NO_STOPS": 409,
    "ERR_REFERENTIAL_INCOMPLETE": 422,
    "ERR_OFFER_NOT_UNDER_REVIEW": 409,
    "ERR_OFFER_NOT_ACCEPTED": 409,
    "ERR_ORDER_NOT_SCHEDULABLE": 409,
    "ERR_POSTING_NOT_OPEN": 409,
    "ERR_BID_WINDOW_OPEN": 409,
    "ERR_STATEMENT_NOT_ACCRUED": 409,
    "ERR_ALREADY_COACHED": 409,
    "ERR_REVIEW_ROUND_LIMIT": 409,
    "ERR_DEFERRAL_LIMIT": 409,
    "ERR_STOP_SEQUENCE_CONFLICT": 409,
    "ERR_STOP_SEQUENCE_DISORDER": 422,
    "ERR_STALE_TRIP_VERSION": 412,
    "ERR_STALE_POSTING_VERSION": 412,
    "ERR_STALE_DRIVER_VERSION": 412,
    "ERR_ASSET_NOT_AVAILABLE": 409,
    "ERR_TRACTOR_PM_HOLD": 409,
    "ERR_DRIVER_NOT_ACTIVE": 409,
    "ERR_STORE_SUSPENDED": 409,
    "ERR_BACKHAUL_ALREADY_LINKED": 422,
    "ERR_DRIVER_COACHING_HOLD": 422,
    "ERR_DRIVER_SAFETY_INELIGIBLE": 422,
    "ERR_DOMICILE_MISMATCH": 422,
    "ERR_HOS_DRIVE_LIMIT": 422,
    "ERR_HOS_DUTY_LIMIT": 422,
    "ERR_HOS_WEEKLY_LIMIT": 422,
    "ERR_DOCK_HOURS_VIOLATION": 422,
    "ERR_DELIVERY_WINDOW_VIOLATION": 422,
    "ERR_DOCK_CAPACITY_EXCEEDED": 409,
    "ERR_ASSET_MAINTENANCE_CONFLICT": 409,
    "ERR_DRIVER_REST_GAP": 422,
    "ERR_TRAILER_CAPACITY_EXCEEDED": 422,
    "ERR_TEMPERATURE_MODE_MISMATCH": 422,
    "ERR_DUPLICATE_BID": 422,
    "ERR_MARGIN_BELOW_FLOOR": 422,
    "ERR_ZERO_PAY_SETTLEMENT": 422,
    "ERR_BENCHMARK_NO_VOLUME": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or _default_message(error_id)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def real_now():
    return datetime.now(timezone.utc)


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": fmt_instant(real_now()),
    }


def respond(data, code=200):
    return jsonify({"meta": base_meta(), "response_type": "object", "data": data}), code


def respond_list(rows, limit, offset, total):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(rows)) < total
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def respond_error(error_id, message, status):
    return (
        jsonify({
            "meta": base_meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        }),
        status,
    )


# ---------------------------------------------------------------------------
# In-memory store (PRD: nothing is seeded; every collection starts empty)
# ---------------------------------------------------------------------------
class Store(dict):
    pass


class DB:
    def __init__(self):
        self.stores = {}
        self.domiciles = {}
        self.pay_plans = {}
        self.drivers = {}
        self.tractors = {}
        self.trailers = {}
        self.orders = {}
        self.trips = {}
        self.stops = {}
        self.offers = {}
        self.work_orders = {}
        self.statements = {}
        self.postings = {}
        self.bids = {}
        self.events = {}
        # Logical clock (PRD 2.5): fixed origin, never wall-clock time.
        self.clock = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.clock_raw = "2026-08-01T00:00:00Z"


db = DB()

_seq = itertools.count(1)

NOT_FOUND_CODE = {
    "stores": "ERR_STORE_NOT_FOUND",
    "domiciles": "ERR_DOMICILE_NOT_FOUND",
    "pay_plans": "ERR_PAY_PLAN_NOT_FOUND",
    "drivers": "ERR_DRIVER_NOT_FOUND",
    "tractors": "ERR_TRACTOR_NOT_FOUND",
    "trailers": "ERR_TRAILER_NOT_FOUND",
    "orders": "ERR_ORDER_NOT_FOUND",
    "trips": "ERR_TRIP_NOT_FOUND",
    "stops": "ERR_TRIP_STOP_NOT_FOUND",
    "offers": "ERR_OFFER_NOT_FOUND",
    "work_orders": "ERR_WORK_ORDER_NOT_FOUND",
    "statements": "ERR_STATEMENT_NOT_FOUND",
    "postings": "ERR_POSTING_NOT_FOUND",
    "bids": "ERR_BID_NOT_FOUND",
    "events": "ERR_EVENT_NOT_FOUND",
}


def coll(name):
    return getattr(db, name)


def must_exist(name, row_id):
    """Level 4 / 5 existence check."""
    if not isinstance(row_id, str):
        fail(NOT_FOUND_CODE[name])
    row = coll(name).get(row_id)
    if row is None:
        fail(NOT_FOUND_CODE[name])
    return row


def new_row(fields, versioned=True):
    now = fmt_instant(real_now())
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    row["created_at"] = now
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    row["_seq"] = next(_seq)
    return row


def bump(row):
    """A mutation: version += 1 and updated_at refreshed (PRD 2.4)."""
    row["version"] = row.get("version", 0) + 1
    row["updated_at"] = fmt_instant(real_now())
    return row


def out(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def out_many(rows):
    return [out(r) for r in rows]


def by_created(rows):
    """Default collection ordering: created_at ascending (PRD 2.3)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
def clock_now():
    return db.clock


# ---------------------------------------------------------------------------
# Authentication / authorisation (PRD 2.1, precedence levels 1 and 2)
# ---------------------------------------------------------------------------
def auth(allowed_roles):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role == "" or role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role must be one of the six declared roles.")
    if user_id is None or user_id == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID is required on every request.")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not call this endpoint." % role)
    g.role = role
    g.user_id = user_id
    return role, user_id


# ---------------------------------------------------------------------------
# Instant / date parsing (precedence level 7)
# ---------------------------------------------------------------------------
_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"([Zz]|[+-]\d{2}:\d{2})$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


@lru_cache(maxsize=8192)
def parse_instant(value):
    if not isinstance(value, str):
        return None
    m = _INSTANT_RE.match(value)
    if not m:
        return None
    txt = value
    if txt[-1] in "Zz":
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def D(value):
    """Parsed instant for a stored raw string (None-safe)."""
    if value is None:
        return None
    return parse_instant(value)


def valid_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


# ---------------------------------------------------------------------------
# Rounding (PRD 2.6)
# ---------------------------------------------------------------------------
def rhu_cents(value):
    """Round half up to a whole cent."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu4(numerator, denominator):
    """Round half up to four decimal places."""
    q = Decimal(numerator) / Decimal(denominator)
    return float(q.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def dec(value):
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def ceil_div(numerator, denominator):
    return int(
        (Decimal(numerator) / Decimal(denominator)).quantize(
            Decimal("1"), rounding=ROUND_CEILING
        )
    )


# ---------------------------------------------------------------------------
# Collection helpers
# ---------------------------------------------------------------------------
def unique_code(collection, field, value):
    """Level 15 uniqueness on the eight business codes."""
    for row in collection.values():
        if row.get(field) == value:
            fail("ERR_DUPLICATE_CODE", "%s '%s' is already in use." % (field, value))


def apply_filters(rows, filters):
    """filters: list of (row_field, wanted_value); None wanted values are skipped."""
    out_rows = []
    for row in rows:
        keep = True
        for field, wanted in filters:
            if wanted is None:
                continue
            if row.get(field) != wanted:
                keep = False
                break
        if keep:
            out_rows.append(row)
    return out_rows


def page(rows, limit, offset, ordered=None):
    ordered_rows = by_created(rows) if ordered is None else ordered
    total = len(ordered_rows)
    window = ordered_rows[offset: offset + limit]
    return respond_list(out_many(window), limit, offset, total)
