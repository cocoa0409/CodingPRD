"""Authentication, role authorisation and client self-service scope (PRD 2.1)."""
from functools import wraps

from flask import g, request

from errors import (
    ERR_CLIENT_SCOPE_VIOLATION,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    fail,
)
from store import db

RIGHTS_MANAGER = "RightsManager"
COMMERCIAL_MANAGER = "CommercialManager"
COMMERCIAL_DIRECTOR = "CommercialDirector"
CLIENT_SERVICE_AGENT = "ClientServiceAgent"
OPERATIONS_MANAGER = "OperationsManager"
FINANCE_CONTROLLER = "FinanceController"
CLIENT_PORTAL_USER = "ClientPortalUser"

ROLES = (
    RIGHTS_MANAGER,
    COMMERCIAL_MANAGER,
    COMMERCIAL_DIRECTOR,
    CLIENT_SERVICE_AGENT,
    OPERATIONS_MANAGER,
    FINANCE_CONTROLLER,
    CLIENT_PORTAL_USER,
)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        fail(ERR_UNAUTHENTICATED, "X-User-ID header is required.")
    if role is None or role not in ROLES:
        fail(ERR_UNAUTHENTICATED, "X-User-Role header must name one of the seven declared roles.")
    g.user_id = str(user_id)
    g.role = role


def authorize(allowed):
    if g.role not in allowed:
        fail(ERR_UNAUTHORIZED, "Role %s may not call this endpoint." % g.role)


def guard(*allowed):
    """Wrap a view with rejection steps 1 and 2 of the ladder (PRD 2.7)."""

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(allowed)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def is_portal_user():
    return g.role == CLIENT_PORTAL_USER


def portal_client():
    """The acting Client for a ClientPortalUser; 403 when the header names no client."""
    client = db.clients.get(g.user_id)
    if client is None:
        fail(ERR_CLIENT_SCOPE_VIOLATION, "X-User-ID does not identify a known client.")
    return client


def require_own_client_id(client_id):
    if client_id != g.user_id:
        fail(ERR_CLIENT_SCOPE_VIOLATION, "This resource belongs to another client.")


def scope_client_id(client_id):
    """Step 3 of the ladder for the five client-scoped endpoints (PRD 2.1)."""
    if is_portal_user():
        portal_client()
        require_own_client_id(client_id)
