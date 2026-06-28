"""Auth header extraction and RBAC (PRD §2.1, §2.10; SCAFFOLD §1.4, §1.7).

Headers (PRD §2.1):
  X-User-ID   — acting user id (opaque for Anonymous/StudioStaff/StudioManager;
                the LoyaltyMember.id when role == LoyaltyMember)
  X-User-Role — one of: Anonymous, StudioStaff, StudioManager, LoyaltyMember

Validation order (PRD §2.10):
  1. authentication  -> ERR_UNAUTHENTICATED (401) when role missing/unknown
  2. role authorization -> ERR_FORBIDDEN_ROLE (403)
  3. ownership (LoyaltyMember on own resource) -> ERR_NOT_RESOURCE_OWNER (403)
  ... then existence/state/business handled in route logic.
"""

from flask import request

from errors import unauthenticated, forbidden_role

KNOWN_ROLES = {"Anonymous", "StudioStaff", "StudioManager", "LoyaltyMember"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_member(self):
        return self.role == "LoyaltyMember"


def get_caller(allow_anonymous=False):
    """Authenticate the request (step 1) and return a Caller.

    allow_anonymous is informational only — the auth rule (SCAFFOLD validation
    priority 1) is "X-User-Role present and a known role". Anonymous IS a known
    role, so the two open endpoints (register member, open walk-in visit) simply
    permit the Anonymous role; any unknown/missing role still fails 401.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in KNOWN_ROLES:
        raise unauthenticated()
    return Caller(user_id, role)


def require_roles(caller, allowed_roles):
    """Step 2: role authorization. allowed_roles is an iterable of role names."""
    if caller.role not in allowed_roles:
        raise forbidden_role(
            "Role %s is not permitted for this operation" % caller.role
        )
