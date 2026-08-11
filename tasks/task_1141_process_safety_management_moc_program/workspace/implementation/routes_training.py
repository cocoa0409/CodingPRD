"""ProcedureUpdate and TrainingAssignment endpoints."""
from flask import Blueprint, g

from db import store
from errors import (
    ApiError, ERR_PROCEDURE_UPDATE_INVALID_STATE, ERR_MOC_INVALID_STATE,
    ERR_TRAINING_ASSIGNMENT_INVALID_STATE, ERR_NOT_RESOURCE_OWNER,
    ERR_NO_TRAINING_ASSIGNED, ERR_DUPLICATE_TRAINING_ASSIGNMENT,
)
from helpers import (
    ALL_ROLES, ENTITY_ROLES, require_roles, body_json, ok, ok_list,
    pagination_params, f_str,
)
from services import (
    new_entity, touch, get_moc, get_person, get_procedure, get_training,
    ser_procedure, ser_training, sorted_rows, require_active_person,
)

bp = Blueprint("training", __name__)


@bp.post("/psm/moc-requests/<mid>/procedure-updates")
@require_roles("TrainingCoordinator")
def create_procedure_update(mid):
    m = get_moc(mid)
    b = body_json()
    document_ref = f_str(b, "document_ref")
    p = new_entity()
    p.update({
        "moc_id": m["id"],
        "document_ref": document_ref,
        "status": "DRAFT",
        "published_at": None,
    })
    store.procedures[p["id"]] = p
    return ok(ser_procedure(p), 201)


@bp.get("/psm/moc-requests/<mid>/procedure-updates")
@require_roles(*ALL_ROLES)
def list_moc_procedures(mid):
    m = get_moc(mid)
    limit, offset = pagination_params()
    rows = [ser_procedure(p) for p in sorted_rows(store.procedures.values())
            if p["moc_id"] == m["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/procedure-updates/<pid>")
@require_roles(*ALL_ROLES)
def get_one_procedure(pid):
    return ok(ser_procedure(get_procedure(pid)), 200)


@bp.post("/psm/procedure-updates/<pid>/publish")
@require_roles("TrainingCoordinator")
def publish_procedure(pid):
    p = get_procedure(pid)
    if p["status"] != "DRAFT":
        raise ApiError(ERR_PROCEDURE_UPDATE_INVALID_STATE, "Only a DRAFT update can be published", 409)
    m = store.mocs[p["moc_id"]]
    if m["status"] not in ("APPROVED_IMPLEMENTATION", "IMPLEMENTED_PSSR_PENDING"):
        raise ApiError(ERR_MOC_INVALID_STATE,
                       "MOC must be APPROVED_IMPLEMENTATION or IMPLEMENTED_PSSR_PENDING", 409)
    has_assignment = any(t["procedure_update_id"] == p["id"] for t in store.trainings.values())
    if not has_assignment:
        raise ApiError(ERR_NO_TRAINING_ASSIGNED, "Publish requires at least one TrainingAssignment", 409)
    p["published_at"] = store.clock
    p["status"] = "PUBLISHED"
    touch(p)
    return ok(ser_procedure(p), 200)


@bp.post("/psm/procedure-updates/<pid>/training-assignments")
@require_roles("TrainingCoordinator")
def create_training_assignment(pid):
    p = get_procedure(pid)
    b = body_json()
    personnel_id = f_str(b, "personnel_id")
    require_active_person(personnel_id, "Trainee")
    if any(t["procedure_update_id"] == p["id"] and t["personnel_id"] == personnel_id
           for t in store.trainings.values()):
        raise ApiError(ERR_DUPLICATE_TRAINING_ASSIGNMENT,
                       "Assignment already exists for this update and person", 409)
    t = new_entity()
    t.update({
        "procedure_update_id": p["id"],
        "personnel_id": personnel_id,
        "status": "ASSIGNED",
        "completed_at": None,
    })
    store.trainings[t["id"]] = t
    return ok(ser_training(t), 201)


@bp.get("/psm/procedure-updates/<pid>/training-assignments")
@require_roles(*ALL_ROLES)
def list_update_assignments(pid):
    p = get_procedure(pid)
    limit, offset = pagination_params()
    rows = [ser_training(t) for t in sorted_rows(store.trainings.values())
            if t["procedure_update_id"] == p["id"]]
    return ok_list(rows, limit, offset)


@bp.get("/psm/personnel/<pid>/training-assignments")
@require_roles(*ALL_ROLES)
def list_personnel_assignments(pid):
    person = get_person(pid)
    limit, offset = pagination_params()
    rows = [ser_training(t) for t in sorted_rows(store.trainings.values())
            if t["personnel_id"] == person["id"]]
    return ok_list(rows, limit, offset)


@bp.post("/psm/training-assignments/<tid>/complete")
@require_roles(*ENTITY_ROLES)
def complete_training(tid):
    t = get_training(tid)
    if t["status"] != "ASSIGNED":
        raise ApiError(ERR_TRAINING_ASSIGNMENT_INVALID_STATE, "Only an ASSIGNED assignment can be completed", 409)
    if t["personnel_id"] != g.user_id:
        raise ApiError(ERR_NOT_RESOURCE_OWNER, "Only the trainee may complete the assignment", 403)
    t["completed_at"] = store.clock
    t["status"] = "COMPLETED"
    touch(t)
    return ok(ser_training(t), 200)
