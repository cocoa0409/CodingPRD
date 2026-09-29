"""Authentication, RBAC, pagination and request-shape validation.

The rule ladder of PRD 2.8 is enforced by calling these helpers in order
inside each handler: auth -> role -> ownership -> shape -> pagination ->
path existence -> body references -> parent version -> state -> ...
"""

from flask import request

import db
from errors import ApiError
from util import dec, parse_date, parse_dt

ROLE_ACCOUNT_MANAGER = "AccountManager"
ROLE_SERVICE_TECHNICIAN = "ServiceTechnician"
ROLE_QUALITY_AUDITOR = "QualityAuditor"
ROLE_CUSTOMER_CONTACT = "CustomerContact"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

ALL_ROLES = (
    ROLE_ACCOUNT_MANAGER,
    ROLE_SERVICE_TECHNICIAN,
    ROLE_QUALITY_AUDITOR,
    ROLE_CUSTOMER_CONTACT,
    ROLE_PLATFORM_ADMIN,
)


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def authenticate():
    """Rung 1: both identity headers must be present and non-empty."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if role is None or not role.strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is required")
    return user_id, role


def require_roles(*allowed):
    """Rungs 1 and 2. Returns (user_id, role)."""
    user_id, role = authenticate()
    if role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN_ROLE",
            "Role %s may not perform this operation" % role,
        )
    return user_id, role


def deny_owner(message="The caller does not own the addressed resource"):
    raise ApiError("ERR_NOT_RESOURCE_OWNER", message)


def scope_customer(role, user_id, customer_id):
    """Rung 3: a CustomerContact may only reach its own account."""
    if role != ROLE_CUSTOMER_CONTACT:
        return
    if customer_id is None:
        return
    if user_id != customer_id:
        deny_owner()


# --------------------------------------------------------------------------
# request body helpers
# --------------------------------------------------------------------------

def raw_body():
    """The soft-parsed body, used by ownership scoping before shape checks."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def body_object():
    """Rung 4: the body must be a JSON object."""
    if not request.data or not request.data.strip():
        return {}
    data = request.get_json(silent=True)
    if data is None:
        bad("The request body is not valid JSON")
    if not isinstance(data, dict):
        bad("The request body must be a JSON object")
    return data


def present(body, name):
    return name in body and body[name] is not None


def _missing(name):
    bad("%s is required" % name)


def f_str(body, name, required=False, min_len=None, max_len=None,
          upper=False):
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = body[name]
    if not isinstance(value, str):
        bad("%s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        bad("%s must be at least %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("%s must be at most %d characters" % (name, max_len))
    if required and not value.strip():
        bad("%s must not be blank" % name)
    if upper and value != value.upper():
        bad("%s must be uppercase" % name)
    return value


def f_enum(body, name, members, required=False):
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = body[name]
    if not isinstance(value, str) or value not in members:
        bad("%s must be one of %s" % (name, ", ".join(sorted(members))))
    return value


def f_int(body, name, required=False, minimum=None, maximum=None):
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, int):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s must be at least %s" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be at most %s" % (name, maximum))
    return value


def f_num(body, name, required=False, gt=None, ge=None, le=None):
    """A decimal number field, returned as an exact Decimal."""
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = body[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad("%s must be a number" % name)
    value = dec(value)
    if gt is not None and not value > dec(gt):
        bad("%s must be greater than %s" % (name, gt))
    if ge is not None and value < dec(ge):
        bad("%s must be at least %s" % (name, ge))
    if le is not None and value > dec(le):
        bad("%s must be at most %s" % (name, le))
    return value


def f_bool(body, name, required=False, default=None):
    if not present(body, name):
        if required:
            _missing(name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        bad("%s must be a boolean" % name)
    return value


def f_dt(body, name, required=False):
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = parse_dt(body[name])
    if value is None:
        bad("%s must be an ISO 8601 UTC timestamp" % name)
    return value


def f_date(body, name, required=False):
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = parse_date(body[name])
    if value is None:
        bad("%s must be a YYYY-MM-DD date" % name)
    return value


def f_str_list(body, name, required=False, members=None, distinct=True,
               non_empty=True):
    if not present(body, name):
        if required:
            _missing(name)
        return None
    value = body[name]
    if not isinstance(value, list):
        bad("%s must be an array" % name)
    if non_empty and len(value) == 0:
        bad("%s must not be empty" % name)
    for item in value:
        if not isinstance(item, str) or not item.strip():
            bad("%s must contain non-empty strings" % name)
        if members is not None and item not in members:
            bad("%s contains an unsupported value" % name)
    if distinct and len(set(value)) != len(value):
        bad("%s must not contain duplicates" % name)
    return value


# --------------------------------------------------------------------------
# pagination (rung 5)
# --------------------------------------------------------------------------

def _pag_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION", "%s must be an integer" % name)
    value = int(text)
    return value


def pagination():
    limit = _pag_int("limit", 10)
    offset = _pag_int("offset", 0)
    if limit < 1 or limit > 100:
        raise ApiError(
            "ERR_INVALID_PAGINATION", "limit must be between 1 and 100"
        )
    if offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION", "offset must be at least 0")
    return limit, offset


def page(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total


# --------------------------------------------------------------------------
# path existence (rung 6) and body references (rung 7)
# --------------------------------------------------------------------------

def must_exist(table, row_id, label):
    row = db.get(table, row_id)
    if row is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND", "%s not found" % label)
    return row


def must_reference(table, row_id, label):
    row = db.get(table, row_id)
    if row is None:
        raise ApiError("ERR_UNKNOWN_REFERENCE", "%s does not exist" % label)
    return row


def check_parent_version(parent, supplied, label):
    """Rung 8: optimistic concurrency on the parent row."""
    if parent["version"] != supplied:
        raise ApiError(
            "ERR_STALE_PARENT_VERSION",
            "%s version is %s, request supplied %s"
            % (label, parent["version"], supplied),
        )
