"""Auth header extraction, role checking, pagination parsing, and payload
validation helpers. Validation priority (PRD §2.8):

  0. request shape (ERR_VALIDATION / ERR_INVALID_REQUEST)
  1. authentication (ERR_UNAUTHENTICATED)
  2. role authorization (ERR_UNAUTHORIZED)
  3. path existence, left-to-right (ERR_NOT_FOUND)
  4. body FK existence (ERR_REFERENCE_NOT_FOUND)
  5. state machine (ERR_INVALID_STATE)
  6. business safety (confidentiality / plan ownership / publish gate / duty)
  7+. business constraints (duplicate, window, cadence, unit cycle,
     threshold inversion, single-open, insufficient items)
  15. OCC (ERR_STALE_VERSION)
"""

from flask import request

from errors import (
    ApiError, err,
    ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, ERR_INVALID_REQUEST, ERR_VALIDATION,
)

ROLES = {"HRAdmin", "PeopleAnalyst", "UnitManager", "EmployeeRole", "Executive"}


# ---------------------------------------------------------------------------
# Authentication / authorization
# ---------------------------------------------------------------------------

def get_auth():
    """Extract and validate X-User-ID / X-User-Role. Returns (user_id, role).

    Raises ERR_UNAUTHENTICATED when either header is missing or the role is
    not one of the five declared roles.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED,
                  "missing/invalid X-User-Role or X-User-ID header", 401)
    return user_id, role


def require_roles(*allowed):
    """Authenticate, then authorize against the endpoint's role list."""
    user_id, role = get_auth()
    if role not in allowed:
        raise err(ERR_UNAUTHORIZED,
                  "authenticated role not permitted on endpoint", 403)
    return user_id, role


# ---------------------------------------------------------------------------
# Pagination & query envelope
# ---------------------------------------------------------------------------

def parse_pagination(allowed_query_params):
    """Parse limit/offset for list endpoints and reject unknown query params.

    Defaults: limit=10 (min 1, max 100), offset=0 (>= 0). Any query parameter
    outside the declared set (which must already include 'limit'/'offset' when
    the endpoint paginates) is rejected with ERR_INVALID_REQUEST.
    """
    allowed = set(allowed_query_params) | {"limit", "offset"}
    for key in request.args.keys():
        if key not in allowed:
            raise err(ERR_INVALID_REQUEST,
                      f"unknown query parameter: {key}", 400)

    raw_limit = request.args.get("limit")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if str(raw_limit).strip() != str(limit):
            raise err(ERR_INVALID_REQUEST, "limit must be an integer", 400)
        if limit < 1 or limit > 100:
            raise err(ERR_INVALID_REQUEST, "limit outside 1..100", 400)

    raw_offset = request.args.get("offset")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if str(raw_offset).strip() != str(offset):
            raise err(ERR_INVALID_REQUEST, "offset must be an integer", 400)
        if offset < 0:
            raise err(ERR_INVALID_REQUEST, "offset must not be negative", 400)

    return limit, offset


def paginate(items, limit, offset):
    """Slice items (already in created_at-ascending order) and return
    (page, total_count)."""
    total = len(items)
    return items[offset:offset + limit], total


# ---------------------------------------------------------------------------
# Body / field validation
# ---------------------------------------------------------------------------

def get_json_body(required=True):
    """Return the parsed JSON object body, raising ERR_VALIDATION when the
    payload is not a JSON object."""
    if not request.is_json:
        if required:
            raise err(ERR_VALIDATION, "request body must be a JSON object", 400)
        return {}
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise err(ERR_VALIDATION, "request body must be a JSON object", 400)
        return {}
    if not isinstance(body, dict):
        raise err(ERR_VALIDATION, "request body must be a JSON object", 400)
    return body


def require_fields(body, fields):
    """Every listed field must be present (and not None) in the body."""
    for f in fields:
        if f not in body or body[f] is None:
            raise err(ERR_VALIDATION, f"missing required field: {f}", 400)


def optional_fields_present(body, fields):
    """Undeclared body fields are ignored.

    PRD §2.8 enumerates request-shape validation as: required body fields
    present, field types valid, enum members legal, numeric ranges honored.
    The unknown-identifier rejection is scoped to query parameters on list
    endpoints only ("any query parameter the endpoint does not declare is
    rejected with ERR_INVALID_REQUEST"). Client-supplied system or derived
    fields in a body are therefore ignored, never rejected.
    """
    return None


def as_non_empty_string(value, field):
    if not isinstance(value, str) or value == "":
        raise err(ERR_VALIDATION, f"field {field} must be a non-empty string", 400)
    return value


def as_string(value, field):
    if not isinstance(value, str):
        raise err(ERR_VALIDATION, f"field {field} must be a string", 400)
    return value


def as_enum(value, field, members):
    if not isinstance(value, str) or value not in members:
        raise err(ERR_VALIDATION,
                  f"field {field} must be one of {sorted(members)}", 400)
    return value


def as_bool(value, field):
    if not isinstance(value, bool):
        raise err(ERR_VALIDATION, f"field {field} must be a boolean", 400)
    return value


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err(ERR_VALIDATION, f"field {field} must be an integer", 400)
    return value


def as_number(value, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise err(ERR_VALIDATION, f"field {field} must be a number", 400)
    return value
