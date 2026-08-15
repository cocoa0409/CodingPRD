"""Accumulation area routes (PRD §3.3)."""
from flask import Blueprint

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import get_actor, require_role
from response import success_object, success_list
from services.common import (get_body, serialize_area, parse_pagination, paginate,
                             get_or_404, require_fields, require_string, require_enum,
                             require_positive_int, AREA_TYPES)

bp = Blueprint("areas", __name__)

READ_ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


@bp.post("/ehs/accumulation-areas")
def create_area():
    _, role = get_actor()
    body = get_body()
    require_role(role, ("EHSAdmin",))
    # Priority 2: full body well-formedness before FK existence (priority 5).
    require_fields(body, ["lab_id", "name", "area_type", "capacity_containers"])
    name = require_string(body, "name")
    area_type = require_enum(body, "area_type", AREA_TYPES)
    capacity = require_positive_int(body, "capacity_containers")
    lab = db.labs.get(body["lab_id"])
    if lab is None:
        raise ApiError(ERR_NOT_FOUND, f"Lab not found: {body['lab_id']}", 404)
    area = {
        "id": db.new_id(),
        "lab_id": lab["id"],
        "name": name,
        "area_type": area_type,
        "capacity_containers": capacity,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.accumulation_areas[area["id"]] = area
    return success_object(serialize_area(area), 201)


@bp.get("/ehs/labs/<lab_id>/accumulation-areas")
def list_lab_areas(lab_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    get_or_404(db.labs, lab_id, "Lab")
    limit, offset = parse_pagination()
    records = [a for a in db.accumulation_areas.values() if a["lab_id"] == lab_id]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_area(a) for a in page], limit, offset, total)
