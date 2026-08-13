"""Inspection routes (PRD §3.5)."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import get_actor, require_role
from response import success_object, success_list
from services import inspection as inspection_service
from services.common import (get_body, serialize_inspection, parse_pagination,
                             paginate, get_or_404, serialize_corrective_action)

bp = Blueprint("inspections", __name__)

READ_ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


@bp.post("/ehs/inspections")
def create_inspection():
    _, role = get_actor()
    body = get_body()
    require_role(role, ("EHSAdmin",))
    # Priority 2: full body well-formedness before FK existence (priority 5).
    inspection_service.validate_inspection_body(body)
    lab = db.labs.get(body["lab_id"])
    if lab is None:
        raise ApiError(ERR_NOT_FOUND, f"Lab not found: {body['lab_id']}", 404)
    insp = inspection_service.create_inspection(lab, body)
    return success_object(serialize_inspection(insp), 201)


@bp.get("/ehs/inspections")
def list_inspections():
    _, role = get_actor()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    records = list(db.inspections.values())
    lab_id = request.args.get("lab_id")
    inspector_id = request.args.get("inspector_id")
    status = request.args.get("status")
    if lab_id is not None:
        records = [i for i in records if i["lab_id"] == lab_id]
    if inspector_id is not None:
        records = [i for i in records if i["inspector_id"] == inspector_id]
    if status is not None:
        records = [i for i in records if i["status"] == status]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_inspection(i) for i in page], limit, offset, total)


@bp.get("/ehs/inspections/<inspection_id>")
def get_inspection(inspection_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    insp = get_or_404(db.inspections, inspection_id, "LabInspection")
    return success_object(serialize_inspection(insp))


@bp.post("/ehs/inspections/<inspection_id>/complete")
def complete_inspection(inspection_id):
    user_id, role = get_actor()
    body = get_body()
    require_role(role, ("EHSInspector",))
    findings = inspection_service.validate_findings(body)
    insp = get_or_404(db.inspections, inspection_id, "LabInspection")
    lab = db.labs[insp["lab_id"]]
    insp = inspection_service.complete_inspection(insp, lab, user_id, findings)
    return success_object(serialize_inspection(insp))


@bp.get("/ehs/inspections/<inspection_id>/corrective-actions")
def list_inspection_corrective_actions(inspection_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    get_or_404(db.inspections, inspection_id, "LabInspection")
    limit, offset = parse_pagination()
    records = [ca for ca in db.corrective_actions.values()
               if ca["inspection_id"] == inspection_id]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_corrective_action(ca) for ca in page],
                        limit, offset, total)
