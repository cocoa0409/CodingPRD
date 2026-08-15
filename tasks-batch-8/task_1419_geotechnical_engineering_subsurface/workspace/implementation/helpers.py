"""Auth middleware, body validation, and pagination helpers."""

from functools import wraps

from flask import g, request

from db import parse_dt, store
from errors import err

ROLES = {
    "FirmAdmin",
    "ClientRep",
    "ProjectManager",
    "StaffEngineer",
    "FieldGeologist",
    "DrillingSub",
    "LabManager",
    "LabTechnician",
    "SeniorEngineer",
    "PrincipalEngineer",
}


def require_roles(*roles):
    """Category 1 + endpoint-level category 2 of the evaluation pipeline."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise err(
                    "ERR_UNAUTHENTICATED",
                    "Missing or invalid X-User-ID / X-User-Role headers",
                )
            if role not in roles:
                raise err(
                    "ERR_FORBIDDEN_ROLE",
                    "Role %s is not authorized for this endpoint" % role,
                )
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def forbid_role(message="Entity-backed ownership check failed"):
    return err("ERR_FORBIDDEN_ROLE", message)


def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_VALIDATION", "Request body must be a JSON object")
    return data


def _is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise err("ERR_VALIDATION", "Field '%s' is required and must be a string" % field)
    return v


def opt_str(body, field, default=None):
    v = body.get(field, default)
    if v is not None and not isinstance(v, str):
        raise err("ERR_VALIDATION", "Field '%s' must be a string" % field)
    return v


def req_int(body, field, min_v=None):
    v = body.get(field)
    if not isinstance(v, int) or isinstance(v, bool):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be an integer" % field)
    if min_v is not None and v < min_v:
        raise err("ERR_VALIDATION", "Field '%s' must be >= %s" % (field, min_v))
    return v


def opt_int(body, field, default=None, min_v=None):
    if field not in body or body[field] is None:
        return default
    return req_int(body, field, min_v=min_v)


def req_num(body, field, min_v=None, strict_gt=None):
    v = body.get(field)
    if not _is_num(v):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be a number" % field)
    if min_v is not None and v < min_v:
        raise err("ERR_VALIDATION", "Field '%s' must be >= %s" % (field, min_v))
    if strict_gt is not None and not v > strict_gt:
        raise err("ERR_VALIDATION", "Field '%s' must be > %s" % (field, strict_gt))
    return v


def opt_num(body, field, default=None, min_v=None, strict_gt=None):
    if field not in body or body[field] is None:
        return default
    return req_num(body, field, min_v=min_v, strict_gt=strict_gt)


def opt_bool(body, field, default=False):
    v = body.get(field, default)
    if not isinstance(v, bool):
        raise err("ERR_VALIDATION", "Field '%s' must be a boolean" % field)
    return v


def req_dt(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise err("ERR_VALIDATION", "Field '%s' is required and must be an ISO-8601 timestamp" % field)
    try:
        return v, parse_dt(v)
    except (ValueError, TypeError):
        raise err("ERR_VALIDATION", "Field '%s' is not a valid ISO-8601 timestamp" % field)


def opt_dt(body, field):
    if field not in body or body[field] is None:
        return None, None
    return req_dt(body, field)


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err(
            "ERR_VALIDATION",
            "Field '%s' must be one of %s" % (field, sorted(allowed)),
        )
    return v


def opt_enum(body, field, allowed, default=None):
    if field not in body or body[field] is None:
        return default
    return req_enum(body, field, allowed)


def paginate(items):
    """Offset pagination per PRD 2.3: limit default 10 (min 1, max 100), offset default 0.

    Caller passes the full filtered list (already sorted created_at ascending);
    returns (page, pagination_meta).
    """
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "Query parameter 'limit' must be an integer")
    try:
        offset = int(raw_offset)
    except (TypeError, ValueError):
        raise err("ERR_VALIDATION", "Query parameter 'offset' must be an integer")
    if isinstance(raw_limit, str) and raw_limit.strip().lstrip("+-").isdigit() is False:
        raise err("ERR_VALIDATION", "Query parameter 'limit' must be an integer")
    if isinstance(raw_offset, str) and raw_offset.strip().lstrip("+-").isdigit() is False:
        raise err("ERR_VALIDATION", "Query parameter 'offset' must be an integer")
    if limit < 1 or limit > 100:
        raise err("ERR_VALIDATION", "Query parameter 'limit' must be between 1 and 100")
    if offset < 0:
        raise err("ERR_VALIDATION", "Query parameter 'offset' must be >= 0")
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
