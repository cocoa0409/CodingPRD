"""Auth header extraction, role checking, request-body schema validation, pagination.

Header names and role values come straight from SCAFFOLD §1.4 priority-1 rule and
PRD §2.1: X-User-ID + X-User-Role, eight declared roles.
"""
from flask import request

from errors import (
    ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_INVALID_REQUEST,
)

ROLES = [
    "StoreManager", "IntakeAttendant", "Pricer", "Cashier",
    "Driver", "Volunteer", "VolunteerCoordinator", "FinanceClerk",
]

ALL_ROLES = list(ROLES)


def get_auth():
    """Priority 1: headers present and role recognized, else ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(ERR_UNAUTHENTICATED, 401,
                       "Missing/invalid X-User-Role or X-User-ID header, or unknown role")
    return user_id, role


def require_roles(allowed):
    """Priority 3: role must be in the endpoint's roles list."""
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED, 403,
                       "Role %s is not authorized for this endpoint" % role)
    return user_id, role


def get_body(required=None, optional=None, enums=None):
    """Priority 2: schema validation — required fields present, types valid, enum
    values in domain, unknown fields rejected.

    required/optional: iterables of (name, type-spec) where type-spec is one of
      'string', 'number', 'integer', 'boolean', 'array', 'object', 'any'
    enums: {field_name: [allowed values]}
    Returns the payload dict. Empty-body actions (POST transitions) call with no
    required/optional fields: a missing body then yields {}.
    """
    required = required or []
    optional = optional or []
    enums = enums or {}

    if request.is_json:
        payload = request.get_json(silent=True)
    else:
        payload = None
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")

    allowed_names = {n for n, _ in required} | {n for n, _ in optional}
    for key in payload:
        if key not in allowed_names:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Unknown field: %s" % key)

    for name, spec in required:
        if name not in payload or payload[name] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Missing required field: %s" % name)

    for name, spec in required + optional:
        if name not in payload or payload[name] is None:
            continue
        _check_type(name, payload[name], spec)

    for name, domain in enums.items():
        if name in payload and payload[name] is not None:
            if payload[name] not in domain:
                raise ApiError(ERR_INVALID_REQUEST, 400,
                               "Field %s must be one of %s" % (name, domain))
    return payload


def _check_type(name, value, spec):
    ok = True
    if spec == "string":
        ok = isinstance(value, str)
    elif spec == "integer":
        ok = isinstance(value, int) and not isinstance(value, bool)
    elif spec == "number":
        ok = (isinstance(value, (int, float)) and not isinstance(value, bool))
    elif spec == "boolean":
        ok = isinstance(value, bool)
    elif spec == "array":
        ok = isinstance(value, list)
    elif spec == "object":
        ok = isinstance(value, dict)
    elif spec == "any":
        ok = True
    if not ok:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "Field %s has invalid type (expected %s)" % (name, spec))


def get_pagination():
    """PRD §2.3: limit default 10 (min 1, max 100), offset default 0."""
    args = request.args

    def _parse_int(raw, default):
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "Pagination parameter must be an integer")

    limit = _parse_int(args.get("limit"), 10)
    offset = _parse_int(args.get("offset"), 0)
    if limit < 1 or limit > 100:
        raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Sort by created_at ascending, apply limit/offset, return (page, meta args)."""
    limit, offset = get_pagination()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["id"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


def query_filters(allowed):
    """Return {name: value} for present query args within the allowed set."""
    out = {}
    for name in allowed:
        v = request.args.get(name)
        if v is not None:
            out[name] = v
    return out


def apply_filters(records, filters):
    def match(rec):
        for k, v in filters.items():
            rv = rec.get(k)
            if rv is None:
                return False
            if isinstance(rv, bool) or isinstance(rv, (int, float)):
                if str(rv) != v:
                    return False
            elif rv != v:
                return False
        return True
    return [r for r in records if match(r)]
