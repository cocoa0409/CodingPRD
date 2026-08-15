"""Auth header extraction, role checks, Investor ownership scoping (PRD 2.1)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = {"FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager", "Investor"}
STAFF_ROLES = {"FundAdmin", "ComplianceOfficer", "TransferAgent", "PortfolioManager"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role

    @property
    def is_investor(self) -> bool:
        return self.role == "Investor"


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role present and well-formed."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-ID and X-User-Role headers must be present and well-formed")
    return Caller(user_id, role)


def require_roles(*roles) -> Caller:
    """Priorities 1-2: authentication then role authorization."""
    caller = get_caller()
    if caller.role not in roles:
        raise_error(ERR_FORBIDDEN,
                    f"role {caller.role} is not authorized for this endpoint")
    return caller


def check_investor_owns(caller: Caller, investor_id):
    """Investor callers may only act on their own records (ERR_FORBIDDEN)."""
    if caller.is_investor and caller.user_id != investor_id:
        raise_error(ERR_FORBIDDEN,
                    "Investor callers may only access their own resources")
