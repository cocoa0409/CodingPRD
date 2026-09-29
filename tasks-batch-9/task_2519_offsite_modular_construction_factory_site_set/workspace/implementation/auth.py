"""Authentication, role authorisation and entity-backed ownership.

Ladder positions implemented here:
  1  ERR_UNAUTHENTICATED     — headers present, role is a declared role
  2  ERR_ROLE_NOT_PERMITTED  — role appears in the endpoint's roles list
  6  ERR_ACTOR_NOT_OWNER     — entity_backed callers act only on their aggregate
"""

import functools

from flask import g, request

from errors import ApiError
from store import ROLES

# §1.7 identity column: three roles are entity_backed, seven are opaque.
ENTITY_BACKED = {
    "FactoryProductionManager": "Factory",
    "ThirdPartyInspector": "InspectionAgency",
    "SiteSuperintendent": "Project",
}


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID header is required")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-Role header is missing or unknown")
    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(*allowed_roles):
    """Runs ladder rank 1 then rank 2 before the handler body executes."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed_roles:
                raise ApiError(
                    "ERR_ROLE_NOT_PERMITTED",
                    "role %s may not call this endpoint" % role,
                )
            return view(*args, **kwargs)

        return wrapper

    return decorator


def user_id():
    return g.get("user_id")


def role():
    return g.get("role")


def _deny(detail):
    raise ApiError("ERR_ACTOR_NOT_OWNER", detail)


def own_factory_of(project):
    """FactoryProductionManager's X-User-ID must equal project.factory_id."""
    if role() == "FactoryProductionManager" and user_id() != project["factory_id"]:
        _deny("caller is not the plant that manufactures this project")


def own_project(project):
    """SiteSuperintendent's X-User-ID must equal the project id."""
    if role() == "SiteSuperintendent" and user_id() != project["id"]:
        _deny("caller is not the superintendent of this project")


def own_agency(agency_id):
    """ThirdPartyInspector's X-User-ID must equal the agency it records under."""
    if role() == "ThirdPartyInspector" and user_id() != agency_id:
        _deny("caller is not the agency recording this inspection")
