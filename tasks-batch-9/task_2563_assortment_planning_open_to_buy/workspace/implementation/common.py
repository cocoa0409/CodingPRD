"""Shared foundation: errors, response envelope, auth, rounding, body validation."""
import random
import string
import uuid
from datetime import datetime, timezone
from fractions import Fraction

from flask import jsonify, request

# ---------------------------------------------------------------------------
# Error catalogue (§5 of the PRD / 1.6 of the scaffold)
# ---------------------------------------------------------------------------
ERROR_HTTP = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED_ROLE": 403,
    "ERR_NOT_COMMITMENT_VENDOR": 403,
    "ERR_INVALID_REQUEST": 400,
    "ERR_INVALID_PAGINATION": 400,
    "ERR_DEPARTMENT_NOT_FOUND": 404,
    "ERR_CATEGORY_NOT_FOUND": 404,
    "ERR_STORE_CLUSTER_NOT_FOUND": 404,
    "ERR_VENDOR_NOT_FOUND": 404,
    "ERR_VENDOR_AUTHORIZATION_NOT_FOUND": 404,
    "ERR_CATEGORY_PLAN_NOT_FOUND": 404,
    "ERR_PLAN_MONTH_NOT_FOUND": 404,
    "ERR_OPTION_PLAN_NOT_FOUND": 404,
    "ERR_ASSORTMENT_ITEM_NOT_FOUND": 404,
    "ERR_RECEIPT_COMMITMENT_NOT_FOUND": 404,
    "ERR_REFORECAST_CYCLE_NOT_FOUND": 404,
    "ERR_CHASE_CANCEL_DECISION_NOT_FOUND": 404,
    "ERR_LOCALIZATION_OVERLAY_NOT_FOUND": 404,
    "ERR_SEGREGATION_OF_DUTIES": 409,
    "ERR_INVALID_STATE": 409,
    "ERR_PLAN_MONTH_NOT_OPEN": 409,
    "ERR_OPTION_PLAN_NOT_SLOTTED": 409,
    "ERR_CATEGORY_PLAN_NOT_APPROVED": 409,
    "ERR_VENDOR_NOT_AUTHORIZED": 409,
    "ERR_OPEN_DECISIONS_REMAIN": 409,
    "ERR_STALE_PLAN_MONTH_VERSION": 412,
    "ERR_STALE_CATEGORY_PLAN_VERSION": 412,
    "ERR_OTB_POSTURE_FROZEN": 409,
    "ERR_POSTURE_RESTRICTED_NEW_ITEM": 409,
    "ERR_REFORECAST_ROUND_LIMIT": 409,
    "ERR_VENDOR_NOT_AUTHORIZED_FOR_CATEGORY": 422,
    "ERR_PLAN_SCOPE_MISMATCH": 422,
    "ERR_CLUSTER_NOT_IN_PLAN": 422,
    "ERR_DUPLICATE_CATEGORY_PLAN": 409,
    "ERR_DUPLICATE_PLAN_MONTH": 409,
    "ERR_DUPLICATE_OPTION_PLAN": 409,
    "ERR_DUPLICATE_ACTUALS_WEEK": 409,
    "ERR_SIZE_CURVE_EMPTY": 422,
    "ERR_SIZE_CURVE_NOT_BALANCED": 422,
    "ERR_SIZE_CURVE_ZERO_CELL": 422,
    "ERR_NO_OPTION_SLOT": 409,
    "ERR_BELOW_VENDOR_MINIMUM": 422,
    "ERR_VENDOR_CAPACITY_EXCEEDED": 409,
    "ERR_OVERLAY_WINDOW_CONFLICT": 409,
    "ERR_SHIP_WINDOW_INVERTED": 422,
    "ERR_OVERLAY_WINDOW_INVERTED": 422,
    "ERR_LEAD_TIME_INFEASIBLE": 422,
    "ERR_CANCEL_CUTOFF_PASSED": 409,
    "ERR_OTB_EXCEEDED": 422,
    "ERR_RECEIPT_BUDGET_ZERO": 422,
    "ERR_NO_FEASIBLE_RECEIPT_MONTH": 422,
    "ERR_RECEIPT_OVER_COMMITMENT": 422,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None, http_status=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.message = message or error_id.replace("ERR_", "").replace("_", " ").lower()
        self.http_status = http_status or ERROR_HTTP.get(error_id, 400)


def fail(error_id, message=None):
    raise ApiError(error_id, message)


