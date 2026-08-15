"""Auth header extraction and role checks (PRD 2.1; validation priorities 1-2)."""
import functools

from flask import request

from errors import raise_error

SPONSOR = "SponsorOperator"
COMPLIANCE = "ComplianceOfficer"
AGENT = "TransferAgent"
INVESTOR = "Investor"
ALL_ROLES = (SPONSOR, COMPLIANCE, AGENT, INVESTOR)


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def get_caller() -> Caller:
    """Priority 1: X-User-ID and X-User-Role must be present and well-formed."""
    uid = (request.headers.get("X-User-ID") or "").strip()
    role = (request.headers.get("X-User-Role") or "").strip()
    if not uid or not role or role not in ALL_ROLES:
        raise_error(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and well-formed",
        )
    return Caller(uid, role)


def endpoint(*roles):
    """Decorator: runs auth priority 1 (headers) then priority 2 (role allowed)."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(**path):
            caller = get_caller()
            if caller.role not in roles:
                raise_error(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    f"role {caller.role} is not permitted to invoke this endpoint",
                )
            return fn(caller, **path)

        return wrapper

    return deco
