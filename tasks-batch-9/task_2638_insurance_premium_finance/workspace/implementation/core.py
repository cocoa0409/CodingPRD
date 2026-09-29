"""Core infrastructure: logical clock, in-memory store, response envelope,
errors, auth/RBAC, pagination and shared helpers.

Storage is in-memory only (plain Python dicts).  Nothing is seeded at import
time or at startup -- every entity is created through the API surface.
"""

import calendar
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

from flask import g, jsonify, request

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_RESOURCE_OWNER": 403,
    "ERR_VERIFIER_NOT_AUTHORIZED": 403,
    "ERR_SOD_ORIGINATOR_CANNOT_APPROVE": 403,
    "ERR_SOD_NOTICE_ISSUER_CANNOT_EXECUTE": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_STATE_RULE_NOT_FOUND": 404,
    "ERR_LICENSE_NOT_FOUND": 404,
    "ERR_INSURED_NOT_FOUND": 404,
    "ERR_AGENT_NOT_FOUND": 404,
    "ERR_INSURER_NOT_FOUND": 404,
    "ERR_AGREEMENT_NOT_FOUND": 404,
    "ERR_POLICY_NOT_FOUND": 404,
    "ERR_PAYMENT_NOT_FOUND": 404,
    "ERR_LATE_FEE_NOT_FOUND": 404,
    "ERR_CANCEL_REQUEST_NOT_FOUND": 404,
    "ERR_ENDORSEMENT_NOT_FOUND": 404,
    "ERR_CHARGEBACK_NOT_FOUND": 404,
    "ERR_STALE_AGREEMENT_VERSION": 412,
    "ERR_STALE_CHARGEBACK_VERSION": 412,
    "ERR_AGREEMENT_STATE_INVALID": 409,
    "ERR_DELINQUENCY_STATE_INVALID": 409,
    "ERR_POLICY_STATE_INVALID": 409,
    "ERR_NOTICE_STATE_INVALID": 409,
    "ERR_CANCEL_REQUEST_STATE_INVALID": 409,
    "ERR_CHARGEBACK_STATE_INVALID": 409,
    "ERR_ENDORSEMENT_STATE_INVALID": 409,
    "ERR_PAYMENT_ALREADY_REVERSED": 409,
    "ERR_LATE_FEE_NOT_OUTSTANDING": 409,
    "ERR_POLICY_AGREEMENT_MISMATCH": 409,
    "ERR_VERIFICATION_ALREADY_RECORDED": 409,
    "ERR_STATE_NOT_LICENSED": 422,
    "ERR_AGENT_SUSPENDED": 422,
    "ERR_DUPLICATE_STATE_RULE": 409,
    "ERR_TERM_EXCEEDS_STATE_MAXIMUM": 422,
    "ERR_DOWN_PAYMENT_BELOW_MINIMUM": 422,
    "ERR_SERVICE_FEE_ABOVE_CAP": 422,
    "ERR_RATE_ABOVE_STATE_MAXIMUM": 422,
    "ERR_NO_FINANCED_POLICIES": 422,
    "ERR_POLICY_NOT_VERIFIED": 422,
    "ERR_RESTRUCTURE_NOT_ELIGIBLE": 422,
    "ERR_NO_PENDING_ENDORSEMENTS": 422,
    "ERR_INVALID_POLICY_TERM": 422,
    "ERR_POLICY_TERM_OVERLAP": 409,
    "ERR_INVALID_FIRST_DUE_DATE": 422,
    "ERR_NOTICE_WINDOW_OPEN": 409,
    "ERR_NOTICE_BLACKOUT_ACTIVE": 409,
    "ERR_NOTICE_PERIOD_NOT_ELAPSED": 422,
    "ERR_CLOCK_REWIND": 422,
    "ERR_PREMIUM_VARIANCE_EXCEEDED": 422,
    "ERR_PAYMENT_EXCEEDS_PAYOFF": 422,
    "ERR_OFFSET_EXCEEDS_RESERVE": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.message = message or error_id
        self.http_status = http_status or ERROR_STATUS.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.value = CLOCK_EPOCH

    def reset(self):
        self.value = CLOCK_EPOCH

    def now(self):
        return self.value

    def now_iso(self):
        return fmt_dt(self.value)

    def date(self):
        return self.value.astimezone(timezone.utc).date()


clock = Clock()


def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


# ---------------------------------------------------------------------------
# In-memory store
# ---------------------------------------------------------------------------

