"""Auth context (validation priorities 1-2) and shared request helpers."""
import functools

from flask import g, request

from errors import ApiError

ROLES = {
    "IntegratorAdmin",
    "Grower",
    "ServiceTech",
    "LivehaulScheduler",
    "SettlementAnalyst",
}


def _check_context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            "X-User-ID and X-User-Role headers are required and the role must be one of the declared roles.",
            401,
        )
    return uid, role


def require_roles(*roles):
    """Validate headers (401) then endpoint role permission (403)."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = _check_context()
            if role not in roles:
                raise ApiError(
                    "ERR_UNAUTHORIZED",
                    "Role %s is not permitted to invoke this endpoint." % role,
                    403,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return deco


def grower_owns_or_403(owner_grower_id):
    """Entity-backed ownership check (PRD §2.1): a Grower may only touch resources
    whose owning grower id equals their X-User-ID. No-op for opaque roles."""
    if g.user_role == "Grower" and g.user_id != owner_grower_id:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Grower may only access their own resources.",
            403,
        )


def body():
    """Parse the JSON request body; malformed or missing body -> empty dict."""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {}


def parse_pagination():
    """limit (default 10, 1..100), offset (default 0, >=0) per PRD §2.3.

    Out-of-range or unparseable values are clamped to the documented bounds.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 10
        limit = max(1, min(100, limit))
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            offset = 0
        offset = max(0, offset)
    return limit, offset


def list_response(records, filters=None):
    """Filter, sort by created_at ascending, paginate, and envelope."""
    import utils
    from response import ok_list

    limit, offset = parse_pagination()
    rows = list(records)
    if filters:
        rows = [
            r
            for r in rows
            if all(v is None or r.get(k) == v for k, v in filters.items())
        ]
    rows = utils.created_order(rows)
    total = len(rows)
    page = rows[offset : offset + limit]
    return ok_list([utils.pub(r) for r in page], limit, offset, total)
