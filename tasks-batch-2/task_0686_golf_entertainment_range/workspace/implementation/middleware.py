"""Auth header extraction and RBAC (PRD §2.1, §2.6; SCAFFOLD §1.4, §1.7).

Headers (PRD §2.1):
  X-User-ID   — acting user id. For role Guest it is the acting Member.id and is
                used for ownership checks. For FrontDesk / RangeManager it is an
                opaque operator identifier never matched against any entity id.
  X-User-Role — exactly one of: Guest, FrontDesk, RangeManager.

Validation order (PRD §2.6):
  1. authentication   -> ERR_UNAUTHENTICATED (401) when role missing/unknown
  2. role authorization -> ERR_FORBIDDEN_ROLE (403)
  3. ownership (Guest on own member-scoped resource) -> ERR_NOT_RESOURCE_OWNER (403)
  ... then existence/state/business handled in route logic.
"""

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER

KNOWN_ROLES = {"Guest", "FrontDesk", "RangeManager"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_guest(self):
        return self.role == "Guest"


def get_caller():
    """Authenticate the request (step 1) and return a Caller.

    The auth rule (SCAFFOLD validation priority 1, PRD §2.1) is "X-User-Role
    present and a recognized role". A missing or unrecognized role fails 401.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in KNOWN_ROLES:
        raise_err(ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-Role")
    return Caller(user_id, role)


def require_roles(caller, allowed_roles):
    """Step 2: role authorization (PRD §2.1)."""
    if caller.role not in allowed_roles:
        raise_err(
            ERR_FORBIDDEN_ROLE,
            "Role %s is not permitted for this operation" % caller.role,
        )


def require_owner(caller, owner_member_id):
    """Step 3: ownership check for a Guest acting on a member-scoped resource (PRD §2.1).

    FrontDesk and RangeManager are opaque operators and are never subject to the
    member-ownership check. A Guest whose X-User-ID is not the resource's owning
    member reference is rejected with ERR_NOT_RESOURCE_OWNER.
    """
    if caller.is_guest and caller.user_id != owner_member_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Guest does not own this resource")
