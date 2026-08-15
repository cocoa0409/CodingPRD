"""Crew members and volunteers: rostering rules (certificates for
ENGINEER/CONDUCTOR, volunteers limited to DOCENT/CAR_HOST) and the
DEACTIVATE/REACTIVATE events with the assignment-release cascade."""
from flask import Blueprint

import db
from auth import ALL_ROLES, require_roles
from db import new_entity, public, touch
from envelope import success_obj
from errors import (
    ApiError,
    ERR_CERTIFICATION_REQUIRED,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_VALIDATION,
)
from services.core import CERT_ROLES, deactivate_member
from validators import body, opt_date, req_bool, req_enum, req_str

bp = Blueprint("crew_members", __name__)

CREW_ROLES = ("ENGINEER", "CONDUCTOR", "CAR_HOST", "CHEF", "SERVER", "DOCENT")
VOLUNTEER_ROLES = ("DOCENT", "CAR_HOST")


def get_member_or_404(member_id):
    member = db.crew_members.get(member_id)
    if member is None:
        raise ApiError(ERR_NOT_FOUND, "Crew member not found", 404)
    return member


@bp.post("/railroad/crew-members")
def create_member():
    require_roles("CrewManager")
    data = body()
    name = req_str(data, "name")
    role = req_enum(data, "role", CREW_ROLES)
    is_volunteer = req_bool(data, "is_volunteer")
    cert = opt_date(data, "cert_expires_on")
    # Tier 8e: certificate-holding roles must carry cert_expires_on.
    if role in CERT_ROLES and cert is None:
        raise ApiError(
            ERR_CERTIFICATION_REQUIRED,
            "ENGINEER and CONDUCTOR require cert_expires_on",
            422,
        )
    # Tier 8g: cert must be null for the other roles; volunteers are limited
    # to DOCENT or CAR_HOST.
    if role not in CERT_ROLES and cert is not None:
        raise ApiError(
            ERR_VALIDATION,
            "cert_expires_on must be null for this role",
            400,
        )
    if is_volunteer and role not in VOLUNTEER_ROLES:
        raise ApiError(
            ERR_VALIDATION,
            "Volunteers may only hold DOCENT or CAR_HOST roles",
            400,
        )
    member = new_entity(
        {
            "name": name,
            "role": role,
            "is_volunteer": is_volunteer,
            "cert_expires_on": cert,
            "status": "ACTIVE",
        }
    )
    db.crew_members[member["id"]] = member
    return success_obj(public(member), 201)


@bp.get("/railroad/crew-members/<mid>")
def get_member(mid):
    require_roles(*ALL_ROLES)
    return success_obj(public(get_member_or_404(mid)), 200)


@bp.post("/railroad/crew-members/<mid>/events")
def member_event(mid):
    require_roles("CrewManager")
    member = get_member_or_404(mid)
    data = body()
    event_type = data.get("event_type")
    if event_type == "DEACTIVATE":
        if member["status"] != "ACTIVE":
            raise ApiError(
                ERR_INVALID_STATE, "Only an ACTIVE member can be deactivated", 409
            )
        deactivate_member(member)
    elif event_type == "REACTIVATE":
        if member["status"] != "INACTIVE":
            raise ApiError(
                ERR_INVALID_STATE, "Only an INACTIVE member can be reactivated", 409
            )
        member["status"] = "ACTIVE"
        touch(member)
    else:
        raise ApiError(ERR_VALIDATION, "Unknown event_type: %r" % event_type, 400)
    return success_obj(public(member), 200)
