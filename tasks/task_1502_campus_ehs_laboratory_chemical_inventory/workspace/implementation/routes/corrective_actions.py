"""Corrective-action routes (PRD §3.5)."""
from flask import Blueprint, request

import db
from middleware import get_actor, require_role
from response import success_object, success_list
from services import corrective_action as ca_service
from services.common import (get_body, serialize_corrective_action, parse_pagination,
                             paginate, get_or_404, require_string)

bp = Blueprint("corrective_actions", __name__)

READ_ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


@bp.get("/ehs/labs/<lab_id>/corrective-actions")
def list_lab_corrective_actions(lab_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    get_or_404(db.labs, lab_id, "Lab")
    limit, offset = parse_pagination()
    records = [ca for ca in db.corrective_actions.values() if ca["lab_id"] == lab_id]
    status = request.args.get("status")
    if status is not None:
        records = [ca for ca in records if ca["status"] == status]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_corrective_action(ca) for ca in page],
                        limit, offset, total)


@bp.post("/ehs/corrective-actions/<ca_id>/submit")
def submit_corrective_action(ca_id):
    user_id, role = get_actor()
    body = get_body()
    require_role(role, ("PrincipalInvestigator",))
    resolution_note = require_string(body, "resolution_note")
    ca = get_or_404(db.corrective_actions, ca_id, "CorrectiveAction")
    lab = db.labs[ca["lab_id"]]
    ca = ca_service.submit(ca, lab, user_id, resolution_note)
    return success_object(serialize_corrective_action(ca))


@bp.post("/ehs/corrective-actions/<ca_id>/verify")
def verify_corrective_action(ca_id):
    user_id, role = get_actor()
    body = get_body()
    require_role(role, ("EHSInspector",))
    decision = ca_service.validate_decision(body)
    ca = get_or_404(db.corrective_actions, ca_id, "CorrectiveAction")
    lab = db.labs[ca["lab_id"]]
    inspection = db.inspections[ca["inspection_id"]]
    ca = ca_service.verify(ca, lab, inspection, user_id, decision)
    return success_object(serialize_corrective_action(ca))
