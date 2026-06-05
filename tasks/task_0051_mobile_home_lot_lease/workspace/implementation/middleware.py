from flask import request
import errors
from errors import err

# The system recognizes exactly three roles, spelled precisely (PRD §2.1).
RECOGNIZED_ROLES = {"ParkManager", "Resident", "HousingAuthority"}


def authenticate():
    """Validation priority 1 (PRD §2.1).

    Every request must carry X-User-ID and X-User-Role. If X-User-Role is
    missing or is not one of the three declared roles, reject with
    ERR_UNAUTHENTICATED (401). Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not role or role not in RECOGNIZED_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or unrecognized X-User-Role header.")
    return user_id, role


def require_role(role, allowed):
    """Role authorization (PRD §2.1, priority 2): the acting role must be
    permitted for this operation, else ERR_FORBIDDEN (403)."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN, "Role not permitted for this operation.")
