"""Waitlist application endpoints."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_ownership, require_roles
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_APPLICATION_NOT_QUEUED,
    ERR_APPLICATION_NOT_WITHDRAWABLE,
    ERR_AIRPORT_NOT_ACTIVE,
    ERR_NOT_FOUND,
)
from services.core import BASE_POINTS, SIZE_CLASSES, TRANSFER_PRIORITY_BONUS, touch
from validators import body, paginate, pagination, req_bool, req_enum, req_str

bp = Blueprint("applications", __name__)


def get_application_or_404(app_id):
    app = db.applications.get(app_id)
    if app is None:
        raise ApiError(ERR_NOT_FOUND, "Application not found", 404)
    return app


@bp.post("/applications")
def create_application():
    require_roles("Applicant")
    data = body()
    airport_id = req_str(data, "airport_id")
    airport = db.airports.get(airport_id)
    if airport is None:
        raise ApiError(ERR_NOT_FOUND, "Airport not found", 404)
    if airport["status"] != "ACTIVE":
        raise ApiError(ERR_AIRPORT_NOT_ACTIVE, "Airport is SUSPENDED", 409)
    applicant_name = req_str(data, "applicant_name")
    applicant_contact = req_str(data, "applicant_contact")
    size_class_requested = req_enum(data, "size_class_requested", SIZE_CLASSES)
    aircraft_n_number = req_str(data, "aircraft_n_number")
    is_transfer = req_bool(data, "is_based_tenant_transfer")
    app = db.new_entity({
        "airport_id": airport_id,
        "applicant_name": applicant_name,
        "applicant_contact": applicant_contact,
        "size_class_requested": size_class_requested,
        "aircraft_n_number": aircraft_n_number,
        "is_based_tenant_transfer": is_transfer,
        # Score at creation: zero whole days queued yet.
        "priority_score": BASE_POINTS + (TRANSFER_PRIORITY_BONUS if is_transfer else 0),
        "decline_count": 0,
        "status": "QUEUED",
    })
    db.applications[app["id"]] = app
    return success_obj(db.public(app), 201)


@bp.get("/applications")
def list_applications():
    require_roles(*ALL_ROLES)
    items = list(db.applications.values())
    airport_id = request.args.get("airport_id")
    size_class = request.args.get("size_class_requested")
    status = request.args.get("status")
    if airport_id is not None:
        items = [a for a in items if a["airport_id"] == airport_id]
    if size_class is not None:
        items = [a for a in items if a["size_class_requested"] == size_class]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([db.public(a) for a in page], limit, offset, total)


@bp.get("/applications/<aid>")
def get_application(aid):
    require_roles(*ALL_ROLES)
    return success_obj(db.public(get_application_or_404(aid)), 200)


@bp.post("/applications/<aid>/withdraw")
def withdraw_application(aid):
    uid, _role = require_roles("Applicant")
    app = get_application_or_404(aid)
    require_ownership(app["id"], uid)
    if app["status"] not in ("QUEUED", "OFFERED"):
        raise ApiError(ERR_APPLICATION_NOT_WITHDRAWABLE, "Application must be QUEUED or OFFERED to withdraw", 409)
    if app["status"] == "OFFERED":
        for offer in db.offers.values():
            if offer["application_id"] == app["id"] and offer["status"] == "OPEN":
                offer["status"] = "CANCELLED"
                touch(offer)
    app["status"] = "WITHDRAWN"
    touch(app)
    return success_obj(db.public(app), 200)


@bp.post("/applications/<aid>/reject")
def reject_application(aid):
    require_roles("AirportManager")
    app = get_application_or_404(aid)
    if app["status"] != "QUEUED":
        raise ApiError(ERR_APPLICATION_NOT_QUEUED, "Application must be QUEUED to reject", 409)
    app["status"] = "REJECTED"
    touch(app)
    return success_obj(db.public(app), 200)
