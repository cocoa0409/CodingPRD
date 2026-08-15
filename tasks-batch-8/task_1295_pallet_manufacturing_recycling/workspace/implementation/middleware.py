"""Auth header extraction, RBAC, pagination, and request-body validation.

Auth model (PRD section 2.1): every request must carry X-User-Role naming one
of the six declared roles. X-User-ID is an opaque operator id; it is never
compared against resource ids. GET endpoints accept any authenticated role
(pseudo-role "Any"); the role value "Any" itself is NOT accepted as a
requesting role -- it is a matrix placeholder for shared read access.
"""

from datetime import datetime, timezone

from flask import request

from errors import raise_err

ROLES = {
    "ProcurementManager",
    "YardSupervisor",
    "HeatTreatOperator",
    "SalesRep",
    "FleetPlanner",
    "PlantManager",
}


def require_roles(*allowed):
    """Validate the X-User-Role header and enforce the RBAC matrix.

    Priority 1: header missing or not a declared role -> ERR_UNAUTHENTICATED.
    Priority 2: role recognized but not permitted     -> ERR_UNAUTHORIZED.
    Call with no arguments to allow any authenticated role (GET endpoints).
    """
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise_err(
            "ERR_UNAUTHENTICATED",
            "Missing or unrecognized X-User-Role header",
        )
    if allowed and role not in allowed:
        raise_err(
            "ERR_UNAUTHORIZED",
            "Role %s is not permitted for this endpoint" % role,
        )
    return role


def get_json_body():
    """Return the request JSON body as a dict (empty dict when absent)."""
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return body


# --- pagination (limit/offset, defaults 10/0, min 1, max 100) ----------------

def parse_pagination():
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise_err("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1 or limit > 100:
        raise_err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if offset < 0:
        raise_err("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Slice an already-sorted list and build the pagination meta fields."""
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


# --- field validators ---------------------------------------------------------

def req_field(body, name):
    if name not in body or body[name] is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    return body[name]


def opt_field(body, name, default=None):
    val = body.get(name, default)
    return default if val is None else val


def as_str(val, name):
    if not isinstance(val, str) or val == "":
        raise_err("ERR_INVALID_REQUEST", "Field %s must be a non-empty string" % name)
    return val


def as_bool(val, name):
    if not isinstance(val, bool):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be a boolean" % name)
    return val


def as_int(val, name, minimum=None):
    if isinstance(val, bool) or not isinstance(val, int):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be an integer" % name)
    if minimum is not None and val < minimum:
        raise_err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    return val


def as_number(val, name, minimum=None, exclusive_min=False):
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be a number" % name)
    if minimum is not None:
        if exclusive_min and not val > minimum:
            raise_err("ERR_INVALID_REQUEST", "Field %s must be > %s" % (name, minimum))
        if not exclusive_min and val < minimum:
            raise_err("ERR_INVALID_REQUEST", "Field %s must be >= %s" % (name, minimum))
    return val


def as_enum(val, name, choices):
    if not isinstance(val, str) or val not in choices:
        raise_err(
            "ERR_INVALID_REQUEST",
            "Field %s must be one of %s" % (name, sorted(choices)),
        )
    return val


def as_datetime(val, name):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(val, str):
        raise_err("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 datetime string" % name)
    text = val.strip()
    try:
        if text.endswith("Z"):
            dt = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(text)
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "Field %s is not a valid ISO 8601 datetime" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
