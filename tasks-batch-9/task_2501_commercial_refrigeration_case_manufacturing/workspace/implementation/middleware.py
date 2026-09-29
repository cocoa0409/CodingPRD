"""Rank 1 and rank 2 of the evaluation ladder (PRD 2.1 / 2.5)."""

from flask import current_app, g, request

from errors import ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED, fail

ROLES = [
    "PlatformAdmin",
    "DesignEngineer",
    "TestLabTechnician",
    "ComplianceOfficer",
    "SalesEngineer",
    "PlantSupervisor",
    "LogisticsCoordinator",
    "InstallContractor",
    "ServiceManager",
]

ALL_ROLES = list(ROLES)


def roles_required(*allowed):
    """Attach the endpoint's authorised role list to the view function."""
    def decorator(view):
        view.roles_allowed = list(allowed)
        return view
    return decorator


def authenticate():
    if request.url_rule is None:
        return  # unrouted request: let the 404 handler answer
    view = current_app.view_functions.get(request.endpoint)
    allowed = getattr(view, "roles_allowed", None)
    if allowed is None:
        return

    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    # rank 1
    if not user_id or not role or role not in ROLES:
        fail(ERR_UNAUTHENTICATED, "Valid X-User-ID and X-User-Role headers are required")
    # rank 2
    if role not in allowed:
        fail(ERR_UNAUTHORIZED, "Role %s may not call this endpoint" % role)

    g.user_id = user_id
    g.user_role = role


def user_id():
    return getattr(g, "user_id", None)


def user_role():
    return getattr(g, "user_role", None)
