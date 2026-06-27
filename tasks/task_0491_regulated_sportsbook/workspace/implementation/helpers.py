"""Shared helpers: auth extraction, pagination, field validation."""

from flask import request

from errors import err

# Roles recognized by the system (PRD §2.1), spelled exactly.
ROLES = {"Anonymous", "Bettor", "TradingOps", "SettlementAgent", "ComplianceOfficer"}


def get_auth():
    """Return (user_id, user_role) from headers, or (None, None) if absent.

    PRD §2.1: every protected request carries X-User-ID and X-User-Role.
    """
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    return uid, role


def require_auth(allowed_roles):
    """Validate auth headers and role, in priority order (PRD §2.10):

    1. missing X-User-ID / X-User-Role -> ERR_UNAUTHENTICATED (401)
    2. role not permitted              -> ERR_FORBIDDEN (403)

    Returns (user_id, user_role).
    """
    uid, role = get_auth()
    if not uid or not role:
        raise err("ERR_UNAUTHENTICATED", "Missing X-User-ID or X-User-Role header")
    if role not in ROLES:
        # An unrecognized role cannot be permitted for any operation.
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
    if role not in allowed_roles:
        raise err("ERR_FORBIDDEN", "Role not permitted for this operation")
    return uid, role


def get_json():
    """Parse the JSON body; treat absent/invalid as an empty object."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise err("ERR_INVALID_REQUEST", "Request body must be a JSON object")
    return data


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3): limit default 10, min 1, max 100; offset default 0.
# A limit outside the band is a malformed request (ERR_INVALID_REQUEST).
# ---------------------------------------------------------------------------
def get_pagination():
    args = request.args

    limit_raw = args.get("limit")
    offset_raw = args.get("offset")

    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            raise err("ERR_INVALID_REQUEST", "limit must be between 1 and 100")

    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be >= 0")

    return limit, offset


def paginate(rows, limit, offset):
    """Apply the page window. Returns (page_rows, pagination_meta).

    Rows are expected to already be sorted (ascending created_at, PRD §2.3).
    total_count is the full match count before windowing; has_more is true when
    records beyond the window remain.
    """
    total = len(rows)
    page = rows[offset: offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    return page, meta


def sorted_by_created(rows):
    """Stable ascending order by (created_at, _seq) for deterministic listing."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---------------------------------------------------------------------------
# Field-level validation primitives (ERR_INVALID_REQUEST, PRD §2.10 lowest).
# ---------------------------------------------------------------------------
def require_fields(body, names):
    for n in names:
        if n not in body or body[n] is None:
            raise err("ERR_INVALID_REQUEST", f"Missing required field: {n}")


def require_enum(value, allowed, field):
    if value not in allowed:
        raise err("ERR_INVALID_REQUEST", f"Invalid {field}: {value!r}")


def require_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise err("ERR_INVALID_REQUEST", f"{field} must be an integer")
    return value


def require_positive_int(value, field):
    require_int(value, field)
    if value <= 0:
        raise err("ERR_INVALID_REQUEST", f"{field} must be a positive integer")
    return value
