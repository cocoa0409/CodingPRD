"""Training assignment routes (PRD §3.1)."""
from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import get_actor, require_role
from response import success_object, success_list
from services import training as training_service
from services.common import (get_body, serialize_training, parse_pagination, paginate,
                             get_or_404, require_fields, require_enum, require_datetime,
                             HAZARD_CLASSES)

bp = Blueprint("training", __name__)

READ_ROLES = ("EHSAdmin", "EHSInspector", "PrincipalInvestigator", "LabMember")


@bp.post("/ehs/training-assignments")
def create_training():
    _, role = get_actor()
    body = get_body()
    require_role(role, ("EHSAdmin", "PrincipalInvestigator"))
    require_fields(body, ["lab_id", "worker_id", "hazard_class", "due_date"])
    hazard_class = require_enum(body, "hazard_class", HAZARD_CLASSES)
    due_date = require_datetime(body, "due_date")
    lab = db.labs.get(body["lab_id"])
    if lab is None:
        raise ApiError(ERR_NOT_FOUND, f"Lab not found: {body['lab_id']}", 404)
    worker = db.workers.get(body["worker_id"])
    if worker is None:
        raise ApiError(ERR_NOT_FOUND, f"Worker not found: {body['worker_id']}", 404)
    assignment = {
        "id": db.new_id(),
        "lab_id": lab["id"],
        "worker_id": worker["id"],
        "hazard_class": hazard_class,
        "status": "ASSIGNED",
        "due_date": due_date,
        "completed_at": None,
        "created_at": db.now(),
        "updated_at": db.now(),
        "version": 1,
        "_seq": db.next_seq(),
    }
    db.training_assignments[assignment["id"]] = assignment
    return success_object(serialize_training(assignment), 201)


@bp.get("/ehs/labs/<lab_id>/training-assignments")
def list_lab_training(lab_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    get_or_404(db.labs, lab_id, "Lab")
    limit, offset = parse_pagination()
    records = [t for t in db.training_assignments.values() if t["lab_id"] == lab_id]
    status = request.args.get("status")
    if status is not None:
        records = [t for t in records if t["status"] == status]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_training(t) for t in page], limit, offset, total)


@bp.get("/ehs/workers/<worker_id>/training-assignments")
def list_worker_training(worker_id):
    _, role = get_actor()
    require_role(role, READ_ROLES)
    get_or_404(db.workers, worker_id, "Worker")
    limit, offset = parse_pagination()
    records = [t for t in db.training_assignments.values() if t["worker_id"] == worker_id]
    status = request.args.get("status")
    if status is not None:
        records = [t for t in records if t["status"] == status]
    page, total = paginate(records, limit, offset)
    return success_list([serialize_training(t) for t in page], limit, offset, total)


@bp.post("/ehs/training-assignments/<assignment_id>/complete")
def complete_training(assignment_id):
    user_id, role = get_actor()
    get_body()
    require_role(role, ("LabMember", "PrincipalInvestigator"))
    assignment = get_or_404(db.training_assignments, assignment_id, "TrainingAssignment")
    lab = db.labs[assignment["lab_id"]]
    assignment = training_service.complete(assignment, lab, user_id)
    return success_object(serialize_training(assignment))
