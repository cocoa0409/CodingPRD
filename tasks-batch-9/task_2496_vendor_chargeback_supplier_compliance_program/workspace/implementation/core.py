"""Core plumbing for the Vendor Chargeback & Supplier Compliance Program API.

Contains: the program logical clock (PRD 2.5), the in-memory store (empty at
boot, never seeded), the response envelope (PRD 2.2), the error catalogue
(PRD 5), authentication / authorisation (PRD 2.1), request body and query
validation (rejection ladder rung 3, PRD 2.7) and the rounding discipline
(PRD 2.6).
"""

import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import request

# ---------------------------------------------------------------------------
# Program constants (SCAFFOLD program_constants / PRD 3)
# ---------------------------------------------------------------------------

LOGICAL_CLOCK_DEFAULT_UTC = "2026-08-01T00:00:00.000Z"
VIOLATION_FILING_WINDOW_HOURS = 72
DISPUTE_WINDOW_DAYS = 30
DISPUTE_MAX_ROUNDS = 2
CAP_MAX_SUBMISSIONS = 2
SCORECARD_PERIOD_GAP_DAYS = 1
VENDOR_EXPOSURE_ALERT_CENTS = 500000

GRACE_LOOKBACK_DAYS = 180
GOODWILL_PCT = Decimal("25")
GOODWILL_OTIF_THRESHOLD = Decimal("95.00")

OTIF_WEIGHT = Decimal("0.60")
FILL_WEIGHT = Decimal("0.40")

REPEAT_LOOKBACK_DAYS = 180
REPEAT_VIOLATION_THRESHOLD = 3
REPEAT_TIER1_SCORE = Decimal("90.00")
CAP_TRIGGER_SCORE = Decimal("92.00")
CRITICAL_SCORE = Decimal("80.00")
CAP_DUE_DAYS_BY_LEVEL = {1: 30, 2: 21, 3: 14}

ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_DC_INSPECTOR = "DCInspector"
ROLE_VENDOR = "Vendor"
ROLE_AP_ACCOUNTANT = "APAccountant"
ROLE_CATEGORY_BUYER = "CategoryBuyer"

ALL_ROLES = (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_DC_INSPECTOR,
    ROLE_VENDOR,
    ROLE_AP_ACCOUNTANT,
    ROLE_CATEGORY_BUYER,
)

SCOPE_CODES = ("ALL", "SHIPMENT", "LABELING", "PACKAGING", "DOCUMENTATION")
DOMAINS = ("SHIPMENT", "LABELING", "PACKAGING", "DOCUMENTATION")
SEVERITY_TIERS = ("TIER_1", "TIER_2", "TIER_3")
EVIDENCE_KINDS = ("PHOTO", "SCAN", "MEASUREMENT", "DOCUMENT")
DISPUTE_REASON_CODES = (
    "NOT_OUR_LABEL",
    "CARRIER_CAUSED",
    "DUPLICATE_ASSESSMENT",
    "EVIDENCE_INSUFFICIENT",
    "FEE_MISCALCULATED",
)
MEASUREMENT_VARIANTS = ("ORDER_WEIGHTED", "UNIT_WEIGHTED")
BUYING_DECISIONS = ("NONE", "RANGE_REVIEW", "SOURCING_HOLD")


