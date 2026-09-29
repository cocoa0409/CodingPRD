"""Auth header extraction, RBAC, ownership and request-shape validation.

Implements ladder rungs 1-4 of PRD 2.5 plus reusable existence / OCC helpers.
"""

import re

from flask import request

from db import db, parse_date, parse_dt, parse_period
from errors import ApiError

# ------------------------------------------------------------------ role names

PLATFORM_ADMIN = "PlatformAdmin"
PROPERTY_MANAGER = "PropertyManager"
SERVICE_MEMBER = "ServiceMember"
MAINTENANCE_TECH = "MaintenanceTech"
ENVIRONMENTAL_SPECIALIST = "EnvironmentalSpecialist"
INSTALLATION_HOUSING_OFFICE = "InstallationHousingOffice"

ALL_ROLES = (
    PLATFORM_ADMIN,
    PROPERTY_MANAGER,
    SERVICE_MEMBER,
    MAINTENANCE_TECH,
    ENVIRONMENTAL_SPECIALIST,
    INSTALLATION_HOUSING_OFFICE,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"

# ----------------------------------------------------------------------- enums

BRANCHES = ("ARMY", "NAVY", "AIR_FORCE", "MARINE_CORPS")
UNIT_TYPES = ("SFH", "DUPLEX", "TOWNHOME", "APARTMENT")
RANK_CATEGORIES = (
    "JUNIOR_ENLISTED", "SENIOR_ENLISTED", "WARRANT_OFFICER",
    "JUNIOR_OFFICER", "SENIOR_OFFICER",
)
ACCESSIBILITY_FEATURES = ("ROLL_IN_SHOWER", "ZERO_STEP_ENTRY", "WIDENED_DOORWAYS")
UNIT_STATUSES = ("AVAILABLE", "ASSIGNED", "OCCUPIED", "OFFLINE_MAINTENANCE", "HAZARD_HOLD")
DEPLOYMENT_STATUSES = ("NOT_DEPLOYED", "DEPLOYED", "RETURNED")
RELATIONSHIPS = ("SPOUSE", "CHILD", "OTHER_AUTHORIZED")
GENDERS = ("MALE", "FEMALE")
APPLICATION_STATUSES = ("PENDING", "OFFERED", "ACCEPTED", "HOUSED", "EXPIRED")
OCCUPANCY_STATUSES = ("PENDING_MOVE_IN", "OCCUPIED", "NOTICE_GIVEN", "TERMINATED")
ALLOTMENT_STATUSES = ("NOT_STARTED", "ACTIVE", "SUSPENDED", "CLOSED")
RENT_BASES = ("OFFER_PROVISIONAL", "MOVE_IN_FINAL")
TERMINATION_REASONS = ("PCS", "DEPLOYMENT", "SEPARATION", "CONVENIENCE", "LANDLORD")
INSPECTION_STATUSES = ("SCHEDULED", "DEFICIENCIES_LOGGED", "TENANT_ACKNOWLEDGED", "COMPLETED")
DEFICIENCY_SEVERITIES = ("COSMETIC", "FUNCTIONAL", "HABITABILITY_CRITICAL")
DEFICIENCY_ENTRY_STATUSES = ("OPEN", "WORK_ORDER_CREATED", "RESOLVED")
WORK_ORDER_CATEGORIES = (
    "NO_HEAT", "NO_WATER", "GAS_LEAK", "SEWAGE_BACKUP", "ELECTRICAL",
    "PLUMBING_LEAK", "HVAC", "APPLIANCE", "COSMETIC", "GROUNDS",
    "MOLD_SUSPECTED", "LEAD_SUSPECTED",
)
PRIORITY_CLASSES = ("EMERGENCY", "URGENT", "ROUTINE")
WORK_ORDER_STATUSES = ("SUBMITTED", "ASSIGNED", "IN_PROGRESS", "COMPLETED", "REOPENED", "CLOSED")
HAZARD_TYPES = ("MOLD", "LEAD_PAINT", "LEAD_WATER")
HAZARD_SEVERITIES = ("SEVERITY_1", "SEVERITY_2", "SEVERITY_3")
HAZARD_STATUSES = (
    "REPORTED", "ASSESSED", "REMEDIATION_IN_PROGRESS", "DISPLACEMENT_ACTIVE",
    "CLEARANCE_PENDING", "CLOSED", "VOIDED",
)
LODGING_STATUSES = ("AUTHORIZED", "CLOSED")
DISPUTE_CATEGORIES = (
    "RENT_CHARGE", "MAINTENANCE_QUALITY", "HABITABILITY", "DAMAGE_CLAIM",
    "UTILITY_BILLING",
)
DISPUTE_STATUSES = (
    "UNDER_REVIEW", "PROPOSED_RESOLUTION", "RESIDENT_REJECTED",
    "ESCALATED_INSTALLATION", "CLOSED_RESOLVED",
)
TRANSACTION_TYPES = (
    "CHARGE", "ABATEMENT", "REFUND", "ARREARS_ADJUSTMENT", "EARLY_TERMINATION_FEE",
)
OCCUPANCY_BASES = ("UNIT_DAY_WEIGHTED", "MONTH_END_SNAPSHOT")

PAY_GRADE_RE = re.compile(r"^(E[1-9]|W[1-5]|O([1-9]|10))$")

BOOL_TRUE = ("true", "True", "TRUE", "1")
BOOL_FALSE = ("false", "False", "FALSE", "0")


# ------------------------------------------------------------- rungs 1 and 2

def authenticate(allowed_roles):
    """Rung 1 then rung 2.  Returns (user_id, role)."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")
    return user_id, role


# ------------------------------------------------------------------- rung 3

def require_owner(role, user_id, sponsor_id):
    """Rung 3.  Only ServiceMember callers are constrained."""
    if role != SERVICE_MEMBER:
        return
    if sponsor_id is None:
        return
    if user_id != sponsor_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def lease_sponsor(lease_id):
    lease = db.leases.get(lease_id) if isinstance(lease_id, str) else None
    return lease.get("service_member_id") if lease else None


# ------------------------------------------------------------------- rung 4

def json_body():
    if not request.data:
        return {}
    payload = request.get_json(silent=True)
    if payload is None:
        raise ApiError("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


def raw_ref(body, name):
    """Best-effort read of a reference id before shape validation (rung 3)."""
    value = body.get(name)
    return value if isinstance(value, str) else None


def bad(name, detail="is invalid"):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (name, detail))


def _missing(body, name, required, default):
    if name not in body or body.get(name) is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return True, default
    return False, None


def v_str(body, name, required=True, default=None, allow_empty=False):
    absent, fallback = _missing(body, name, required, default)
    if absent:
        return fallback
    value = body[name]
    if not isinstance(value, str):
        bad(name, "must be a string")
    if not allow_empty and value.strip() == "":
        bad(name, "must be a non-empty string")
    return value


def v_bool(body, name, required=True, default=None):
    absent, fallback = _missing(body, name, required, default)
    if absent:
        return fallback
    value = body[name]
    if not isinstance(value, bool):
        bad(name, "must be a boolean")
    return value


def v_int(body, name, required=True, default=None, minimum=None, maximum=None):
    absent, fallback = _missing(body, name, required, default)
    if absent:
        return fallback
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %s" % maximum)
    return value


def v_money(body, name, required=True, default=None, minimum=0):
    """Monetary amounts are integer cents and (unless told otherwise) non-negative."""
    return v_int(body, name, required=required, default=default, minimum=minimum)


def v_number(body, name, required=True, default=None, minimum=None, maximum=None):
    absent, fallback = _missing(body, name, required, default)
    if absent:
        return fallback
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(name, "must be a number")
    if minimum is not None and value < minimum:
        bad(name, "must be >= %s" % minimum)
    if maximum is not None and value > maximum:
        bad(name, "must be <= %s" % maximum)
    return value


def v_enum(body, name, allowed, required=True, default=None):
    absent, fallback = _missing(body, name, required, default)
    if absent:
        return fallback
    value = body[name]
    if not isinstance(value, str) or value not in allowed:
        bad(name, "must be one of %s" % ", ".join(allowed))
    return value


def v_date(body, name, required=True, default=None):
    absent, fallback = _missing(body, name, required, default)
    if absent:
        return fallback
    try:
        return parse_date(body[name])
    except Exception:
        bad(name, "must be a YYYY-MM-DD date")


def v_datetime(body, name, required=True, default=None):
    absent, fallback = _missing(body, name, required, default)
    if absent:
        return fallback
    try:
        return parse_dt(body[name])
    except Exception:
        bad(name, "must be an ISO 8601 UTC timestamp")


def v_period(body, name, required=True, default=None):
    absent, fallback = _missing(body, name, required, default)
    if absent:
        return fallback
    value = body[name]
    try:
        parse_period(value)
    except Exception:
        bad(name, "must be a YYYY-MM period")
    return value


def v_id(body, name, required=True, default=None):
    return v_str(body, name, required=required, default=default)


def v_pay_grade(body, name, required=True, default=None):
    absent, fallback = _missing(body, name, required, default)
    if absent:
        return fallback
    value = body[name]
    if not isinstance(value, str) or not PAY_GRADE_RE.match(value):
        bad(name, "must be a pay grade between E1-E9, W1-W5 or O1-O10")
    return value


def v_features(body, name, required=False, default=None):
    absent, fallback = _missing(body, name, required, default)
    if absent:
        return list(fallback) if fallback is not None else []
    value = body[name]
    if not isinstance(value, list):
        bad(name, "must be an array")
    out = []
    for item in value:
        if not isinstance(item, str) or item not in ACCESSIBILITY_FEATURES:
            bad(name, "must contain only declared accessibility features")
        if item not in out:
            out.append(item)
    return out


# ------------------------------------------------------------- query handling

def pagination():
    limit = _query_int("limit", 10)
    offset = _query_int("offset", 0)
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'limit' is out of range.")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'offset' is out of range.")
    return limit, offset


def _query_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        if raw.strip() != raw or raw.strip() == "":
            raise ValueError
        return int(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def q_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def q_enum(name, allowed):
    raw = q_str(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is invalid." % name)
    return raw


def q_bool(name):
    raw = q_str(name)
    if raw is None:
        return None
    if raw in BOOL_TRUE:
        return True
    if raw in BOOL_FALSE:
        return False
    raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be a boolean." % name)


def q_int(name, minimum=None, maximum=None):
    raw = q_str(name)
    if raw is None:
        return None
    value = _query_int(name, None)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is out of range." % name)
    return value


def q_pay_grade(name):
    raw = q_str(name)
    if raw is None:
        return None
    if not PAY_GRADE_RE.match(raw):
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is invalid." % name)
    return raw


def q_period(name):
    raw = q_str(name)
    if raw is None:
        return None
    try:
        parse_period(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' is invalid." % name)
    return raw
