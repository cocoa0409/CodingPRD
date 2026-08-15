"""Auth header extraction and role checking (PRD section 2.1).

Every request must carry X-User-ID and X-User-Role. The four recognized roles
are Developer, QueueAdministrator, StudyEngineer, Regulator. A missing or
uninterpretable header is ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400);
a well-formed role that is not permitted for the endpoint is
ERR_INSUFFICIENT_PERMISSIONS (403).
"""
import threading

from flask import request

from errors import ApiError

ROLES = ("Developer", "QueueAdministrator", "StudyEngineer", "Regulator")
READ_ROLES = list(ROLES)  # all GET endpoints are shared by every role

# Single process-wide lock: makes check-then-act sequences (OCC version check,
# deposit overpayment check, milestone review) atomic under threaded serving.
WRITE_LOCK = threading.RLock()


def auth(allowed=None):
    """Validate the user-context headers; optionally enforce an endpoint role set.
    Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not isinstance(user_id, str) or not role or role not in ROLES:
        raise ApiError(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            400,
            "X-User-ID and X-User-Role headers must be present and valid",
        )
    if allowed is not None and role not in allowed:
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS", 403, "Role not permitted for this endpoint"
        )
    return user_id, role
