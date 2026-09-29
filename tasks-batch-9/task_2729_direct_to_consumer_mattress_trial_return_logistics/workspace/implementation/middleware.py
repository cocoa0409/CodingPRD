"""Authentication, role authorisation and ownership."""
import functools

from flask import g, request

from errors import api_error

ROLES = (
    "Customer",
    "RetailPartner",
    "TrialSupportAgent",
    "LogisticsCoordinator",
    "FinanceController",
    "PlatformAdmin",
)

# The two entity-backed roles: their X-User-ID is the id of a stored record.
ENTITY_ROLES = ("Customer", "RetailPartner")


def require(*roles):
    """Every request must carry X-User-ID and X-User-Role; the role must be one
    of the six declared roles and must be permitted on this endpoint."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise api_error(
                    "ERR_UNAUTHENTICATED",
                    "Authentication required: X-User-ID and a recognised "
                    "X-User-Role must be supplied",
                )
            if role not in roles:
                raise api_error(
                    "ERR_UNAUTHORIZED",
                    "Role %s may not perform this operation" % role,
                )
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def acting_role():
    return getattr(g, "role", None)


def acting_user_id():
    return getattr(g, "user_id", None)


def deny_not_owner(what="resource"):
    raise api_error(
        "ERR_NOT_OWNER",
        "Caller does not own this %s" % what,
    )


def require_customer_owner(customer_id, what="resource"):
    """Ownership only constrains the entity-backed Customer role; the four
    opaque operator roles are unconstrained on these endpoints."""
    if acting_role() == "Customer" and acting_user_id() != customer_id:
        deny_not_owner(what)


def require_partner_owner(partner_id, what="resource"):
    if acting_role() == "RetailPartner" and acting_user_id() != partner_id:
        deny_not_owner(what)