# ---------------------------------------------------------------------------
# Errors (PRD 5 error catalogue)
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_ROUTING_GUIDE_NOT_FOUND": 404,
    "ERR_REQUIREMENT_NOT_FOUND": 404,
    "ERR_PURCHASE_ORDER_NOT_FOUND": 404,
    "ERR_SHIPMENT_NOT_FOUND": 404,
    "ERR_VIOLATION_NOT_FOUND": 404,
    "ERR_CHARGEBACK_NOT_FOUND": 404,
    "ERR_DISPUTE_NOT_FOUND": 404,
    "ERR_SCORECARD_NOT_FOUND": 404,
    "ERR_CAP_NOT_FOUND": 404,
    "ERR_DEDUCTION_NOT_FOUND": 404,
    "ERR_ALLOCATION_NOT_FOUND": 404,
    "ERR_VENDOR_SCOPE_VIOLATION": 403,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_STALE_VERSION": 412,
    "ERR_GUIDE_NOT_DRAFT": 409,
    "ERR_GUIDE_HAS_NO_REQUIREMENTS": 422,
    "ERR_GUIDE_EFFECTIVE_OVERLAP": 409,
    "ERR_GUIDE_NOT_EFFECTIVE": 422,
    "ERR_GUIDE_EFFECTIVE_FROM_IN_PAST": 422,
    "ERR_REQUIREMENT_CODE_TAKEN": 409,
    "ERR_VENDOR_CODE_TAKEN": 409,
    "ERR_VENDOR_SOURCING_HOLD": 409,
    "ERR_SHIPMENT_ALREADY_RECEIVED": 409,
    "ERR_SHIPMENT_NOT_RECEIVED": 409,
    "ERR_RECEIPT_EXCEEDS_SHIPPED": 422,
    "ERR_AFFECTED_UNITS_EXCEED_RECEIPT": 422,
    "ERR_VIOLATION_FILING_WINDOW_CLOSED": 422,
    "ERR_DUPLICATE_VIOLATION": 409,
    "ERR_VIOLATION_NOT_OPEN": 409,
    "ERR_EVIDENCE_INSUFFICIENT": 422,
    "ERR_CHARGEBACK_WRITTEN_OFF": 409,
    "ERR_DISPUTE_WINDOW_CLOSED": 422,
    "ERR_DISPUTE_ALREADY_EXISTS": 409,
    "ERR_DISPUTE_NOT_AWAITING_DECISION": 409,
    "ERR_DISPUTE_NOT_INFO_REQUESTED": 409,
    "ERR_DISPUTE_ROUND_LIMIT_EXCEEDED": 422,
    "ERR_CLAIM_EXCEEDS_ASSESSMENT": 422,
    "ERR_SCORECARD_PERIOD_OVERLAP": 409,
    "ERR_SCORECARD_NO_MEASURABLE_ORDERS": 422,
    "ERR_SCORECARD_NOT_MEASURED": 409,
    "ERR_SCORECARD_ALREADY_FINALIZED": 409,
    "ERR_CAP_NOT_AWAITING_SUBMISSION": 409,
    "ERR_CAP_SUBMISSION_LIMIT_EXCEEDED": 422,
    "ERR_CAP_COMMITMENT_PAST_DUE": 422,
    "ERR_CAP_NOT_DECIDABLE": 409,
    "ERR_CAP_NOT_ESCALATABLE": 409,
    "ERR_CAP_ESCALATION_LEVEL_TOO_LOW": 422,
    "ERR_CAP_NOT_CLOSABLE": 409,
    "ERR_DEDUCTION_NOT_DRAFT": 409,
    "ERR_DEDUCTION_ALREADY_POSTED": 409,
    "ERR_DEDUCTION_NOT_POSTED": 409,
    "ERR_DEDUCTION_NO_ALLOCATIONS": 422,
    "ERR_ALLOCATION_EXCEEDS_OUTSTANDING": 422,
    "ERR_OVER_APPLICATION": 422,
    "ERR_DEDUCTION_EXCEEDS_EXPOSURE": 422,
    "ERR_CHARGEBACK_DISPUTE_OPEN": 409,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or _default_message(error_id)
        self.http_status = ERROR_STATUS.get(error_id, 400)


def _default_message(error_id):
    return error_id.replace("ERR_", "").replace("_", " ").capitalize() + "."


# ---------------------------------------------------------------------------
# Time helpers / logical clock
# ---------------------------------------------------------------------------


