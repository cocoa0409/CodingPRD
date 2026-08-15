"""Auth header extraction and role checking."""

from flask import request

from errors import unauthenticated, forbidden_role


VALID_ROLES = {
    "ProjectManager",
    "InventoryTechnician",
    "BillingClerk",
    "ClaimsAdjuster",
    "SubcontractorContact",
    "CarrierRepresentative",
}


def get_auth():
    """Extract and validate X-User-ID / X-User-Role. Raises on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        raise unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Validate auth headers and role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise forbidden_role()
    return user_id, role


def parse_pagination():
    """Parse limit/offset query params with defaults and bounds."""
    from errors import validation
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("offset must be an integer")
        if offset < 0:
            raise validation("offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """Sort by created_at ascending and slice."""
    sorted_items = sorted(items, key=lambda r: (r.get("created_at", ""), r.get("id", "")))
    total = len(sorted_items)
    return sorted_items[offset:offset + limit], total
