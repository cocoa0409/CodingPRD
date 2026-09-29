"""Authentication, authorization, body-shape validation and pagination.

Implements rungs 1-4 of the rejection ladder (PRD 2.7).
"""
import json
from decimal import Decimal, InvalidOperation

from flask import g, request

from errors import ApiError
from util import dec, decimal_places, parse_date, parse_ts

# PRD 2.1 -- the seven role names
ROLE_NETWORK_ENGINEER = "NetworkEngineer"
ROLE_CAPACITY_PLANNER = "CapacityPlanner"
ROLE_SALES_AGENT = "SalesAgent"
ROLE_FIELD_TECH = "FieldTech"
ROLE_BILLING_ADMIN = "BillingAdmin"
ROLE_FINANCE_APPROVER = "FinanceApprover"
ROLE_SUBSCRIBER = "Subscriber"

OPERATOR_ROLES = (
    ROLE_NETWORK_ENGINEER,
    ROLE_CAPACITY_PLANNER,
    ROLE_SALES_AGENT,
    ROLE_FIELD_TECH,
    ROLE_BILLING_ADMIN,
    ROLE_FINANCE_APPROVER,
)
ALL_ROLES = OPERATOR_ROLES + (ROLE_SUBSCRIBER,)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

MISSING = object()


# ---------------------------------------------------------------------------
# rungs 1 and 2
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(*allowed):
    if g.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
    return g.role


def require(*allowed):
    """Run rung 1 then rung 2."""
    authenticate()
    authorize(*allowed)


def is_subscriber_caller():
    return g.role == ROLE_SUBSCRIBER


# ---------------------------------------------------------------------------
# rung 3 -- request body shape
# ---------------------------------------------------------------------------
def body():
    """Parse the JSON body preserving literal decimal precision."""
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", "The request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", "The request body must be a JSON object.")
    return parsed


def _bad(name, detail):
    raise ApiError("ERR_VALIDATION", "Field '%s' %s." % (name, detail))


def _raw(payload, name):
    if name not in payload:
        return MISSING
    value = payload[name]
    if value is None:
        return MISSING
    return value


def _absent(payload, name, required, default):
    if required:
        _bad(name, "is required")
    return default


def v_str(payload, name, required=True, default=None, min_len=None, max_len=None,
          allow_blank=False):
    value = _raw(payload, name)
    if value is MISSING:
        return _absent(payload, name, required, default)
    if not isinstance(value, str):
        _bad(name, "must be a string")
    if not allow_blank and value.strip() == "":
        _bad(name, "must not be blank")
    if min_len is not None and len(value) < min_len:
        _bad(name, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(name, "must be at most %d characters" % max_len)
    return value


def v_enum(payload, name, members, required=True, default=None):
    value = _raw(payload, name)
    if value is MISSING:
        return _absent(payload, name, required, default)
    if not isinstance(value, str) or value not in members:
        _bad(name, "must be one of %s" % ", ".join(members))
    return value


def v_bool(payload, name, required=True, default=None):
    value = _raw(payload, name)
    if value is MISSING:
        return _absent(payload, name, required, default)
    if not isinstance(value, bool):
        _bad(name, "must be a boolean")
    return value


def v_int(payload, name, required=True, default=None, minimum=None, maximum=None,
          multiple_of=None):
    value = _raw(payload, name)
    if value is MISSING:
        return _absent(payload, name, required, default)
    if isinstance(value, bool) or isinstance(value, str):
        _bad(name, "must be an integer")
    if isinstance(value, Decimal):
        if value != value.to_integral_value():
            _bad(name, "must be an integer")
        value = int(value)
    if not isinstance(value, int):
        _bad(name, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(name, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(name, "must be at most %s" % maximum)
    if multiple_of is not None and value % multiple_of != 0:
        _bad(name, "must be an exact multiple of %d" % multiple_of)
    return value


def v_num(payload, name, required=True, default=None, minimum=None, maximum=None,
          places=None, exclusive_minimum=None):
    value = _raw(payload, name)
    if value is MISSING:
        return _absent(payload, name, required, default)
    if isinstance(value, bool) or isinstance(value, str):
        _bad(name, "must be a number")
    if not isinstance(value, (int, Decimal, float)):
        _bad(name, "must be a number")
    try:
        number = dec(value)
    except (InvalidOperation, TypeError, ValueError):
        _bad(name, "must be a number")
    if not number.is_finite():
        _bad(name, "must be a finite number")
    if places is not None and decimal_places(number) > places:
        _bad(name, "must carry at most %d decimal place(s)" % places)
    if minimum is not None and number < dec(minimum):
        _bad(name, "must be at least %s" % minimum)
    if exclusive_minimum is not None and number <= dec(exclusive_minimum):
        _bad(name, "must be greater than %s" % exclusive_minimum)
    if maximum is not None and number > dec(maximum):
        _bad(name, "must be at most %s" % maximum)
    return number


def v_ts(payload, name, required=True, default=None):
    value = _raw(payload, name)
    if value is MISSING:
        return _absent(payload, name, required, default)
    if not isinstance(value, str):
        _bad(name, "must be an ISO 8601 timestamp string")
    parsed = parse_ts(value)
    if parsed is None:
        _bad(name, "must be an ISO 8601 timestamp string")
    return parsed


def v_date(payload, name, required=True, default=None):
    value = _raw(payload, name)
    if value is MISSING:
        return _absent(payload, name, required, default)
    if not isinstance(value, str):
        _bad(name, "must be a YYYY-MM-DD date string")
    parsed = parse_date(value)
    if parsed is None:
        _bad(name, "must be a YYYY-MM-DD date string")
    return parsed


def v_ref(payload, name, required=True, default=None):
    """A body reference: shape-checked here, resolved at rung 6."""
    value = _raw(payload, name)
    if value is MISSING:
        return _absent(payload, name, required, default)
    if not isinstance(value, str) or value.strip() == "":
        _bad(name, "must be a non-empty string identifier")
    return value


# ---------------------------------------------------------------------------
# rung 4 -- pagination bounds
# ---------------------------------------------------------------------------
LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0


def pagination():
    args = request.args
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION_INVALID")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise ApiError("ERR_PAGINATION_INVALID")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(str(raw).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_PAGINATION_INVALID")
        if offset < OFFSET_MIN:
            raise ApiError("ERR_PAGINATION_INVALID")
    return limit, offset


def filters(*names):
    """Collect the optional exact-match filters this listing declares."""
    out = {}
    for name in names:
        if name in request.args:
            value = request.args.get(name)
            if value is not None and value != "":
                out[name] = value
    return out


def apply_filters(records, spec):
    if not spec:
        return records
    out = []
    for record in records:
        keep = True
        for key, wanted in spec.items():
            actual = record.get(key)
            if actual is None or str(actual) != str(wanted):
                keep = False
                break
        if keep:
            out.append(record)
    return out


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total