# ---------------------------------------------------------------------------
# Time / identity helpers
# ---------------------------------------------------------------------------
_ALNUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso_ms(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso_ms(datetime.now(timezone.utc))


def new_id():
    return str(uuid.uuid4())


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Arithmetic conventions (§2.5): integer cents, integer bps, round half up
# away from zero, floor = truncate toward zero.
# ---------------------------------------------------------------------------
def rhu(numerator, denominator=1):
    """round_half_up away from zero on the rational numerator/denominator."""
    frac = Fraction(numerator, denominator)
    n, d = frac.numerator, frac.denominator
    if d == 1:
        return n
    if n >= 0:
        return (2 * n + d) // (2 * d)
    return -((-2 * n + d) // (2 * d))


def trunc(numerator, denominator=1):
    """floor toward zero."""
    frac = Fraction(numerator, denominator)
    return int(frac)


def retail_to_cost(retail_cents, planned_margin_bps):
    """§2.5: retail -> cost by retaining the complement of the planned margin."""
    return rhu(retail_cents * (10000 - planned_margin_bps), 10000)


# ---------------------------------------------------------------------------
# Response envelope (§2.2)
# ---------------------------------------------------------------------------
def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def respond(data, status=200, page_meta=None):
    body = {
        "meta": _meta(page_meta),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def respond_error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# Auth (§2.1) — priorities 1 and 2 of the validation ladder
# ---------------------------------------------------------------------------
ROLE_ADMIN = "MerchOpsAdmin"
ROLE_PLANNER = "MerchandisePlanner"
ROLE_DIRECTOR = "PlanningDirector"
ROLE_BUYER = "CategoryBuyer"
ROLE_VENDOR = "VendorRep"

ALL_ROLES = [ROLE_ADMIN, ROLE_PLANNER, ROLE_DIRECTOR, ROLE_BUYER, ROLE_VENDOR]
PLANNING_ROLES = [ROLE_ADMIN, ROLE_PLANNER, ROLE_DIRECTOR, ROLE_BUYER]
ANY_ROLE = list(ALL_ROLES)


def auth(allowed_roles):
    """Returns (user_id, role). Raises ERR_UNAUTHENTICATED / ERR_UNAUTHORIZED_ROLE."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if not role or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    if role not in ALL_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a declared role")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED_ROLE", "role %s is not authorized for this endpoint" % role)
    return user_id, role


# ---------------------------------------------------------------------------
# Request body validation (§2.8 priority 3)
# ---------------------------------------------------------------------------
MISSING = object()


class F:
    """Declared body field."""

    def __init__(self, name, kind, required=True, default=None,
                 minimum=None, maximum=None, min_len=None, max_len=None,
                 enum=None, upper=False, pattern=None):
        self.name = name
        self.kind = kind
        self.required = required
        self.default = default
        self.minimum = minimum
        self.maximum = maximum
        self.min_len = min_len
        self.max_len = max_len
        self.enum = enum
        self.upper = upper
        self.pattern = pattern


def json_body():
    """Return the parsed JSON object, or {} when the body is empty."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "request body is not valid JSON")
    if not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return parsed


def _check_scalar(field, value):
    name = field.name
    if field.kind == "int":
        if isinstance(value, bool) or not isinstance(value, int):
            fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
        if field.minimum is not None and value < field.minimum:
            fail("ERR_INVALID_REQUEST", "%s must be >= %d" % (name, field.minimum))
        if field.maximum is not None and value > field.maximum:
            fail("ERR_INVALID_REQUEST", "%s must be <= %d" % (name, field.maximum))
        return value
    if field.kind == "str":
        if not isinstance(value, str):
            fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
        if field.min_len is not None and len(value) < field.min_len:
            fail("ERR_INVALID_REQUEST", "%s is shorter than %d chars" % (name, field.min_len))
        if field.max_len is not None and len(value) > field.max_len:
            fail("ERR_INVALID_REQUEST", "%s is longer than %d chars" % (name, field.max_len))
        if field.upper and value != value.upper():
            fail("ERR_INVALID_REQUEST", "%s must be uppercase" % name)
        if field.pattern is not None:
            import re
            if re.match(field.pattern, value) is None:
                fail("ERR_INVALID_REQUEST", "%s is malformed" % name)
        return value
    if field.kind == "enum":
        if not isinstance(value, str):
            fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
        if value not in field.enum:
            fail("ERR_INVALID_REQUEST", "%s is not a declared enum member" % name)
        return value
    if field.kind == "datetime":
        if not isinstance(value, str):
            fail("ERR_INVALID_REQUEST", "%s must be an ISO-8601 string" % name)
        if parse_dt(value) is None:
            fail("ERR_INVALID_REQUEST", "%s is not a parseable ISO-8601 instant" % name)
        return value
    if field.kind == "list":
        if not isinstance(value, list):
            fail("ERR_INVALID_REQUEST", "%s must be an array" % name)
        return value
    fail("ERR_INVALID_REQUEST", "unsupported field %s" % name)


def parse_input(fields, body=None):
    """Validate the body against the declared field list.  Unknown fields are rejected."""
    body = json_body() if body is None else body
    known = set(f.name for f in fields)
    for key in body.keys():
        if key not in known:
            fail("ERR_INVALID_REQUEST", "unknown body field '%s'" % key)
    out = {}
    for field in fields:
        if field.name not in body or body[field.name] is None:
            if field.required:
                fail("ERR_INVALID_REQUEST", "%s is required" % field.name)
            out[field.name] = field.default
            continue
        out[field.name] = _check_scalar(field, body[field.name])
    return out


# ---------------------------------------------------------------------------
# Pagination (§2.3) — priority 4
# ---------------------------------------------------------------------------
def _int_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    text = raw.strip()
    if text == "" or (text.startswith("-") and not text[1:].isdigit()) or \
            (not text.startswith("-") and not text.isdigit()):
        fail("ERR_INVALID_PAGINATION", "%s must be an integer" % name)
    return int(text)


def pagination():
    limit = _int_param("limit")
    offset = _int_param("offset")
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_PAGINATION", "limit must be between 1 and 100")
    if offset < 0:
        fail("ERR_INVALID_PAGINATION", "offset must be >= 0")
    return limit, offset


def page_of(rows, limit, offset):
    total = len(rows)
    window = rows[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return window, meta


def public(record):
    """Strip internal bookkeeping keys before serialisation."""
    return dict((k, v) for k, v in record.items() if not k.startswith("_"))


def public_list(records):
    return [public(r) for r in records]
