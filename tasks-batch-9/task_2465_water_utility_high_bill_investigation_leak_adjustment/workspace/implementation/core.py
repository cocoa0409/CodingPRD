"""Foundation layer: in-memory store, logical clock, response envelope, errors,
auth/RBAC, schema validators and pagination.

Storage is in-memory only (plain dicts keyed by id).  The store starts EMPTY on
every boot -- nothing is seeded, preloaded or hardcoded.
"""

import itertools
import json
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
ROLES = (
    "Customer",
    "CustomerServiceRep",
    "MeterTechnician",
    "BillingSupervisor",
    "UtilityBoardClerk",
    "SystemAdmin",
)

# ---------------------------------------------------------------------------
# Error catalogue (PRD 5)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN_ROLE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_RATE_SCHEDULE_NOT_FOUND": 404,
    "ERR_BILLING_PERIOD_NOT_FOUND": 404,
    "ERR_SERVICE_ACCOUNT_NOT_FOUND": 404,
    "ERR_METER_NOT_FOUND": 404,
    "ERR_METER_READING_NOT_FOUND": 404,
    "ERR_BILL_NOT_FOUND": 404,
    "ERR_INVESTIGATION_NOT_FOUND": 404,
    "ERR_METER_TEST_REQUEST_NOT_FOUND": 404,
    "ERR_REPAIR_PROOF_NOT_FOUND": 404,
    "ERR_LEAK_ADJUSTMENT_NOT_FOUND": 404,
    "ERR_PAYMENT_ARRANGEMENT_NOT_FOUND": 404,
    "ERR_BOARD_APPEAL_NOT_FOUND": 404,
    "ERR_ACCOUNT_OWNERSHIP_MISMATCH": 403,
    "ERR_STALE_INVESTIGATION_VERSION": 412,
    "ERR_STALE_ACCOUNT_VERSION": 412,
    "ERR_INVALID_STATE_TRANSITION": 409,
    "ERR_INVESTIGATION_ALREADY_OPEN": 409,
    "ERR_BILLING_PERIOD_CLOSED": 409,
    "ERR_SEGREGATION_OF_DUTIES": 403,
    "ERR_HEARING_OFFICER_CONFLICT": 403,
    "ERR_SHUTOFF_HOLD_ACTIVE": 409,
    "ERR_SHUTOFF_NOTICE_NOT_ELAPSED": 409,
    "ERR_BILLING_PERIOD_LOCKED": 409,
    "ERR_REBILL_WINDOW_EXPIRED": 422,
    "ERR_APPEAL_UNTIMELY": 422,
    "ERR_HEARING_NOTICE_TOO_SHORT": 422,
    "ERR_HEARING_NOT_YET_HELD": 422,
    "ERR_METER_TEST_QUARANTINE": 409,
    "ERR_TEST_RESULT_OUTSIDE_WINDOW": 422,
    "ERR_BILLING_PERIOD_NOT_ENDED": 422,
    "ERR_READ_DATE_IN_FUTURE": 422,
    "ERR_BILLING_PERIOD_OVERLAP": 409,
    "ERR_METER_TEST_WINDOW_CONFLICT": 409,
    "ERR_DUPLICATE_BILL_FOR_PERIOD": 409,
    "ERR_EVIDENCE_ROUND_LIMIT": 422,
    "ERR_REMAND_LIMIT_EXCEEDED": 422,
    "ERR_HEARING_DOCKET_FULL": 409,
    "ERR_REINSTATEMENT_LIMIT": 422,
    "ERR_NEGATIVE_CONSUMPTION": 422,
    "ERR_INSUFFICIENT_BASELINE_HISTORY": 422,
    "ERR_REPAIR_PROOF_REQUIRED": 422,
    "ERR_METER_NOT_BILLABLE": 422,
    "ERR_SUBMETER_PARENT_INVALID": 422,
    "ERR_INSTALLMENT_LIMIT_EXCEEDED": 422,
    "ERR_LEAK_TYPE_MISMATCH": 422,
    "ERR_ADJUSTMENT_BILL_MISMATCH": 422,
    "ERR_TEST_METER_ACCOUNT_MISMATCH": 422,
    "ERR_ARRANGEMENT_ACCOUNT_MISMATCH": 422,
    "ERR_BILL_METER_ACCOUNT_MISMATCH": 422,
    "ERR_LEAK_ADJUSTMENT_CAP_EXCEEDED": 422,
    "ERR_DOWN_PAYMENT_TOO_LOW": 422,
    "ERR_ARRANGEMENT_AMOUNT_MISMATCH": 422,
    "ERR_PAYMENT_AMOUNT_INVALID": 422,
    "ERR_TEST_DEPOSIT_INVALID": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


