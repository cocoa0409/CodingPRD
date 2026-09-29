"""Foundation: constants, in-memory store, logical clock, envelope, errors, validators."""
import math
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from fractions import Fraction

from flask import g, jsonify, request

API_PREFIX = "/price-integrity"

# ---------------------------------------------------------------- constants
OZ_PER_LB = 16
FL_OZ_PER_GAL = 128
ACTION_WEIGHTS = {
    "COACHING": 5,
    "RETRAINING_ASSIGNED": 10,
    "WRITTEN_WARNING": 15,
    "SUSPENSION": 25,
}
TASK_WEIGHT_NUMERATOR = 40
TASK_WEIGHT_OFFSET = 4
SUSPENSION_SCORE_FLOOR = 80
TRAINING_PASS_SCORE_PCT = 80
CERTIFICATION_VALID_DAYS = 365
REMEDIAL_MODULE_CODE = "REMEDIAL_LABEL_101"
REJECTION_ACTION_THRESHOLD = 2
VERIFICATION_GRACE_HOURS = 48
POSTURE_AUDIT_WINDOW_DAYS = 30
FROZEN_OPEN_FINDING_COUNT = 3
FROZEN_FAILED_AUDIT_COUNT = 2
RESTRICTED_BACKLOG_COUNT = 5
SEVERITY_WEIGHTS = {"MINOR": 1, "MAJOR": 3, "CRITICAL": 8}
PENALTY_ITEM_CAP = 10
REFUND_CREDIT_RATE_BP = 7500
CREDIT_CAP_PCT = 50
MIN_CATEGORY_SAMPLE = 2
ASSOCIATE_DAILY_MINUTES_CAP = 480
AISLE_AUDIT_COOLDOWN_MINUTES = 60

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

# ---------------------------------------------------------------- roles
R_PRICING_ADMIN = "PricingAdmin"
R_COMPLIANCE_OFFICER = "ComplianceOfficer"
R_STORE_MANAGER = "StoreManager"
R_LABEL_ASSOCIATE = "LabelAssociate"
R_PRICE_AUDITOR = "PriceAuditor"
R_CUSTOMER_SERVICE_DESK = "CustomerServiceDesk"
ALL_ROLES = [
    R_PRICING_ADMIN,
    R_COMPLIANCE_OFFICER,
    R_STORE_MANAGER,
    R_LABEL_ASSOCIATE,
    R_PRICE_AUDITOR,
    R_CUSTOMER_SERVICE_DESK,
]
# entity-backed roles -> required Associate.role_code
ENTITY_BACKED_ROLES = {
    R_STORE_MANAGER: "STORE_MANAGER",
    R_LABEL_ASSOCIATE: "LABEL_ASSOCIATE",
    R_PRICE_AUDITOR: "PRICE_AUDITOR",
}
HEADER_ROLE = "X-User-Role"
HEADER_USER_ID = "X-User-ID"
ALL_READ_ROLES = ALL_ROLES

