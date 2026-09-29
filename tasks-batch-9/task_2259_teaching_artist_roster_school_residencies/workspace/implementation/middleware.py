"""Authentication, authorization, pagination and school-health reconciliation."""
from functools import wraps

from flask import request

import db
from enums import ROLES
from errors import ApiError
from validators import bad, parse_date


def actor():
    """PRD 2.9 priority 1 — headers present and role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "valid X-User-ID and X-User-Role headers are required")
    return user_id, role


def auth(*allowed):
    """Priority 1 then priority 2."""
    user_id, role = actor()
    if allowed and role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", "role %s may not perform this operation" % role)
    return user_id, role


def _int_arg(name, default, minimum=None, maximum=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        bad("%s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("%s must be >= %d" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("%s must be <= %d" % (name, maximum))
    return value


def pagination():
    limit = _int_arg("limit", 10, minimum=1, maximum=100)
    offset = _int_arg("offset", 0, minimum=0)
    return limit, offset


def q_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if raw not in allowed:
        bad("%s must be one of %s" % (name, ", ".join(allowed)))
    return raw


def q_str(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def q_date(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    if parse_date(raw) is None:
        bad("%s must be an ISO 8601 date (YYYY-MM-DD)" % name)
    return raw


def page(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total


def school_health_sync(fn):
    """No-op marker for the handlers that move a school's derived health figures.

    ``partnership_health`` and ``open_residency_count`` are recomputed on every
    read of the school, so nothing has to be written when a residency or a
    session moves.  The version counter of a SchoolPartner row is deliberately
    left alone: the specification only ever attributes a version increment to
    the row whose own stored fields changed.
    """

    @wraps(fn)
    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    return wrapper
