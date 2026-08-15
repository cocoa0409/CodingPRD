"""Authentication & authorization helpers (PRD §2.1).

Headers: X-User-ID and X-User-Role. Five roles: FacilityAdmin, CoreStaff,
FinanceOfficer (opaque operator ids) and Researcher, ExternalClient
(entity-backed: X-User-ID must reference an existing User).
"""

from flask import request, g

from errors import fail
from store import store

ROLES = {"FacilityAdmin", "CoreStaff", "FinanceOfficer", "Researcher", "ExternalClient"}
ENTITY_ROLES = {"Researcher", "ExternalClient"}
OPAQUE_ROLES = {"FacilityAdmin", "CoreStaff", "FinanceOfficer"}


def authenticate():
    """Priority 1: headers present, role recognized, entity-backed id resolves."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not isinstance(uid, str) or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role headers")
    user = None
    if role in ENTITY_ROLES:
        user = store.users.get(uid)
        if user is None:
            fail("ERR_UNAUTHENTICATED", "X-User-ID does not reference an existing user")
    g.auth_id = uid
    g.auth_role = role
    g.auth_user = user
    return uid, role, user


def auth_id():
    return g.auth_id


def auth_role():
    return g.auth_role


def auth_user():
    return g.auth_user


def require_roles(*roles):
    """Priority 2 (first half): role must be listed for the endpoint."""
    if g.auth_role not in roles:
        fail("ERR_FORBIDDEN", "Role %s is not permitted on this endpoint" % g.auth_role)


def is_entity_role():
    return g.auth_role in ENTITY_ROLES


def check_create_ownership(body):
    """Priority 2 (second half): entity-backed callers may only create
    resources whose user_id equals their own X-User-ID. Skipped when the
    body does not carry a (parseable) user_id — format validation reports
    the missing field later at its own priority."""
    if is_entity_role():
        uid = body.get("user_id") if isinstance(body, dict) else None
        if uid is not None and uid != g.auth_id:
            fail("ERR_FORBIDDEN", "Entity-backed callers may only create resources for themselves")


def check_resource_ownership(resource_user_id):
    """Entity-backed callers may only read/mutate their own resources."""
    if is_entity_role() and resource_user_id != g.auth_id:
        fail("ERR_FORBIDDEN", "Entity-backed callers may only access their own resources")