# ---------------------------------------------------------------- enums
UOM_RULES = ["PER_UNIT_MEASURE_CANONICAL", "PER_100_COUNT", "PER_SINGLE_ITEM"]
ROUNDING_MODES = ["ROUND_HALF_UP", "ROUND_CEILING"]
RATE_VARIANTS = ["GROSS_MISMATCH", "NET_OVERCHARGE"]
REFUND_POLICIES = [
    "REFUND_DIFFERENCE_ONLY",
    "REFUND_DIFFERENCE_PLUS_FIXED",
    "ITEM_FREE_UP_TO_CAP",
]
ACCOUNTABILITY_VARIANTS = ["OCCURRENCE_WEIGHTED", "TASK_WEIGHTED"]
POSTURES = ["OPEN", "RESTRICTED", "FROZEN"]
ASSOCIATE_ROLE_CODES = ["LABEL_ASSOCIATE", "PRICE_AUDITOR", "STORE_MANAGER"]
TRAINING_STATUSES = ["UNTRAINED", "IN_TRAINING", "CERTIFIED", "SUSPENDED"]
ACTION_TRIGGER_CODES = [
    "AUDIT_FAIL",
    "OVERDUE_LABEL_TASK",
    "VERIFICATION_REJECTED",
    "INSPECTION_FINDING",
    "EXCEPTION_ROOT_CAUSE",
]
ACTION_TYPES = ["COACHING", "RETRAINING_ASSIGNED", "WRITTEN_WARNING", "SUSPENSION"]
ACTION_STATUSES = ["ISSUED", "COMPLETED", "VOIDED"]
FILE_PRIORITIES = ["ROUTINE", "COMPETITIVE", "REGULATORY"]
FILE_STATUSES = ["DRAFT", "DISTRIBUTED", "PARTIALLY_EXECUTED", "EXECUTED", "SUPERSEDED"]
LINE_STATUSES = ["PENDING", "TASKED", "LABELED", "VERIFIED", "FAILED", "WITHDRAWN"]
NET_CONTENT_UOMS = ["EACH", "OZ", "FL_OZ", "LB", "GAL", "CT"]
PRINT_STATUSES = ["NOT_PRINTED", "PRINTED", "REPRINT_REQUIRED"]
PLACEMENT_STATUSES = ["UNPLACED", "PLACED", "VERIFIED", "REJECTED"]
VERIFY_OUTCOMES = ["VERIFIED", "REJECTED"]
AUDIT_TYPES = ["ROUTINE", "FOLLOW_UP", "REGULATORY"]
AUDIT_STATUSES = ["OPEN", "SCANNING", "CLOSED", "REOPENED"]
AUDIT_OUTCOMES = ["PENDING", "PASS", "FAIL"]
CLASSIFICATIONS = ["MATCH", "OVERCHARGE", "UNDERCHARGE"]
SIGNAGE_STATUSES = [
    "DRAFT",
    "POSTED",
    "EXPIRED_PENDING_REMOVAL",
    "NON_COMPLIANT",
    "REMOVED",
]
SIGNAGE_COMPLIANCE_STATES = [
    "COMPLIANT",
    "MISSING_DISCLOSURE",
    "EXPIRED_NOT_REMOVED",
    "NOT_APPLICABLE",
]
INSPECTION_STATUSES = [
    "SCHEDULED",
    "FINDINGS_ISSUED",
    "RESPONSE_SUBMITTED",
    "RESPONSE_REJECTED",
    "CLOSED",
]
FINDING_CODES = [
    "SHELF_TAG_MISMATCH",
    "UNIT_PRICE_FORMAT",
    "SIGNAGE_DISCLOSURE",
    "EXPIRED_SIGNAGE",
    "SCANNER_ERROR_RATE",
]
SEVERITIES = ["MINOR", "MAJOR", "CRITICAL"]
FINDING_STATUSES = [
    "OPEN",
    "REMEDIATION_PLANNED",
    "REMEDIATED",
    "WAIVED",
    "ESCALATED",
]
REFUND_STATUSES = ["PENDING", "APPROVED", "PAID", "DENIED"]
DECISIONS = ["ACCEPT", "REJECT"]
EXCEPTION_REPORT_STATUSES = ["GENERATED", "REMEDIATION_OPEN", "CLOSED"]
ROOT_CAUSE_CODES = [
    "LABEL_NOT_PLACED",
    "LABEL_PRINT_ERROR",
    "FILE_LATE_DISTRIBUTION",
    "SIGNAGE_NOT_REMOVED",
    "REGISTER_FILE_MISMATCH",
    "TRAINING_GAP",
]

