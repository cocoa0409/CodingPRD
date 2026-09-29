"""Authentication (step 1) and authorisation (step 2) of the screening ladder."""
import functools

from flask import g, request

import store
from common import (ALL_ROLES, ROLE_AUDITOR, ROLE_BREWER, ROLE_DISPATCH, ROLE_TECH,
                    ROLE_VENUE)
from errors import raise_error

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or str(user_id).strip() == "":
        raise_error("ERR_UNAUTHENTICATED")
    if role is None or str(role).strip() == "":
        raise_error("ERR_UNAUTHENTICATED")
    role = str(role).strip()
    if role not in ALL_ROLES:
        raise_error("ERR_UNAUTHENTICATED")
    g.user_id = str(user_id).strip()
    g.user_role = role


def authorize(allowed_roles):
    if g.user_role not in allowed_roles:
        raise_error("ERR_UNAUTHORIZED")


def guard(*allowed_roles):
    """Decorator running ladder steps 1 and 2 before the handler body."""
    roles = list(allowed_roles)

    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorate


# --------------------------------------------------------- step 6: scope checks

def venue_scope(account_id):
    """ERR_ACCOUNT_SCOPE_VIOLATION guards exactly four venue-manager operations."""
    if g.user_role == ROLE_VENUE and g.user_id != account_id:
        raise_error("ERR_ACCOUNT_SCOPE_VIOLATION")


def technician_assigned(visit):
    """A ServiceTechnician's X-User-ID is the Technician.id they act as."""
    if g.user_role == ROLE_TECH and g.user_id != visit.get("technician_id"):
        raise_error("ERR_TECHNICIAN_NOT_ASSIGNED")


def require_self_technician(technician_id):
    if g.user_id != technician_id:
        raise_error("ERR_TECHNICIAN_NOT_ASSIGNED")


def segregation(escalated_by_user_id):
    if escalated_by_user_id is not None and g.user_id == escalated_by_user_id:
        raise_error("ERR_SEGREGATION_OF_DUTIES")
