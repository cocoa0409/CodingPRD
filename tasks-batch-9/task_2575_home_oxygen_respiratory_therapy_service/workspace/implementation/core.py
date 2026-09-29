"""Core infrastructure: error catalog, in-memory store, logical clock,
response envelope helpers and authentication/RBAC enforcement.

Storage is process-local and in-memory only.  Nothing is seeded at import
time or at server start: every row is created through the declared API.
"""
import os
import random
import re
import string
import uuid
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, request

UTC = timezone.utc

# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
ROLE_INTAKE = "IntakeCoordinator"
ROLE_PHYSICIAN = "Physician"
ROLE_AUDITOR = "ComplianceAuditor"
ROLE_THERAPIST = "RespiratoryTherapist"
ROLE_DRIVER = "DeliveryDriver"
ROLE_MANAGER = "BranchManager"
ROLE_BILLING = "BillingSpecialist"

ALL_ROLES = (
    ROLE_INTAKE,
    ROLE_PHYSICIAN,
    ROLE_AUDITOR,
    ROLE_THERAPIST,
    ROLE_DRIVER,
    ROLE_MANAGER,
    ROLE_BILLING,
)

# Reader role sets exactly as declared per endpoint in PRD 4 / SCAFFOLD 1.5.
CLINICAL_READERS = (
    ROLE_MANAGER,
    ROLE_INTAKE,
    ROLE_THERAPIST,
    ROLE_BILLING,
    ROLE_AUDITOR,
    ROLE_PHYSICIAN,
)
CONTRACT_READERS = (
    ROLE_MANAGER,
    ROLE_INTAKE,
    ROLE_THERAPIST,
    ROLE_DRIVER,
    ROLE_BILLING,
    ROLE_AUDITOR,
)
LOGISTICS_READERS = (
    ROLE_MANAGER,
    ROLE_THERAPIST,
    ROLE_DRIVER,
    ROLE_AUDITOR,
    ROLE_BILLING,
)
RECALL_READERS = (ROLE_MANAGER, ROLE_THERAPIST, ROLE_AUDITOR, ROLE_BILLING)
TRAVEL_READERS = (
    ROLE_MANAGER,
    ROLE_INTAKE,
    ROLE_THERAPIST,
    ROLE_BILLING,
    ROLE_AUDITOR,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

API_PREFIX = "/home-oxygen"

# --------------------------------------------------------------------------
# Error catalog (PRD 5) -- error_id -> http status
# --------------------------------------------------------------------------
ERROR_STATUS = {
    # authentication / authorization
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNKNOWN_ROLE": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    # path existence
    "ERR_BRANCH_NOT_FOUND": 404,
    "ERR_PATIENT_NOT_FOUND": 404,
    "ERR_QUALIFYING_TEST_NOT_FOUND": 404,
    "ERR_CMN_NOT_FOUND": 404,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_EQUIPMENT_UNIT_NOT_FOUND": 404,
    "ERR_PLACEMENT_NOT_FOUND": 404,
    "ERR_ROUTE_NOT_FOUND": 404,
    "ERR_ROUTE_STOP_NOT_FOUND": 404,
    "ERR_RECALL_NOTICE_NOT_FOUND": 404,
    "ERR_TRAVEL_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_POSTED_MONTH_NOT_FOUND": 404,
    # schema
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_ENUM_VALUE": 400,
    "ERR_INVALID_PAGINATION": 400,
    # optimistic concurrency
    "ERR_STALE_PATIENT_VERSION": 412,
    "ERR_STALE_CONTRACT_VERSION": 412,
    # uniqueness
    "ERR_DUPLICATE_MRN": 409,
    "ERR_DUPLICATE_SERIAL_NUMBER": 409,
    # state
    "ERR_INVALID_STATE": 409,
    "ERR_REVISION_LIMIT_REACHED": 409,
    "ERR_PATIENT_NOT_ACTIVE": 409,
    "ERR_CONTRACT_CLOSED": 409,
    "ERR_CONTRACT_BILLING_SUSPENDED": 409,
    "ERR_CONTRACT_NOT_IN_SERVICE": 409,
    "ERR_ROUTE_NOT_DISPATCHED": 409,
    "ERR_ROUTE_NOT_EDITABLE": 409,
    "ERR_STOP_TYPE_MISMATCH": 409,
    "ERR_RECALL_NOT_REMEDIATED": 409,
    "ERR_TRANSFER_NOT_DUE": 409,
    "ERR_CONTRACT_NOT_RETURNED": 409,
    # clinical safety
    "ERR_QUALIFYING_TEST_STALE": 422,
    "ERR_DOCUMENTATION_INCOMPLETE": 422,
    "ERR_TEST_NON_QUALIFYING": 422,
    "ERR_PATIENT_ON_COMPLIANCE_HOLD": 409,
    "ERR_PORTABLE_NOT_INDICATED": 422,
    "ERR_REFILL_REQUIRES_LIQUID_PORTABLE": 422,
    "ERR_NO_RESERVED_EQUIPMENT": 422,
    # referential integrity
    "ERR_TEST_PATIENT_MISMATCH": 422,
    "ERR_CMN_PATIENT_MISMATCH": 422,
    "ERR_PATIENT_HAS_OPEN_CONTRACT": 409,
    "ERR_CMN_NOT_ACTIVE": 409,
    "ERR_STOP_BRANCH_MISMATCH": 422,
    "ERR_RECEIVING_BRANCH_INVALID": 422,
    "ERR_REPLACED_UNIT_NOT_REPLACEABLE": 422,
    "ERR_CONTRACT_HAS_RECALLED_EQUIPMENT": 409,
    # temporal
    "ERR_TEST_DATE_IN_FUTURE": 422,
    "ERR_INVALID_SHIFT": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_WINDOW_OUTSIDE_SHIFT": 422,
    "ERR_ROUTE_STOP_WINDOW_CONFLICT": 409,
    "ERR_INVALID_TRAVEL_INTERVAL": 422,
    "ERR_TRAVEL_INTERVAL_CONFLICT": 409,
    "ERR_TRANSFER_DATE_IN_PAST": 422,
    "ERR_CLOCK_NOT_MONOTONIC": 422,
    "ERR_SERVICE_MONTH_BEFORE_START": 422,
    "ERR_SERVICE_MONTH_IN_FUTURE": 422,
    "ERR_SERVICE_MONTH_ALREADY_POSTED": 409,
    # capacity / resource
    "ERR_ROUTE_HAS_NO_STOPS": 422,
    "ERR_REFILL_CAPACITY_EXCEEDED": 422,
    "ERR_ROLE_ALREADY_OCCUPIED": 409,
    "ERR_NO_ELIGIBLE_EQUIPMENT": 409,
    "ERR_CYLINDERS_NOT_APPLICABLE": 422,
    "ERR_BRANCH_NOT_LIQUID_CERTIFIED": 422,
    "ERR_PATIENT_HAS_ACTIVE_SERVICE": 409,
    "ERR_TRAVEL_SUPPLY_EXCEEDS_LIMIT": 422,
    # fiscal
    "ERR_CAP_MONTHS_EXHAUSTED": 409,
    "ERR_REVERSAL_WOULD_NOT_CLEAR_CAP": 409,
    "ERR_NO_PLACED_EQUIPMENT": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.status = ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    body = error_id[4:] if error_id.startswith("ERR_") else error_id
    return body.replace("_", " ").lower().capitalize()


# --------------------------------------------------------------------------
# In-memory store + logical clock (PRD 2.6)
# --------------------------------------------------------------------------
CLOCK_START = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)


class Store(object):
    def __init__(self):
        self.branches = {}
        self.patients = {}
        self.qualifying_tests = {}
        self.cmns = {}
        self.contracts = {}
        self.equipment_units = {}
        self.placements = {}
        self.routes = {}
        self.route_stops = {}
        self.recall_notices = {}
        self.travel_authorizations = {}
        self.clock = CLOCK_START
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def now():
    """The logical clock instant. Real wall-clock time is never read."""
    return db.clock


def today():
    return db.clock.date()


def today_iso():
    return db.clock.date().isoformat()


def current_month():
    return db.clock.strftime("%Y-%m")


def new_id():
    return str(uuid.uuid4())


def iso(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        return dt
    dt = dt.astimezone(UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_date(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return value.isoformat()


# --------------------------------------------------------------------------
# parsing / numeric helpers
# --------------------------------------------------------------------------
_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_datetime(value):
    """Parse an ISO 8601 instant; returns a UTC aware datetime or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        micro = int(round(float(frac) * 1000000))
    offset = m.group(8)
    try:
        base = datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        off = offset[1:].replace(":", "")
        delta = timedelta(hours=int(off[:2]), minutes=int(off[2:4]))
        base = base - sign * delta
    return base


def parse_date_value(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_month_value(value):
    if not isinstance(value, str):
        return None
    m = _MONTH_RE.match(value.strip())
    if not m:
        return None
    month = int(m.group(2))
    if month < 1 or month > 12:
        return None
    return (int(m.group(1)), month)


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places=2):
    quant = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def money(value):
    """Round to whole cents, half up, returning an int."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def num2(value):
    """Serialize a 2 decimal place quantity as a JSON number."""
    if value is None:
        return None
    return float(round_half_up(value, 2))


def add_days(value, days):
    if isinstance(value, datetime):
        return value + timedelta(days=days)
    return value + timedelta(days=days)


def add_months(base_date, months):
    """Add whole months keeping the day-of-month, clamped to month end."""
    total = base_date.month - 1 + months
    year = base_date.year + total // 12
    month = total % 12 + 1
    day = min(base_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def days_in_month(year, month):
    return monthrange(year, month)[1]


def month_str(year, month):
    return "%04d-%02d" % (year, month)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------
def base_row(versioned=True):
    row = {
        "id": new_id(),
        "created_at": now(),
        "_seq": db.next_seq(),
    }
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def touch(row):
    """Record a mutation: refresh updated_at and bump version by one."""
    if row is None:
        return
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1


def order_key(row):
    return (row["created_at"], row["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=order_key)


# --------------------------------------------------------------------------
# response envelope (PRD 2.2 / 2.3)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso(now()),
    }


def respond(data, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(payload), status


def respond_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    payload = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(payload), 200


def respond_error(error_id, message=None, status=None):
    err = ApiError(error_id, message)
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(payload), status or err.status


# --------------------------------------------------------------------------
# authentication / RBAC (ladder positions 1-3)
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def actor():
    return getattr(g, "user_id", None)


# --------------------------------------------------------------------------
# pagination (ladder position 19)
# --------------------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def _int_param(raw):
    if raw is None:
        return None
    text = raw.strip()
    if not re.match(r"^[+-]?\d+$", text):
        raise ApiError("ERR_INVALID_PAGINATION")
    return int(text)


def pagination():
    limit = _int_param(request.args.get("limit"))
    offset = _int_param(request.args.get("offset"))
    if limit is None:
        limit = LIMIT_DEFAULT
    elif limit < LIMIT_MIN or limit > LIMIT_MAX:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset is None:
        offset = OFFSET_DEFAULT
    elif offset < OFFSET_MIN:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginate(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return respond_list([serializer(r) for r in window], limit, offset, total)


def bool_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    low = raw.strip().lower()
    if low == "true":
        return True
    if low == "false":
        return False
    return None


def str_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def enum_filter(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_ENUM_VALUE", "%s is not a valid %s" % (raw, name))
    return raw