def parse_iso(value):
    """Parse an ISO 8601 instant into a tz-aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    text = raw
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if value is None:
        return None
    aware = value.astimezone(timezone.utc)
    return "%s.%03dZ" % (aware.strftime("%Y-%m-%dT%H:%M:%S"), aware.microsecond // 1000)


class LogicalClock(object):
    """Service-wide logical clock; initialised at boot, never self-advancing."""

    def __init__(self):
        self._now = parse_iso(LOGICAL_CLOCK_DEFAULT_UTC)

    def now(self):
        return self._now

    def set(self, value):
        self._now = value

    def reset(self):
        self._now = parse_iso(LOGICAL_CLOCK_DEFAULT_UTC)


clock = LogicalClock()


def days(count):
    return timedelta(days=count)


def hours(count):
    return timedelta(hours=count)


# ---------------------------------------------------------------------------
# Rounding discipline (PRD 2.6)
# ---------------------------------------------------------------------------


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value, places):
    exponent = Decimal(1).scaleb(-places)
    return dec(value).quantize(exponent, rounding=ROUND_HALF_UP)


def round_cents(value):
    """Round a Decimal amount half-up to a whole number of cents."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pct2(value):
    if value is None:
        return None
    return round_half_up(value, 2)


# ---------------------------------------------------------------------------
# In-memory store — starts empty on every boot, never seeded.
# ---------------------------------------------------------------------------


class Store(object):
    def __init__(self):
        self.vendors = {}
        self.guides = {}
        self.requirements = {}
        self.purchase_orders = {}
        self.shipments = {}
        self.violations = {}
        self.evidence = {}
        self.chargebacks = {}
        self.disputes = {}
        self.scorecards = {}
        self.caps = {}
        self.deductions = {}
        self.allocations = {}
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


store = Store()


def new_record(**fields):
    stamp = clock.now()
    record = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": store.next_seq(),
    }
    record.update(fields)
    return record


def new_append_only_record(**fields):
    """Evidence items carry only id and created_at (PRD 2.5)."""
    stamp = clock.now()
    record = {"id": str(uuid.uuid4()), "created_at": stamp, "_seq": store.next_seq()}
    record.update(fields)
    return record


def touch(record):
    """Refresh updated_at and advance version by one (PRD 2.10)."""
    record["updated_at"] = clock.now()
    record["version"] = record["version"] + 1


def touch_if_changed(record, keys, mutator):
    before = dict((key, record.get(key)) for key in keys)
    mutator()
    for key in keys:
        if record.get(key) != before[key]:
            touch(record)
            return True
    return False


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------

_ID_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def envelope(response_type, data, extra_meta=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(clock.now()),
    }
    if extra_meta:
        meta.update(extra_meta)
    return {"meta": meta, "response_type": response_type, "data": data}


def object_response(data, status=200):
    return envelope("object", data), status


def error_response(error_id, message):
    return envelope("error", {"error_id": error_id, "message": message})


# ---------------------------------------------------------------------------
# Authentication / authorisation (rungs 1 and 2)
# ---------------------------------------------------------------------------


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers.")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Request body validation (rung 3)
# ---------------------------------------------------------------------------


def invalid(message):
    return ApiError("ERR_INVALID_REQUEST", message)


def body_dict():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise invalid("Request body must be a JSON object.")
    return payload


def _present(body, field):
    return field in body and body[field] is not None


