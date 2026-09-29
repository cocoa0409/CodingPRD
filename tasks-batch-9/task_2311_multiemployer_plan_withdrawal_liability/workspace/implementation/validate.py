"""Authentication / authorisation (tiers 1-2) and request-shape screening (tier 3).

Header names, role names and the pagination contract are taken verbatim from
PRD §2.1, §2.3 and §2.9.
"""

from flask import request

from clockutil import parse_iso
from errors import fail, invalid

ROLES = (
    "FundAdministrator",
    "PlanActuary",
    "PlanTrustee",
    "EmployerRepresentative",
    "Arbitrator",
)

ANY_ROLE = ROLES

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


class Ctx(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authorize(allowed_roles):
    """Tier 1 (ERR_UNAUTHENTICATED) then tier 2 (ERR_ROLE_NOT_PERMITTED)."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    return Ctx(user_id, role)


# --------------------------------------------------------------------------
# body helpers
# --------------------------------------------------------------------------

_MISSING = object()


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid("Request body must be a JSON object.")
    return data


def present(data, name):
    return name in data and data[name] is not None


def _raw(data, name, required, default):
    if name not in data or data[name] is None:
        if required:
            invalid("Missing required field '%s'." % name)
        return default
    return data[name]


def field_str(data, name, required=False, default=None, min_len=None, max_len=None):
    value = _raw(data, name, required, default)
    if value is default and not present(data, name):
        return default
    if not isinstance(value, str):
        invalid("Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        invalid("Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        invalid("Field '%s' is too long." % name)
    return value


def field_int(data, name, required=False, default=None, minimum=None, maximum=None):
    value = _raw(data, name, required, default)
    if value is default and not present(data, name):
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        invalid("Field '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid("Field '%s' is below its minimum." % name)
    if maximum is not None and value > maximum:
        invalid("Field '%s' is above its maximum." % name)
    return value


def field_bool(data, name, required=False, default=None):
    value = _raw(data, name, required, default)
    if value is default and not present(data, name):
        return default
    if not isinstance(value, bool):
        invalid("Field '%s' must be a boolean." % name)
    return value


def field_enum(data, name, choices, required=False, default=None):
    value = _raw(data, name, required, default)
    if value is default and not present(data, name):
        return default
    if not isinstance(value, str) or value not in choices:
        invalid("Field '%s' must be one of %s." % (name, ", ".join(choices)))
    return value


def field_fraction(data, name, required=False, default=None):
    """A number constrained to 0.0 .. 1.0 inclusive."""
    value = _raw(data, name, required, default)
    if value is default and not present(data, name):
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        invalid("Field '%s' must be a number." % name)
    if value < 0.0 or value > 1.0:
        invalid("Field '%s' must lie between 0.0 and 1.0." % name)
    return float(value)


def field_datetime(data, name, required=False, default=None):
    value = _raw(data, name, required, default)
    if value is default and not present(data, name):
        return default
    parsed = parse_iso(value)
    if parsed is None:
        invalid("Field '%s' must be an ISO 8601 UTC timestamp." % name)
    return parsed


# --------------------------------------------------------------------------
# query helpers / pagination (PRD §2.3)
# --------------------------------------------------------------------------

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0
PAGE_OFFSET_MIN = 0


def _query_int(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        invalid("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        invalid("Query parameter '%s' is out of range." % name)
    if maximum is not None and value > maximum:
        invalid("Query parameter '%s' is out of range." % name)
    return value


def page_params():
    limit = _query_int("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _query_int("offset", PAGE_OFFSET_DEFAULT, PAGE_OFFSET_MIN, None)
    return limit, offset


def query_str(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def query_int_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        invalid("Query parameter '%s' must be an integer." % name)
