"""Authentication, role checks and segregation of duties (PRD sections 2.1, 2.7)."""

import functools

from flask import g, request

from errors import fail

SIGNAL_OPS_ADMIN = "SignalOpsAdmin"
TIMING_ENGINEER = "TimingEngineer"
CERTIFYING_ENGINEER = "CertifyingEngineer"
FIELD_TECHNICIAN = "FieldTechnician"
CITIZEN_LIAISON = "CitizenLiaison"
PUBLIC_REQUESTER = "PublicRequester"

ALL_ROLES = (
    SIGNAL_OPS_ADMIN,
    TIMING_ENGINEER,
    CERTIFYING_ENGINEER,
    FIELD_TECHNICIAN,
    CITIZEN_LIAISON,
    PUBLIC_REQUESTER,
)

# "every operational GET under /signal-ops" -- the five staff roles.
STAFF = (
    SIGNAL_OPS_ADMIN,
    TIMING_ENGINEER,
    CERTIFYING_ENGINEER,
    FIELD_TECHNICIAN,
    CITIZEN_LIAISON,
)


def authenticate():
    """Rungs 1 and 2 of the validation ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED")
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED")
    role = role.strip()
    if role not in ALL_ROLES:
        fail("ERR_UNKNOWN_ROLE")
    g.user_id = str(user_id).strip()
    g.role = role
    return g.user_id, g.role


def roles(*allowed):
    """Decorator: authenticate, then rung 3 (role authorised for the endpoint)."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            authenticate()
            if g.role not in allowed:
                fail("ERR_ROLE_NOT_PERMITTED")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def user_id():
    return g.user_id


def role():
    return g.role


def segregation(authoring_user_id):
    """Rung 4.  Refuse when the acting user authored the artefact under review."""
    if authoring_user_id is not None and user_id() == authoring_user_id:
        fail("ERR_SEGREGATION_OF_DUTIES")


def require_owner(owner_requester_id):
    """Rung 5.  A PublicRequester may only act on their own requester row."""
    if role() == PUBLIC_REQUESTER and owner_requester_id != user_id():
        fail("ERR_NOT_RESOURCE_OWNER")
