"""Registration routes with the system's single OCC point (PRD §3.7, §2.4)."""
from flask import Blueprint, request

import db
from errors import (ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_DUPLICATE_ACTIVE_REGISTRATION, stale_version)
from middleware import get_actor, require_role
from response import success_object, success_list
from services import registration as registration_service
from services.common import (get_body, serialize_registration, parse_pagination,
                             paginate, get_or_404, require_fields, require_enum,
                             require_string, MATERIAL_TYPES, touch)

bp = Blueprint("registrations", __name__)

READ_ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


@bp.post("/ehs/registrations")
def create_registration():
    _, role = get_actor()
    body = get_body()
    require_role(role, ("PrincipalInvestigator", "EHSAdmin"))
    require_fields(body, ["lab_id", "material_type", "registration_number",
                          "expected_lab_version"])
    material_type = require_enum(body, "material_type", MATERIAL_TYPES)
    registration_number = require_string(body, "registration_number")
    expected_lab_version = body.get("expected_lab_version")
    if isinstance(expected_lab_version, bool) or not isinstance(expected_lab_version, int):
        raise ApiError(ERR_INVALID_REQUEST,
                       "expected_lab_version must be an integer", 400)
    lab = db.labs.get(body["lab_id"])
    if lab is None:
        raise ApiError(ERR_NOT_FOUND, f"Lab not found: {body['lab_id']}", 404)

    # OCC (concurrency rule registration-create-stale-lab): the lab's version
    # must match the client-observed expected_lab_version.
    if lab["version"] != expected_lab_version:
        raise stale_version()

    # Priority 13: duplicate-active rule — an ACTIVE or SUSPENDED same-type
    # registration blocks creation outright.
    for reg in db.registrations.values():
        if (reg["lab_id"] == lab["id"] and reg["material_type"] == material_type
                and reg["status"] in ("ACTIVE", "SUSPENDED")):
            raise ApiError(ERR_DUPLICATE_ACTIVE_REGISTRATION,
                           "An ACTIVE or SUSPENDED registration of this material type exists", 409)

    # A PENDING same-type registration is auto-SUPERSEDED.
    for reg in db.registrations.values():
        if (reg["lab_id"] == lab["id"] and reg["material_type"] == material_type
                and reg["status"] == "PENDING"):
            reg["status"] = "SUPERSEDED"
            touch(reg)

    reg = {
        "id": db.new_id(),
        "lab_id": lab["id"],
        "material_type": material_type,
        "registration_number": registration_number,
        "status": "PENDING",
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.registrations[reg["id"]] = reg
    # Creating a registration increments the lab's version by 1.
    touch(lab)
    return success_object(serialize_registration(reg), 201)


@bp.get("/ehs/labs/<lab_id>/registrations")
def list_lab_registrations(lab_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    get_or_404(db.labs, lab_id, "Lab")
    limit, offset = parse_pagination()
    records = [r for r in db.registrations.values() if r["lab_id"] == lab_id]
    status = request.args.get("status")
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_registration(r) for r in page], limit, offset, total)


@bp.post("/ehs/registrations/<registration_id>/activate")
def activate_registration(registration_id):
    _, role = get_actor()
    get_body()
    require_role(role, ("EHSAdmin",))
    reg = get_or_404(db.registrations, registration_id, "Registration")
    registration_service.activate(reg)
    return success_object(serialize_registration(reg))


@bp.post("/ehs/registrations/<registration_id>/suspend")
def suspend_registration(registration_id):
    _, role = get_actor()
    get_body()
    require_role(role, ("EHSAdmin",))
    reg = get_or_404(db.registrations, registration_id, "Registration")
    registration_service.suspend(reg)
    return success_object(serialize_registration(reg))


@bp.post("/ehs/registrations/<registration_id>/surrender")
def surrender_registration(registration_id):
    _, role = get_actor()
    get_body()
    require_role(role, ("EHSAdmin",))
    reg = get_or_404(db.registrations, registration_id, "Registration")
    registration_service.surrender(reg)
    return success_object(serialize_registration(reg))
