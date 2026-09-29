"""Authentication (priority 1), endpoint role membership (priority 2) and
entity-backed ownership (priority 6). PRD 2.1."""
from functools import wraps

from flask import request, g

from errors import fail
from store import db

ROLES = (
    "ProgramAdmin", "RTWCoordinator", "OccHealthNurse", "ClaimAdjuster",
    "TreatingProvider", "Supervisor", "Employee",
)

ENTITY_BACKED = ("TreatingProvider", "Supervisor", "Employee")


def require_roles(*allowed):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                fail("ERR_UNAUTHENTICATED",
                     "X-User-ID and a valid X-User-Role header are required.")
            if role not in allowed:
                fail("ERR_UNAUTHORIZED",
                     "Role %s may not call this endpoint." % role)
            g.user_id = user_id
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def _not_owner():
    fail("ERR_NOT_RESOURCE_OWNER",
         "The acting principal does not own the addressed resource.")


def own_employee_id(employee_id):
    if g.role == "Employee" and g.user_id != employee_id:
        _not_owner()


def own_claim(claim):
    if g.role == "Employee" and g.user_id != claim["employee_id"]:
        _not_owner()


def own_placement(placement):
    if g.role == "Supervisor" and g.user_id != placement["supervisor_id"]:
        _not_owner()
    if g.role == "Employee":
        claim = db.claims.get(placement["claim_id"])
        if not claim or g.user_id != claim["employee_id"]:
            _not_owner()


def own_supervisor_id(supervisor_id):
    if g.role == "Supervisor" and g.user_id != supervisor_id:
        _not_owner()


def own_training_record(record):
    if g.role == "Supervisor" and g.user_id != record["supervisor_id"]:
        _not_owner()


def own_restriction_set(restriction_set):
    if (g.role == "TreatingProvider"
            and g.user_id != restriction_set["treating_provider_id"]):
        _not_owner()


def own_provider_body(treating_provider_id):
    if g.role == "TreatingProvider" and g.user_id != treating_provider_id:
        _not_owner()
