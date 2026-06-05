"""Authentication & role context (PRD §2.1, SCAFFOLD §1.4 priorities 1-3).

Headers:  X-User-Role  (required; one of ComplianceAdmin | Manager | Learner)
          X-User-ID    (required for entity-backed roles Manager/Learner, except
                        on the public catalog GETs and clock reads)

Auth order is fixed (evaluated before resource existence):
  1. X-User-Role present and valid               -> else ERR_UNAUTHENTICATED 401
  2. X-User-ID present for Manager/Learner        -> else ERR_UNAUTHENTICATED 401
     (exempt: GET catalog/clock reads listed below)
  3. Acting role permitted for the operation      -> else ERR_UNAUTHORIZED 403
"""

from flask import request

import errors

ROLE_ADMIN = "ComplianceAdmin"
ROLE_MANAGER = "Manager"
ROLE_LEARNER = "Learner"
VALID_ROLES = {ROLE_ADMIN, ROLE_MANAGER, ROLE_LEARNER}
ENTITY_BACKED_ROLES = {ROLE_MANAGER, ROLE_LEARNER}


class Principal:
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_admin(self):
        return self.role == ROLE_ADMIN

    @property
    def is_manager(self):
        return self.role == ROLE_MANAGER

    @property
    def is_learner(self):
        return self.role == ROLE_LEARNER


def authenticate(require_user_id=True):
    """Run auth steps 1 & 2; return a Principal or raise ApiError.

    require_user_id=False marks the public catalog/clock reads where a missing
    X-User-ID is tolerated (still requires a valid X-User-Role).
    """
    role = request.headers.get("X-User-Role")
    if role is None or role not in VALID_ROLES:
        raise errors.unauthenticated("Missing or invalid X-User-Role")

    user_id = request.headers.get("X-User-ID")
    if role in ENTITY_BACKED_ROLES and require_user_id:
        if user_id is None or user_id == "":
            raise errors.unauthenticated("Missing X-User-ID for entity-backed role")

    return Principal(role, user_id)


def require_roles(principal, allowed_roles):
    """Auth step 3: role-permission check (ERR_UNAUTHORIZED 403)."""
    if principal.role not in allowed_roles:
        raise errors.unauthorized("Role not permitted for this operation")