# ---------------------------------------------------------------- errors
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_ROLE_CODE_MISMATCH": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_JURISDICTION_NOT_FOUND": 404,
    "ERR_STORE_NOT_FOUND": 404,
    "ERR_AISLE_NOT_FOUND": 404,
    "ERR_ASSOCIATE_NOT_FOUND": 404,
    "ERR_PRICE_CHANGE_FILE_NOT_FOUND": 404,
    "ERR_PRICE_CHANGE_LINE_NOT_FOUND": 404,
    "ERR_LABEL_TASK_NOT_FOUND": 404,
    "ERR_SCANNER_AUDIT_NOT_FOUND": 404,
    "ERR_SCAN_LINE_NOT_FOUND": 404,
    "ERR_PROMO_SIGNAGE_NOT_FOUND": 404,
    "ERR_REGULATORY_INSPECTION_NOT_FOUND": 404,
    "ERR_INSPECTION_FINDING_NOT_FOUND": 404,
    "ERR_REFUND_CLAIM_NOT_FOUND": 404,
    "ERR_EXCEPTION_REPORT_NOT_FOUND": 404,
    "ERR_ACCOUNTABILITY_ACTION_NOT_FOUND": 404,
    "ERR_FILE_INVALID_STATE": 409,
    "ERR_LABEL_TASK_INVALID_STATE": 409,
    "ERR_AUDIT_INVALID_STATE": 409,
    "ERR_SIGNAGE_INVALID_STATE": 409,
    "ERR_INSPECTION_INVALID_STATE": 409,
    "ERR_FINDING_INVALID_STATE": 409,
    "ERR_REFUND_CLAIM_INVALID_STATE": 409,
    "ERR_EXCEPTION_REPORT_INVALID_STATE": 409,
    "ERR_ACTION_INVALID_STATE": 409,
    "ERR_ASSOCIATE_INVALID_STATE": 409,
    "ERR_TRANSITION_ALREADY_APPLIED": 409,
    "ERR_AUDIT_NOT_CLOSED": 409,
    "ERR_FILE_NOT_DISTRIBUTED": 409,
    "ERR_EVIDENCE_AUDIT_NOT_CLOSED": 409,
    "ERR_LABEL_NOT_PRINTED": 409,
    "ERR_STALE_PRICE_CHANGE_FILE_VERSION": 412,
    "ERR_STALE_INSPECTION_VERSION": 412,
    "ERR_STALE_SCANNER_AUDIT_VERSION": 412,
    "ERR_SEGREGATION_OF_DUTIES": 422,
    "ERR_ASSOCIATE_NOT_CERTIFIED": 422,
    "ERR_STORE_POSTURE_BLOCKED": 422,
    "ERR_UNIT_PRICE_UNAVAILABLE": 422,
    "ERR_TRAINING_SCORE_TOO_LOW": 422,
    "ERR_EFFECTIVE_DATE_PASSED": 422,
    "ERR_INVALID_WINDOW": 422,
    "ERR_VERIFICATION_WINDOW_CLOSED": 422,
    "ERR_AISLE_AUDIT_WINDOW_CONFLICT": 409,
    "ERR_ASSOCIATE_SCHEDULE_CONFLICT": 409,
    "ERR_MISSING_DISCLOSURE": 422,
    "ERR_DUPLICATE_RESOURCE": 409,
    "ERR_NO_QUALIFYING_AUDIT_DATA": 422,
    "ERR_AUDIT_SAMPLE_EMPTY": 422,
    "ERR_NOT_AN_OVERCHARGE": 422,
    "ERR_REMEDIATION_EVIDENCE_REQUIRED": 422,
    "ERR_FINDINGS_EMPTY": 422,
    "ERR_FILE_HAS_NO_LINES": 422,
    "ERR_SUPERSEDING_FILE_INVALID": 422,
    "ERR_DENIAL_REASON_REQUIRED": 422,
    "ERR_VOID_REASON_REQUIRED": 422,
    "ERR_AISLE_STORE_MISMATCH": 422,
    "ERR_ASSOCIATE_STORE_MISMATCH": 422,
    "ERR_STORE_OUT_OF_FILE_SCOPE": 422,
    "ERR_ASSOCIATE_DAILY_CAP_EXCEEDED": 422,
    "ERR_REFUND_BUDGET_EXCEEDED": 422,
    "ERR_PENALTY_OVERRIDE_TOO_HIGH": 422,
    "ERR_REFUND_NOT_APPROVED": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------- store
COLLECTIONS = [
    "jurisdictions",
    "stores",
    "aisles",
    "associates",
    "price_change_files",
    "price_change_lines",
    "label_tasks",
    "scanner_audits",
    "scan_lines",
    "promo_signage",
    "regulatory_inspections",
    "inspection_findings",
    "refund_claims",
    "exception_reports",
    "accountability_actions",
]

DB = {name: {} for name in COLLECTIONS}
STATE = {"seq": 0, "clock": CLOCK_DEFAULT, "print_seq": {}}

