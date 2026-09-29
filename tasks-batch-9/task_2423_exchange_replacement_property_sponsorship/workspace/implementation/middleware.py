"""Authentication, authorisation and request-shape validation.

Rungs 1, 2 and 5 of the rejection ladder (PRD 2.10) live here.
"""
import json
import re
from decimal import Decimal, InvalidOperation

from flask import request

import response
from constants import ROLES
from errors import ApiError, bad_request
from util import parse_dt, to_fraction

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


# ---------------------------------------------------------------- rungs 1-2
def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip() or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return str(user_id), role


def actor(allowed_roles):
    """Rung 1 then rung 2."""
    user_id, role = authenticate()
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")
    return user_id, role


# ------------------------------------------------------------------- bodies
def read_body():
    """Parse the JSON body leniently.

    Returns (ok, mapping). ``ok`` is False when the payload is present but
    unparseable or not a JSON object; the caller raises ERR_INVALID_REQUEST at
    rung 5, which is after the ownership and segregation-of-duties rungs.
    """
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return True, {}
    try:
        parsed = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except Exception:
        return False, {}
    if not isinstance(parsed, dict):
        return False, {}
    return True, parsed


def body_or_400():
    ok, payload = read_body()
    if not ok:
        raise bad_request("Request body must be a JSON object.")
    return payload


# ------------------------------------------------------------ field helpers
def _present(payload, name):
    return name in payload and payload[name] is not None


def req_str(payload, name, allow_empty=False):
    if not _present(payload, name):
        raise bad_request("Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    if not allow_empty and not value.strip():
        raise bad_request("Field '%s' must not be blank." % name)
    return value


def opt_str(payload, name, default=None, allow_empty=True):
    if not _present(payload, name):
        return default
    value = payload[name]
    if not isinstance(value, str):
        raise bad_request("Field '%s' must be a string." % name)
    if not allow_empty and not value.strip():
        raise bad_request("Field '%s' must not be blank." % name)
    return value


def _as_int(name, value):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad_request("Field '%s' must be an integer." % name)
    return value


def req_int(payload, name, minimum=None, maximum=None):
    if not _present(payload, name):
        raise bad_request("Field '%s' is required." % name)
    value = _as_int(name, payload[name])
    if minimum is not None and value < minimum:
        raise bad_request("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        raise bad_request("Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(payload, name, default=None, minimum=None, maximum=None):
    if not _present(payload, name):
        return default
    return req_int(payload, name, minimum, maximum)


def req_enum(payload, name, allowed):
    value = req_str(payload, name)
    if value not in allowed:
        raise bad_request("Field '%s' must be one of %s." % (name, ", ".join(allowed)))
    return value


def req_ratio(payload, name, minimum=None, maximum=None,
              exclusive_maximum=None, exclusive_minimum=None):
    """A rate expressed as a JSON number, kept exact as a Decimal."""
    if not _present(payload, name):
        raise bad_request("Field '%s' is required." % name)
    value = payload[name]
    if isinstance(value, bool):
        raise bad_request("Field '%s' must be a number." % name)
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        pass
    elif isinstance(value, float):
        try:
            value = Decimal(repr(value))
        except InvalidOperation:
            raise bad_request("Field '%s' must be a number." % name)
    else:
        raise bad_request("Field '%s' must be a number." % name)
    frac = to_fraction(value)
    if minimum is not None and frac < to_fraction(minimum):
        raise bad_request("Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and frac > to_fraction(maximum):
        raise bad_request("Field '%s' must be <= %s." % (name, maximum))
    if exclusive_maximum is not None and frac >= to_fraction(exclusive_maximum):
        raise bad_request("Field '%s' must be < %s." % (name, exclusive_maximum))
    if exclusive_minimum is not None and frac <= to_fraction(exclusive_minimum):
        raise bad_request("Field '%s' must be > %s." % (name, exclusive_minimum))
    return value


def req_dt(payload, name):
    value = req_str(payload, name)
    parsed = parse_dt(value)
    if parsed is None:
        raise bad_request("Field '%s' must be an ISO 8601 timestamp." % name)
    return parsed


def opt_dt(payload, name, default=None):
    if not _present(payload, name):
        return default
    return req_dt(payload, name)


def req_id(payload, name):
    return req_str(payload, name)


# -------------------------------------------------------------- pagination
_INT_RE = re.compile(r"^[+-]?\d+$")


def pagination():
    args = request.args
    limit = response.PAGINATION_DEFAULT_LIMIT
    offset = response.PAGINATION_DEFAULT_OFFSET
    raw_limit = args.get("limit")
    if raw_limit is not None:
        if not _INT_RE.match(raw_limit.strip()):
            raise bad_request("Query parameter 'limit' must be an integer.")
        limit = int(raw_limit.strip())
        if limit < response.PAGINATION_MIN_LIMIT or limit > response.PAGINATION_MAX_LIMIT:
            raise bad_request("Query parameter 'limit' is out of range.")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        if not _INT_RE.match(raw_offset.strip()):
            raise bad_request("Query parameter 'offset' must be an integer.")
        offset = int(raw_offset.strip())
        if offset < 0:
            raise bad_request("Query parameter 'offset' must be >= 0.")
    return limit, offset


def paged(rows):
    limit, offset = pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    return window, limit, offset, total


def filter_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    return value


def int_filter_arg(name):
    value = request.args.get(name)
    if value is None:
        return None
    if not _INT_RE.match(value.strip()):
        raise bad_request("Query parameter '%s' must be an integer." % name)
    return int(value.strip())
