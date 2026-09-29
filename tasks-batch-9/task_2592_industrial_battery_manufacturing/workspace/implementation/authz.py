"""Authentication, RBAC and the acting-worker tiers (PRD 2.1, 2.10 tiers 1-6)."""
import functools

from flask import g, request

from errors import ApiError
from store import db
from validation import pagination, validate_payload

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

PLANT_ADMIN = "PlantAdmin"
DESIGN_ENGINEER = "DesignEngineer"
PRODUCTION_SUPERVISOR = "ProductionSupervisor"
QUALITY_INSPECTOR = "QualityInspector"
SAFETY_OFFICER = "SafetyOfficer"
FLEET_ENGINEER = "FleetEngineer"
WARRANTY_ADMINISTRATOR = "WarrantyAdministrator"

ALL_ROLES = [
    PLANT_ADMIN,
    DESIGN_ENGINEER,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    SAFETY_OFFICER,
    FLEET_ENGINEER,
    WARRANTY_ADMINISTRATOR,
]

# Roles whose X-User-ID must resolve to a Worker row.
ENTITY_BACKED_ROLES = {
    DESIGN_ENGINEER,
    PRODUCTION_SUPERVISOR,
    QUALITY_INSPECTOR,
    SAFETY_OFFICER,
}

JOB_ENGINEER = "ENGINEER"
JOB_PRODUCTION = "PRODUCTION"
JOB_QUALITY = "QUALITY"
JOB_SAFETY = "SAFETY"
JOB_MAINTENANCE = "MAINTENANCE"
JOB_CLASSES = [
    JOB_ENGINEER,
    JOB_PRODUCTION,
    JOB_QUALITY,
    JOB_SAFETY,
    JOB_MAINTENANCE,
]


def _authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "%s header is required" % USER_ID_HEADER)
    if role is None or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED", "%s header is required" % USER_ROLE_HEADER)
    role = role.strip()
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role %s" % role)
    g.user_id = str(user_id).strip()
    g.role = role


def _authorize(roles):
    if g.role not in roles:
        raise ApiError(
            "ERR_ROLE_NOT_PERMITTED",
            "Role %s may not perform this operation" % g.role,
        )


def _resolve_actor():
    g.actor = None
    if g.role not in ENTITY_BACKED_ROLES:
        return
    worker = db.workers.get(g.user_id)
    if worker is None:
        raise ApiError(
            "ERR_ACTING_WORKER_NOT_FOUND",
            "Acting worker %s does not exist" % g.user_id,
        )
    if worker.get("removal_status") != "ACTIVE":
        raise ApiError(
            "ERR_ACTOR_MEDICALLY_REMOVED",
            "Acting worker is medically removed from lead work",
        )
    g.actor = worker


def endpoint(roles, body=None, paginated=False, at_least_one=False, schema_check=None):
    """Wrap a view with tiers 1-5 of the validation ladder, in order.

    `schema_check` is an optional tier-3 continuation (discriminator rules and
    the plate-coherence rule) that must run before tier 4 resolves the actor.
    """

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            _authenticate()
            _authorize(roles)
            if paginated:
                g.limit, g.offset = pagination()
            if body is not None:
                g.body = validate_payload(body, at_least_one=at_least_one)
            else:
                g.body = {}
            if schema_check is not None:
                schema_check(g.body)
            _resolve_actor()
            return view(*args, **kwargs)

        return wrapper

    return decorator


def require_job_class(expected):
    """Tier 6: the three operations that pin the acting worker's job class."""
    actor = getattr(g, "actor", None)
    if actor is None or actor.get("job_class") != expected:
        raise ApiError(
            "ERR_ACTOR_JOB_CLASS_MISMATCH",
            "This operation requires job class %s" % expected,
        )