NOT_FOUND_CODE = {
    "jurisdictions": "ERR_JURISDICTION_NOT_FOUND",
    "stores": "ERR_STORE_NOT_FOUND",
    "aisles": "ERR_AISLE_NOT_FOUND",
    "associates": "ERR_ASSOCIATE_NOT_FOUND",
    "price_change_files": "ERR_PRICE_CHANGE_FILE_NOT_FOUND",
    "price_change_lines": "ERR_PRICE_CHANGE_LINE_NOT_FOUND",
    "label_tasks": "ERR_LABEL_TASK_NOT_FOUND",
    "scanner_audits": "ERR_SCANNER_AUDIT_NOT_FOUND",
    "scan_lines": "ERR_SCAN_LINE_NOT_FOUND",
    "promo_signage": "ERR_PROMO_SIGNAGE_NOT_FOUND",
    "regulatory_inspections": "ERR_REGULATORY_INSPECTION_NOT_FOUND",
    "inspection_findings": "ERR_INSPECTION_FINDING_NOT_FOUND",
    "refund_claims": "ERR_REFUND_CLAIM_NOT_FOUND",
    "exception_reports": "ERR_EXCEPTION_REPORT_NOT_FOUND",
    "accountability_actions": "ERR_ACCOUNTABILITY_ACTION_NOT_FOUND",
}


def next_seq():
    STATE["seq"] += 1
    return STATE["seq"]


def now():
    """The logical clock. Never wall-clock time."""
    return STATE["clock"]


def set_clock(dt):
    STATE["clock"] = dt


