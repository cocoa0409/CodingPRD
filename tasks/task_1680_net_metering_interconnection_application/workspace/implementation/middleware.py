"""Request pipeline rungs 1-6: auth headers, role permission, body schema,
foreign-key existence, and pagination (PRD 2.10)."""

from flask import request

import clock as clockmod
from errors import ApiError
from store import db

ROLES = (
    "Applicant",
    "InterconnectionCoordinator",
    "DistributionEngineer",
    "MeterTechnician",
    "Inspector",
    "ProgramAdministrator",
)


class Ctx(object):
    def __init__(self, user_id, role, body, query):
        self.user_id = user_id
        self.role = role
        self.body = body
        self.query = query


def begin(*allowed_roles):
    """Rungs 1 and 2: header presence/recognition, then role permission."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_MISSING_CONTEXT_HEADER")
    if allowed_roles and role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        body = {}
    return Ctx(user_id, role, body, request.args)


def must_exist(collection, row_id):
    row = collection.get(row_id) if isinstance(row_id, str) else None
    if row is None:
        raise ApiError("ERR_NOT_FOUND")
    return row


def must_ref(collection, value):
    """Rung 6: a body foreign key must resolve to an existing resource."""
    row = collection.get(value) if isinstance(value, str) else None
    if row is None:
        raise ApiError("ERR_INVALID_REFERENCE")
    return row


# ---------------------------------------------------------------------------
# Schema field helpers (rung 5 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def _bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def req_string(body, name):
    value = body.get(name)
    if not isinstance(value, str) or value == "":
        _bad("%s is required and must be a non-empty string." % name)
    return value


def opt_string(body, name):
    value = body.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        _bad("%s must be a string." % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        _bad("%s is required and must be an integer." % name)
    if minimum is not None and value < minimum:
        _bad("%s is out of range." % name)
    if maximum is not None and value > maximum:
        _bad("%s is out of range." % name)
    return value


def opt_int(body, name, minimum=None, maximum=None):
    if name not in body or body.get(name) is None:
        return None
    return req_int(body, name, minimum, maximum)


def req_enum(body, name, allowed):
    value = body.get(name)
    if value not in allowed:
        _bad("%s must be one of %s." % (name, ", ".join(allowed)))
    return value


def opt_enum(body, name, allowed):
    if name not in body or body.get(name) is None:
        return None
    return req_enum(body, name, allowed)


def req_instant(body, name):
    """Return (datetime, literal) for a required ISO 8601 instant field."""
    value = body.get(name)
    instant = clockmod.parse_instant(value)
    if instant is None:
        _bad("%s is required and must be an ISO 8601 instant." % name)
    return instant, value


def opt_instant(body, name):
    """Return (datetime|None, literal|None); explicit null is allowed."""
    if name not in body or body.get(name) is None:
        return None, None
    return req_instant(body, name)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def pagination(query):
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    raw_limit = query.get("limit")
    raw_offset = query.get("offset")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if str(raw_limit).strip() != str(limit):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be within [1, 100].")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if str(raw_offset).strip() != str(offset):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")
    return limit, offset


def paginate(rows, limit, offset):
    total = len(rows)
    return rows[offset:offset + limit], total
