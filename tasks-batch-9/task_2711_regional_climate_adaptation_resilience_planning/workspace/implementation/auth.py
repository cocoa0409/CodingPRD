"""Authentication, role recognition, role permission and jurisdictional ownership.

PRD 2.1 and the first three rungs of the ladder in PRD 2.5:
  1. X-User-ID and X-User-Role must both be present and non-empty -> ERR_UNAUTHENTICATED
  2. X-User-Role must name one of the six declared roles -> ERR_UNKNOWN_ROLE
  3. the role must be permitted on the endpoint -> ERR_ROLE_NOT_PERMITTED
Rung 6 (jurisdictional ownership) is applied by the route handlers through
require_owned_jurisdiction() once path/body references have resolved.
"""

from functools import wraps

from flask import g, request

from errors import fail

ROLE_REGIONAL_ADMINISTRATOR = "RegionalAdministrator"
ROLE_HAZARD_ANALYST = "HazardAnalyst"
ROLE_PROJECT_SPONSOR = "ProjectSponsor"
ROLE_BCA_REVIEWER = "BCAReviewer"
ROLE_JURISDICTION_DELEGATE = "JurisdictionDelegate"
ROLE_EQUITY_OFFICER = "EquityOfficer"

ALL_ROLES = (
    ROLE_REGIONAL_ADMINISTRATOR,
    ROLE_HAZARD_ANALYST,
    ROLE_PROJECT_SPONSOR,
    ROLE_BCA_REVIEWER,
    ROLE_JURISDICTION_DELEGATE,
    ROLE_EQUITY_OFFICER,
)

USER_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"


def _authenticate():
    user_id = request.headers.get(USER_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if role is None or str(role).strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-Role header is required.")
    if role not in ALL_ROLES:
        fail("ERR_UNKNOWN_ROLE", "%s is not a recognised role." % role)
    g.user_id = user_id
    g.role = role


def guard(*permitted):
    """Wrap a view with the auth -> role recognition -> role permission ladder."""

    allowed = tuple(permitted) if permitted else ALL_ROLES

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            _authenticate()
            if g.role not in allowed:
                fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not use this endpoint." % g.role)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def acting_user():
    return g.get("user_id")


def acting_role():
    return g.get("role")


def require_owned_jurisdiction(jurisdiction_id, roles=None):
    """Rung 6: the entity-backed roles may only act inside their own jurisdiction.

    ProjectSponsor and JurisdictionDelegate carry the acting Jurisdiction's id in
    X-User-ID; every other role carries an opaque operator identifier that is never
    compared to an entity id.
    """
    scoped = roles if roles is not None else (ROLE_PROJECT_SPONSOR, ROLE_JURISDICTION_DELEGATE)
    if acting_role() not in scoped:
        return
    if jurisdiction_id != acting_user():
        fail(
            "ERR_JURISDICTION_SCOPE_VIOLATION",
            "Caller may only act within its own jurisdiction.",
        )
