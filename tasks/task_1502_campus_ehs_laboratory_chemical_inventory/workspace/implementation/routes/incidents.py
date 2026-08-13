"""Incident routes (PRD §3.6)."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST
from middleware import get_actor, require_role
from response import success_object, success_list
from services import incident as incident_service
from services.common import (get_body, serialize_incident, parse_pagination, paginate,
                             get_or_404, require_string)

bp = Blueprint("incidents", __name__)

READ_ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


@bp.post("/ehs/incidents")
def create_incident():
    user_id, role = get_actor()
    body = get_body()
    require_role(role, ("LabMember", "PrincipalInvestigator", "EHSAdmin"))
    # Priority 2: full body well-formedness before FK existence (priority 5).
    incident_service.validate_incident_body(body)
    lab = db.labs.get(body["lab_id"])
    if lab is None:
        raise ApiError(ERR_NOT_FOUND, f"Lab not found: {body['lab_id']}", 404)
    incident = incident_service.create_incident(lab, body, user_id)
    return success_object(serialize_incident(incident), 201)


@bp.get("/ehs/labs/<lab_id>/incidents")
def list_lab_incidents(lab_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    get_or_404(db.labs, lab_id, "Lab")
    limit, offset = parse_pagination()
    records = [i for i in db.incidents.values() if i["lab_id"] == lab_id]
    status = request.args.get("status")
    severity = request.args.get("severity")
    if status is not None:
        records = [i for i in records if i["status"] == status]
    if severity is not None:
        records = [i for i in records if i["severity"] == severity]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_incident(i) for i in page], limit, offset, total)


@bp.post("/ehs/incidents/<incident_id>/close")
def close_incident(incident_id):
    _, role = get_actor()
    body = get_body()
    require_role(role, ("EHSAdmin",))
    resolution = require_string(body, "resolution")
    incident = get_or_404(db.incidents, incident_id, "Incident")
    lab = db.labs[incident["lab_id"]]
    incident = incident_service.close(incident, lab, resolution)
    return success_object(serialize_incident(incident))
