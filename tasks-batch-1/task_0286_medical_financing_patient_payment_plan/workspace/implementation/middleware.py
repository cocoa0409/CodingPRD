"""Auth header extraction + role/ownership checks (PRD §2.1, §2.8).

Headers (fixed by PRD §2.1):
  X-User-ID    — acting principal id
  X-User-Role  — one of PlatformAdmin | Provider | Patient | Anonymous
"""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE

VALID_ROLES = {"PlatformAdmin", "Provider", "Patient", "Anonymous"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate(allow_unauthenticated=False):
    """Validate the two auth headers (priority 1).

    allow_unauthenticated=True is used for the public application-submission
    endpoint and the /_clock,/_cycle,/_autopay test endpoints, which per
    PRD §2.1 / validations[priority=1].applies_to do not require headers.

    Even when unauthenticated callers are allowed, if headers ARE supplied they
    must be coherent: an X-User-Role that is not a declared role is rejected.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if role is None and user_id is None and allow_unauthenticated:
        return Principal(None, None)

    if role is None or user_id is None:
        if allow_unauthenticated:
            # Partial headers on an open endpoint: if a role is given it must be valid.
            if role is not None and role not in VALID_ROLES:
                raise err(ERR_UNAUTHENTICATED, "Unknown X-User-Role")
            return Principal(user_id, role)
        raise err(ERR_UNAUTHENTICATED, "Missing X-User-ID or X-User-Role header")

    if role not in VALID_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Unknown X-User-Role")

    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Priority 2: acting role must be permitted to invoke this endpoint."""
    if principal.role not in allowed_roles:
        raise err(ERR_FORBIDDEN_ROLE,
                  "Role %s is not permitted for this operation" % principal.role)
