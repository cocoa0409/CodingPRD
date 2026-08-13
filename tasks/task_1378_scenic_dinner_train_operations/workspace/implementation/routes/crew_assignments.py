"""Crew assignments: assign ACTIVE members to DRAFT/PUBLISHED excursions with
role match, same-date exclusivity, and certificate validity; RELEASE bumps the
excursion's version."""
from flask import Blueprint, request

import db
from auth import ALL_ROLES, require_roles
from db import new_entity, public, touch
from envelope import success_list, success_obj
from errors import (
    ApiError,
    ERR_CERTIFICATION_EXPIRED,
    ERR_CREW_DATE_CONFLICT,
    ERR_INVALID_REFERENCE,
    ERR_INVALID_STATE,
    ERR_NOT_FOUND,
    ERR_POSITION_ROLE_MISMATCH,
    ERR_VALIDATION,
)
from services.core import CERT_ROLES
from validators import body, paginate, pagination, req_enum, req_str

bp = Blueprint("crew_assignments", __name__)

POSITIONS = ("ENGINEER", "CONDUCTOR", "CAR_HOST", "CHEF", "SERVER", "DOCENT")


def get_assignment_or_404(ca_id):
    ca = db.crew_assignments.get(ca_id)
    if ca is None:
        raise ApiError(ERR_NOT_FOUND, "Crew assignment not found", 404)
    return ca


@bp.post("/railroad/crew-assignments")
def create_crew_assignment():
    require_roles("CrewManager")
    data = body()
    excursion_id = req_str(data, "excursion_id")
    # Tier 4: the excursion must be DRAFT or PUBLISHED.
    exc = db.excursions.get(excursion_id)
    if exc is not None and exc["status"] not in ("DRAFT", "PUBLISHED"):
        raise ApiError(
            ERR_INVALID_STATE,
            "Crew can only be assigned to a DRAFT or PUBLISHED excursion",
            409,
        )
    crew_member_id = req_str(data, "crew_member_id")
    position = req_enum(data, "position", POSITIONS)
    # Tier 7: body FK existence.
    if exc is None:
        raise ApiError(ERR_INVALID_REFERENCE, "excursion_id does not exist", 422)
    member = db.crew_members.get(crew_member_id)
    if member is None:
        raise ApiError(ERR_INVALID_REFERENCE, "crew_member_id does not exist", 422)
    # The member must be ACTIVE.
    if member["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE, "Crew member is not ACTIVE", 409
        )
    # Tier 8d: the assignment position must equal the member's role.
    if position != member["role"]:
        raise ApiError(
            ERR_POSITION_ROLE_MISMATCH,
            "position differs from the member's role",
            422,
        )
    # Tier 9f: one person cannot be in two places on the same service date.
    for ca in db.crew_assignments.values():
        if ca["crew_member_id"] != member["id"] or ca["status"] != "ASSIGNED":
            continue
        if ca["excursion_id"] == exc["id"]:
            continue
        other = db.excursions.get(ca["excursion_id"])
        if other is not None and other["service_date"] == exc["service_date"]:
            raise ApiError(
                ERR_CREW_DATE_CONFLICT,
                "Member is already assigned to another excursion on this "
                "service date",
                409,
            )
    # Tier 9g: certificate must cover the service date.
    if member["role"] in CERT_ROLES and (
        member["cert_expires_on"] is None
        or member["cert_expires_on"] < exc["service_date"]
    ):
        raise ApiError(
            ERR_CERTIFICATION_EXPIRED,
            "cert_expires_on falls before the excursion's service date",
            422,
        )
    ca = new_entity(
        {
            "excursion_id": exc["id"],
            "crew_member_id": member["id"],
            "position": position,
            "status": "ASSIGNED",
        }
    )
    db.crew_assignments[ca["id"]] = ca
    # Every roster change increments the excursion's version.
    touch(exc)
    return success_obj(public(ca), 201)


@bp.get("/railroad/crew-assignments/<cid>")
def get_crew_assignment(cid):
    require_roles(*ALL_ROLES)
    return success_obj(public(get_assignment_or_404(cid)), 200)


@bp.get("/railroad/crew-assignments")
def list_crew_assignments():
    require_roles(*ALL_ROLES)
    items = list(db.crew_assignments.values())
    excursion_id = request.args.get("excursion_id")
    crew_member_id = request.args.get("crew_member_id")
    if excursion_id is not None:
        items = [c for c in items if c["excursion_id"] == excursion_id]
    if crew_member_id is not None:
        items = [c for c in items if c["crew_member_id"] == crew_member_id]
    limit, offset = pagination()
    page, total = paginate(items, limit, offset)
    return success_list([public(c) for c in page], limit, offset, total)


@bp.post("/railroad/crew-assignments/<cid>/events")
def crew_assignment_event(cid):
    require_roles("CrewManager")
    ca = get_assignment_or_404(cid)
    data = body()
    event_type = data.get("event_type")
    if event_type != "RELEASE":
        raise ApiError(ERR_VALIDATION, "Unknown event_type: %r" % event_type, 400)
    if ca["status"] != "ASSIGNED":
        raise ApiError(
            ERR_INVALID_STATE, "Only an ASSIGNED assignment can be released", 409
        )
    ca["status"] = "RELEASED"
    touch(ca)
    exc = db.excursions.get(ca["excursion_id"])
    if exc is not None:
        touch(exc)
    return success_obj(public(ca), 200)
