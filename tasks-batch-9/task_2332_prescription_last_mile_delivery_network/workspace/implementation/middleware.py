"""Authentication, role resolution, scope guards and error rendering."""

import functools

from flask import g, request

from db import db
from errors import ApiError, api_error
import response

ROLE_PHARMACY = "PharmacyOperator"
ROLE_PATIENT = "Patient"
ROLE_COURIER = "Courier"
ROLE_PLAN = "PlanAdministrator"
ROLE_OPS = "NetworkOps"


def resolve_actor():
    """Rung 1 + rung 2 groundwork: the acting id is an ownership claim."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise api_error("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    if user_id in db.pharmacies:
        role = ROLE_PHARMACY
    elif user_id in db.patients:
        role = ROLE_PATIENT
    elif user_id in db.couriers:
        role = ROLE_COURIER
    elif user_id in db.health_plans:
        role = ROLE_PLAN
    else:
        role = ROLE_OPS
    return user_id, role


def require_roles(*roles):
    """Rung 2: the resolved role must appear in the endpoint's authorised list."""
    allowed = set(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = resolve_actor()
            g.user_id = user_id
            g.role = role
            if role not in allowed:
                raise api_error("ERR_UNAUTHORIZED")
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return getattr(g, "user_id", None)


def actor_role():
    return getattr(g, "role", None)


# --------------------------------------------------------------------------
# scope guards (rungs 3 - 6)
# --------------------------------------------------------------------------
def guard_order_scope(order):
    """Rungs 3 and 4 against the PharmacyOrder behind the addressed resource."""
    if order is None:
        return
    role = actor_role()
    if role == ROLE_PHARMACY and order.get("pharmacy_id") != actor_id():
        raise api_error("ERR_PHARMACY_SCOPE_VIOLATION")
    if role == ROLE_PATIENT and order.get("patient_id") != actor_id():
        raise api_error("ERR_PATIENT_SCOPE_VIOLATION")


def guard_plan_scope_on_order(order):
    """Rung 6 against the PharmacyOrder behind the addressed delivery."""
    if order is None:
        return
    if actor_role() == ROLE_PLAN and order.get("health_plan_id") != actor_id():
        raise api_error("ERR_PLAN_SCOPE_VIOLATION")


def guard_plan_scope(health_plan_id):
    if actor_role() == ROLE_PLAN and health_plan_id != actor_id():
        raise api_error("ERR_PLAN_SCOPE_VIOLATION")


def guard_courier_scope(courier_id):
    if actor_role() == ROLE_COURIER and courier_id != actor_id():
        raise api_error("ERR_COURIER_SCOPE_VIOLATION")


# --------------------------------------------------------------------------
# wiring
# --------------------------------------------------------------------------
def install(app):
    @app.before_request
    def authenticate():
        # Rung 1 runs ahead of routing, role resolution and path existence.
        resolve_actor()
        return None

    @app.errorhandler(ApiError)
    def handle_api_error(exc):
        return response.failure(exc.error_id, exc.message, exc.http_status)

    @app.errorhandler(404)
    def handle_not_found(exc):
        return response.failure("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(405)
    def handle_method_not_allowed(exc):
        return response.failure("ERR_NOT_FOUND", "The requested resource does not exist.", 404)

    @app.errorhandler(400)
    def handle_bad_request(exc):
        return response.failure("ERR_INVALID_REQUEST", "The request could not be parsed.", 400)

    @app.errorhandler(Exception)
    def handle_unexpected(exc):
        if isinstance(exc, ApiError):
            return response.failure(exc.error_id, exc.message, exc.http_status)
        app.logger.exception("unhandled error")
        return response.failure("ERR_INVALID_REQUEST", "Unexpected server error: %s" % exc, 400)
