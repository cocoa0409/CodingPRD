"""Request-level concerns: authentication, RBAC, and request-shape parsing.

Auth headers and role names come from PRD 2.1:
  X-User-ID    - opaque caller identity (an entity id for entity-backed roles)
  X-User-Role  - one of PlanAdmin, CompensationCommittee, BusinessUnitManager,
                 HRBusinessPartner, FinanceController, Employee
"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from flask import request

from errors import ApiError
from response import LIMIT_DEFAULT, LIMIT_MAX, LIMIT_MIN, OFFSET_DEFAULT

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PLAN_ADMIN = "PlanAdmin"
COMPENSATION_COMMITTEE = "CompensationCommittee"
BUSINESS_UNIT_MANAGER = "BusinessUnitManager"
HR_BUSINESS_PARTNER = "HRBusinessPartner"
FINANCE_CONTROLLER = "FinanceController"
EMPLOYEE = "Employee"

KNOWN_ROLES = {
    PLAN_ADMIN,
    COMPENSATION_COMMITTEE,
    BUSINESS_UNIT_MANAGER,
    HR_BUSINESS_PARTNER,
    FINANCE_CONTROLLER,
    EMPLOYEE,
}


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


# ---------------------------------------------------------------------------
# Ladder step 1 + 2: authentication then role authorization
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)

    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in KNOWN_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return Caller(str(user_id), role)


# ---------------------------------------------------------------------------
# Ladder step 4: request shape (ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------
def bad_request(detail=None):
    return ApiError("ERR_INVALID_REQUEST", detail)


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        if request.data and request.data.strip():
            raise bad_request("Request body is not valid JSON")
        return {}
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def require_present(body, name):
    if not _present(body, name):
        raise bad_request("Missing required field '%s'" % name)
    return body[name]


def req_string(body, name, min_length=1):
    value = require_present(body, name)
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string" % name)
    if len(value) < min_length:
        raise bad_request("Field '%s' must be at least %d character(s)" % (name, min_length))
    return value


def opt_string(body, name, default=None, min_length=0):
    if not _present(body, name):
        return default
    value = body[name]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string" % name)
    if len(value) < min_length:
        raise bad_request("Field '%s' must be at least %d character(s)" % (name, min_length))
    return value


def _check_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer" % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    value = _check_int(require_present(body, name), name)
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s" % (name, maximum))
    return value


def opt_int(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return req_int(body, name, minimum=minimum, maximum=maximum)


def _to_decimal(value, name):
    if isinstance(value, bool):
        raise bad_request("Field '%s' must be a number" % name)
    if isinstance(value, (int, float)):
        try:
            return Decimal(str(value))
        except InvalidOperation:
            raise bad_request("Field '%s' must be a number" % name)
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            raise bad_request("Field '%s' must be a number" % name)
    raise bad_request("Field '%s' must be a number" % name)


def req_number(body, name, minimum=None, maximum=None):
    value = _to_decimal(require_present(body, name), name)
    if not value.is_finite():
        raise bad_request("Field '%s' must be a finite number" % name)
    if minimum is not None and value < Decimal(str(minimum)):
        raise bad_request("Field '%s' must be >= %s" % (name, minimum))
    if maximum is not None and value > Decimal(str(maximum)):
        raise bad_request("Field '%s' must be <= %s" % (name, maximum))
    return value


def opt_number(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return req_number(body, name, minimum=minimum, maximum=maximum)


def req_percent(body, name, minimum=None, maximum=None):
    """A 2-decimal percentage field (PRD 2.5)."""
    return quantize2(req_number(body, name, minimum=minimum, maximum=maximum))


def opt_percent(body, name, default=None, minimum=None, maximum=None):
    if not _present(body, name):
        return default
    return req_percent(body, name, minimum=minimum, maximum=maximum)


def quantize2(value):
    from decimal import ROUND_HALF_UP
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def req_date(body, name):
    value = require_present(body, name)
    return parse_date_string(value, name)


def opt_date(body, name, default=None):
    if not _present(body, name):
        return default
    return parse_date_string(body[name], name)


def parse_date_string(value, name):
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)" % name)
    text = value.strip()
    if len(text) != 10:
        raise bad_request("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)" % name)
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise bad_request("Field '%s' must be an ISO 8601 date (YYYY-MM-DD)" % name)


def req_enum(body, name, allowed):
    value = require_present(body, name)
    if not isinstance(value, str) or value not in allowed:
        raise bad_request("Field '%s' must be one of %s" % (name, sorted(allowed)))
    return value


def opt_enum(body, name, allowed, default=None):
    if not _present(body, name):
        return default
    return req_enum(body, name, allowed)


def req_bool(body, name):
    value = require_present(body, name)
    if not isinstance(value, bool):
        raise bad_request("Field '%s' must be a boolean" % name)
    return value


def opt_bool(body, name, default=None):
    if not _present(body, name):
        return default
    return req_bool(body, name)


def req_id(body, name):
    value = require_present(body, name)
    if not isinstance(value, str) or not value.strip():
        raise bad_request("Field '%s' must be a non-empty string identifier" % name)
    return value


def opt_id(body, name, default=None):
    if not _present(body, name):
        return default
    return req_id(body, name)


def parse_timestamp(body, name):
    value = require_present(body, name)
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be an ISO 8601 timestamp" % name)
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise bad_request("Field '%s' must be an ISO 8601 timestamp" % name)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'limit' must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise bad_request("Query parameter 'limit' must be between %d and %d"
                              % (LIMIT_MIN, LIMIT_MAX))
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise bad_request("Query parameter 'offset' must be an integer")
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be >= 0")
    return limit, offset


def query_param(name):
    value = request.args.get(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def query_int(name):
    value = query_param(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        raise bad_request("Query parameter '%s' must be an integer" % name)


def query_date(name):
    value = query_param(name)
    if value is None:
        return None
    return parse_date_string(value, name)
