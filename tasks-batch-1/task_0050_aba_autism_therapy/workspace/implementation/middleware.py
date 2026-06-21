from flask import request
import errors
from errors import err

# The system recognizes exactly five roles, spelled precisely (PRD §2.1).
RECOGNIZED_ROLES = {"IntakeCoordinator", "BCBA", "RBT", "BillingSpecialist", "Caregiver"}


def authenticate():
    """Validation priority 1 (PRD §2.1 / §2.4).

    Every request must carry X-User-ID and X-User-Role. If either header is
    missing, or X-User-Role is not one of the five declared roles, reject with
    ERR_UNAUTHENTICATED. Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in RECOGNIZED_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Role authorization (PRD §2.4): the acting role must be permitted for this
    operation, else ERR_UNAUTHORIZED. Checked AFTER body validation per the
    PRD's fixed precedence (auth -> body -> role -> existence)."""
    if role not in allowed:
        raise err(errors.ERR_UNAUTHORIZED, "Role not permitted for this operation.")
