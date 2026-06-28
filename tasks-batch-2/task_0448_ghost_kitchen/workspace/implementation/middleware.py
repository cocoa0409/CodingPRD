"""Auth header extraction and RBAC helpers (PRD §2.1, scaffold §1.4 / §1.7).

Two mandatory headers on every request:
  X-User-ID   — acting principal id
  X-User-Role — one of {PlatformOps, StallOperator, BrandOwner, AggregatorGateway}

Auth (priority 1) runs before role permission (priority 2). Ownership for
entity-backed roles is enforced at the per-endpoint level via helpers here.
"""
from flask import request

import errors

KNOWN_ROLES = {"PlatformOps", "StallOperator", "BrandOwner", "AggregatorGateway"}


def get_identity():
    """Validate presence + known role (priority 1: ERR_UNAUTHENTICATED).

    Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_role(role, allowed):
    """Priority 2 role-permission check (ERR_FORBIDDEN).

    `allowed` is an iterable of role names permitted for the endpoint."""
    if role not in allowed:
        raise errors.forbidden()
