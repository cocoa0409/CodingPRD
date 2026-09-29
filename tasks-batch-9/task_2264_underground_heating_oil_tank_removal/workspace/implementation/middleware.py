"""Auth headers, RBAC, ownership, body shape validation and pagination.

Header names, role spellings and error ids all come from PRD §2.1/§2.11 and
SCAFFOLD §1.4.
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from db import db
from errors import ApiError

ROLES = (
    "ProjectCoordinator",
    "FieldTechnician",
    "LabAnalyst",
    "Homeowner",
    "LicensedSiteProfessional",
    "ComplianceOfficer",
)

ALL_ROLES = ROLES


# ---------------------------------------------------------------------------
# 1. authentication / 2. role authorization
# ---------------------------------------------------------------------------

def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role


# ---------------------------------------------------------------------------
# 4./5. reference resolution
# ---------------------------------------------------------------------------

_TABLE_ERRORS = {
    "properties": "ERR_PROPERTY_NOT_FOUND",
    "tank_projects": "ERR_TANK_PROJECT_NOT_FOUND",
    "disclosures": "ERR_DISCLOSURE_NOT_FOUND",
    "permits": "ERR_PERMIT_NOT_FOUND",
    "crews": "ERR_CREW_NOT_FOUND",
    "work_orders": "ERR_WORK_ORDER_NOT_FOUND",
    "laboratories": "ERR_LABORATORY_NOT_FOUND",
    "soil_samples": "ERR_SOIL_SAMPLE_NOT_FOUND",
    "change_orders": "ERR_CHANGE_ORDER_NOT_FOUND",
    "trust_fund_claims": "ERR_CLAIM_NOT_FOUND",
    "nfa_letters": "ERR_NFA_LETTER_NOT_FOUND",
    "insurance_notifications": "ERR_INSURANCE_NOTIFICATION_NOT_FOUND",
}


def resolve(table, entity_id):
    if not isinstance(entity_id, str):
        raise ApiError(_TABLE_ERRORS[table])
    entity = getattr(db, table).get(entity_id)
    if entity is None:
        raise ApiError(_TABLE_ERRORS[table])
    return entity


# ---------------------------------------------------------------------------
# 3. ownership for entity-backed roles
# ---------------------------------------------------------------------------

def require_project_owner(project, user_id, role):
    """Homeowner's X-User-ID must be the project's property_id."""
    if role == "Homeowner" and project.get("property_id") != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_sample_owner(sample, user_id, role):
    """LabAnalyst's X-User-ID must be the sample's laboratory_id."""
    if role == "LabAnalyst" and sample.get("laboratory_id") != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


# ---------------------------------------------------------------------------
# 6. request body shape
# ---------------------------------------------------------------------------

def body():
    if request.data:
        payload = request.get_json(silent=True, force=True)
        if payload is None:
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be valid JSON.")
        if not isinstance(payload, dict):
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
        return payload
    return {}


def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, detail))


def _present(payload, field):
    return field in payload and payload[field] is not None


def req_str(payload, field):
    if not _present(payload, field):
        _bad(field, "is required.")
    value = payload[field]
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "must be a non-empty string.")
    return value


def opt_str(payload, field, default=None):
    if not _present(payload, field):
        return default
    value = payload[field]
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "must be a non-empty string.")
    return value


def req_enum(payload, field, allowed):
    value = req_str(payload, field)
    if value not in allowed:
        _bad(field, "must be one of %s." % ", ".join(allowed))
    return value


def opt_enum(payload, field, allowed, default=None):
    if not _present(payload, field):
        return default
    value = req_enum(payload, field, allowed)
    return value


def req_bool(payload, field):
    if not _present(payload, field):
        _bad(field, "is required.")
    value = payload[field]
    if not isinstance(value, bool):
        _bad(field, "must be a boolean.")
    return value


def opt_bool(payload, field, default=None):
    if not _present(payload, field):
        return default
    return req_bool(payload, field)


def _as_int(field, value):
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer.")
    return value


def req_int(payload, field, minimum=None, maximum=None, exclusive_min=None):
    if not _present(payload, field):
        _bad(field, "is required.")
    value = _as_int(field, payload[field])
    _range(field, Decimal(value), minimum, maximum, exclusive_min)
    return value


def opt_int(payload, field, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not _present(payload, field):
        return default
    return req_int(payload, field, minimum, maximum, exclusive_min)


def _range(field, value, minimum, maximum, exclusive_min):
    if minimum is not None and value < Decimal(str(minimum)):
        _bad(field, "must be >= %s." % minimum)
    if maximum is not None and value > Decimal(str(maximum)):
        _bad(field, "must be <= %s." % maximum)
    if exclusive_min is not None and value <= Decimal(str(exclusive_min)):
        _bad(field, "must be > %s." % exclusive_min)


def _as_decimal(field, value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number.")
    try:
        return Decimal(str(value))
    except InvalidOperation:
        _bad(field, "must be a number.")


def req_num(payload, field, minimum=None, maximum=None, exclusive_min=None):
    if not _present(payload, field):
        _bad(field, "is required.")
    value = _as_decimal(field, payload[field])
    _range(field, value, minimum, maximum, exclusive_min)
    return value


def opt_num(payload, field, default=None, minimum=None, maximum=None, exclusive_min=None):
    if not _present(payload, field):
        return default
    return req_num(payload, field, minimum, maximum, exclusive_min)


def parse_datetime(field, raw):
    if not isinstance(raw, str) or not raw.strip():
        _bad(field, "must be an ISO 8601 datetime string.")
    text = raw.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        _bad(field, "must be an ISO 8601 datetime string.")
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def req_datetime(payload, field):
    if not _present(payload, field):
        _bad(field, "is required.")
    return parse_datetime(field, payload[field])


def opt_id(payload, field):
    if not _present(payload, field):
        return None
    value = payload[field]
    if not isinstance(value, str) or value.strip() == "":
        _bad(field, "must be a non-empty string.")
    return value


# ---------------------------------------------------------------------------
# 7. pagination bounds
# ---------------------------------------------------------------------------

def pagination():
    limit, offset = 10, 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_PAGINATION")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def filter_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def int_filter_arg(name):
    value = filter_arg(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        # An unparsable numeric filter simply matches no row.
        return value
