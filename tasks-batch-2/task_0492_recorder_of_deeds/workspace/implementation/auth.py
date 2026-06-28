"""Authentication + RBAC (PRD §2.1, §4).

Every request must carry X-User-ID (acting user) and X-User-Role (operational
capacity). The system recognizes exactly four roles, spelled precisely:
Submitter, Examiner, Recorder, Clerk. A missing or unrecognized X-User-Role
yields ERR_UNAUTHENTICATED; a recognized role not permitted for the operation
yields ERR_FORBIDDEN."""
from flask import request

import errors

SUBMITTER = "Submitter"
EXAMINER = "Examiner"
RECORDER = "Recorder"
CLERK = "Clerk"

KNOWN_ROLES = {SUBMITTER, EXAMINER, RECORDER, CLERK}

# Every role can read (all GET endpoints list all four).
ALL_READERS = [CLERK, EXAMINER, RECORDER, SUBMITTER]


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def require_auth(allowed_roles):
    """Run the auth (priority 1) then RBAC (priority 2) gates, returning Caller.

    PRD §2.1 / §2.10: a missing or unrecognized X-User-Role -> ERR_UNAUTHENTICATED;
    a recognized role not permitted for the op -> ERR_FORBIDDEN.

    allowed_roles: iterable of role names permitted for the endpoint."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in KNOWN_ROLES:
        raise errors.err(errors.ERR_UNAUTHENTICATED, "Missing or unrecognized role")
    if role not in allowed_roles:
        raise errors.err(errors.ERR_FORBIDDEN, "Role not permitted for this operation")
    return Caller(user_id, role)
