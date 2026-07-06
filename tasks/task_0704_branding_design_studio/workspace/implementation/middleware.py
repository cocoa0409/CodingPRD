"""Auth header extraction and role validation (PRD §2.1)."""
from flask import request

from errors import err, ERR_UNAUTHENTICATED

# The system recognizes exactly four roles (PRD §2.1).
KNOWN_ROLES = {"StudioOps", "Designer", "Client", "BillingOps"}


class Caller:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Validate the two mandatory auth headers and return the Caller.

    Every request must carry X-User-ID and X-User-Role. If either header is
    missing, or X-User-Role is not a recognized role, reject with
    ERR_UNAUTHENTICATED (PRD §2.1).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        raise err(ERR_UNAUTHENTICATED, "Missing or unknown authentication headers")
    return Caller(user_id, role)
