"""Identity, roles and access control (PRD 2.1)."""
import functools

from flask import g, request

from errors import ApiError

ROLE_CIRCULATION_MANAGER = "CirculationManager"
ROLE_QUALIFICATION_SPECIALIST = "QualificationSpecialist"
ROLE_CIRCULATION_AUDITOR = "CirculationAuditor"
ROLE_PUBLISHER_EXECUTIVE = "PublisherExecutive"
ROLE_ADVERTISER_CONTACT = "AdvertiserContact"

ALL_ROLES = (
    ROLE_CIRCULATION_MANAGER,
    ROLE_QUALIFICATION_SPECIALIST,
    ROLE_CIRCULATION_AUDITOR,
    ROLE_PUBLISHER_EXECUTIVE,
    ROLE_ADVERTISER_CONTACT,
)

OPERATOR_ROLES = (
    ROLE_CIRCULATION_MANAGER,
    ROLE_QUALIFICATION_SPECIALIST,
    ROLE_CIRCULATION_AUDITOR,
    ROLE_PUBLISHER_EXECUTIVE,
)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required.")
    if not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header must name one of the five declared roles.")
    g.user_id = str(user_id)
    g.user_role = role


def authorize(roles):
    if g.user_role not in roles:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s is not authorised for this endpoint." % g.user_role,
        )


def endpoint(*roles):
    """Decorator enforcing precedence steps 1 and 2 of PRD 2.12."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def current_user():
    return g.user_id


def current_role():
    return g.user_role
