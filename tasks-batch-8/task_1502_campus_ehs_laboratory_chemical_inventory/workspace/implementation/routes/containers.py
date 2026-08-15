"""Container routes: register, list, get, tag-waste, untag-waste."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import get_actor, require_role
from response import success_object, success_list
from services import container as container_service
from services.common import (get_body, serialize_container, parse_pagination,
                             paginate, get_or_404)

bp = Blueprint("containers", __name__)

READ_ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


@bp.post("/ehs/containers")
def create_container():
    user_id, role = get_actor()
    body = get_body()
    require_role(role, ("PrincipalInvestigator", "LabMember"))
    # Priority 2: body well-formedness (all fields validated before FK
    # existence at priority 5).
    container_service.validate_container_body(body)
    lab = db.labs.get(body["lab_id"])
    if lab is None:
        raise ApiError(ERR_NOT_FOUND, f"Lab not found: {body['lab_id']}", 404)
    container = container_service.create_container(lab, body)
    return success_object(serialize_container(container), 201)


@bp.get("/ehs/containers")
def list_containers():
    _, role = get_actor()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.containers.values())
    lab_id = request.args.get("lab_id")
    area_id = request.args.get("accumulation_area_id")
    pickup_id = request.args.get("pickup_request_id")
    state = request.args.get("state")
    hazard = request.args.get("hazard_class")
    if lab_id is not None:
        records = [c for c in records if c["lab_id"] == lab_id]
    if area_id is not None:
        records = [c for c in records if c["accumulation_area_id"] == area_id]
    if pickup_id is not None:
        records = [c for c in records if c["pickup_request_id"] == pickup_id]
    if state is not None:
        records = [c for c in records if c["state"] == state]
    if hazard is not None:
        records = [c for c in records if c["hazard_class"] == hazard]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_container(c) for c in page], limit, offset, total)


@bp.get("/ehs/containers/<container_id>")
def get_container(container_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    container = get_or_404(db.containers, container_id, "Container")
    return success_object(serialize_container(container))


@bp.post("/ehs/containers/<container_id>/tag-waste")
def tag_waste(container_id):
    user_id, role = get_actor()
    body = get_body()
    require_role(role, ("PrincipalInvestigator", "LabMember"))
    # Priority 2: body well-formedness before existence checks (priority 5).
    area_id = body.get("accumulation_area_id")
    if area_id is None:
        raise ApiError(ERR_INVALID_REQUEST, "Missing required field: accumulation_area_id", 400)
    # Priority 5: path id first, then body FK.
    container = get_or_404(db.containers, container_id, "Container")
    area = db.accumulation_areas.get(area_id)
    if area is None:
        raise ApiError(ERR_NOT_FOUND, f"AccumulationArea not found: {area_id}", 404)
    lab = db.labs[container["lab_id"]]
    container = container_service.tag_waste(container, lab, area, user_id)
    return success_object(serialize_container(container))


@bp.post("/ehs/containers/<container_id>/untag-waste")
def untag_waste(container_id):
    user_id, role = get_actor()
    get_body()
    require_role(role, ("PrincipalInvestigator", "LabMember"))
    container = get_or_404(db.containers, container_id, "Container")
    lab = db.labs[container["lab_id"]]
    container = container_service.untag_waste(container, lab)
    return success_object(serialize_container(container))
