"""Request screening ladder rungs 1-6 plus reusable field validators.

PRD 2.8 fixes the screening order; the first failing check determines the
response.  Rungs 1-3 (headers, role recognition, endpoint role admission) are
applied by @endpoint; rungs 4-6 (path existence, body FK existence, request
shape) are applied inside each handler in that exact order.
"""

import functools
import re
from datetime import datetime, timezone

from flask import g, request

from constants import ALL_ROLES, ROLE_BUYER, ROLE_PRODUCER
from errors import ApiError

_REGION_RE = re.compile(r"^[A-Z]{3}$")
_COMMODITY_RE = re.compile(r"^[A-Z_]{1,40}$")


# ---------------------------------------------------------------------------
# rungs 1-3
# ---------------------------------------------------------------------------

def endpoint(roles):
    """Ladder rungs 1, 2 and 3."""
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            # rung 1 — both headers present and non-empty
            if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED")
            # rung 2 — the role is one of the five cooperative roles
            if role not in ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            # rung 3 — the acting role is admitted by this operation
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)
        return wrapper
    return decorator


def actor():
    return g.user_id, g.role


def is_producer_actor():
    return g.role == ROLE_PRODUCER


def is_buyer_actor():
    return g.role == ROLE_BUYER


# ---------------------------------------------------------------------------
# body access
# ---------------------------------------------------------------------------

def body():
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return payload


# ---------------------------------------------------------------------------
# rung 6 — request shape validators
# ---------------------------------------------------------------------------

def _bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "Field '%s' %s." % (field, detail))


def require_present(payload, field):
    if field not in payload or payload[field] is None:
        _bad(field, "is required")
    return payload[field]


def req_string(payload, field, min_len=1, max_len=None, pattern=None, non_blank=True):
    value = require_present(payload, field)
    if not isinstance(value, str):
        _bad(field, "must be a string")
    candidate = value.strip() if non_blank else value
    if non_blank and candidate == "":
        _bad(field, "must not be blank")
    if len(value) < min_len:
        _bad(field, "is shorter than the minimum length")
    if max_len is not None and len(value) > max_len:
        _bad(field, "is longer than the maximum length")
    if pattern is not None and not pattern.match(value):
        _bad(field, "does not match the required format")
    return value


def opt_string(payload, field, max_len=None):
    if field not in payload or payload[field] is None:
        return None
    value = payload[field]
    if not isinstance(value, str):
        _bad(field, "must be a string")
    if max_len is not None and len(value) > max_len:
        _bad(field, "is longer than the maximum length")
    return value


def req_enum(payload, field, allowed):
    value = require_present(payload, field)
    if not isinstance(value, str) or value not in allowed:
        _bad(field, "must be one of %s" % ", ".join(allowed))
    return value


def req_int(payload, field, minimum=None, maximum=None):
    value = require_present(payload, field)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(field, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(field, "must be >= %d" % minimum)
    if maximum is not None and value > maximum:
        _bad(field, "must be <= %d" % maximum)
    return value


def opt_int(payload, field, minimum=None, maximum=None, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_int(payload, field, minimum, maximum)


def req_number(payload, field, minimum_exclusive=None):
    value = require_present(payload, field)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _bad(field, "must be a number")
    if minimum_exclusive is not None and value <= minimum_exclusive:
        _bad(field, "must be greater than %s" % minimum_exclusive)
    return value


def opt_number(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return req_number(payload, field)


def parse_iso8601(value, field):
    if not isinstance(value, str):
        _bad(field, "must be an ISO 8601 UTC datetime string")
    text = value.strip()
    if text == "":
        _bad(field, "must be an ISO 8601 UTC datetime string")
    normalised = text
    if normalised.endswith("Z") or normalised.endswith("z"):
        normalised = normalised[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        _bad(field, "must be an ISO 8601 UTC datetime string")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def req_datetime(payload, field):
    return parse_iso8601(require_present(payload, field), field)


def opt_datetime(payload, field, default=None):
    if field not in payload or payload[field] is None:
        return default
    return parse_iso8601(payload[field], field)


REGION_RE = _REGION_RE
COMMODITY_RE = _COMMODITY_RE
