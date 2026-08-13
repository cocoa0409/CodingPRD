"""Auth middleware, resource scoping, body validation, and pagination helpers.

Validation pipeline (PRD 2.5): header presence -> role authorization ->
resource scoping -> path existence -> body FKs -> schema -> OCC -> SoD ->
state -> business gates. The decorators below implement steps 1-3; route
handlers implement the rest in order.
"""

from functools import wraps

from flask import g, request

from db import parse_dt, store
from errors import err

ROLES = {
    "FleetAdmin",
    "CredentialingOfficer",
    "CrewingManager",
    "PortCaptain",
    "UnionDispatcher",
    "Mariner",
}


def require_roles(*roles):
    """Pipeline steps 1 (header presence) and 2 (role authorization)."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role:
                raise err(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    "X-User-ID and X-User-Role headers must be present and non-empty",
                )
            if role not in ROLES or role not in roles:
                raise err(
                    "ERR_UNAUTHORIZED_ROLE",
                    "Role %s is not authorized for this endpoint" % role,
                )
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def scope_mariner_id(mariner_id):
    """Pipeline step 3: role Mariner may only address their own mariner id."""
    if g.role == "Mariner" and g.user_id != mariner_id:
        raise err(
            "ERR_FORBIDDEN_RESOURCE_ACCESS",
            "Mariner role may only address its own resources",
        )


def scope_mariner_resource(owner_mariner_id):
    """Pipeline step 3 for resources linked to a mariner via FK."""
    if g.role == "Mariner" and g.user_id != owner_mariner_id:
        raise err(
            "ERR_FORBIDDEN_RESOURCE_ACCESS",
            "Mariner role may only address its own resources",
        )


def scope_dispatcher_hall(hall_id):
    """Pipeline step 3: UnionDispatcher may only mutate their own hall."""
    if g.role == "UnionDispatcher" and g.user_id != hall_id:
        raise err(
            "ERR_FORBIDDEN_RESOURCE_ACCESS",
            "UnionDispatcher may only act on their own hall",
        )


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err(
            "ERR_INVALID_REQUEST",
            "Field '%s' is required and must be a non-empty string" % field,
        )
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a string" % field)
    return v


def req_int(body, field, min_v=None, max_v=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err(
            "ERR_INVALID_REQUEST",
            "Field '%s' is required and must be an integer" % field,
        )
    if min_v is not None and v < min_v:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be >= %s" % (field, min_v))
    if max_v is not None and v > max_v:
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be <= %s" % (field, max_v))
    return v


def opt_int(body, field, default=None, min_v=None, max_v=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, min_v=min_v, max_v=max_v)


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise err(
            "ERR_INVALID_REQUEST", "Field '%s' is required and must be a boolean" % field
        )
    return v


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise err("ERR_INVALID_REQUEST", "Field '%s' must be a boolean" % field)
    return v


def req_dt(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise err(
            "ERR_INVALID_REQUEST",
            "Field '%s' is required and must be an ISO-8601 timestamp" % field,
        )
    try:
        return parse_dt(v)
    except (ValueError, TypeError):
        raise err(
            "ERR_INVALID_REQUEST",
            "Field '%s' is not a valid ISO-8601 timestamp" % field,
        )


def opt_dt(body, field):
    if field not in body or body[field] is None:
        return None
    return req_dt(body, field)


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err(
            "ERR_INVALID_REQUEST",
            "Field '%s' must be one of %s" % (field, sorted(allowed)),
        )
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def req_list(body, field):
    v = body.get(field)
    if not isinstance(v, list):
        raise err(
            "ERR_INVALID_REQUEST", "Field '%s' is required and must be an array" % field
        )
    return v


def opt_list(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return req_list(body, field)


def paginate(items):
    """Offset pagination per PRD 2.3: limit default 10 (min 1, max 100), offset 0.

    Caller passes the full filtered list (already sorted created_at ascending);
    returns (page, pagination_meta).
    """
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise err(
            "ERR_INVALID_REQUEST", "Query parameters 'limit'/'offset' must be integers"
        )
    if limit < 1 or limit > 100:
        raise err(
            "ERR_INVALID_REQUEST", "Query parameter 'limit' must be between 1 and 100"
        )
    if offset < 0:
        raise err("ERR_INVALID_REQUEST", "Query parameter 'offset' must be >= 0")
    total = len(items)
    page = items[offset : offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta


def sorted_items(records):
    """created_at ascending, ties broken by creation sequence (insertion order)."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
