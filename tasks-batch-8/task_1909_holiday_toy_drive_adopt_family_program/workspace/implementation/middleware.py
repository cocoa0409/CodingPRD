"""Auth header extraction + role gate per PRD §2.1."""

from functools import wraps

from flask import request

from errors import err_unauthenticated, err_forbidden

ROLES = {"PlatformAdmin", "AgencyCoordinator", "CaseWorker", "Donor", "DistributionVolunteer"}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def current_actor():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise err_unauthenticated()
    if not user_id or not user_id.strip():
        raise err_unauthenticated()
    return Actor(user_id=user_id, role=role)


def require_roles(*roles):
    """Decorator: enforce auth headers then role membership."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor = current_actor()
            if actor.role not in roles:
                raise err_forbidden(
                    "Role %s is not permitted for this endpoint" % actor.role
                )
            return fn(actor, *args, **kwargs)

        return wrapper

    return deco
