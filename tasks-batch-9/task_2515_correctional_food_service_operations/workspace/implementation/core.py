"""Core infrastructure: logical clock, in-memory store, response envelope,
error catalogue, auth middleware and the ordered validation helpers.

Correctional Food Service Operations API (prefix /cfs).
"""
import random
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, ROUND_DOWN

from flask import jsonify, request

# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
ROLE_CONTRACT_ADMINISTRATOR = "ContractAdministrator"
ROLE_FOOD_SERVICE_SUPERVISOR = "FoodServiceSupervisor"
ROLE_REGISTERED_DIETITIAN = "RegisteredDietitian"
ROLE_CORRECTIONAL_OFFICER = "CorrectionalOfficer"
ROLE_MEDICAL_PROVIDER = "MedicalProvider"
ROLE_CHAPLAIN_DESIGNEE = "ChaplainDesignee"
ROLE_GRIEVANCE_COORDINATOR = "GrievanceCoordinator"
ROLE_COMPLIANCE_AUDITOR = "ComplianceAuditor"

ALL_ROLES = (
    ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_FOOD_SERVICE_SUPERVISOR,
    ROLE_REGISTERED_DIETITIAN,
    ROLE_CORRECTIONAL_OFFICER,
    ROLE_MEDICAL_PROVIDER,
    ROLE_CHAPLAIN_DESIGNEE,
    ROLE_GRIEVANCE_COORDINATOR,
    ROLE_COMPLIANCE_AUDITOR,
)

