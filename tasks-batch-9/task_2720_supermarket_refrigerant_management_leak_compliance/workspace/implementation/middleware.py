"""Authentication and role authorization (PRD 2.1)."""
import functools

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PLATFORM_ADMIN = "PlatformAdmin"
COMPLIANCE_MANAGER = "ComplianceManager"
TECHNICIAN = "Technician"
STORE_MANAGER = "StoreManager"
REGULATOR = "Regulator"

ALL_ROLES = (
    PLATFORM_ADMIN,
    COMPLIANCE_MANAGER,
    TECHNICIAN,
    STORE_MANAGER,
    REGULATOR,
)


def _authenticate(allowed_roles, header_exempt):
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if header_exempt:
        # PRD 2.4: the clock endpoint is the only operation exempt from the
        # header requirements of 2.1. A role that IS presented still has to be
        # allowed to call the endpoint.
        if role is not None and role.strip() != "" and role not in allowed_roles:
            raise ApiError("ERR_FORBIDDEN_ROLE")
        g.user_id = user_id
        g.user_role = role
        return
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "" or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    g.user_id = user_id
    g.user_role = role


def endpoint(roles, header_exempt=False):
    """Decorator enforcing validation priorities 1 (auth) and 2 (authorization)."""
    allowed = tuple(roles)

    def decorate(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            _authenticate(allowed, header_exempt)
            return view(*args, **kwargs)
        return wrapper
    return decorate


def read_endpoint(view):
    """All five roles may perform every read (subject to store scoping)."""
    return endpoint(ALL_ROLES)(view)


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "user_role", None)


def require_technician_identity(technician_id):
    """Validation priority 6: the Technician's X-User-ID is the entity id."""
    if current_role() == TECHNICIAN and current_user_id() != technician_id:
        raise ApiError("ERR_TECHNICIAN_IDENTITY_MISMATCH")


def require_store_scope(store_id):
    """Validation priority 7: a StoreManager's X-User-ID is the Store id."""
    if current_role() == STORE_MANAGER and current_user_id() != store_id:
        raise ApiError("ERR_STORE_SCOPE_VIOLATION")
