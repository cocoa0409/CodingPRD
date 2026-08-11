"""Auth header extraction, role checking, and request body parsing (PRD 2.1)."""

from flask import request

from errors import err_forbidden, err_unauthenticated, err_validation

ROLES = (
    "SystemAdmin",
    "GrantsOfficer",
    "FinanceManager",
    "ProgramDirector",
    "Funder",
    "Auditor",
)

ALL_READ_ROLES = frozenset(ROLES)
ALLOC_READ_ROLES = frozenset(r for r in ROLES if r != "Funder")


def actor():
    """Authenticate: both headers present and role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err_unauthenticated()
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        raise err_forbidden("Role %s is not authorized for this endpoint" % role)


def body():
    """Parse the JSON request body; empty body becomes {}."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise err_validation("Request body is not valid JSON")
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def check_funder_scope(uid, grant):
    """Funder-scoped action: acting X-User-ID must equal grant.funder_id."""
    if uid != grant["funder_id"]:
        raise err_forbidden("Funder may only act on its own grants")
