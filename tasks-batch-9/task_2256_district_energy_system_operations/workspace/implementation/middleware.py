"""Auth ladder steps 1-2, the endpoint decorator and offset pagination."""

import functools

from flask import g, request

import response as resp
from db import LOCK
from errors import fail
from validators import bad

ROLES = (
    "SystemController",
    "DispatchOperator",
    "NetworkEngineer",
    "FieldTechnician",
    "BillingAnalyst",
    "CustomerAccount",
)

ALL_STAFF = (
    "SystemController",
    "DispatchOperator",
    "NetworkEngineer",
    "FieldTechnician",
    "BillingAnalyst",
)


class Page(object):
    """A list result plus its pagination meta."""

    def __init__(self, items, pagination):
        self.items = items
        self.pagination = pagination


def authenticate(allowed):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id.strip() == "" or role.strip() == "":
        fail("ERR_MISSING_AUTH_HEADERS",
             "both X-User-ID and X-User-Role headers are required")
    if role not in ROLES or role not in allowed:
        fail("ERR_UNAUTHORIZED", "role '%s' may not call this endpoint" % role)
    g.user_id = user_id
    g.role = role


def endpoint(bp, rule, methods, roles, status=200):
    """Register a handler: authenticate, run under the store lock, envelope."""

    def decorator(fn):
        @bp.route(rule, methods=methods, endpoint=fn.__name__)
        @functools.wraps(fn)
        def wrapper(**kwargs):
            with LOCK:
                authenticate(roles)
                result = fn(**kwargs)
                if isinstance(result, Page):
                    data = [resp.serialize(item) for item in result.items]
                    return resp.success(data, status, result.pagination, "array")
                return resp.success(resp.serialize(result), status)

        return wrapper

    return decorator


def _int_arg(name, default, minimum, maximum=None):
    if name not in request.args:
        return default
    raw = request.args.get(name)
    if raw is None or raw.strip() == "":
        bad("query parameter '%s' must be an integer" % name)
    try:
        value = int(raw.strip())
    except ValueError:
        bad("query parameter '%s' must be an integer" % name)
    if value < minimum:
        bad("query parameter '%s' must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("query parameter '%s' must be at most %d" % (name, maximum))
    return value


def pagination_args():
    limit = _int_arg("limit", 10, 1, 100)
    offset = _int_arg("offset", 0, 0)
    return limit, offset


def paginate(items):
    """Apply limit/offset from the query string to an already-ordered list."""
    limit, offset = pagination_args()
    total = len(items)
    window = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return Page(window, meta)
