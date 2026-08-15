"""Auth header extraction, role checking, ownership checks (PRD section 2.1).

Every request carries X-User-ID and X-User-Role. Roles: Insider,
ComplianceOfficer, CommitteeMember, LegalAdmin. Auth requires the headers to
be present and the role recognized; X-User-ID is not otherwise resolved
(LegalAdmin ids are opaque; entity-backed roles are compared by id only).
"""
from flask import g, request

from errors import err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {"Insider", "ComplianceOfficer", "CommitteeMember", "LegalAdmin"}


def authenticate():
    """Runs before every API request. Populates g.user_id / g.user_role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, "missing or malformed X-User-ID / X-User-Role headers")
    g.user_id = uid
    g.user_role = role


def require_roles(*roles):
    if g.user_role not in roles:
        raise err(ERR_UNAUTHORIZED, "caller role is not permitted for this endpoint")


def is_insider():
    return g.user_role == "Insider"


def insider_owns(covered_person_id):
    """An Insider may only act on resources whose covered_person_id equals
    X-User-ID. No-op for other roles."""
    if g.user_role == "Insider" and covered_person_id is not None and g.user_id != covered_person_id:
        raise err(ERR_UNAUTHORIZED, "an Insider may only act on their own resources")


def insider_owns_read(covered_person_id):
    """Insider read scoping: GET of a single person-owned resource."""
    insider_owns(covered_person_id)
