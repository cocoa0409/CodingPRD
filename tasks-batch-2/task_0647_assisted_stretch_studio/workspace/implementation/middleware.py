"""Auth header extraction & role checks (PRD §2.1, scaffold validations 1-2)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

KNOWN_ROLES = {"Member", "Flexologist", "FrontDesk", "StudioManager"}

# Roles tied to persisted entities (ownership enforced); others are opaque.
ENTITY_BACKED_ROLES = {"Member", "Flexologist"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_member(self):
        return self.role == "Member"

    @property
    def is_flexologist(self):
        return self.role == "Flexologist"

    @property
    def is_front_desk(self):
        return self.role == "FrontDesk"

    @property
    def is_manager(self):
        return self.role == "StudioManager"


def authenticate():
    """Validation priority 1: headers present & role known (ERR_UNAUTHENTICATED, 401)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers.")
    return Principal(user_id, role)


def require_role(principal, allowed_roles):
    """Validation priority 2 (role part): acting role permitted (ERR_FORBIDDEN, 403)."""
    if principal.role not in allowed_roles:
        raise err(ERR_FORBIDDEN, "Role not permitted for this operation.")


def forbid():
    raise err(ERR_FORBIDDEN, "Ownership check failed for this operation.")
