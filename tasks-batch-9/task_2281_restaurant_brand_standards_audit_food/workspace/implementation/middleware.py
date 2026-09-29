"""Authentication, authorization, path resolution and request-body validation.

The evaluation order implemented by the route modules follows PRD 2.8 exactly:
  1 ERR_UNAUTHENTICATED, 2 ERR_UNAUTHORIZED, 3 path existence,
  4 ERR_ACTING_IDENTITY_NOT_FOUND, 5 ERR_NOT_RESOURCE_OWNER,
  6 ERR_INVALID_REQUEST, 7 body foreign keys, then the numbered business rules.
"""

from flask import g, request

import db
from common import parse_dt
from errors import ApiError, fail

ROLES = (
    "BrandAdmin",
    "Auditor",
    "CalibrationReviewer",
    "Franchisee",
    "ComplianceIntegrator",
)

ENTITY_BACKED = {
    "Auditor": "auditors",
    "CalibrationReviewer": "auditors",
    "Franchisee": "franchisees",
}

PATH_ENTITIES = {
    "brand": ("brands", "ERR_BRAND_NOT_FOUND"),
    "franchisee": ("franchisees", "ERR_FRANCHISEE_NOT_FOUND"),
    "auditor": ("auditors", "ERR_AUDITOR_NOT_FOUND"),
    "location": ("locations", "ERR_LOCATION_NOT_FOUND"),
    "rubric_version": ("rubric_versions", "ERR_RUBRIC_VERSION_NOT_FOUND"),
    "rubric_item": ("rubric_items", "ERR_RUBRIC_ITEM_NOT_FOUND"),
    "visit": ("audit_visits", "ERR_VISIT_NOT_FOUND"),
    "scored_item": ("scored_items", "ERR_SCORED_ITEM_NOT_FOUND"),
    "corrective_action": ("corrective_actions", "ERR_CORRECTIVE_ACTION_NOT_FOUND"),
    "dispute": ("disputes", "ERR_DISPUTE_NOT_FOUND"),
    "health_inspection": ("health_inspections", "ERR_HEALTH_INSPECTION_NOT_FOUND"),
}


# --------------------------------------------------------------------------
# 1 + 2 + 4: authentication, authorization, acting-identity resolution
# --------------------------------------------------------------------------

def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and a valid X-User-Role header are required.")
    g.user_id = user_id
    g.role = role


def authorize(*allowed_roles):
    if g.role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "Role %s may not perform this operation." % g.role)


def begin(*allowed_roles):
    """Steps 1 and 2 of the precedence order."""
    authenticate()
    authorize(*allowed_roles)


def resolve_identity():
    """Step 4: X-User-ID must resolve for the three entity-backed roles."""
    collection = ENTITY_BACKED.get(g.role)
    if collection is None:
        g.actor = None
        return None
    actor = getattr(db.store, collection).get(g.user_id)
    if actor is None:
        fail("ERR_ACTING_IDENTITY_NOT_FOUND", "The acting identity does not exist.")
    g.actor = actor
    return actor


# --------------------------------------------------------------------------
# 3 + 7: existence resolution
# --------------------------------------------------------------------------

def lookup(kind, identifier):
    collection, _ = PATH_ENTITIES[kind]
    if not isinstance(identifier, str):
        return None
    return getattr(db.store, collection).get(identifier)


def require(kind, identifier):
    record = lookup(kind, identifier)
    if record is None:
        _, error_id = PATH_ENTITIES[kind]
        fail(error_id, "%s does not exist." % kind.replace("_", " ").capitalize())
    return record


# --------------------------------------------------------------------------
# 6: request body well-formedness
# --------------------------------------------------------------------------

def body():
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    parsed = request.get_json(silent=True)
    if parsed is None or not isinstance(parsed, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return parsed


def _missing(payload, name):
    return name not in payload or payload[name] is None


def req_str(payload, name, min_len=None, max_len=None):
    if _missing(payload, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = payload[name]
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a string." % name)
    if min_len is not None and len(value) < min_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too short." % name)
    if max_len is not None and len(value) > max_len:
        fail("ERR_INVALID_REQUEST", "Field '%s' is too long." % name)
    return value


def opt_str(payload, name, min_len=None, max_len=None, default=None):
    if _missing(payload, name):
        return default
    return req_str(payload, name, min_len, max_len)


def req_int(payload, name, low=None, high=None):
    if _missing(payload, name):
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    value = payload[name]
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an integer." % name)
    if low is not None and value < low:
        fail("ERR_INVALID_REQUEST", "Field '%s' is below its minimum." % name)
    if high is not None and value > high:
        fail("ERR_INVALID_REQUEST", "Field '%s' is above its maximum." % name)
    return value


def opt_int(payload, name, low=None, high=None, default=None):
    if _missing(payload, name):
        return default
    return req_int(payload, name, low, high)


def req_bool(payload, name, default=None):
    if _missing(payload, name):
        if default is None:
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
        return default
    value = payload[name]
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field '%s' must be a boolean." % name)
    return value


def req_enum(payload, name, choices):
    value = req_str(payload, name)
    if value not in choices:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be one of %s." % (name, ", ".join(choices)))
    return value


def opt_enum(payload, name, choices, default=None):
    if _missing(payload, name):
        return default
    return req_enum(payload, name, choices)


def req_dt(payload, name):
    value = req_str(payload, name)
    parsed = parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an ISO 8601 instant." % name)
    return parsed


def opt_dt(payload, name, default=None):
    if _missing(payload, name):
        return default
    return req_dt(payload, name)


def req_id(payload, name):
    """A foreign key reference in the body: must be a non-empty string."""
    value = payload.get(name)
    if value is None:
        fail("ERR_INVALID_REQUEST", "Field '%s' is required." % name)
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an identifier string." % name)
    return value


def opt_id(payload, name):
    value = payload.get(name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        fail("ERR_INVALID_REQUEST", "Field '%s' must be an identifier string." % name)
    return value


# --------------------------------------------------------------------------
# Pagination + query filters (PRD 2.3)
# --------------------------------------------------------------------------

def pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "Query parameter 'offset' may not be negative.")
    return limit, offset


def filter_value(name):
    value = request.args.get(name)
    if value is None or value == "":
        return None
    return value


def filter_enum(name, choices):
    value = filter_value(name)
    if value is None:
        return None
    if value not in choices:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be one of %s." % (name, ", ".join(choices)))
    return value


def paginate(records, limit, offset, serializer):
    total = len(records)
    page = records[offset:offset + limit]
    return [serializer(r) for r in page], total


def listing(records, serializer, sort_key=None):
    """Validate pagination, order the collection and build the array envelope."""
    from response import list_response

    limit, offset = pagination()
    records = sorted(records, key=sort_key or db.sort_key)
    items, total = paginate(records, limit, offset, serializer)
    return list_response(items, total, limit, offset)


__all__ = [
    "ApiError",
    "ROLES",
    "begin",
    "authenticate",
    "authorize",
    "resolve_identity",
    "lookup",
    "require",
    "body",
    "req_str",
    "opt_str",
    "req_int",
    "opt_int",
    "req_bool",
    "req_enum",
    "opt_enum",
    "req_dt",
    "opt_dt",
    "req_id",
    "opt_id",
    "pagination",
    "filter_value",
    "filter_enum",
    "paginate",
    "listing",
]
