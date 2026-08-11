"""Auth header extraction, role checking, ownership checks.

Headers (PRD section 2.1): X-User-ID and X-User-Role on every request.
Roles: BenefitsAdmin, ClaimsReviewer, Member, ProviderOperator, Auditor,
PlatformAdmin. Member/ProviderOperator are entity-backed: X-User-ID must
resolve to an existing Member/Provider record.
"""
from flask import g, request

from db import STORE
from errors import err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_FORBIDDEN_OWNERSHIP

ROLES = {"BenefitsAdmin", "ClaimsReviewer", "Member", "ProviderOperator", "Auditor", "PlatformAdmin"}


def authenticate():
    """Runs before every API request. Populates g.user_id / g.user_role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err(ERR_UNAUTHENTICATED, 401, "missing or unrecognized X-User-ID / X-User-Role")
    if role == "Member" and uid not in STORE.members:
        raise err(ERR_UNAUTHENTICATED, 401, "entity-backed X-User-ID does not resolve to a Member")
    if role == "ProviderOperator" and uid not in STORE.providers:
        raise err(ERR_UNAUTHENTICATED, 401, "entity-backed X-User-ID does not resolve to a Provider")
    g.user_id = uid
    g.user_role = role


def require_roles(*roles):
    if g.user_role not in roles:
        raise err(ERR_FORBIDDEN_ROLE, 403, "caller role is not listed for this endpoint")


def is_member():
    return g.user_role == "Member"


def is_provider_operator():
    return g.user_role == "ProviderOperator"


def member_owns(member_id):
    """Member callers may only touch resources whose member_id == X-User-ID."""
    if is_member() and g.user_id != member_id:
        raise err(ERR_FORBIDDEN_OWNERSHIP, 403, "resource is owned by another member")


def provider_owns(provider_id):
    """ProviderOperator callers may only touch visits/claims with provider_id == X-User-ID."""
    if is_provider_operator() and provider_id is not None and g.user_id != provider_id:
        raise err(ERR_FORBIDDEN_OWNERSHIP, 403, "resource is owned by another provider")
