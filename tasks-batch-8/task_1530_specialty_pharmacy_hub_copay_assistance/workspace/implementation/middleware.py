"""Auth header extraction and role checking.

Header names come from PRD 2.1 and scaffold validations[1-2]:
  - X-User-ID
  - X-User-Role

Role names come from scaffold `roles[]` (exactly seven):
  HubAdmin, CaseManager, FinancialCounselor, NurseEducator,
  PharmacyPartner, PayerReviewer, ManufacturerMonitor
"""

from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN


ALL_ROLES = (
    "HubAdmin",
    "CaseManager",
    "FinancialCounselor",
    "NurseEducator",
    "PharmacyPartner",
    "PayerReviewer",
    "ManufacturerMonitor",
)


def get_auth():
    """Extract and validate the two auth headers.

    Returns (user_id, role). Raises ApiError(ERR_UNAUTHENTICATED) when
    either header is missing, blank, or the role is unrecognized.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError(ERR_UNAUTHENTICATED,
                       "Missing X-User-ID or X-User-Role header.", 401)
    if not user_id.strip() or not role.strip():
        raise ApiError(ERR_UNAUTHENTICATED,
                       "Blank X-User-ID or X-User-Role header.", 401)
    if role not in ALL_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED,
                       f"Unrecognized role: {role}.", 401)
    return user_id, role


def require_roles(*roles):
    """Validate auth headers and that the caller's role is in `roles`.

    Returns (user_id, role). Raises ERR_UNAUTHENTICATED then
    ERR_FORBIDDEN, per validation priority order.
    """
    user_id, role = get_auth()
    if role not in roles:
        raise ApiError(ERR_FORBIDDEN,
                       f"Role {role} is not authorized for this endpoint.",
                       403)
    return user_id, role
