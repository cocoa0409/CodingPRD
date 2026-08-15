"""Auth header extraction and role checking (PRD §2.1).

Every request must carry `X-User-ID` and `X-User-Role`. A request missing
either header, or presenting a malformed value (empty / unrecognized role),
is rejected with ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). A request
whose role is not permitted for the target endpoint is rejected with
ERR_FORBIDDEN_FOR_ROLE (403).
"""
from flask import request

from errors import err_missing_headers, err_forbidden

ROLES = {
    "FirmAdmin",
    "PricingAnalyst",
    "BillingPartner",
    "ManagingPartner",
    "Timekeeper",
    "ClientContact",
}


class UserContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_context():
    """Validate and extract the user-context headers.

    Raises ApiError(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, 400) when
    either header is absent, blank, or the role is not one of the six
    recognized role spellings.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise err_missing_headers()
    if not str(user_id).strip() or not str(role).strip():
        raise err_missing_headers()
    if role not in ROLES:
        raise err_missing_headers()
    return UserContext(str(user_id), role)


def require_roles(ctx, *roles):
    """Raise ERR_FORBIDDEN_FOR_ROLE unless the caller's role is permitted."""
    if ctx.role not in roles:
        raise err_forbidden(
            f"Role {ctx.role} is not permitted for this endpoint"
        )
