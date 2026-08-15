"""Auth header extraction and role checking (PRD section 2.1).

Headers: X-User-ID and X-User-Role. Identity semantics:
- CarrierUnderwriter: X-User-ID is the acting Carrier's id (entity-backed).
- TPAAdjuster: X-User-ID is the acting TPA's id (entity-backed).
- PlatformAdmin / MGAUnderwriter / MGAFinance / CarrierAuditor: opaque.
"""
from flask import g, request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PlatformAdmin",
    "MGAUnderwriter",
    "MGAFinance",
    "CarrierUnderwriter",
    "CarrierAuditor",
    "TPAAdjuster",
}

ALL_ROLES = sorted(ROLES)


def authenticate():
    """Pipeline stage 1: header presence + recognized role."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED[0],
            ERR_UNAUTHENTICATED[1],
            "X-User-ID and X-User-Role headers are required and the role must be one of the declared roles.",
        )
    g.user_id = user_id
    g.user_role = role


def require_roles(*roles):
    """Pipeline stage 2: endpoint-level role permission."""
    if g.user_role not in roles:
        raise ApiError(
            ERR_FORBIDDEN[0],
            ERR_FORBIDDEN[1],
            "Role %s is not permitted to perform this operation." % g.user_role,
        )


def require_carrier_owner(program):
    """Entity-backed ownership: the acting CarrierUnderwriter must be the
    carrier that granted the program."""
    if g.user_id != program["carrier_id"]:
        raise ApiError(
            ERR_FORBIDDEN[0],
            ERR_FORBIDDEN[1],
            "X-User-ID does not match the program's carrier_id.",
        )


def require_tpa_owner(claim):
    """Entity-backed ownership: the acting TPAAdjuster must be the claim's
    assigned TPA."""
    if g.user_id != claim["assigned_tpa_id"]:
        raise ApiError(
            ERR_FORBIDDEN[0],
            ERR_FORBIDDEN[1],
            "X-User-ID does not match the claim's assigned_tpa_id.",
        )
