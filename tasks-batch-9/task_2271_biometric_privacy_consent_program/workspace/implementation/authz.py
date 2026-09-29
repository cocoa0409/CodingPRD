"""Steps 1, 2 and 5 of the validation precedence (PRD 2.5)."""

from flask import request

from constants import ROLES
from errors import fail


def actor():
    """Step 1: header authentication."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if user_id == "" or role == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Unknown X-User-Role value.")
    return user_id, role


def require_role(role, allowed):
    """Step 2: role authority for a fixed-role endpoint."""
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation." % role)


def require_role_for_target(role, to_status, status_enum, grants, endpoint_roles):
    """Step 2 on a shared lifecycle endpoint: the role must be granted the
    requested to_status.  When to_status is absent or not a member of the
    entity's status enum the generic endpoint role list is used, so that step 3
    can report the malformed body."""
    if not isinstance(to_status, str) or to_status not in status_enum:
        require_role(role, endpoint_roles)
        return
    if role not in grants.get(to_status, ()):
        fail(
            "ERR_FORBIDDEN_ROLE",
            "Role %s may not drive this resource to %s." % (role, to_status),
        )


def require_subject_owner(role, user_id, owner_subject_id):
    """Step 5: subject ownership."""
    if role == "Subject" and user_id != owner_subject_id:
        fail("ERR_SUBJECT_MISMATCH", "This resource belongs to another data subject.")
