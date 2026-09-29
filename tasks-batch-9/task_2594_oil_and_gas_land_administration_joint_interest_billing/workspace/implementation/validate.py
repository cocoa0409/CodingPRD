"""Rungs 1-5 of the request evaluation ladder: authentication, authorization,
required fields, field shapes, pagination shape."""
import re

from flask import g, request

from common import dec, decimal_places, parse_date, parse_datetime, q1, q2, q6
from errors import fail

ROLE_LAND = "LandAdministrator"
ROLE_JIA = "JointInterestAccountant"
ROLE_AUDIT = "AuditReviewer"
ROLE_COMPLIANCE = "ComplianceOfficer"
ROLE_PARTNER = "PartnerRepresentative"

ROLES = (ROLE_LAND, ROLE_JIA, ROLE_AUDIT, ROLE_COMPLIANCE, ROLE_PARTNER)

MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")
INT_RE = re.compile(r"^-?[0-9]+$")


# ---------------------------------------------------------------- rungs 1-2

def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = role


def authorize(*allowed):
    if g.user_role not in allowed:
        fail("ERR_UNAUTHORIZED")


def acting_user():
    return g.user_id


def acting_role():
    return g.user_role


def is_partner():
    return g.user_role == ROLE_PARTNER


# ---------------------------------------------------------------- body access

def body():
    payload = request.get_json(silent=True)
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        fail("ERR_VALIDATION", "Request body must be a JSON object.")
    return payload


def require(payload, names):
    for name in names:
        if payload.get(name) is None:
            fail("ERR_VALIDATION", "Field '%s' is required." % name)


def present(payload, name):
    return payload.get(name) is not None


# ---------------------------------------------------------------- rung 4 shapes

def v_str(payload, name, min_len=1, max_len=None, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_VALIDATION", "Field '%s' must be a string." % name)
    if len(value) < min_len:
        fail("ERR_VALIDATION", "Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_VALIDATION", "Field '%s' is too long." % name)
    return value


def v_enum(payload, name, allowed, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or value not in allowed:
        fail("ERR_VALIDATION", "Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def v_bool(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, bool):
        fail("ERR_VALIDATION", "Field '%s' must be a boolean." % name)
    return value


def _as_int(payload, name):
    value = payload[name]
    if isinstance(value, bool):
        fail("ERR_VALIDATION", "Field '%s' must be an integer." % name)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and float(value).is_integer():
        return int(value)
    fail("ERR_VALIDATION", "Field '%s' must be an integer." % name)


def v_int(payload, name, minimum=None, maximum=None, default=None):
    if not present(payload, name):
        return default
    value = _as_int(payload, name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "Field '%s' is below the permitted minimum." % name)
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "Field '%s' is above the permitted maximum." % name)
    return value


def v_cents(payload, name, default=None, strictly_positive=False):
    """Integer cent field: zero or greater (rung 4)."""
    if not present(payload, name):
        return default
    value = _as_int(payload, name)
    if value < 0:
        fail("ERR_VALIDATION", "Field '%s' must be zero or greater." % name)
    if strictly_positive and value == 0:
        fail("ERR_VALIDATION", "Field '%s' must be greater than zero." % name)
    return value


def v_pct(payload, name, default=None, min_exclusive=False, max_exclusive=False):
    """Percentage field: within [0.000000, 1.000000], at most six decimals."""
    if not present(payload, name):
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    try:
        amount = dec(value)
    except Exception:
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    if amount.is_nan() or amount.is_infinite():
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    if decimal_places(amount) > 6:
        fail("ERR_VALIDATION", "Field '%s' carries more than six decimal places." % name)
    lo = dec(0)
    hi = dec(1)
    if amount < lo or amount > hi:
        fail("ERR_VALIDATION", "Field '%s' must lie within 0.000000 and 1.000000." % name)
    if min_exclusive and amount == lo:
        fail("ERR_VALIDATION", "Field '%s' must be greater than zero." % name)
    if max_exclusive and amount == hi:
        fail("ERR_VALIDATION", "Field '%s' must be less than one." % name)
    return q6(amount)


def v_number(payload, name, default=None, strictly_positive=False, maximum=None, places=2):
    if not present(payload, name):
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    try:
        amount = dec(value)
    except Exception:
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    if amount.is_nan() or amount.is_infinite():
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    if strictly_positive and amount <= 0:
        fail("ERR_VALIDATION", "Field '%s' must be greater than zero." % name)
    if amount < 0:
        fail("ERR_VALIDATION", "Field '%s' must be zero or greater." % name)
    if maximum is not None and amount > maximum:
        fail("ERR_VALIDATION", "Field '%s' is above the permitted maximum." % name)
    if places == 2:
        return q2(amount)
    if places == 6:
        return q6(amount)
    return amount


def v_multiple(payload, name, default=None):
    """non_consent_penalty_multiple: within [1.0, 5.0], at most one decimal."""
    if not present(payload, name):
        return default
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    try:
        amount = dec(value)
    except Exception:
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    if amount.is_nan() or amount.is_infinite():
        fail("ERR_VALIDATION", "Field '%s' must be a number." % name)
    if decimal_places(amount) > 1:
        fail("ERR_VALIDATION", "Field '%s' carries more than one decimal place." % name)
    if amount < dec(1) or amount > dec(5):
        fail("ERR_VALIDATION", "Field '%s' must lie within 1.0 and 5.0." % name)
    return q1(amount)


def v_date(payload, name, default=None):
    if not present(payload, name):
        return default
    parsed = parse_date(payload[name])
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 calendar date." % name)
    return parsed


def v_datetime(payload, name, default=None):
    if not present(payload, name):
        return default
    parsed = parse_datetime(payload[name])
    if parsed is None:
        fail("ERR_VALIDATION", "Field '%s' must be an ISO 8601 UTC timestamp." % name)
    return parsed


def v_month(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or not MONTH_RE.match(value):
        fail("ERR_VALIDATION", "Field '%s' must match YYYY-MM." % name)
    return value


def v_id(payload, name, default=None):
    if not present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str) or not value:
        fail("ERR_VALIDATION", "Field '%s' must be a string identifier." % name)
    return value


# ---------------------------------------------------------------- rung 5 pagination

def pagination():
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        if not INT_RE.match(raw_limit.strip()):
            fail("ERR_PAGINATION_INVALID")
        limit = int(raw_limit.strip())
        if limit < 1 or limit > 100:
            fail("ERR_PAGINATION_INVALID")
    if raw_offset is not None:
        if not INT_RE.match(raw_offset.strip()):
            fail("ERR_PAGINATION_INVALID")
        offset = int(raw_offset.strip())
        if offset < 0:
            fail("ERR_PAGINATION_INVALID")
    return limit, offset


def window(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


def filt(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


READ_ALL = (ROLE_LAND, ROLE_JIA, ROLE_COMPLIANCE, ROLE_AUDIT, ROLE_PARTNER)
READ_INTERNAL = (ROLE_LAND, ROLE_JIA, ROLE_COMPLIANCE, ROLE_AUDIT)
