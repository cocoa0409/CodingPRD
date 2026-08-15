"""Volunteer endpoints."""

from flask import Blueprint
from db import db
from middleware import require_roles
from validate import get_body, req_string, opt_string, opt_enum
from response import success_object
from errors import not_found, invalid_state, ApiError

bp = Blueprint("volunteers", __name__)


def volunteer_view(v):
    return {k: v for k, v in v.items() if not k.startswith("_")}


def get_volunteer_or_404(volunteer_id):
    v = db.volunteers.get(volunteer_id)
    if v is None:
        raise not_found("Volunteer not found.")
    return v


@bp.post("/api/volunteers")
def create_volunteer():
    require_roles("ProgramAdmin")
    body = get_body()
    email = req_string(body, "email")
    full_name = req_string(body, "full_name")
    for v in db.volunteers.values():
        if v["email"] == email:
            raise ApiError("ERR_DUPLICATE_LOT_CODE", 409,
                           "A volunteer with this email already exists.")
    vol = {"email": email, "full_name": full_name, "status": "APPLIED"}
    db.stamp_new(vol)
    db.volunteers[vol["id"]] = vol
    return success_object(volunteer_view(vol), 201)


@bp.get("/api/volunteers/<volunteer_id>")
def get_volunteer(volunteer_id):
    require_roles("ProgramAdmin", "Volunteer")
    v = get_volunteer_or_404(volunteer_id)
    return success_object(volunteer_view(v))


@bp.post("/api/volunteers/<volunteer_id>/approve")
def approve_volunteer(volunteer_id):
    require_roles("ProgramAdmin")
    v = get_volunteer_or_404(volunteer_id)
    if v["status"] != "APPLIED":
        raise invalid_state("Only an APPLIED volunteer can be approved.")
    v["status"] = "ACTIVE"
    db.touch(v)
    return success_object(volunteer_view(v))


@bp.patch("/api/volunteers/<volunteer_id>")
def patch_volunteer(volunteer_id):
    require_roles("ProgramAdmin")
    v = get_volunteer_or_404(volunteer_id)
    body = get_body()
    full_name = opt_string(body, "full_name")
    new_status = opt_enum(body, "status", {"ACTIVE", "INACTIVE"}, default=None)
    if new_status is not None and new_status != v["status"]:
        if v["status"] == "ACTIVE" and new_status == "INACTIVE":
            for a in db.assignments.values():
                if a["volunteer_id"] == v["id"] and a["status"] == "SIGNUP":
                    raise invalid_state(
                        "Volunteer holds a live SIGNUP assignment.")
            v["status"] = "INACTIVE"
        elif v["status"] == "INACTIVE" and new_status == "ACTIVE":
            v["status"] = "ACTIVE"
        elif v["status"] == "APPLIED" and new_status == "ACTIVE":
            # not a declared transition (approve endpoint handles APPLIED->ACTIVE)
            raise invalid_state("Use approve endpoint for APPLIED -> ACTIVE.")
        else:
            raise invalid_state("Unsupported volunteer status transition.")
    if full_name is not None:
        v["full_name"] = full_name
    db.touch(v)
    return success_object(volunteer_view(v))
