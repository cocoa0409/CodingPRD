"""Auth middleware and validation helpers (scaffold §1.4 / PRD §2.1, §2.4)."""

from flask import request

from errors import (
    ApiError,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_PAGINATION_PARAMETERS,
)

VALID_ROLES = {"PlatformAdmin", "ReviewCoordinator", "Reviewer", "ChiefReviewer", "Applicant"}


def get_caller():
    """Layer 1: X-User-ID and X-User-Role must be present and non-empty."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or uid.strip() == "" or role.strip() == "":
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return uid, role


def require_roles(*roles):
    """Layers 1-2: header presence + role authorization."""
    uid, role = get_caller()
    if role not in roles:
        raise ApiError(
            ERR_INSUFFICIENT_PERMISSIONS,
            403,
            "Caller role not in the endpoint's roles list",
        )
    return uid, role


def get_json_body(required=False):
    """Return the parsed JSON object body; raises ERR_INVALID_REQUEST if the
    body is not a JSON object when required."""
    body = request.get_json(silent=True)
    if body is None:
        if required:
            raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
        return {}
    if not isinstance(body, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return body


def require_fields(body, fields):
    """Layer 3: required fields present and non-null."""
    for f in fields:
        if f not in body or body[f] is None:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Required field missing: {f}")


def reject_unknown_fields(body, allowed):
    for k in body.keys():
        if k not in allowed:
            raise ApiError(ERR_INVALID_REQUEST, 400, f"Unknown field: {k}")


def require_enum(body, field, values):
    v = body.get(field)
    if v not in values:
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Invalid enum value for {field}")
    return v


def require_string(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field must be a non-empty string: {field}")
    return v


def require_int(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field must be an integer: {field}")
    return v


def require_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, f"Field must be a boolean: {field}")
    return v


def opt_string(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return require_string(body, field)


def opt_int(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return require_int(body, field)


def opt_bool(body, field, default=None):
    if field not in body or body[field] is None:
        return default
    return require_bool(body, field)


def opt_enum(body, field, values, default=None):
    if field not in body or body[field] is None:
        return default
    return require_enum(body, field, values)


def parse_pagination():
    """Layer 4: pagination params on list endpoints."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")

    def _parse_int(raw):
        if raw is None:
            return None
        try:
            # reject floats / non-numeric strings
            return int(raw, 10) if isinstance(raw, str) else int(raw)
        except (ValueError, TypeError):
            raise ApiError(
                ERR_INVALID_PAGINATION_PARAMETERS, 400,
                "limit and offset must be integers",
            )

    limit = _parse_int(raw_limit)
    offset = _parse_int(raw_offset)
    if limit is None:
        limit = 10
    if offset is None:
        offset = 0
    if limit < 1 or limit > 100 or offset < 0:
        raise ApiError(
            ERR_INVALID_PAGINATION_PARAMETERS, 400,
            "limit must be in [1,100] and offset must be >= 0",
        )
    return limit, offset


def paginate(items, limit, offset):
    """Slice a pre-sorted list per pagination params. Returns (page, total)."""
    total = len(items)
    return items[offset:offset + limit], total
