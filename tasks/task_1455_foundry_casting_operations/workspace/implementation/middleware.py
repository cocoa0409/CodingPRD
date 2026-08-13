"""Auth (PRD 2.1) and list-pagination (PRD 2.3) helpers."""

from flask import request

from errors import fail

ROLES = {
    "FoundryAdmin",
    "PatternMaker",
    "MeltSupervisor",
    "Spectrographer",
    "LineOperator",
    "QualityInspector",
    "WarrantyManager",
    "Customer",
}

ALL_ROLES = [
    "FoundryAdmin", "PatternMaker", "MeltSupervisor", "Spectrographer",
    "LineOperator", "QualityInspector", "WarrantyManager", "Customer",
]


def auth():
    """Priority 1: headers present and role declared -> else ERR_UNAUTHENTICATED."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "missing or invalid X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, allowed):
    """Priority 2: role permitted on this endpoint -> else ERR_UNAUTHORIZED_ROLE."""
    if role not in allowed:
        fail("ERR_UNAUTHORIZED_ROLE", "role %s is not permitted on this endpoint" % role)


def pagination_params():
    """limit defaults 10 (min 1, max 100); offset defaults 0 (PRD 2.3)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paged(recs):
    """Sort by created_at ascending (PRD 2.3) and apply limit/offset."""
    limit, offset = pagination_params()
    ordered = sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    return ordered[offset:offset + limit], limit, offset, total
