"""Authentication and role authorization (PRD §2.1, scaffold validations 1-2).

Identity headers are exactly X-User-ID and X-User-Role. The five declared
roles are RecoveryManager, RepoAgent, Auctioneer, ComplianceOfficer, Borrower.
"""
from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
)

ROLES = {"RecoveryManager", "RepoAgent", "Auctioneer", "ComplianceOfficer", "Borrower"}
ALL_ROLES = ("RecoveryManager", "RepoAgent", "Auctioneer", "ComplianceOfficer", "Borrower")


def require_roles(*allowed):
    """Validate auth headers (401) then endpoint role membership (403).

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing or invalid X-User-Role / X-User-ID headers",
        )
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED,
            403,
            f"Role {role} is not permitted on this endpoint",
        )
    return user_id, role
