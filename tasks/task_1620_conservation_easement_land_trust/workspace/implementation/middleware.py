"""Auth context (pipeline priorities 1-2) and shared request helpers."""
import functools

from flask import g, request

from errors import ApiError

ROLES = {
    "TrustAdmin",
    "StewardshipCoordinator",
    "FieldMonitor",
    "Landowner",
    "TrustBoardReviewer",
    "Appraiser",
}


def _check_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers are required and the role must be a declared role.",
            400,
        )
    return uid, role


def require_roles(*roles):
    """Validate headers (400) then endpoint role permission (403)."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = _check_context()
            if role not in roles:
                raise ApiError(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    "Role %s is not permitted for this endpoint." % role,
                    403,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


ANY_ROLE = (
    "TrustAdmin",
    "StewardshipCoordinator",
    "FieldMonitor",
    "Landowner",
    "TrustBoardReviewer",
    "Appraiser",
)


def body(required=True):
    """Parse the JSON request body; malformed -> ERR_INVALID_REQUEST."""
    data = request.get_json(silent=True)
    if data is None:
        if required:
            raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.", 400)
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object.", 400)
    return data


def parse_pagination():
    """limit (default 10, 1..100), offset (default 0) per PRD §2.3."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.", 400)
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.", 400)
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.", 400)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0.", 400)
    return limit, offset


def paginate(records, serializer, filters):
    """Filter, sort by created_at ascending, slice, and envelope."""
    limit, offset = parse_pagination()
    rows = [r for r in records if all(r.get(k) == v for k, v in filters.items())]
    rows.sort(key=lambda r: r["created_at"])  # stable: insertion order breaks ties
    total = len(rows)
    page = rows[offset : offset + limit]
    from response import ok_list

    return ok_list([serializer(r) for r in page], limit, offset, total)