def err(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Workflow constants
# ---------------------------------------------------------------------------
BILL_DUE_DAYS = 21
SHUTOFF_NOTICE_DAYS = 10
MAX_EVIDENCE_ROUNDS = 3
REMAND_MAX = 1
APPEAL_FILING_DAYS = 30
HEARING_MIN_NOTICE_DAYS = 10
HEARING_DOCKET_CAPACITY = 3
METER_TEST_DEPOSIT_CENTS = 3000
METER_TEST_QUARANTINE_HOURS = 48

PAST_DUE_THRESHOLD_CENTS = 5000
BASELINE_SAMPLE_COUNT = 3
BASELINE_MIN_SAMPLES = 3
ANOMALY_RATIO_THRESHOLD = Decimal("2.000")
MAX_CREDIT_PCT_BP = 6000
MAX_CREDIT_CENTS = 50000
SEWER_RELIEF_LEAK_TYPES = ("SERVICE_LINE", "UNDERGROUND", "IRRIGATION", "POOL")
SEWER_RELIEF_BASIS_GALLONS = 8000
ADJ_ROLLING_WINDOW_MONTHS = 12
SMALL_METER_MAX_INCHES = Decimal("2.0")
AWWA_WEIGHT_LOW = Decimal("0.15")
AWWA_WEIGHT_MID = Decimal("0.70")
AWWA_WEIGHT_HIGH = Decimal("0.15")
FAST_THRESHOLD_PCT = Decimal("101.50")
SLOW_THRESHOLD_PCT = Decimal("98.50")
DOWN_PAYMENT_MIN_BP = 2000
MAX_INSTALLMENTS = 12
MISSED_PAYMENTS_TO_DEFAULT = 2
MAX_ARRANGEMENT_REINSTATEMENTS = 1

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
SEASONS = ("SUMMER", "WINTER")
PERIOD_STATUSES = ("OPEN", "CLOSED", "LOCKED")
SERVICE_STATUSES = ("ACTIVE", "SHUTOFF_SCHEDULED", "SHUTOFF_HELD", "SHUTOFF_EXECUTED")
CREDIT_STATUSES = ("CURRENT", "PAST_DUE", "IN_ARRANGEMENT", "ARRANGEMENT_DEFAULTED")
METER_TYPES = ("POTABLE_MASTER", "IRRIGATION_SUBMETER", "BACKFLOW_FIRE_LINE")
ACCURACY_STATUSES = ("UNTESTED", "VERIFIED_ACCURATE", "FAILED_FAST", "FAILED_SLOW")
READ_TYPES = ("ACTUAL", "ESTIMATED", "CORRECTED")
BILL_READ_TYPES = ("ACTUAL", "ESTIMATED")
BILLING_STATUSES = (
    "DRAFT",
    "ISSUED",
    "UNDER_INVESTIGATION",
    "ADJUSTED",
    "UPHELD_AS_BILLED",
    "REBILL_PENDING",
    "REBILLED",
)
INVESTIGATION_STATUSES = (
    "OPEN",
    "EVIDENCE_REQUESTED",
    "EVIDENCE_UNDER_REVIEW",
    "EVIDENCE_EXHAUSTED",
    "DETERMINED",
    "ADJUSTMENT_PENDING",
    "APPEALED",
    "RESOLVED",
    "CLOSED_NO_ADJUSTMENT",
)
LEAK_DETERMINATIONS = (
    "UNDETERMINED",
    "CUSTOMER_SIDE_LEAK",
    "UTILITY_SIDE_LEAK",
    "METER_ERROR",
    "NO_LEAK",
    "IRRIGATION_USE",
)
HOLD_ACTIVE_STATUSES = (
    "OPEN",
    "EVIDENCE_REQUESTED",
    "EVIDENCE_UNDER_REVIEW",
    "EVIDENCE_EXHAUSTED",
    "DETERMINED",
    "ADJUSTMENT_PENDING",
    "APPEALED",
)
TEST_TYPES = ("FIELD", "BENCH")
REQUESTED_BY_KINDS = ("CUSTOMER", "UTILITY")
TEST_STATUSES = (
    "REQUESTED",
    "FIELD_TEST_SCHEDULED",
    "BENCH_TEST_PENDING",
    "CLOSED_PASS",
    "CLOSED_FAST",
    "CLOSED_SLOW",
)
FIELD_RESULTS = ("PASS", "SUSPECT")
BENCH_RESULTS = ("PASS", "FAST", "SLOW")
ACCURACY_METHODS = ("AWWA_WEIGHTED", "SIMPLE_MEAN")
LEAK_TYPES = ("SERVICE_LINE", "UNDERGROUND", "TOILET", "IRRIGATION", "POOL")
PROOF_STATUSES = ("SUBMITTED", "VERIFIED", "REJECTED")
VARIANTS = ("EXCESS_REPRICE", "BASELINE_REBILL")
ADJUSTMENT_STATUSES = (
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "POSTED",
    "DENIED",
    "REVERSED",
)
ARRANGEMENT_STATUSES = ("PROPOSED", "ACTIVE", "DEFAULTED", "COMPLETED", "CANCELLED")
APPEAL_STATUSES = ("FILED", "SCHEDULED", "UPHELD", "REVERSED", "REMANDED")
DECISIONS = ("UPHOLD", "REVERSE", "REMAND")
ENTRY_TYPES = ("CHARGE", "CREDIT", "PAYMENT", "REVERSAL")
SOURCE_KINDS = (
    "BILL_CHARGE",
    "REBILL_REVERSAL",
    "REBILL_CHARGE",
    "LEAK_ADJUSTMENT_CREDIT",
    "LEAK_ADJUSTMENT_ADMIN_FEE",
    "LEAK_ADJUSTMENT_REVERSAL",
    "METER_TEST_DEPOSIT",
    "METER_TEST_DEPOSIT_REFUND",
    "CUSTOMER_PAYMENT",
    "ARRANGEMENT_DOWN_PAYMENT",
    "ARRANGEMENT_INSTALLMENT",
)

# ---------------------------------------------------------------------------
# Rounding discipline (PRD 2.5) -- always Decimal, always half-up
# ---------------------------------------------------------------------------


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(value)


def rhu(value, places=0):
    """Round half-up to `places` decimal places."""
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------
COLLECTIONS = (
    "rate_schedules",
    "billing_periods",
    "service_accounts",
    "meters",
    "meter_readings",
    "bills",
    "investigations",
    "meter_test_requests",
    "repair_proofs",
    "leak_adjustments",
    "payment_arrangements",
    "board_appeals",
    "ledger_entries",
)

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_EPOCH
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


store = Store()


# ---------------------------------------------------------------------------
# Logical clock and timestamps
# ---------------------------------------------------------------------------


def clock_now():
    return store.clock


def clock_date():
    return store.clock.date()


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


def now_iso():
    return iso(store.clock)


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value):
    if not isinstance(value, str) or not _DATE_RE.match(value):
        return None
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        return None


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns a tz-aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def as_dt(value):
    """Coerce a stored datetime-ish value (string or datetime) to a datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    return parse_dt(value)


def as_date(value):
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = parse_date(value) if isinstance(value, str) else None
    if parsed is not None:
        return parsed
    dt = as_dt(value)
    return dt.date() if dt else None


def date_str(d):
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def add_days(d, days):
    return d + timedelta(days=days)


def minus_months(d, months):
    year = d.year
    month = d.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = d.day
    while day > 1:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1
    return date(year, month, 1)


# ---------------------------------------------------------------------------
# Record helpers
# ---------------------------------------------------------------------------


def new_id():
    return str(uuid.uuid4())


def base_record():
    stamp = now_iso()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": store.next_seq(),
    }


def register_new(rec):
    """Mark a freshly created row so in-request follow-up writes do not bump it."""
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    touched.add(rec["id"])
    return rec


def touch(rec):
    """Refresh updated_at / version, at most once per request per row."""
    touched = getattr(g, "touched", None)
    if touched is None:
        touched = set()
        g.touched = touched
    if rec["id"] in touched:
        return rec
    touched.add(rec["id"])
    rec["updated_at"] = now_iso()
    rec["version"] = rec.get("version", 1) + 1
    return rec


def serialize(rec):
    out = {}
    for key, value in rec.items():
        if key.startswith("_"):
            continue
        out[key] = float(value) if isinstance(value, Decimal) else value
    return out


def sort_key(rec):
    return (rec.get("created_at") or "", rec.get("_seq") or 0)


# ---------------------------------------------------------------------------
# Response envelope (PRD 2.2)
# ---------------------------------------------------------------------------

_ALNUM = string.ascii_uppercase + string.digits


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + "".join(random.choice(_ALNUM) for _ in range(20)),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_response(data, status=200):
    return (
        jsonify({"meta": _meta(), "response_type": "object", "data": data}),
        status,
    )


def created_response(data):
    return object_response(data, 201)


def array_response(rows, limit, offset, total_count):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(rows)) < total_count,
        }
    )
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), 200


def error_response(error_id, message, status):
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
# Auth / RBAC (ladder tiers 1 and 2)
# ---------------------------------------------------------------------------


def endpoint(*roles):
    allowed = set(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role:
                err(
                    "ERR_UNAUTHENTICATED",
                    "X-User-ID and X-User-Role headers are required",
                )
            if role not in ROLES or role not in allowed:
                err(
                    "ERR_FORBIDDEN_ROLE",
                    "role %s may not perform this operation" % role,
                )
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def is_customer():
    return getattr(g, "role", None) == "Customer"


# ---------------------------------------------------------------------------
# Body schema validation (ladder tier 3)
# ---------------------------------------------------------------------------


class Body(object):
    def __init__(self):
        raw = request.get_data(cache=True, as_text=True)
        if raw is None or raw.strip() == "":
            self.data = {}
            return
        try:
            parsed = json.loads(raw)
        except Exception:
            err("ERR_INVALID_REQUEST", "request body is not valid JSON")
            return
        if parsed is None:
            self.data = {}
            return
        if not isinstance(parsed, dict):
            err("ERR_INVALID_REQUEST", "request body must be a JSON object")
        self.data = parsed

    # -- presence ---------------------------------------------------------
    def present(self, name):
        return name in self.data and self.data[name] is not None

    def _fetch(self, name, required):
        if name not in self.data or self.data[name] is None:
            if required:
                err("ERR_INVALID_REQUEST", "field '%s' is required" % name)
            return None, False
        return self.data[name], True

    # -- typed accessors --------------------------------------------------
    def string(self, name, required=True):
        value, found = self._fetch(name, required)
        if not found:
            return None
        if not isinstance(value, str):
            err("ERR_INVALID_REQUEST", "field '%s' must be a string" % name)
        return value

    def integer(self, name, required=True, minimum=None, maximum=None):
        value, found = self._fetch(name, required)
        if not found:
            return None
        if isinstance(value, bool) or not isinstance(value, int):
            err("ERR_INVALID_REQUEST", "field '%s' must be an integer" % name)
        if minimum is not None and value < minimum:
            err("ERR_INVALID_REQUEST", "field '%s' must be >= %s" % (name, minimum))
        if maximum is not None and value > maximum:
            err("ERR_INVALID_REQUEST", "field '%s' must be <= %s" % (name, maximum))
        return value

    def number(self, name, required=True, minimum=None, exclusive_min=None):
        value, found = self._fetch(name, required)
        if not found:
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            err("ERR_INVALID_REQUEST", "field '%s' must be a number" % name)
        if minimum is not None and value < minimum:
            err("ERR_INVALID_REQUEST", "field '%s' must be >= %s" % (name, minimum))
        if exclusive_min is not None and value <= exclusive_min:
            err("ERR_INVALID_REQUEST", "field '%s' must be > %s" % (name, exclusive_min))
        return value

    def boolean(self, name, required=True):
        value, found = self._fetch(name, required)
        if not found:
            return None
        if not isinstance(value, bool):
            err("ERR_INVALID_REQUEST", "field '%s' must be a boolean" % name)
        return value

    def enum(self, name, choices, required=True):
        value = self.string(name, required)
        if value is None:
            return None
        if value not in choices:
            err(
                "ERR_INVALID_REQUEST",
                "field '%s' must be one of %s" % (name, ", ".join(choices)),
            )
        return value

    def date(self, name, required=True):
        value = self.string(name, required)
        if value is None:
            return None
        parsed = parse_date(value)
        if parsed is None:
            err("ERR_INVALID_REQUEST", "field '%s' must be an ISO date (YYYY-MM-DD)" % name)
        return value

    def datetime(self, name, required=True):
        value = self.string(name, required)
        if value is None:
            return None
        if parse_dt(value) is None:
            err("ERR_INVALID_REQUEST", "field '%s' must be an ISO 8601 instant" % name)
        return value


# ---------------------------------------------------------------------------
# Query string validation and pagination (ladder tier 3, PRD 2.3)
# ---------------------------------------------------------------------------

_INT_RE = re.compile(r"^[+-]?\d+$")


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if not _INT_RE.match(raw.strip()):
        err("ERR_INVALID_REQUEST", "query parameter '%s' must be an integer" % name)
    return int(raw.strip())


def pagination():
    limit = _query_int("limit", 10)
    offset = _query_int("offset", 0)
    if limit < 1 or limit > 100:
        err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def q_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def q_enum(name, choices):
    raw = q_str(name)
    if raw is None:
        return None
    if raw not in choices:
        err(
            "ERR_INVALID_REQUEST",
            "query parameter '%s' must be one of %s" % (name, ", ".join(choices)),
        )
    return raw


def q_bool(name):
    raw = q_str(name)
    if raw is None:
        return None
    lowered = raw.lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    err("ERR_INVALID_REQUEST", "query parameter '%s' must be a boolean" % name)


def q_date(name):
    raw = q_str(name)
    if raw is None:
        return None
    if parse_date(raw) is None:
        err("ERR_INVALID_REQUEST", "query parameter '%s' must be an ISO date" % name)
    return raw


def paginate(rows, limit, offset, key=None):
    ordered = sorted(rows, key=key or sort_key)
    total = len(ordered)
    window = ordered[offset : offset + limit]
    return [serialize(r) for r in window], total


def list_result(rows, key=None):
    limit, offset = pagination()
    page, total = paginate(rows, limit, offset, key)
    return array_response(page, limit, offset, total)


# ---------------------------------------------------------------------------
# Lookup helpers (ladder tiers 4 and 5)
# ---------------------------------------------------------------------------

_NOT_FOUND = {
    "rate_schedules": "ERR_RATE_SCHEDULE_NOT_FOUND",
    "billing_periods": "ERR_BILLING_PERIOD_NOT_FOUND",
    "service_accounts": "ERR_SERVICE_ACCOUNT_NOT_FOUND",
    "meters": "ERR_METER_NOT_FOUND",
    "meter_readings": "ERR_METER_READING_NOT_FOUND",
    "bills": "ERR_BILL_NOT_FOUND",
    "investigations": "ERR_INVESTIGATION_NOT_FOUND",
    "meter_test_requests": "ERR_METER_TEST_REQUEST_NOT_FOUND",
    "repair_proofs": "ERR_REPAIR_PROOF_NOT_FOUND",
    "leak_adjustments": "ERR_LEAK_ADJUSTMENT_NOT_FOUND",
    "payment_arrangements": "ERR_PAYMENT_ARRANGEMENT_NOT_FOUND",
    "board_appeals": "ERR_BOARD_APPEAL_NOT_FOUND",
}


def get_or_404(collection, row_id):
    table = getattr(store, collection)
    rec = table.get(row_id) if isinstance(row_id, str) else None
    if rec is None:
        err(_NOT_FOUND[collection], "%s '%s' not found" % (collection, row_id))
    return rec


def maybe(collection, row_id):
    table = getattr(store, collection)
    return table.get(row_id) if isinstance(row_id, str) else None


def rows(collection):
    return list(getattr(store, collection).values())


def insert(collection, rec):
    getattr(store, collection)[rec["id"]] = rec
    return rec


def unique_or_400(collection, field, value):
    for rec in getattr(store, collection).values():
        if rec.get(field) == value:
            err(
                "ERR_INVALID_REQUEST",
                "%s '%s' is already in use" % (field, value),
            )


# ---------------------------------------------------------------------------
# Customer scoping (ladder tier 6)
# ---------------------------------------------------------------------------


def require_own_account(account_id):
    if is_customer() and account_id != g.user_id:
        err(
            "ERR_ACCOUNT_OWNERSHIP_MISMATCH",
            "caller may only access their own service account",
        )


def scope_filter(account_id_getter, rows_in):
    if not is_customer():
        return rows_in
    return [r for r in rows_in if account_id_getter(r) == g.user_id]
