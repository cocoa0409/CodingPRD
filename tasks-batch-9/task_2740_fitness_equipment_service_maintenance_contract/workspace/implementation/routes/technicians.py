"""Technicians and their calendar reservations."""
from flask import Blueprint

import db
import middleware
import response
from errors import ApiError
from services import calc, domain, validate

bp = Blueprint("technicians", __name__)


@bp.post("/fleetcare/technicians")
def create_technician():
    middleware.auth(middleware.CONTRACT_ADMIN, middleware.SERVICE_COORDINATOR)
    body = middleware.body()
    full_name = validate.string(body, "full_name", min_len=1, max_len=80)
    region = validate.region_code(body, "region_code")
    skills = validate.string_list(body, "skill_categories", calc.CATEGORIES,
                                  min_items=1, max_items=4)
    is_inspector = validate.boolean(body, "is_safety_inspector", default=False)
    max_minutes = validate.integer(body, "max_committed_minutes", minimum=1,
                                   required=False, default=480)

    row = db.base_row()
    row.update({
        "full_name": full_name,
        "region_code": region,
        "skill_categories": skills,
        "is_safety_inspector": is_inspector,
        "max_committed_minutes": max_minutes,
        "duty_status": "ON_DUTY",
        "committed_minutes": 0,
    })
    db.technicians[row["id"]] = row
    return response.created_response(row)


@bp.get("/fleetcare/technicians")
def list_technicians():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.technicians, {
        "region_code": response.arg("region_code"),
        "duty_status": response.arg("duty_status"),
        "is_safety_inspector": response.bool_filter("is_safety_inspector"),
    })


@bp.get("/fleetcare/technicians/<technician_id>")
def read_technician(technician_id):
    middleware.auth(*middleware.ALL_ROLES)
    return response.object_response(domain.need_technician(technician_id))


@bp.post("/fleetcare/technicians/<technician_id>/duty-status")
def set_duty_status(technician_id):
    middleware.auth(middleware.CONTRACT_ADMIN, middleware.SERVICE_COORDINATOR)
    technician = domain.need_technician(technician_id)
    body = middleware.body()
    duty_status = validate.enum(body, "duty_status", calc.DUTY_STATUSES)
    # Existing RESERVED / CONFIRMED work is deliberately left untouched.
    db.apply_changes(technician, {"duty_status": duty_status})
    return response.object_response(technician)


@bp.get("/fleetcare/technician-assignments")
def list_assignments():
    middleware.auth(*middleware.ALL_ROLES)
    return response.listing(db.assignments, {
        "technician_id": response.arg("technician_id"),
        "service_call_id": response.arg("service_call_id"),
        "preventive_visit_id": response.arg("preventive_visit_id"),
        "status": response.arg("status"),
    })


@bp.get("/fleetcare/technician-assignments/<assignment_id>")
def read_assignment(assignment_id):
    middleware.auth(*middleware.ALL_ROLES)
    return response.object_response(domain.need_assignment(assignment_id))


@bp.post("/fleetcare/technician-assignments/<assignment_id>/release")
def release_assignment(assignment_id):
    middleware.auth(middleware.SERVICE_COORDINATOR, middleware.CONTRACT_ADMIN)
    assignment = domain.need_assignment(assignment_id)
    body = middleware.body()
    reason = validate.string(body, "reason", min_len=1)
    if assignment["status"] not in calc.HELD_ASSIGNMENT_STATUSES:
        raise ApiError("ERR_ASSIGNMENT_INVALID_STATE")
    domain.release_assignment(assignment, reason)
    return response.object_response(assignment)
