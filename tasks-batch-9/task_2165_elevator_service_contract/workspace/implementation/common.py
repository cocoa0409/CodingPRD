"""Shared foundation: error catalog, in-memory store, logical clock, response
envelope, auth middleware and body-validation helpers.

Every structural name here (headers, envelope fields, pagination fields, error
ids, OCC field names) is taken verbatim from SCAFFOLD.yaml / PRD.md.
"""

import random
import re
import string
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP, getcontext
from fractions import Fraction

from flask import request

getcontext().prec = 60

API_PREFIX = "/elevator-program"

# --------------------------------------------------------------------------
# §1.7 RBAC roles
# --------------------------------------------------------------------------
ROLE_ADMIN = "ProgramAdministrator"
ROLE_MANAGER = "BuildingManager"
ROLE_CONTRACTOR = "ServiceContractor"
ROLE_INSPECTOR = "StateInspector"
ROLE_DISPATCHER = "FireDispatcher"

ALL_ROLES = [ROLE_ADMIN, ROLE_MANAGER, ROLE_CONTRACTOR, ROLE_INSPECTOR, ROLE_DISPATCHER]
ROLE_SET = set(ALL_ROLES)

# --------------------------------------------------------------------------
# §1.6 Error catalog
# --------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_NOT_CONTRACT_PARTY": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_VALIDATION": 400,
    "ERR_CONTRACT_NOT_FOUND": 404,
    "ERR_CAR_NOT_FOUND": 404,
    "ERR_PART_NOT_FOUND": 404,
    "ERR_RESOURCE_NOT_FOUND": 404,
    "ERR_STALE_CONTRACT_VERSION": 412,
    "ERR_STALE_CAR_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_CONTRACT_NOT_ACTIVE": 409,
    "ERR_CAR_DECOMMISSIONED": 409,
    "ERR_CAR_RED_TAGGED": 409,
    "ERR_CERTIFICATE_NOT_ISSUED": 409,
    "ERR_CERTIFICATE_EXPIRED": 409,
    "ERR_VISIT_MONTH_DUPLICATE": 409,
    "ERR_DOWNTIME_WINDOW_CONFLICT": 409,
    "ERR_CONTRACT_MODERNIZATION_CAPACITY": 409,
    "ERR_TASK_LIST_INCOMPLETE": 422,
    "ERR_REWORK_LIMIT_EXCEEDED": 422,
    "ERR_ENTRAPMENT_REQUIRES_FIRE_DISPATCH": 422,
    "ERR_FIRE_DISPATCH_NOT_REQUIRED": 422,
    "ERR_SCOPE_EXCLUDES_REPAIR": 422,
    "ERR_PART_DISCONTINUED": 422,
    "ERR_SUPERSESSION_CHAIN_TOO_DEEP": 422,
    "ERR_INVALID_QUANTITY": 422,
    "ERR_NO_CARS_IN_SCOPE": 422,
    "ERR_PENALTY_PERIOD_NOT_CLOSED": 422,
    "ERR_RENEGOTIATION_NOT_WARRANTED": 422,
    "ERR_RENEGOTIATION_ROUND_LIMIT": 422,
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


# --------------------------------------------------------------------------
# Business constants
# --------------------------------------------------------------------------
UPTIME_TARGET_PCT = Decimal("98.50")
SEVERE_SHORTFALL_PP = Decimal("2.00")
LATE_CALLBACK_FEE_CENTS = 25000
ENTRAPMENT_FEE_CENTS = 100000
MISSED_VISIT_FEE_CENTS = 75000
UPTIME_PENALTY_PER_PP_CENTS = 40000
PENALTY_CAP_PCT_A = Decimal("0.25")
SCHEDULE_B_BREACH_PCT = Decimal("0.02")
PENALTY_CAP_PCT_B = Decimal("0.30")

W_UPTIME = Decimal("0.50")
W_RESPONSE = Decimal("0.25")
W_VISIT = Decimal("0.25")
DRAG_DIVISOR_CENTS = 100000
PENALTY_DRAG_CAP_PTS = Decimal("15.00")
RENEGOTIATION_TRIGGER_SCORE = Decimal("75.00")
MAX_RENEGOTIATION_ROUNDS = 4

