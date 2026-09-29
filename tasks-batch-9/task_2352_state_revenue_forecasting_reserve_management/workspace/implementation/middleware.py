"""Auth headers, RBAC and the request-shape helpers (PRD §2.1, §2.3, §2.9 tier 4)."""

import functools
import re

from flask import g, request

from errors import ApiError, fail, validation
from util import is_date_str, parse_dt

# PRD §2.1 — six roles, spelled exactly.
ROLES = (
    "ForecastDirector",
    "ExecutiveEconomist",
    "LegislativeEconomist",
    "ReserveTreasurer",
    "LegislativeVoter",
    "RatingAnalyst",
)

ROLE_HEADER = "X-User-Role"
USER_HEADER = "X-User-ID"


def authorize(*allowed_roles):
    """Ladder tiers 1-3: role header, user header, then the endpoint's role list."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get(ROLE_HEADER)
            if role is None:
                role = request.headers.get("X-Role-Name")
            if role is None or not str(role).strip() or str(role).strip() not in ROLES:
                fail("ERR_MISSING_ROLE_HEADER", "a valid %s header is required" % ROLE_HEADER)
            user_id = request.headers.get(USER_HEADER)
            if user_id is None or not str(user_id).strip():
                fail("ERR_MISSING_USER_HEADER", "a non-empty %s header is required" % USER_HEADER)
            g.role = str(role).strip()
            g.user_id = str(user_id)
            if g.role not in allowed_roles:
                fail("ERR_UNAUTHORIZED", "role %s may not perform this operation" % g.role)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# Body helpers
# --------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        validation("request body must be a JSON object")
    return data


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def check_int(name, value, minimum=None, maximum=None, allow_negative=False):
    if not is_int(value):
        validation("%s must be an integer" % name)
    if not allow_negative and value < 0:
        validation("%s may not be negative" % name)
    if minimum is not None and value < minimum:
        validation("%s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        validation("%s must be <= %s" % (name, maximum))
    return value


def req_int(data, name, minimum=None, maximum=None, allow_negative=False):
    if name not in data or data[name] is None:
        validation("%s is required" % name)
    return check_int(name, data[name], minimum, maximum, allow_negative)


def opt_int(data, name, default=None, minimum=None, maximum=None, allow_negative=False):
    if name not in data or data[name] is None:
        return default
    return check_int(name, data[name], minimum, maximum, allow_negative)


def req_enum(data, name, allowed):
    if name not in data or data[name] is None:
        validation("%s is required" % name)
    value = data[name]
    if not isinstance(value, str) or value not in allowed:
        validation("%s must be one of %s" % (name, ", ".join(allowed)))
    return value


def opt_enum(data, name, allowed, default=None):
    if name not in data or data[name] is None:
        return default
    return req_enum(data, name, allowed)


def req_str(data, name, min_len=1):
    if name not in data or data[name] is None:
        validation("%s is required" % name)
    value = data[name]
    if not isinstance(value, str):
        validation("%s must be a string" % name)
    if len(value) < min_len:
        validation("%s must be at least %d characters" % (name, min_len))
    return value


def opt_str(data, name, min_len=1, default=None):
    if name not in data or data[name] is None:
        return default
    return req_str(data, name, min_len)


def req_date(data, name):
    if name not in data or data[name] is None:
        validation("%s is required" % name)
    if not is_date_str(data[name]):
        validation("%s must be an ISO date (YYYY-MM-DD)" % name)
    return data[name]


def opt_date(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    return req_date(data, name)


def req_bool(data, name, default=None):
    if name not in data or data[name] is None:
        return default
    if not isinstance(data[name], bool):
        validation("%s must be a boolean" % name)
    return data[name]


def req_datetime(data, name):
    if name not in data or data[name] is None:
        validation("%s is required" % name)
    try:
        return parse_dt(data[name])
    except ValueError:
        validation("%s must be an ISO 8601 UTC timestamp" % name)


# --------------------------------------------------------------------------
# Pagination and filters (PRD §2.3)
# --------------------------------------------------------------------------
_INT_RE = re.compile(r"^-?\d+$")

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    if limit_raw is not None and limit_raw != "":
        if not _INT_RE.match(limit_raw.strip()):
            validation("limit must be an integer")
        limit = int(limit_raw)
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            validation("limit must be between %d and %d" % (LIMIT_MIN, LIMIT_MAX))
    if offset_raw is not None and offset_raw != "":
        if not _INT_RE.match(offset_raw.strip()):
            validation("offset must be an integer")
        offset = int(offset_raw)
        if offset < 0:
            validation("offset may not be negative")
    return limit, offset


def apply_filters(rows, spec):
    """spec: {query_param: (field_name, kind)} with kind in {str, int, bool}."""
    out = rows
    for param, (field, kind) in spec.items():
        raw = request.args.get(param)
        if raw is None or raw == "":
            continue
        if kind is int:
            if not _INT_RE.match(raw.strip()):
                out = []
                continue
            wanted = int(raw)
        elif kind is bool:
            low = raw.strip().lower()
            if low in ("true", "1"):
                wanted = True
            elif low in ("false", "0"):
                wanted = False
            else:
                out = []
                continue
        else:
            wanted = raw
        out = [r for r in out if r.get(field) == wanted]
    return out
