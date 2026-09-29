"""Authentication, RBAC and ownership-scope enforcement (PRD 2.1 / 2.5)."""

import functools

from flask import g, request

from db import db, touch
from errors import ApiError

ROLE_PROJECT_MANAGER = "ProjectManager"
ROLE_SURVEY_TECHNICIAN = "SurveyTechnician"
ROLE_BUILDING_REPRESENTATIVE = "BuildingRepresentative"
ROLE_AHJ_INSPECTOR = "AHJInspector"
ROLE_SERVICE_MANAGER = "ServiceManager"
ROLE_SYSTEM_OPERATOR = "SystemOperator"

ALL_ROLES = [
    ROLE_PROJECT_MANAGER,
    ROLE_SURVEY_TECHNICIAN,
    ROLE_BUILDING_REPRESENTATIVE,
    ROLE_AHJ_INSPECTOR,
    ROLE_SERVICE_MANAGER,
    ROLE_SYSTEM_OPERATOR,
]
ROLE_SET = set(ALL_ROLES)


def endpoint(roles):
    """Decorator running validation bands 1 and 2 for one route."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_id.strip():
                raise ApiError("ERR_MISSING_AUTH")
            if not user_role or not user_role.strip() or user_role not in ROLE_SET:
                raise ApiError("ERR_MISSING_AUTH")
            if user_role not in roles:
                raise ApiError("ERR_ROLE_NOT_PERMITTED")
            g.user_id = user_id
            g.user_role = user_role
            g.endpoint_roles = roles
            g.project_touched = set()
            return fn(*args, **kwargs)

        return wrapper

    return decorator


# --------------------------------------------------------------------------
# project resolution used by the two entity-backed ownership checks
# --------------------------------------------------------------------------

def project_of_group(group):
    return db.projects.get(group["project_id"]) if group else None


def project_of_car(car):
    return db.projects.get(car["project_id"]) if car else None


def project_of_survey(survey):
    return project_of_car(db.cars.get(survey["car_id"])) if survey else None


def project_of_option(option):
    return project_of_car(db.cars.get(option["car_id"])) if option else None


def project_of_trigger(trigger):
    return project_of_option(db.scope_options.get(trigger["scope_option_id"])) if trigger else None


def project_of_order(order):
    return project_of_option(db.scope_options.get(order["scope_option_id"])) if order else None


def project_of_reservation(reservation):
    if not reservation:
        return None
    return project_of_order(db.procurement_orders.get(reservation["procurement_order_id"]))


def project_of_window(window):
    return project_of_car(db.cars.get(window["car_id"])) if window else None


def project_of_inspection(appointment):
    return project_of_car(db.cars.get(appointment["car_id"])) if appointment else None


def project_of_transition(transition):
    return project_of_car(db.cars.get(transition["car_id"])) if transition else None


def project_of_contract(contract):
    return db.projects.get(contract["project_id"]) if contract else None


def enforce_scope(project):
    """Validation bands 5 and 6.

    ``project`` is the ModernizationProject owning the target resource, or
    None when the target has no owning project (in which case neither
    ownership claim is applicable).
    """
    if project is None:
        return
    roles = getattr(g, "endpoint_roles", ())
    role = getattr(g, "user_role", None)
    user_id = getattr(g, "user_id", None)
    if role == ROLE_BUILDING_REPRESENTATIVE and ROLE_BUILDING_REPRESENTATIVE in roles:
        if project["id"] != user_id:
            raise ApiError("ERR_PROJECT_SCOPE_MISMATCH")
    if role == ROLE_AHJ_INSPECTOR and ROLE_AHJ_INSPECTOR in roles:
        if project.get("jurisdiction_id") != user_id:
            raise ApiError("ERR_JURISDICTION_SCOPE_MISMATCH")


def scope_filter(rows, project_resolver):
    """List reads by the two entity-backed roles are scoped to their own rows."""
    role = getattr(g, "user_role", None)
    user_id = getattr(g, "user_id", None)
    if project_resolver is None:
        return rows
    if role == ROLE_BUILDING_REPRESENTATIVE:
        kept = []
        for row in rows:
            owner = project_resolver(row)
            if owner is None or owner["id"] == user_id:
                kept.append(row)
        return kept
    if role == ROLE_AHJ_INSPECTOR:
        kept = []
        for row in rows:
            owner = project_resolver(row)
            if owner is None or owner.get("jurisdiction_id") == user_id:
                kept.append(row)
        return kept
    return rows


def touch_project(project):
    """Bump the project row once per request, however many children moved."""
    if project is None:
        return
    seen = getattr(g, "project_touched", None)
    if seen is None:
        seen = set()
        g.project_touched = seen
    if project["id"] in seen:
        return
    seen.add(project["id"])
    touch(project)