SUPERSESSION_MAX_DEPTH = 3
OBSOLETE_SUBSTITUTION_PENALTY_DAYS = 10
EXPEDITE_DAYS_SAVED = 7
MIN_LEAD_DAYS = 3
EXPEDITE_PCT_TIER_SMALL = Decimal("0.20")
EXPEDITE_PCT_TIER_MEDIUM = Decimal("0.15")
EXPEDITE_PCT_TIER_LARGE = Decimal("0.10")

CERTIFICATE_VALIDITY_DAYS = 365
OUT_OF_SERVICE_ESCALATION_COUNT = 2
INTER_TYPE_BUFFER_MINUTES = 120
MAX_CONCURRENT_MODERNIZATION_CARS = 1
MAX_REWORK_COUNT = 2

FULL_MAINTENANCE_REQUIRED_TASK_CODES = [
    "BRAKE", "CONTROLLER", "DOOR_OPERATOR", "FIRE_SERVICE_TEST",
    "GOVERNOR", "PIT_CLEAN", "ROPES",
]
OIL_AND_GREASE_REQUIRED_TASK_CODES = ["LUBRICATION", "PIT_CLEAN", "VISUAL_INSPECTION"]

SCOPE_TYPES = ["FULL_MAINTENANCE", "OIL_AND_GREASE"]
PENALTY_SCHEDULES = ["SCHEDULE_A", "SCHEDULE_B"]
CAR_TYPES = ["TRACTION", "HYDRAULIC"]
CALLBACK_TYPES = ["ENTRAPMENT", "MALFUNCTION", "NUISANCE"]
INSPECTION_TYPES = ["PERIODIC", "FIVE_YEAR_FULL_LOAD", "REINSPECTION"]
INSPECTION_RESULTS = ["PASS", "PASS_WITH_DEFICIENCIES", "FAIL"]
WINDOW_TYPES = ["MODERNIZATION", "INSPECTION", "REPAIR"]
PART_CLASSES = ["LUBRICATION", "WEAR_ITEM", "COMPONENT", "CONTROLLER_BOARD"]
RESOLUTIONS = ["UPHELD", "WAIVED", "CREDITED"]
CLOSE_OUTCOMES = ["REJECTED", "WITHDRAWN"]

PERIOD_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------
# In-memory store — starts completely empty on every boot.
# --------------------------------------------------------------------------
class Store(object):
    def __init__(self):
        self.contracts = {}
        self.cars = {}
        self.visits = {}
        self.callbacks = {}
        self.inspections = {}
        self.projects = {}
        self.windows = {}
        self.parts = {}
        self.part_orders = {}
        self.penalties = {}
        self.rounds = {}
        self.seq = 0
        self.clock = DEFAULT_CLOCK

    def next_seq(self):
        self.seq += 1
        return self.seq


db = Store()


def now_clock():
    """The logical clock — the ONLY source of business instants."""
    return db.clock


# --------------------------------------------------------------------------
# Time helpers
# --------------------------------------------------------------------------
def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def real_now_iso():
    return iso(datetime.now(timezone.utc))


def clock_iso():
    return iso(db.clock)


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


def parse_dt(value):
    """Parse an ISO 8601 UTC datetime; returns None when unparseable."""
    if not isinstance(value, str) or not value:
        return None
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_str(value):
    if not isinstance(value, str) or not DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def date_str(d):
    return d.isoformat() if d is not None else None


