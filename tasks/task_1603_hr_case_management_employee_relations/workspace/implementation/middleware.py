"""Auth header extraction and role checking (PRD §2.1, validation priorities 1-3).

X-User-Role names one of ERManager, Investigator, LegalCounsel, HRAnalyst.
X-User-ID is the acting Investigator record's id when the role is Investigator;
for the other three roles it is an opaque operator identifier.
"""
from flask import request

from db import db
from errors import ApiError, raise_error, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {"ERManager", "Investigator", "LegalCounsel", "HRAnalyst"}


class Caller:
    def __init__(self, user_id: str, role: str):
        self.user_id = user_id
        self.role = role


def authorize(allowed_roles) -> Caller:
    """Validation priorities 1-3: role header -> id header -> role permission."""
    role = (request.headers.get("X-User-Role") or "").strip()
    if not role or role not in ROLES:
        raise_error(ERR_UNAUTHENTICATED,
                    "X-User-Role header is missing or does not name a declared role")
    user_id = (request.headers.get("X-User-ID") or "").strip()
    if not user_id:
        raise_error(ERR_UNAUTHENTICATED, "X-User-ID header is missing")
    if role not in allowed_roles:
        raise_error(ERR_UNAUTHORIZED,
                    f"role {role} is not permitted to invoke this endpoint")
    return Caller(user_id, role)


def require_investigator(caller: Caller):
    """Resolve an entity-backed Investigator caller to their Investigator record.

    Investigator X-User-ID is the id of the acting Investigator record; an
    unresolvable identity cannot act as an investigator.
    """
    inv = db["investigators"].get(caller.user_id)
    if inv is None:
        raise_error(ERR_UNAUTHORIZED,
                    "X-User-ID does not resolve to an Investigator record")
    return inv
