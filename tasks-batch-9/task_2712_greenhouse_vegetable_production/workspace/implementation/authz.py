"""Authentication, RBAC and entity-backed actor resolution (PRD 2.1)."""
from functools import wraps

from flask import g, request

from errors import ApiError
from store import db

GROWER_MANAGER = "GrowerManager"
IRRIGATION_TECH = "IrrigationTech"
IPM_SCOUT = "IPMScout"
IPM_COORDINATOR = "IPMCoordinator"
HARVEST_SUPERVISOR = "HarvestSupervisor"
QUALITY_INSPECTOR = "QualityInspector"

ALL_ROLES = (
    GROWER_MANAGER,
    IRRIGATION_TECH,
    IPM_SCOUT,
    IPM_COORDINATOR,
    HARVEST_SUPERVISOR,
    QUALITY_INSPECTOR,
)

# Roles whose X-User-ID must resolve to a Worker carrying a particular skill.
ENTITY_BACKED_SKILL = {
    IPM_SCOUT: "SCOUT",
    IPM_COORDINATOR: "SCOUT",
    HARVEST_SUPERVISOR: "HARVEST",
}


def body():
    if not hasattr(g, "_json_body"):
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = {}
        g._json_body = payload
    return g._json_body


def actor_id():
    return g.user_id


def actor_role():
    return g.role


def resolve_actor():
    """Priority 3 - entity-backed actor resolution."""
    skill = ENTITY_BACKED_SKILL.get(g.role)
    if skill is None:
        return None
    worker = db["workers"].get(g.user_id)
    if worker is None or worker.get("skill") != skill:
        raise ApiError("ERR_ACTOR_NOT_RECOGNIZED")
    g.actor_worker = worker
    return worker


def guard(roles, subroles=None, actor=False):
    """roles     -- roles authorised for the endpoint (priority 2)
    subroles  -- {to_status: (roles,)} sub-action authority, still priority 2
    actor     -- run entity-backed actor resolution (priority 3)
    """
    allowed = tuple(roles)

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            # Priority 1 -- authentication, ahead of path resolution.
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or str(user_id).strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED")
            if role is None or str(role).strip() == "":
                raise ApiError("ERR_UNAUTHENTICATED")
            g.user_id = user_id
            g.role = role
            # Priority 2 -- known role, authorised for this endpoint.
            if role not in ALL_ROLES or role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            if subroles:
                target = body().get("to_status")
                if isinstance(target, str) and target in subroles:
                    if role not in subroles[target]:
                        raise ApiError("ERR_UNAUTHORIZED")
            # Priority 3 -- entity-backed actor resolution.
            if actor:
                resolve_actor()
            return fn(*args, **kwargs)

        return wrapper

    return decorator


READ_ROLES = ALL_ROLES
