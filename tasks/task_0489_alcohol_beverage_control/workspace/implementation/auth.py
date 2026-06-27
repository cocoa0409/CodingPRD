"""Authentication + RBAC (PRD §2.1, §4).

Headers: X-User-ID (acting user), X-User-Role (operational capacity).
Recognised roles (spelled exactly): Director, LicensingExaminer, ZoningOfficer,
AdjudicationOfficer, Investigator, Applicant, Anonymous.

The only endpoint that admits an unauthenticated / Anonymous caller is
POST /protests."""
from flask import request

import errors

KNOWN_ROLES = {
    "Director",
    "LicensingExaminer",
    "ZoningOfficer",
    "AdjudicationOfficer",
    "Investigator",
    "Applicant",
    "Anonymous",
}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_caller():
    """Extract and validate the auth headers.

    Returns a Caller when a recognised (X-User-ID, X-User-Role) pair is present.
    Returns None when either header is absent (treated as anonymous/unauthenticated).
    Raises ERR_UNAUTHENTICATED when a header is present but the role is unknown."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        return None
    if role not in KNOWN_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Unrecognised role")
    return Caller(user_id, role)


def require_auth(allowed_roles):
    """Run the auth (priority 1) then RBAC (priority 2) gates and return the Caller.

    allowed_roles: an iterable of role names permitted for the endpoint."""
    caller = get_caller()
    if caller is None:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing authentication headers")
    if caller.role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation")
    return caller


# Every role that can read anything (all GET endpoints).
ALL_READERS = [
    "Director", "LicensingExaminer", "AdjudicationOfficer",
    "ZoningOfficer", "Investigator", "Applicant",
]
