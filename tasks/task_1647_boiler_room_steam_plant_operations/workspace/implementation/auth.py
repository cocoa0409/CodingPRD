"""Authentication / authorization (PRD 2.1, pipeline stages 1-2).

Headers: X-User-ID (present), X-User-Role (one of the three declared roles).
Operator identity is entity-backed (X-User-ID is an Operator id); PlantManager
and Inspector identities are opaque and never compared to entity ids.
"""
from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = ["PlantManager", "Operator", "Inspector"]


def authenticate():
    """Stage 1: headers present and role declared; else 401."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or malformed X-User-ID / X-User-Role headers")
    return uid, role


def authorize(role, allowed):
    """Stage 2: caller role permitted for this endpoint; else 403."""
    if role not in allowed:
        raise_err(ERR_UNAUTHORIZED, "Role %s is not permitted for this endpoint" % role)
