"""Lab routes: CRUD, closeout, decommission."""
from flask import Blueprint

import db
from middleware import get_actor, require_role
from response import success_object, success_list
from services import lab as lab_service
from services.common import (get_body, serialize_lab, parse_pagination, paginate,
                             get_or_404)

bp = Blueprint("labs", __name__)

READ_ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


@bp.post("/ehs/labs")
def create_lab():
    _, role = get_actor()
    body = get_body()
    require_role(role, ("EHSAdmin",))
    lab = lab_service.create_lab(body)
    return success_object(serialize_lab(lab), 201)


@bp.get("/ehs/labs")
def list_labs():
    _, role = get_actor()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination()
    from flask import request
    posture = request.args.get("posture")
    status = request.args.get("status")
    pi_worker_id = request.args.get("pi_worker_id")
    records = list(db.labs.values())
    if posture is not None:
        records = [l for l in records if l["posture"] == posture]
    if status is not None:
        records = [l for l in records if l["status"] == status]
    if pi_worker_id is not None:
        records = [l for l in records if l["pi_worker_id"] == pi_worker_id]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_lab(l) for l in page], limit, offset, total)


@bp.get("/ehs/labs/<lab_id>")
def get_lab(lab_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    lab = get_or_404(db.labs, lab_id, "Lab")
    return success_object(serialize_lab(lab))


@bp.post("/ehs/labs/<lab_id>/closeout")
def closeout_lab(lab_id):
    user_id, role = get_actor()
    get_body()
    require_role(role, ("PrincipalInvestigator", "EHSAdmin"))
    lab = get_or_404(db.labs, lab_id, "Lab")
    lab = lab_service.closeout(lab, user_id, role)
    return success_object(serialize_lab(lab))


@bp.post("/ehs/labs/<lab_id>/decommission")
def decommission_lab(lab_id):
    _, role = get_actor()
    get_body()
    require_role(role, ("EHSAdmin",))
    lab = get_or_404(db.labs, lab_id, "Lab")
    lab = lab_service.decommission(lab)
    return success_object(serialize_lab(lab))
