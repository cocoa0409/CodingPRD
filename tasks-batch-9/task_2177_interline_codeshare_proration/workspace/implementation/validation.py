"""Validation ladder primitives (PRD section 2.7 steps 1-3 and 6)."""

from flask import request

from errors import ApiError
from store import db, ordered, parse_date, parse_dt, serialize

ROLE_OPERATOR = "ClearinghouseOperator"
ROLE_ACCOUNTANT = "RevenueAccountant"
ROLE_BILLING = "BillingAgent"
ROLE_AUDITOR = "InterlineAuditor"

ALL_ROLES = (ROLE_OPERATOR, ROLE_ACCOUNTANT, ROLE_BILLING, ROLE_AUDITOR)

CURRENCIES = ("USD", "EUR", "GBP", "JPY")
CLASSES = ("ECONOMY", "PREMIUM", "BUSINESS", "FIRST")
AGREEMENT_TYPES = ("STRAIGHT_RATE", "SPA_FLAT", "SPA_PERCENT")
REASON_CODES = ("PRORATE_FACTOR_DISPUTE", "SPA_NOT_APPLIED", "FARE_BASIS_ERROR",
                "DUPLICATE_BILLING", "CURRENCY_ERROR")

CARRIER_STATUSES = ("ACTIVE", "SUSPENDED")
AGREEMENT_STATUSES = ("DRAFT", "ACTIVE", "SUSPENDED")
PERIOD_STATUSES = ("OPEN", "CLOSED", "SETTLED")
PRORATION_STATUSES = ("UNPRORATED", "PROVISIONAL", "FINAL", "REPRORATION_REQUIRED")
BILLING_STATUSES = ("UNBILLED", "BILLED", "SETTLED", "DISPUTED")
COUPON_STATUSES = ("OPEN", "FLOWN", "VOID", "ADJUSTED")
INVOICE_STATUSES = ("DRAFT", "SUBMITTED", "CLEARED", "PARTIALLY_REJECTED",
                    "FULLY_REJECTED", "SETTLED")
MEMO_STATUSES = ("RAISED", "COUNTERED", "ACCEPTED", "WITHDRAWN", "ARBITRATION",
                 "RESOLVED_UPHELD", "RESOLVED_DENIED")
AGING_BUCKETS = ("CURRENT", "AGED_30", "AGED_60", "AGED_90")
SAMPLE_STATUSES = ("DRAWN", "IN_REVIEW", "CLOSED_IMMATERIAL", "CLAIM_RAISED",
                   "CLAIM_ACCEPTED", "CLAIM_DENIED")
RUN_TYPES = ("PROVISIONAL", "FINAL")


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


# ---------------------------------------------------------------- ladder 1-2

def authenticate():
    """Ladder step 1: both identity headers present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if not role or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require(allowed_roles):
    """Ladder steps 1-2: authenticate, then authorize the role."""
    user_id, role = authenticate()
    if role not in ALL_ROLES or role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# ------------------------------------------------------------------ ladder 6

def require_ownership(user_id, role, owner_carrier_id):
    """Ladder step 6.  Operator identities are opaque and never compared."""
    if role == ROLE_OPERATOR:
        return
    if isinstance(owner_carrier_id, (list, tuple, set)):
        if user_id in owner_carrier_id:
            return
    elif user_id == owner_carrier_id:
        return
    raise ApiError("ERR_CARRIER_OWNERSHIP_REQUIRED")


# ------------------------------------------------------------------ ladder 3

def body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True, force=True)
    if payload is None:
        bad("Request body must be a JSON object.")
    if not isinstance(payload, dict):
        bad("Request body must be a JSON object.")
    return payload


def _present(data, key):
    return key in data and data[key] is not None


def req_str(data, key):
    if not _present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, str) or value.strip() == "":
        bad("Field '%s' must be a non-empty string." % key)
    return value


def opt_str(data, key, default=None):
    if not _present(data, key):
        return default
    value = data[key]
    if not isinstance(value, str):
        bad("Field '%s' must be a string." % key)
    return value


def req_enum(data, key, allowed):
    value = req_str(data, key)
    if value not in allowed:
        bad("Field '%s' must be one of %s." % (key, ", ".join(allowed)))
    return value


def opt_enum(data, key, allowed, default=None):
    if not _present(data, key):
        return default
    return req_enum(data, key, allowed)


def _check_int(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        bad("Field '%s' must be at least %d." % (key, minimum))
    if maximum is not None and value > maximum:
        bad("Field '%s' must be at most %d." % (key, maximum))
    return value


def req_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        bad("Field '%s' is required." % key)
    return _check_int(key, data[key], minimum, maximum)


def opt_int(data, key, minimum=None, maximum=None):
    if not _present(data, key):
        return None
    return _check_int(key, data[key], minimum, maximum)


def req_dt(data, key):
    """Returns (raw string as supplied, parsed aware datetime)."""
    raw = req_str(data, key)
    parsed = parse_dt(raw)
    if parsed is None:
        bad("Field '%s' must be an ISO 8601 datetime." % key)
    return raw, parsed


def req_date(data, key):
    raw = req_str(data, key)
    parsed = parse_date(raw)
    if parsed is None:
        bad("Field '%s' must be a YYYY-MM-DD date." % key)
    return raw, parsed


def req_id_list(data, key, min_len=None, max_len=None, no_duplicates=False):
    if not _present(data, key):
        bad("Field '%s' is required." % key)
    value = data[key]
    if not isinstance(value, list):
        bad("Field '%s' must be an array." % key)
    for element in value:
        if not isinstance(element, str) or element.strip() == "":
            bad("Field '%s' must contain non-empty string identifiers." % key)
    if min_len is not None and len(value) < min_len:
        bad("Field '%s' must contain at least %d element(s)." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field '%s' must contain at most %d element(s)." % (key, max_len))
    if no_duplicates and len(set(value)) != len(value):
        bad("Field '%s' must not contain duplicate identifiers." % key)
    return value


# --------------------------------------------------------------- pagination

def pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            bad("Query parameter 'limit' must be between 1 and 100.")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            bad("Query parameter 'offset' must be an integer.")
        if offset < 0:
            bad("Query parameter 'offset' must be at least 0.")
    return limit, offset


def filter_enum(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        bad("Query parameter '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def filter_str(name):
    return request.args.get(name)


def listing(rows, limit, offset, serializer=serialize):
    rows = ordered(rows)
    total = len(rows)
    window = rows[offset:offset + limit]
    return [serializer(r) for r in window], total


def collection(attr):
    return list(getattr(db, attr).values())