# ---------------------------------------------------------------- timestamps
def iso(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year,
        dt.month,
        dt.day,
        dt.hour,
        dt.minute,
        dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """RFC 3339 -> aware datetime in UTC. Raises ValueError when malformed."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not a timestamp")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def ms(dt):
    """Millisecond-resolution comparison key."""
    return int(dt.timestamp() * 1000)


# ---------------------------------------------------------------- envelope
_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def meta(extra=None):
    body = {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(datetime.now(timezone.utc)),
    }
    if extra:
        body.update(extra)
    return body


def ok(data, status=200):
    return (
        jsonify({"meta": meta(), "response_type": "object", "data": data}),
        status,
    )


def ok_list(rows, total, limit, offset):
    payload = {
        "meta": meta(
            {
                "limit": limit,
                "offset": offset,
                "total_count": total,
                "has_more": (offset + len(rows)) < total,
            }
        ),
        "response_type": "array",
        "data": rows,
    }
    return jsonify(payload), 200


def error_response(err):
    return (
        jsonify(
            {
                "meta": meta(),
                "response_type": "error",
                "data": {"error_id": err.error_id, "message": err.message},
            }
        ),
        err.http_status,
    )


# ---------------------------------------------------------------- numbers
def num(value):
    """Render a Fraction/int/float as int when integral, else float."""
    if isinstance(value, Fraction):
        if value.denominator == 1:
            return int(value)
        return float(value)
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


def round_frac(value, places, mode="ROUND_HALF_UP"):
    """Single-step rounding of an exact rational to `places` decimals."""
    scale = 10 ** places
    scaled = Fraction(value) * scale
    if mode == "ROUND_CEILING":
        units = math.ceil(scaled)
    else:  # ROUND_HALF_UP (values in this domain are non-negative)
        units = math.floor(scaled + Fraction(1, 2))
    return Fraction(units, scale)


def pct2(numerator, denominator):
    """percentage rounded half up to 2 decimals, single rounding step."""
    if denominator == 0:
        return None
    return num(round_frac(Fraction(numerator, denominator) * 100, 2))


def floor_div(numerator, denominator):
    return int(Fraction(numerator, denominator).__floor__())


# ---------------------------------------------------------------- records
def touched():
    if not hasattr(g, "_touched_ids"):
        g._touched_ids = set()
    return g._touched_ids


def touch(rec):
    """Refresh updated_at and bump version once per request for this record."""
    if "version" not in rec:
        return
    rec["updated_at"] = now()
    marker = touched()
    if rec["id"] not in marker:
        marker.add(rec["id"])
        rec["version"] += 1


def apply_changes(rec, changes):
    """Write only real changes; touch when at least one field moved."""
    moved = False
    for key, value in changes.items():
        if rec.get(key) != value:
            rec[key] = value
            moved = True
    if moved:
        touch(rec)
    return moved


def insert(collection, fields, audit=True):
    rec = dict(fields)
    rec["id"] = str(uuid.uuid4())
    rec["_seq"] = next_seq()
    rec["created_at"] = now()
    if audit:
        rec["updated_at"] = now()
        rec["version"] = 1
    DB[collection][rec["id"]] = rec
    touched().add(rec["id"])
    return rec


def get(collection, key):
    if not isinstance(key, str):
        return None
    return DB[collection].get(key)


def must(collection, key):
    rec = get(collection, key)
    if rec is None:
        fail(NOT_FOUND_CODE[collection], "%s not found" % collection[:-1])
    return rec


def rows(collection):
    return sorted(DB[collection].values(), key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------- validators
def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_num(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def present(data, field):
    return field in data and data[field] is not None


def _bad(field, why):
    fail("ERR_INVALID_REQUEST", "%s %s" % (field, why))


def req_str(data, field, min_len=1, max_len=None, pattern=None, upper=False):
    if not present(data, field):
        _bad(field, "is required")
    return opt_str(data, field, min_len, max_len, pattern, upper)


def opt_str(data, field, min_len=1, max_len=None, pattern=None, upper=False, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if len(value) < min_len:
        _bad(field, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must be at most %d characters" % max_len)
    if pattern is not None and not re.fullmatch(pattern, value):
        _bad(field, "is malformed")
    if upper and value != value.upper():
        _bad(field, "must be uppercase")
    return value


def req_enum(data, field, allowed):
    if not present(data, field):
        _bad(field, "is required")
    return opt_enum(data, field, allowed)


def opt_enum(data, field, allowed, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "is not a recognised value")
    return value


def req_int(data, field, minimum=None, maximum=None):
    if not present(data, field):
        _bad(field, "is required")
    return opt_int(data, field, minimum, maximum)


def opt_int(data, field, minimum=None, maximum=None, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not is_int(value):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %d" % maximum)
    return value


def req_num(data, field, minimum=None, maximum=None, decimals=None):
    if not present(data, field):
        _bad(field, "is required")
    return opt_num(data, field, minimum, maximum, decimals)


def opt_num(data, field, minimum=None, maximum=None, decimals=None, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not is_num(value):
        _bad(field, "must be a number")
    if minimum is not None and value < minimum:
        _bad(field, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be at most %s" % maximum)
    if decimals is not None:
        text = repr(float(value)) if isinstance(value, float) else str(value)
        if "." in text and len(text.split(".")[1].rstrip("0")) > decimals:
            _bad(field, "carries more than %d decimals" % decimals)
    return num(value)


def req_bool(data, field):
    if not present(data, field):
        _bad(field, "is required")
    return opt_bool(data, field)


def opt_bool(data, field, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean")
    return value


def req_dt(data, field):
    if not present(data, field):
        _bad(field, "is required")
    return opt_dt(data, field)


def opt_dt(data, field, default=None):
    if not present(data, field):
        return default
    try:
        return parse_dt(data[field])
    except (ValueError, TypeError):
        _bad(field, "must be an RFC 3339 timestamp")


def req_str_array(data, field, min_len=0, max_len=None, distinct=True, item_min=1):
    if not present(data, field):
        _bad(field, "is required")
    return opt_str_array(data, field, min_len, max_len, distinct, item_min)


def opt_str_array(data, field, min_len=0, max_len=None, distinct=True, item_min=1, default=None):
    if not present(data, field):
        return default
    value = data[field]
    if not isinstance(value, list):
        _bad(field, "must be an array")
    if len(value) < min_len:
        _bad(field, "must hold at least %d entries" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(field, "must hold at most %d entries" % max_len)
    for item in value:
        if not isinstance(item, str) or len(item) < item_min:
            _bad(field, "must hold non-empty strings")
    if distinct and len(set(value)) != len(value):
        _bad(field, "must not hold duplicates")
    return list(value)


# ---------------------------------------------------------------- pagination
def pagination():
    args = request.args
    limit, offset = 10, 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
            if str(raw).strip() != str(limit):
                raise ValueError
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
            if str(raw).strip() != str(offset):
                raise ValueError
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_PAGINATION", "offset must be at least 0")
    return limit, offset


def arg_enum(param, allowed):
    if param not in request.args:
        return None
    value = request.args.get(param)
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "%s is not a recognised value" % param)
    return value


def arg_bool(param):
    if param not in request.args:
        return None
    value = request.args.get(param)
    if value not in ("true", "false"):
        fail("ERR_INVALID_REQUEST", "%s must be true or false" % param)
    return value == "true"


def arg_str(param):
    if param not in request.args:
        return None
    return request.args.get(param)


def page(items, serializer):
    limit, offset = pagination()
    total = len(items)
    window = items[offset : offset + limit]
    return ok_list([serializer(row) for row in window], total, limit, offset)