def month_bounds(period_month):
    """[first instant of period_month, first instant of the next month)."""
    year = int(period_month[0:4])
    month = int(period_month[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def month_of(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d" % (dt.year, dt.month)


def previous_month(dt):
    dt = dt.astimezone(timezone.utc)
    year, month = dt.year, dt.month
    month -= 1
    if month == 0:
        month = 12
        year -= 1
    return "%04d-%02d" % (year, month)


# --------------------------------------------------------------------------
# Rounding
# --------------------------------------------------------------------------
def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, Fraction):
        return Decimal(value.numerator) / Decimal(value.denominator)
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    """Round half up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return to_decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def dec2(value):
    return rhu(value, 2)


def num(value):
    """Render a Decimal as a JSON number."""
    if value is None:
        return None
    return float(value)


# --------------------------------------------------------------------------
# Entities
# --------------------------------------------------------------------------
def new_entity(fields):
    ts = real_now_iso()
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }
    entity.update(fields)
    return entity


def touch(entity):
    """Every mutation refreshes updated_at and advances version by exactly 1."""
    entity["updated_at"] = real_now_iso()
    entity["version"] = entity["version"] + 1


def serialize(entity):
    if entity is None:
        return None
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def sorted_rows(collection):
    """Default ordering is created_at ascending (insertion order is stable)."""
    return sorted(collection.values(), key=lambda e: e["_seq"])


# --------------------------------------------------------------------------
# Response envelope (§2.2)
# --------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {"api_request_id": _request_id(), "api_request_timestamp": real_now_iso()}


def object_response(data, status=200):
    return {"meta": base_meta(), "response_type": "object", "data": data}, status


def array_response(items, limit, offset, total_count):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {"meta": meta, "response_type": "array", "data": items}, 200


def error_response(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }, ERROR_STATUS.get(error_id, 400)


# --------------------------------------------------------------------------
# Pagination (§2.3): limit default 10 min 1 max 100; offset default 0 min 0
# --------------------------------------------------------------------------
def pagination_params():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None and raw_limit != "":
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
    raw_offset = request.args.get("offset")
    if raw_offset is not None and raw_offset != "":
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(rows):
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return array_response([serialize(r) for r in page], limit, offset, total)


def filter_equals(rows, field, arg_name=None):
    value = request.args.get(arg_name or field)
    if value is None or value == "":
        return rows
    return [r for r in rows if r.get(field) == value]


# --------------------------------------------------------------------------
# Auth middleware (§2.1 / validations priority 10 & 20)
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLE_SET:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    return user_id, role


def check_contract_party(contract, user_id, role):
    """Priority 40 — BuildingManager / ServiceContractor identity binding."""
    if role == ROLE_MANAGER and user_id != contract.get("building_manager_user_id"):
        fail("ERR_NOT_CONTRACT_PARTY")
    if role == ROLE_CONTRACTOR and user_id != contract.get("contractor_user_id"):
        fail("ERR_NOT_CONTRACT_PARTY")


# --------------------------------------------------------------------------
# Lookups (priority 30 — existence, left to right)
# --------------------------------------------------------------------------
def get_contract(contract_id):
    row = db.contracts.get(contract_id)
    if row is None:
        fail("ERR_CONTRACT_NOT_FOUND")
    return row


def get_car(car_id):
    row = db.cars.get(car_id)
    if row is None:
        fail("ERR_CAR_NOT_FOUND")
    return row


def get_part(part_id):
    row = db.parts.get(part_id)
    if row is None:
        fail("ERR_PART_NOT_FOUND")
    return row


def get_resource(collection, resource_id):
    row = collection.get(resource_id)
    if row is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    return row


def contract_of_car(car):
    return db.contracts.get(car["contract_id"])


# --------------------------------------------------------------------------
# Body validation helpers (priority 50 — ERR_VALIDATION 400)
# --------------------------------------------------------------------------
def json_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return body


def _present(body, field):
    return field in body and body[field] is not None


def req_string(body, field):
    if not _present(body, field) or not isinstance(body[field], str) or body[field] == "":
        fail("ERR_VALIDATION", "Field '%s' is required and must be a string." % field)
    return body[field]


def opt_string(body, field, default=None):
    if not _present(body, field):
        return default
    if not isinstance(body[field], str):
        fail("ERR_VALIDATION", "Field '%s' must be a string." % field)
    return body[field]


def req_enum(body, field, choices):
    value = req_string(body, field)
    if value not in choices:
        fail("ERR_VALIDATION", "Field '%s' must be one of %s." % (field, ", ".join(choices)))
    return value


def opt_enum(body, field, choices, default=None):
    if not _present(body, field):
        return default
    return req_enum(body, field, choices)


def req_int(body, field, minimum=None):
    if not _present(body, field):
        fail("ERR_VALIDATION", "Field '%s' is required." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "Field '%s' must be >= %d." % (field, minimum))
    return value


def opt_int(body, field, default=None, minimum=None):
    if not _present(body, field):
        return default
    return req_int(body, field, minimum)


def req_bool(body, field, default=None):
    if not _present(body, field):
        if default is None:
            fail("ERR_VALIDATION", "Field '%s' is required." % field)
        return default
    if not isinstance(body[field], bool):
        fail("ERR_VALIDATION", "Field '%s' must be a boolean." % field)
    return body[field]


def req_date(body, field):
    value = req_string(body, field)
    parsed = parse_date_str(value)
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be a YYYY-MM-DD date." % field)
    return parsed


def req_datetime(body, field):
    value = req_string(body, field)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 UTC datetime." % field)
    return parsed


def req_period_month(body, field="period_month"):
    value = req_string(body, field)
    if not PERIOD_MONTH_RE.match(value):
        fail("ERR_VALIDATION", "Field '%s' must match YYYY-MM." % field)
    return value


def req_id(body, field):
    """A foreign-key body field: must be present and a string."""
    if not _present(body, field) or not isinstance(body[field], str) or body[field] == "":
        fail("ERR_VALIDATION", "Field '%s' is required." % field)
    return body[field]


def opt_id(body, field):
    if not _present(body, field):
        return None
    if not isinstance(body[field], str) or body[field] == "":
        fail("ERR_VALIDATION", "Field '%s' must be a string identifier." % field)
    return body[field]


# --------------------------------------------------------------------------
# Governing-contract status gate (priority 72)
# --------------------------------------------------------------------------
OPERATIONAL_CONTRACT_STATES = ("ACTIVE", "SERVICE_ALERT")


def require_contract_operational(contract):
    if contract is None or contract["status"] not in OPERATIONAL_CONTRACT_STATES:
        fail("ERR_CONTRACT_NOT_ACTIVE")


def require_contract_status(contract, *statuses):
    if contract is None or contract["status"] not in statuses:
        fail("ERR_CONTRACT_NOT_ACTIVE")


# --------------------------------------------------------------------------
# Car safety gates (priority 80 / 82)
# --------------------------------------------------------------------------
def require_car_not_decommissioned(car):
    if car["availability_state"] == "DECOMMISSIONED":
        fail("ERR_CAR_DECOMMISSIONED")


def require_car_not_red_tagged(car):
    if car["compliance_state"] == "RED_TAGGED":
        fail("ERR_CAR_RED_TAGGED")


# --------------------------------------------------------------------------
# Child-row selectors
# --------------------------------------------------------------------------
def cars_of_contract(contract_id, include_decommissioned=False):
    rows = [c for c in db.cars.values() if c["contract_id"] == contract_id]
    if not include_decommissioned:
        rows = [c for c in rows if c["availability_state"] != "DECOMMISSIONED"]
    return sorted(rows, key=lambda c: (c["car_code"], c["_seq"]))


def windows_of_car(car_id):
    return [w for w in db.windows.values() if w["car_id"] == car_id]


def callbacks_of_car(car_id):
    return [c for c in db.callbacks.values() if c["car_id"] == car_id]


def inspections_of_car(car_id):
    return [i for i in db.inspections.values() if i["car_id"] == car_id]


def visits_of_car(car_id):
    return [v for v in db.visits.values() if v["car_id"] == car_id]


def part_orders_of_car(car_id):
    return [o for o in db.part_orders.values() if o["car_id"] == car_id]


def projects_of_contract(contract_id):
    return [p for p in db.projects.values() if p["contract_id"] == contract_id]


def rounds_of_contract(contract_id):
    return [r for r in db.rounds.values() if r["contract_id"] == contract_id]


def penalties_of_contract(contract_id):
    return [p for p in db.penalties.values() if p["contract_id"] == contract_id]


def windows_of_project(project_id):
    return [w for w in db.windows.values() if w.get("project_id") == project_id]
