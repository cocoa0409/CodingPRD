"""Auth header extraction, role authorization, and participant scoping."""
from flask import request

from errors import ApiError, ERR_AUTH, ERR_FORBIDDEN, ERR_OWNERSHIP

ROLES = ("Trader", "SettlementAnalyst", "CreditOfficer", "IsoOperator")
PARTICIPANT_ROLES = ("Trader", "SettlementAnalyst", "CreditOfficer")
ALL_ROLES = list(ROLES)


class Auth:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def parse_auth():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not isinstance(uid, str) or not uid.strip():
        raise ApiError(ERR_AUTH, 400,
                       "X-User-ID header missing or malformed")
    if role is None or role not in ROLES:
        raise ApiError(ERR_AUTH, 400,
                       "X-User-Role header missing or not a declared role")
    return Auth(uid.strip(), role)


def require_role(auth, roles):
    if auth.role not in roles:
        raise ApiError(ERR_FORBIDDEN, 403,
                       "role %s is not authorized for this endpoint" % auth.role)


def check_ownership(auth, participant_id):
    """Participant-scoped roles may only touch resources owned by their own
    MarketParticipant (X-User-ID). IsoOperator is exempt."""
    if auth.role == "IsoOperator":
        return
    if auth.user_id != participant_id:
        raise ApiError(ERR_OWNERSHIP, 403,
                       "resource belongs to a different market participant")
