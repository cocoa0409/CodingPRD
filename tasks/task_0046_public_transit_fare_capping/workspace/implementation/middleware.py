from flask import request
import errors
from errors import err

# The five roles recognized by the system (PRD §2.1). Anonymous is a valid,
# known role (used for rider registration and public fare-product browsing).
RECOGNIZED_ROLES = {"FareAdmin", "Rider", "EmployerAdmin", "PaymentGateway", "Anonymous"}


def authenticate(allow_anonymous=False):
    """Validate auth headers (PRD §2.1, validation priority 1).

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED if either header is
    missing or the role is not one of the five recognized roles.

    ``allow_anonymous`` is used by the truly public endpoints (rider register,
    fare-product reads): when set, a caller with NO headers at all is treated as
    Anonymous. Even then, if headers ARE supplied they must be well-formed.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if allow_anonymous and not user_id and not role:
        return None, "Anonymous"
    if not user_id or not role or role not in RECOGNIZED_ROLES:
        raise err(errors.ERR_UNAUTHENTICATED, "Missing or invalid authentication headers.")
    return user_id, role


def require_role(role, allowed):
    """Validation priority 2: acting role permitted for this operation."""
    if role not in allowed:
        raise err(errors.ERR_FORBIDDEN_ROLE, "Role not permitted for this operation.")


def require_owner(role, user_id, owner_rider_id):
    """Validation priority 3: Rider ownership check (PRD §2.1).

    Only a caller acting as ``Rider`` is subject to this check; the four opaque
    operator roles (FareAdmin, EmployerAdmin, PaymentGateway, Anonymous) are
    never compared to an entity id. When the role is Rider, the targeted
    resource's rider_id must equal X-User-ID, else ERR_NOT_RESOURCE_OWNER.
    """
    if role == "Rider" and user_id != owner_rider_id:
        raise err(errors.ERR_NOT_RESOURCE_OWNER, "Rider does not own this resource.")