def req_str(body, field, min_len=1, max_len=None, pattern=None):
    if not _present(body, field):
        raise invalid("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, str):
        raise invalid("Field '%s' must be a string." % field)
    if len(value) < min_len:
        raise invalid("Field '%s' must be at least %d characters." % (field, min_len))
    if max_len is not None and len(value) > max_len:
        raise invalid("Field '%s' must be at most %d characters." % (field, max_len))
    if pattern is not None and not re.fullmatch(pattern, value):
        raise invalid("Field '%s' has an invalid format." % field)
    return value


def opt_str(body, field, min_len=1, max_len=None, default=None):
    if field not in body or body[field] is None:
        return default
    return req_str(body, field, min_len=min_len, max_len=max_len)


def req_int(body, field, minimum=None, maximum=None):
    if not _present(body, field):
        raise invalid("Field '%s' is required." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, int):
        raise invalid("Field '%s' must be an integer." % field)
    if minimum is not None and value < minimum:
        raise invalid("Field '%s' must be at least %s." % (field, minimum))
    if maximum is not None and value > maximum:
        raise invalid("Field '%s' must be at most %s." % (field, maximum))
    return value


def opt_int(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, minimum=minimum, maximum=maximum)


def req_decimal(body, field, minimum=None, maximum=None):
    if not _present(body, field):
        raise invalid("Field '%s' is required." % field)
    value = body[field]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise invalid("Field '%s' must be a number." % field)
    number = dec(value)
    if minimum is not None and number < dec(minimum):
        raise invalid("Field '%s' must be at least %s." % (field, minimum))
    if maximum is not None and number > dec(maximum):
        raise invalid("Field '%s' must be at most %s." % (field, maximum))
    return round_half_up(number, 2)


def opt_decimal(body, field, minimum=None, maximum=None, default=None):
    if field not in body or body[field] is None:
        return default
    return req_decimal(body, field, minimum=minimum, maximum=maximum)


def req_enum(body, field, members):
    if not _present(body, field):
        raise invalid("Field '%s' is required." % field)
    value = body[field]
    if not isinstance(value, str) or value not in members:
        raise invalid("Field '%s' must be one of %s." % (field, ", ".join(members)))
    return value


def req_dt(body, field):
    if not _present(body, field):
        raise invalid("Field '%s' is required." % field)
    value = body[field]
    parsed = parse_iso(value)
    if parsed is None:
        raise invalid("Field '%s' must be an ISO 8601 UTC instant." % field)
    return parsed


def opt_id(body, field):
    if field not in body or body[field] is None:
        return None
    value = body[field]
    if not isinstance(value, str) or not value:
        raise invalid("Field '%s' must be a string identifier." % field)
    return value


# ---------------------------------------------------------------------------
# Pagination and list responses (PRD 2.3)
# ---------------------------------------------------------------------------

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100


def _query_int(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip()
    if not re.fullmatch(r"[+-]?\d+", text):
        raise invalid("Query parameter '%s' must be an integer." % name)
    return int(text)


def pagination_window():
    limit = _query_int("limit")
    offset = _query_int("offset")
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    elif limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise invalid("Query parameter 'limit' must be between 1 and 100.")
    if offset is None:
        offset = 0
    elif offset < 0:
        raise invalid("Query parameter 'offset' may not be negative.")
    return limit, offset


def list_response(items, serializer):
    limit, offset = pagination_window()
    total = len(items)
    window = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(window)) < total,
    }
    return envelope("array", [serializer(item) for item in window], meta), 200


def query_filter(name, members=None):
    value = request.args.get(name)
    if value is None:
        return None
    if members is not None and value not in members:
        raise invalid("Query parameter '%s' must be one of %s." % (name, ", ".join(members)))
    return value


def query_bool(name):
    value = request.args.get(name)
    if value is None:
        return None
    lowered = value.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    raise invalid("Query parameter '%s' must be a boolean." % name)


# ---------------------------------------------------------------------------
# Deterministic sort keys
# ---------------------------------------------------------------------------

_MIN_DT = datetime(1, 1, 1, tzinfo=timezone.utc)
_MAX_DT = datetime(9999, 12, 31, tzinfo=timezone.utc)


def dt_key(value, nulls_last=True):
    if value is None:
        return _MAX_DT if nulls_last else _MIN_DT
    return value


def sort_asc(items, *fields):
    def key(item):
        parts = []
        for field in fields:
            value = item.get(field)
            parts.append(dt_key(value) if isinstance(value, datetime) or value is None else value)
        parts.append(item["_seq"])
        return tuple(parts)

    return sorted(items, key=key)


def sort_desc_created(items):
    return sorted(items, key=lambda item: (item["created_at"], item["_seq"]), reverse=True)