class Store:
    COLLECTIONS = (
        "state_rules", "licenses", "insureds", "agents", "insurers",
        "agreements", "policies", "verifications", "installments",
        "payments", "late_fees", "notices", "cancel_requests",
        "endorsements", "chargebacks",
    )

    def __init__(self):
        self.reset()

    def reset(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def new_record(collection, versioned=True, **fields):
    rec = {"id": new_id(), "created_at": clock.now_iso()}
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    rec.update(fields)
    rec["_seq"] = db.next_seq()
    getattr(db, collection)[rec["id"]] = rec
    return rec


def touch(rec):
    """Bump a row's version at most once per HTTP request."""
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    key = id(rec)
    if key in touched:
        return rec
    touched.add(key)
    if "version" in rec:
        rec["version"] = rec["version"] + 1
        rec["updated_at"] = clock.now_iso()
    return rec


def ordered(records):
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def ok_list(items, page, status=200):
    limit, offset, total = page
    return jsonify({
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": offset + limit < total,
        }),
        "response_type": "array",
        "data": items,
    }), status


def error_response(err):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------

ROLES = ("FinanceAnalyst", "ComplianceOfficer", "ProducerAgent", "Insurer", "Insured")


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not user_id.strip() or not role or not role.strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required")
    if role not in ROLES or role not in allowed_roles:
        fail("ERR_UNAUTHORIZED_ROLE", "role %s may not perform this operation" % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(roles):
    """Decorator: authenticate + authorize before the handler body runs."""
    def wrap(fn):
        def inner(*args, **kwargs):
            authenticate(roles)
            return fn(*args, **kwargs)
        inner.__name__ = fn.__name__
        return inner
    return wrap


# ---------------------------------------------------------------------------
# Body / query validation helpers
# ---------------------------------------------------------------------------

def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    if not isinstance(payload, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return payload


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(data, key, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    return _int_bounds(data[key], key, minimum, maximum)


def opt_int(data, key, default=None, minimum=None, maximum=None):
    if key not in data or data[key] is None:
        return default
    return _int_bounds(data[key], key, minimum, maximum)


def _int_bounds(value, key, minimum, maximum):
    if not is_int(value):
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % key)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (key, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (key, maximum))
    return value


def req_str(data, key):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "%s must be a non-empty string" % key)
    return value


def opt_str(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    value = data[key]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % key)
    return value


def req_enum(data, key, values):
    value = data.get(key)
    if not isinstance(value, str) or value not in values:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (key, sorted(values)))
    return value


def opt_enum(data, key, values, default=None):
    if key not in data or data[key] is None:
        return default
    return req_enum(data, key, values)


def parse_date(value, key):
    if not isinstance(value, str) or not DATE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 calendar date" % key)
    try:
        return date(int(value[0:4]), int(value[5:7]), int(value[8:10]))
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s is not a valid calendar date" % key)


def req_date(data, key):
    if key not in data or data[key] is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % key)
    return parse_date(data[key], key)


def opt_date(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return parse_date(data[key], key)


def req_bool(data, key):
    value = data.get(key)
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "%s must be a boolean" % key)
    return value


def opt_bool(data, key, default=None):
    if key not in data or data[key] is None:
        return default
    return req_bool(data, key)


STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")


def req_state_code(data, key):
    value = req_str(data, key)
    if not STATE_CODE_RE.match(value):
        fail("ERR_INVALID_REQUEST", "%s must be exactly two uppercase letters" % key)
    return value


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if str(raw).strip() != str(limit):
            # tolerate whitespace but reject floats / junk
            if not re.match(r"^\s*[+-]?\d+\s*$", str(raw)):
                fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if "offset" in args:
        raw = args.get("offset")
        if not re.match(r"^\s*[+-]?\d+\s*$", str(raw)):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = int(raw)
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(rows, serializer):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return [serializer(r) for r in window], (limit, offset, total)


# ---------------------------------------------------------------------------
# Money / date arithmetic
# ---------------------------------------------------------------------------

def round_half_up(numerator, denominator=1):
    """Exact half-up rounding (ties away from zero) of numerator/denominator."""
    frac = Fraction(numerator, denominator)
    num, den = frac.numerator, frac.denominator
    sign = -1 if num < 0 else 1
    num = abs(num)
    quotient, remainder = divmod(num, den)
    if remainder * 2 >= den:
        quotient += 1
    return sign * quotient


def floor_div(numerator, denominator):
    return numerator // denominator


def add_days(d, days):
    return d + timedelta(days=days)


def add_months(d, months):
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def days_between(a, b):
    return (b - a).days


def iso(d):
    return d.isoformat() if d is not None else None
