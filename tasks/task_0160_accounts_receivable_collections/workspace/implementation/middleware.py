"""Auth header extraction and RBAC (PRD §2.1, §3.10 ordering, SCAFFOLD §1.7).

Headers (PRD §2.1):
  X-User-ID   — opaque acting-operator identifier (never compared to entity ids
                except the SoD write-off check in §2.8)
  X-User-Role — one of AR_MANAGER, AR_CLERK, COLLECTIONS_AGENT, AUDITOR

Priority 1 (auth): both headers present & well-formed -> else ERR_UNAUTHENTICATED.
Priority 2 (authz): role permitted for the operation -> else ERR_UNAUTHORIZED.
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {"AR_MANAGER", "AR_CLERK", "COLLECTIONS_AGENT", "AUDITOR"}


def get_identity():
    """Return (user_id, role) after validating both headers are present and the
    role is one of the four recognised roles. Raises ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err(ERR_UNAUTHENTICATED, "missing authentication headers")
    if not isinstance(user_id, str) or user_id.strip() == "":
        raise err(ERR_UNAUTHENTICATED, "malformed X-User-ID")
    if not isinstance(role, str) or role.strip() == "":
        raise err(ERR_UNAUTHENTICATED, "malformed X-User-Role")
    if role not in ROLES:
        # A role string that is not one of the four recognised values is
        # malformed authentication, not an authorization failure.
        raise err(ERR_UNAUTHENTICATED, "unknown role")
    return user_id, role


def authorize(role, allowed_roles):
    """Priority 2: ensure the acting role is permitted for this operation."""
    if role not in allowed_roles:
        raise err(ERR_UNAUTHORIZED, "role %s not permitted" % role)
