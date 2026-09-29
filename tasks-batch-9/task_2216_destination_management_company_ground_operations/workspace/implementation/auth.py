"""Authentication and role authorisation (PRD section 2.1)."""

import functools

from flask import g, request

from errors import fail

ROLE_PROGRAM_DIRECTOR = "ProgramDirector"
ROLE_OPS_COORDINATOR = "OperationsCoordinator"
ROLE_SUPPLIER_MANAGER = "SupplierManager"
ROLE_SUPPLIER = "Supplier"
ROLE_CONTROLLER = "Controller"
ROLE_PERMIT_OFFICER = "PermitOfficer"

# The five internal roles ("All DMC roles" in PRD section 4).
ALL_DMC_ROLES = (
    ROLE_PROGRAM_DIRECTOR,
    ROLE_OPS_COORDINATOR,
    ROLE_SUPPLIER_MANAGER,
    ROLE_CONTROLLER,
    ROLE_PERMIT_OFFICER,
)

# Those five plus the external Supplier role ("All roles").
ALL_ROLES = ALL_DMC_ROLES + (ROLE_SUPPLIER,)

VALID_ROLES = frozenset(ALL_ROLES)


def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    user_id = user_id.strip()
    role = role.strip()
    if not user_id or not role or role not in VALID_ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers must be well-formed.")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint." % role)
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def endpoint(roles):
    """Decorator running the band-1/band-2 checks of PRD section 2.9."""

    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate(allowed)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def current_user_id():
    return getattr(g, "user_id", None)


def current_role():
    return getattr(g, "user_role", None)
