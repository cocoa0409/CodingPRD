"""Shared plumbing: errors, response envelope, auth, validation, calc, dates."""
import random
import string
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import request, jsonify, g

import db


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------
def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": _req_id(), "api_request_timestamp": db.iso(db.now())}
    if extra:
        m.update(extra)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_array(items, limit, offset, total):
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    body = {"meta": _meta(pag), "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# --------------------------------------------------------------------------
# Auth / RBAC
# --------------------------------------------------------------------------
ALL_ROLES = [
    "IntakeCoordinator",
    "Nutritionist",
    "RouteManager",
    "ProgramAdmin",
    "ContributionClerk",
    "VolunteerDriver",
]
_ROLE_SET = set(ALL_ROLES)


def _authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in _ROLE_SET:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers")
    return uid, role


def require_auth(allowed_roles):
    """Decorator: authenticate then authorize against allowed roles."""
    allowed = set(allowed_roles)

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = _authenticate()
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation")
            g.user_id = uid
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


# --------------------------------------------------------------------------
# Request body / pagination
# --------------------------------------------------------------------------
def get_body():
    data = request.get_json(force=True, silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def get_pagination():
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (ValueError, TypeError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (ValueError, TypeError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


# --------------------------------------------------------------------------
# Primitive type predicates
# --------------------------------------------------------------------------
def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def is_bool(v):
    return isinstance(v, bool)


def is_list(v):
    return isinstance(v, list)


_TYPE_PREDICATES = {
    "int": is_int,
    "str": is_str,
    "bool": is_bool,
    "list": is_list,
}


def require_field(data, field, typ):
    """Presence + primitive type -> ERR_INVALID_REQUEST (400)."""
    if field not in data or data[field] is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing required field: {field}")
    val = data[field]
    if not _TYPE_PREDICATES[typ](val):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} has wrong type")
    return val


def optional_field(data, field, typ, default=None):
    if field not in data or data[field] is None:
        return default
    val = data[field]
    if not _TYPE_PREDICATES[typ](val):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Field {field} has wrong type")
    return val


def invalid_value(msg="Invalid field value"):
    raise ApiError("ERR_INVALID_FIELD_VALUE", 422, msg)


def check_enum(value, members, msg=None):
    if value not in members:
        invalid_value(msg or f"Value must be one of {sorted(members)}")


# --------------------------------------------------------------------------
# Dates / weekdays
# --------------------------------------------------------------------------
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
WEEKDAY_SET = set(WEEKDAYS)


def parse_date(s):
    """Parse an ISO date (YYYY-MM-DD, tolerating a time suffix). None on failure."""
    if not isinstance(s, str) or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def weekday_name(d):
    return WEEKDAYS[d.weekday()]


# --------------------------------------------------------------------------
# Calculations
# --------------------------------------------------------------------------
OAA_MIN_AGE = 60
FPL_BASE_MONTHLY_CENTS = 125500
FPL_INCREMENT_CENTS = 44000
BASE_MEAL_COST_CENTS = 725
WEEKS_PER_MONTH = 4
MAX_WEEKLY_MEALS = 21
FROZEN_DAYS_COVERED = 7
HIGH_SEVERITY_MIN = 2

TIER_FACTORS = {
    "TIER_A": Decimal("0.15"),
    "TIER_B": Decimal("0.35"),
    "TIER_C": Decimal("0.55"),
}


def compute_age_years(birth_d, created_dt):
    days = (created_dt.date() - birth_d).days
    return int(days // Decimal("365.2425"))


def compute_oaa_eligible(birth_d, created_dt):
    return compute_age_years(birth_d, created_dt) >= OAA_MIN_AGE


def compute_income_tier(monthly_income_cents, household_size):
    poverty = FPL_BASE_MONTHLY_CENTS + (household_size - 1) * FPL_INCREMENT_CENTS
    # exact rational comparison, inclusive upper edges
    if monthly_income_cents <= poverty:  # ratio <= 1.00
        return "TIER_A"
    if monthly_income_cents * 100 <= poverty * 185:  # ratio <= 1.85
        return "TIER_B"
    return "TIER_C"


def per_meal_contribution_cents(income_tier):
    factor = TIER_FACTORS[income_tier]
    val = (Decimal(BASE_MEAL_COST_CENTS) * factor).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(val)


def compute_nutrition_risk(points):
    if points >= 6:
        return "HIGH"
    if points >= 3:
        return "MODERATE"
    return "GOOD"


def compute_functional_level(adl_score):
    if adl_score >= 5:
        return "DEPENDENT"
    if adl_score >= 2:
        return "PARTIAL"
    return "INDEPENDENT"


def compute_weekly_meal_count(meal_type, meals_per_day, n_days):
    if meal_type == "FROZEN":
        return min(meals_per_day * FROZEN_DAYS_COVERED, MAX_WEEKLY_MEALS)
    return min(meals_per_day * n_days, MAX_WEEKLY_MEALS)


def compute_welfare_severity(consecutive_no_answer):
    return "HIGH" if consecutive_no_answer >= HIGH_SEVERITY_MIN else "LOW"
