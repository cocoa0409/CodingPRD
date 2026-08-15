"""Auth header extraction and role checking (PRD §2.1, §2.9 priorities 1-2)."""

from flask import request

import errors

ROLE_LEGAL_OPS = "LegalOpsReviewer"
ROLE_FIRM_USER = "PanelFirmUser"
VALID_ROLES = (ROLE_LEGAL_OPS, ROLE_FIRM_USER)


def require_auth(allowed_roles):
    """Validate X-User-ID / X-User-Role headers and endpoint role permission.

    Priority 1: headers present and role recognized -> ERR_UNAUTHENTICATED (401)
    Priority 2: acting role listed on endpoint's roles -> ERR_FORBIDDEN (403)

    Returns (user_id, role) on success; raises ApiError otherwise.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise errors.unauthenticated()
    if role not in allowed_roles:
        raise errors.forbidden()
    return user_id, role
