"""Authentication and authorisation — PRD §2.1, ladder levels 1 and 2."""

from flask import g, request

from errors import fail

ROLES = (
    "SponsorOperator",
    "ComplianceOfficer",
    "IndependentValuationAdvisor",
    "TransferAgent",
    "BoardCommittee",
    "BrokerDealerRep",
    "InvestorUser",
)


def authenticate():
    """Level 1 — both headers present and the role one of the seven, else 401.
    Runs before any resource lookup."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip():
        fail("ERR_UNAUTHENTICATED")
    if role is None or not role.strip() or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def role():
    return getattr(g, "role", None)


def user_id():
    return getattr(g, "user_id", None)


def require_roles(*allowed):
    """Level 2 — the acting role is listed for the endpoint."""
    if role() not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED")


def require_transition_role(mapping, value):
    """Level 2 — the acting role may drive this particular action/to_status.

    A value that is not a key of the mapping is left alone: either it is an
    unknown enum member (level 3 reports it) or it is a legal status that no
    role may drive from outside (level 7 reports it)."""
    if value is None or not isinstance(value, str):
        return
    allowed = mapping.get(value)
    if allowed is None:
        return
    if role() not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED")
