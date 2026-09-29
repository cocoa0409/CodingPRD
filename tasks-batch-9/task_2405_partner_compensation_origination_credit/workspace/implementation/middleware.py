"""Auth header extraction and role admission (PRD 2.1, ladder rungs 1-3)."""
from flask import request

from db import store
from errors import ApiError

ROLES = ("CycleAdmin", "Partner", "CommitteeMember", "CreditArbiter", "AuditObserver")
ENTITY_BACKED = {
    "Partner": None,
    "CommitteeMember": "is_committee_member",
    "CreditArbiter": "is_credit_arbiter",
}


def authorize(allowed_roles):
    """Rung 1 authentication, rung 2 role admission, rung 3 actor resolution."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES or role not in allowed_roles:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    if role in ENTITY_BACKED:
        partner = store.partners.get(user_id)
        if partner is None or partner["status"] == "DEPARTED":
            raise ApiError("ERR_ACTOR_NOT_A_PARTNER")
        flag = ENTITY_BACKED[role]
        if flag is not None and not partner.get(flag):
            raise ApiError("ERR_ACTOR_NOT_A_PARTNER")
    return user_id, role