# --------------------------------------------------------------------------
# Error catalogue: error_id -> (http_status, default message)
# --------------------------------------------------------------------------
ERRORS = {
    # auth
    "ERR_MISSING_USER_HEADER": (401, "X-User-ID header is absent or empty."),
    "ERR_MISSING_ROLE_HEADER": (401, "X-User-Role header is absent or empty."),
    "ERR_UNKNOWN_ROLE": (401, "X-User-Role is not one of the eight defined roles."),
    "ERR_UNAUTHORIZED": (403, "The role is not authorized for this endpoint."),
    # shape
    "ERR_INVALID_REQUEST": (400, "A required input field is missing or has the wrong JSON type."),
    "ERR_INVALID_ENUM_VALUE": (422, "An enumerated field carries a value outside its declared domain."),
    "ERR_VALUE_OUT_OF_RANGE": (422, "A numeric field violates its declared range."),
    # existence
    "ERR_SERVICE_CONTRACT_NOT_FOUND": (404, "The referenced service contract does not exist."),
    "ERR_FACILITY_NOT_FOUND": (404, "The referenced facility does not exist."),
    "ERR_MENU_CYCLE_NOT_FOUND": (404, "The referenced menu cycle does not exist."),
    "ERR_MENU_CYCLE_ITEM_NOT_FOUND": (404, "The referenced menu cycle item does not exist."),
    "ERR_INMATE_NOT_FOUND": (404, "The referenced inmate does not exist."),
    "ERR_DIET_ORDER_NOT_FOUND": (404, "The referenced diet order does not exist."),
    "ERR_POPULATION_COUNT_NOT_FOUND": (404, "The referenced population count does not exist."),
    "ERR_MEAL_FORECAST_NOT_FOUND": (404, "The referenced meal forecast does not exist."),
    "ERR_PRODUCTION_BATCH_NOT_FOUND": (404, "The referenced production batch does not exist."),
    "ERR_TEMPERATURE_LOG_NOT_FOUND": (404, "The referenced temperature log does not exist."),
    "ERR_INMATE_WORKER_NOT_FOUND": (404, "The referenced inmate worker does not exist."),
    "ERR_TOOL_ISSUANCE_NOT_FOUND": (404, "The referenced tool issuance does not exist."),
    "ERR_CONTRABAND_INCIDENT_NOT_FOUND": (404, "The referenced contraband incident does not exist."),
    "ERR_MEAL_SERVICE_RECORD_NOT_FOUND": (404, "The referenced meal service record does not exist."),
    "ERR_MENU_SUBSTITUTION_NOT_FOUND": (404, "The referenced menu substitution does not exist."),
    "ERR_GRIEVANCE_NOT_FOUND": (404, "The referenced grievance does not exist."),
    # coherence / uniqueness
    "ERR_FACILITY_MISMATCH": (409, "The referenced parents do not agree on facility."),
    "ERR_CYCLE_DAY_OUT_OF_RANGE": (422, "cycle_day is outside 1..cycle_length_days."),
    "ERR_DUPLICATE_RESOURCE": (409, "A resource with the same natural key already exists."),
    # concurrency
    "ERR_STALE_INMATE_VERSION": (412, "expected_inmate_version does not match the inmate's version."),
    "ERR_STALE_FACILITY_VERSION": (412, "expected_facility_version does not match the facility's version."),
    "ERR_STALE_CONTRACT_VERSION": (412, "expected_service_contract_version does not match the contract's version."),
    # state
    "ERR_ALREADY_TERMINAL": (409, "The target resource already sits in a terminal state."),
    "ERR_INVALID_STATE": (409, "The resource is not in a state that permits this operation."),
    "ERR_ILLEGAL_TRANSITION": (409, "The requested transition is not legal from the current state."),
    # security posture
    "ERR_KITCHEN_POSTURE_BLOCKED": (409, "The facility's kitchen_posture forbids this operation."),
    "ERR_SHARPS_DISCREPANCY_OPEN": (409, "An unaccounted tool is outstanding at this facility."),
    "ERR_WORKER_NOT_SHARPS_ELIGIBLE": (409, "The worker is not sharps eligible."),
    "ERR_WORKER_NOT_CLEARED": (409, "The worker's clearance status forbids this operation."),
    "ERR_MEDICAL_CLEARANCE_EXPIRED": (409, "The worker's medical clearance has expired."),
    "ERR_OPEN_CONTRABAND_HOLD": (409, "The worker has an open contraband incident."),
    "ERR_SHARPS_COUNT_OVER_AUTHORIZED": (422, "The sharps audit exceeds the authorized count."),
    # clinical / duties
    "ERR_CLINICAL_INDICATION_REQUIRED": (422, "clinical_indication is required for a medical diet order."),
    "ERR_VERIFIER_ROLE_MISMATCH": (403, "The verifying role does not match the diet order type."),
    "ERR_SEGREGATION_OF_DUTIES": (409, "The acting user may not both originate and confirm this action."),
    "ERR_INMATE_NOT_IN_CUSTODY": (409, "The inmate is not IN_CUSTODY."),
    # nutrition
    "ERR_NUTRITION_BELOW_STANDARD": (422, "The menu cycle falls below a contracted nutrition floor."),
    "ERR_SODIUM_CAP_EXCEEDED": (422, "The menu cycle exceeds the contracted sodium cap."),
    "ERR_MENU_CYCLE_INCOMPLETE": (409, "The menu cycle does not carry exactly three items per cycle day."),
    "ERR_SUBSTITUTION_NOT_EQUIVALENT": (409, "The substitution is not nutritionally equivalent."),
    # cook-chill
    "ERR_COOK_CHILL_NONCOMPLIANT": (409, "The batch is not cook-chill compliant."),
    "ERR_COOK_LOG_MISSING": (409, "An in-range COOK_END reading is required."),
    "ERR_CHILL_LOG_MISSING": (409, "An in-range CHILL_FINAL reading is required."),
    "ERR_QA_NOT_PASSED": (409, "The batch's qa_status is not QA_PASSED."),
    "ERR_REHEAT_LOG_MISSING": (409, "An in-range REHEAT_SERVE reading is required."),
    "ERR_LOG_POINT_OUT_OF_SEQUENCE": (409, "The temperature log point is out of sequence."),
    "ERR_BATCH_DISCARDED": (409, "The production batch has been discarded."),
    "ERR_CHILLER_CAPACITY_EXCEEDED": (409, "The blast chiller window is at capacity."),
    # windows
    "ERR_INVALID_WINDOW": (422, "effective_to must be strictly after effective_from."),
    "ERR_DIET_ORDER_WINDOW_CONFLICT": (409, "The coverage window overlaps an existing diet order."),
    "ERR_REVERIFICATION_LIMIT_REACHED": (409, "The reverification limit has been reached."),
    # forecasting / service
    "ERR_FORECAST_DATE_PAST": (422, "service_date is earlier than the current logical date."),
    "ERR_SERVICE_WINDOW_MISMATCH": (422, "service_date or meal_slot does not match the forecast."),
    "ERR_NO_ACTIVE_MENU_CYCLE": (409, "The facility has no ACTIVE menu cycle."),
    "ERR_FORECAST_NOT_LOCKED": (409, "The meal forecast is not LOCKED."),
    "ERR_CONTRACT_NOT_ACTIVE": (409, "The governing service contract is not ACTIVE."),
    "ERR_DUPLICATE_FORECAST": (409, "A forecast already exists for this facility, date and meal slot."),
    "ERR_DUPLICATE_SERVICE_RECORD": (409, "A service record already exists for this forecast."),
    "ERR_OPEN_BATCHES_REMAIN": (409, "Production batches for this facility are still open."),
    # grievance
    "ERR_BRANCHES_INCOMPLETE": (409, "The grievance's required branches are not complete."),
    "ERR_REMEDY_NOT_PERMITTED": (409, "The remedy is not permitted for this grievance."),
    "ERR_REFEED_TARGET_INVALID": (409, "The refeed target is invalid."),
    "ERR_REINSTATEMENT_TARGET_INVALID": (409, "The reinstatement target is invalid."),
    # reconciliation
    "ERR_LD_VARIANT_REQUIRED": (422, "ld_variant must be INCIDENT_BASED or POPULATION_WEIGHTED."),
    "ERR_TRAY_BUDGET_EXCEEDED": (409, "The planned trays exceed the forecast tray budget."),
    "ERR_COST_CEILING_EXCEEDED": (422, "The cycle cost exceeds the contracted cost ceiling."),
    "ERR_NOT_FOUND": (404, "Resource not found."),
    "ERR_METHOD_NOT_ALLOWED": (405, "Method not allowed."),
    "ERR_INTERNAL": (500, "Internal server error."),
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        status, default_message = ERRORS.get(error_id, (400, error_id))
        self.http_status = status
        self.message = message or default_message


# --------------------------------------------------------------------------
# Timestamps and the logical clock (PRD 2.4)
# --------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class LogicalClock(object):
    def __init__(self):
        self.current = DEFAULT_CLOCK

    def now(self):
        return self.current

    def set(self, value):
        self.current = value


CLOCK = LogicalClock()


def now_logical():
    """The logical clock: every system-written domain instant reads from here."""
    return CLOCK.now()


def now_wall():
    """Real wall clock: used for created_at / updated_at and envelope meta."""
    return datetime.now(timezone.utc)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10:
        return None
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def date_midnight(service_date):
    """The service date treated as midnight UTC."""
    return parse_date(service_date)


def elapsed_minutes(start, end):
    """Whole elapsed minutes, fractions discarded (floor)."""
    if start is None or end is None:
        return None
    # Timedelta floor division is exact and floors toward negative infinity.
    return int((end - start) // timedelta(minutes=1))


# --------------------------------------------------------------------------
# In-memory store — empty on every boot, no seeding whatsoever
# --------------------------------------------------------------------------
COLLECTIONS = (
    "service_contracts",
    "facilities",
    "menu_cycles",
    "menu_cycle_items",
    "inmates",
    "diet_orders",
    "population_counts",
    "meal_forecasts",
    "production_batches",
    "temperature_logs",
    "inmate_workers",
    "tool_issuances",
    "contraband_incidents",
    "meal_service_records",
    "menu_substitutions",
    "grievances",
)


class Store(object):
    def __init__(self):
        self.data = {}
        for name in COLLECTIONS:
            self.data[name] = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def col(self, name):
        return self.data[name]


DB = Store()


def new_id():
    return str(uuid.uuid4())


def base_row(with_version=True):
    stamp = now_wall()
    row = {"id": new_id(), "created_at": stamp}
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = DB.next_seq()
    return row


def touch(row):
    """Every mutation of a row bumps version by exactly 1 and refreshes updated_at."""
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = now_wall()


def insert(collection, row):
    DB.col(collection)[row["id"]] = row
    return row


def all_rows(collection):
    """Default ordering: created_at ascending, stable by insertion sequence."""
    return sorted(DB.col(collection).values(), key=lambda r: (r["created_at"], r["_seq"]))


def get_row(collection, row_id):
    if not isinstance(row_id, str):
        return None
    return DB.col(collection).get(row_id)


def require_row(collection, row_id, error_id):
    row = get_row(collection, row_id)
    if row is None:
        raise ApiError(error_id)
    return row


# --------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# --------------------------------------------------------------------------
_ID_ALPHABET = string.ascii_uppercase + string.digits


def request_meta():
    return {
        "api_request_id": "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20)),
        "api_request_timestamp": iso(now_wall()),
    }


def to_json(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return dict((k, to_json(v)) for k, v in value.items() if not k.startswith("_"))
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    return value


def public(row):
    """Serialize a stored row, dropping internal (underscore-prefixed) keys."""
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        out[key] = to_json(value)
    return out


def respond_object(payload, http_status=200):
    body = {
        "meta": request_meta(),
        "response_type": "object",
        "data": to_json(payload),
    }
    return jsonify(body), http_status


def respond_list(rows, limit, offset, total_count):
    meta = request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [to_json(r) for r in rows],
    }
    return jsonify(body), 200


def respond_error(error_id, message, http_status):
    body = {
        "meta": request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# --------------------------------------------------------------------------
# Auth (validation ladder priorities 1-4)
# --------------------------------------------------------------------------
class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authorize(*roles):
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_MISSING_USER_HEADER")
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "":
        raise ApiError("ERR_MISSING_ROLE_HEADER")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if roles and role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Actor(user_id, role)


def body_json():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return {}
    return payload


# --------------------------------------------------------------------------
# Pagination (PRD 2.3) — evaluated at ladder priority 7
# --------------------------------------------------------------------------
PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def _query_int(name, default):
    if name not in request.args:
        return default
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        raise ApiError("ERR_VALUE_OUT_OF_RANGE", "%s must be an integer." % name)
    try:
        return int(raw.strip())
    except ValueError:
        raise ApiError("ERR_VALUE_OUT_OF_RANGE", "%s must be an integer." % name)


def pagination():
    limit = _query_int("limit", PAGINATION_LIMIT_DEFAULT)
    if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
        raise ApiError("ERR_VALUE_OUT_OF_RANGE", "limit must be between 1 and 100.")
    offset = _query_int("offset", PAGINATION_OFFSET_DEFAULT)
    if offset < PAGINATION_OFFSET_MIN:
        raise ApiError("ERR_VALUE_OUT_OF_RANGE", "offset must be at least 0.")
    return limit, offset


def page(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


def listing(rows):
    limit, offset = pagination()
    window, total = page(rows, limit, offset)
    return respond_list([public(r) for r in window], limit, offset, total)


def filter_eq(rows, field, param=None):
    """Conjunctive optional query filter on an exact field value."""
    param = param or field
    if param not in request.args:
        return rows
    wanted = request.args.get(param)
    return [r for r in rows if str(r.get(field)) == wanted]


# --------------------------------------------------------------------------
# Field validation (ladder priorities 5, 6, 7) — declared field order matters
# --------------------------------------------------------------------------
class Field(object):
    def __init__(self, name, ftype, required=False, enum=None,
                 min_inclusive=None, min_exclusive=None,
                 max_inclusive=None, max_exclusive=None):
        self.name = name
        self.ftype = ftype
        self.required = required
        self.enum = enum
        self.min_inclusive = min_inclusive
        self.min_exclusive = min_exclusive
        self.max_inclusive = max_inclusive
        self.max_exclusive = max_exclusive

    @property
    def has_range(self):
        return (self.min_inclusive is not None or self.min_exclusive is not None
                or self.max_inclusive is not None or self.max_exclusive is not None)


def _type_ok(value, ftype):
    if ftype == "string":
        return isinstance(value, str)
    if ftype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if ftype == "number":
        return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
    if ftype == "boolean":
        return isinstance(value, bool)
    if ftype == "array":
        return isinstance(value, list)
    if ftype == "object":
        return isinstance(value, dict)
    if ftype == "datetime":
        return parse_instant(value) is not None
    if ftype == "date":
        return parse_date(value) is not None
    return True


def present(body, name):
    return name in body and body[name] is not None


def validate_fields(body, fields):
    """Priorities 5, 6 and 7, each sweeping the declared field order."""
    for f in fields:
        if f.required and not present(body, f.name):
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % f.name)
        if present(body, f.name) and not _type_ok(body[f.name], f.ftype):
            raise ApiError("ERR_INVALID_REQUEST",
                           "Field '%s' must be of type %s." % (f.name, f.ftype))
    for f in fields:
        if f.enum and present(body, f.name):
            if body[f.name] not in f.enum:
                raise ApiError("ERR_INVALID_ENUM_VALUE",
                               "Field '%s' must be one of %s." % (f.name, ", ".join(f.enum)))
    for f in fields:
        if f.has_range and present(body, f.name):
            value = Decimal(str(body[f.name]))
            name = f.name
            if f.min_inclusive is not None and value < Decimal(str(f.min_inclusive)):
                raise ApiError("ERR_VALUE_OUT_OF_RANGE",
                               "Field '%s' must be at least %s." % (name, f.min_inclusive))
            if f.min_exclusive is not None and value <= Decimal(str(f.min_exclusive)):
                raise ApiError("ERR_VALUE_OUT_OF_RANGE",
                               "Field '%s' must be greater than %s." % (name, f.min_exclusive))
            if f.max_inclusive is not None and value > Decimal(str(f.max_inclusive)):
                raise ApiError("ERR_VALUE_OUT_OF_RANGE",
                               "Field '%s' must be at most %s." % (name, f.max_inclusive))
            if f.max_exclusive is not None and value >= Decimal(str(f.max_exclusive)):
                raise ApiError("ERR_VALUE_OUT_OF_RANGE",
                               "Field '%s' must be less than %s." % (name, f.max_exclusive))


def check_string_length(body, name, minimum, maximum):
    if present(body, name):
        length = len(body[name])
        if length < minimum or length > maximum:
            raise ApiError("ERR_VALUE_OUT_OF_RANGE",
                           "Field '%s' must be %d to %d characters." % (name, minimum, maximum))


def optional_str(body, name):
    if present(body, name):
        return body[name]
    return None
