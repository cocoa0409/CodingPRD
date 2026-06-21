"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD §1.4 priority 1-2).

Every request must carry X-User-ID and X-User-Role. X-User-Role must be one of the
three recognized roles or the request is ERR_UNAUTHENTICATED (401). If the role is
recognized but not permitted for the operation, ERR_UNAUTHORIZED (403).

Identity is mostly opaque: for PropertyManager and Accountant, X-User-ID is an
opaque operator id never compared to an entity id (recorded only for the
segregation-of-duties bookkeeping). For Tenant, X-User-ID IS the acting Tenant
entity's id and ownership checks compare it to a lease's tenant_id.
"""
from __future__ import annotations

from typing import Optional
from flask import request, g

from errors import APIError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

PROPERTY_MANAGER = "PropertyManager"
ACCOUNTANT = "Accountant"
TENANT = "Tenant"

ALLOWED_ROLES = {PROPERTY_MANAGER, ACCOUNTANT, TENANT}

# Any authenticated role may perform GET reads.
ALL_ROLES = {PROPERTY_MANAGER, ACCOUNTANT, TENANT}


def auth_required(allowed_roles):
    """Validate auth headers, then enforce role membership for this operation.

    Returns a zero-arg callable so routes read `auth_required({...})()`.
    """
    allowed_set = set(allowed_roles)

    def _check():
        role = request.headers.get("X-User-Role")
        user_id = request.headers.get("X-User-ID")
        # Priority 1: authentication — both headers present, role recognized.
        if not role or not user_id:
            raise APIError(ERR_UNAUTHENTICATED, 401, "Missing X-User-ID or X-User-Role header")
        if role not in ALLOWED_ROLES:
            raise APIError(ERR_UNAUTHENTICATED, 401, "Unknown X-User-Role")
        g.user_role = role
        g.user_id = user_id
        # Priority 2: authorization — role permitted for this operation.
        if role not in allowed_set:
            raise APIError(ERR_UNAUTHORIZED, 403, "Role not permitted for this operation")

    return _check


def current_role() -> Optional[str]:
    return getattr(g, "user_role", None)


def current_user_id() -> Optional[str]:
    return getattr(g, "user_id", None)
