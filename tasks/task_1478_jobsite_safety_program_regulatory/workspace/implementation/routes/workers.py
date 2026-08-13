from flask import Blueprint, request

from db import store, now
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_id,
    f_bool,
    f_enum,
    ok,
    paginate,
    invalid,
)
from errors import ApiError
from services import (
    get_worker,
    get_project,
    get_subcontractor,
    new_entity,
    ser_worker,
    bump,
    training_clearance_ok,
    cascade_worker_permits,
)

bp = Blueprint("workers", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)


@bp.route("/safety/workers", methods=["POST"])
def create_worker():
    require_roles("SiteSuperintendent")
    b = body()
    # priority 3: body FK existence + same-project rule
    raw_pid = b.get("project_id")
    project = get_project(raw_pid) if isinstance(raw_pid, str) else None
    raw_sid = b.get("subcontractor_id")
    if isinstance(raw_sid, str):
        sub = get_subcontractor(raw_sid)
        if project is not None and sub["project_id"] != project["id"]:
            raise ApiError(
                "ERR_SUBCONTRACTOR_NOT_FOUND", 404, "No Subcontractor with the given id"
            )
    # priority 4: shape + conditional rule
    reject_unknown(
        b, {"project_id", "full_name", "employer_type", "subcontractor_id", "is_supervisor"}
    )
    project_id = f_str(b, "project_id")
    if project is None:
        project = get_project(project_id)
    full_name = f_str(b, "full_name")
    employer_type = f_enum(b, "employer_type", {"DIRECT", "SUBCONTRACTOR"})
    subcontractor_id = f_id(b, "subcontractor_id")
    is_supervisor = f_bool(b, "is_supervisor", required=False, default=False)
    if employer_type == "SUBCONTRACTOR" and subcontractor_id is None:
        invalid("subcontractor_id is required when employer_type is SUBCONTRACTOR")
    if employer_type == "DIRECT" and subcontractor_id is not None:
        invalid("subcontractor_id must be null when employer_type is DIRECT")
    w = new_entity()
    w.update(
        {
            "project_id": project_id,
            "full_name": full_name,
            "employer_type": employer_type,
            "subcontractor_id": subcontractor_id,
            "is_supervisor": is_supervisor,
            "status": "PENDING_ORIENTATION",
            "orientation_completed_at": None,
            "suspension_reason": None,
        }
    )
    store.workers[w["id"]] = w
    return ok(ser_worker(w), 201)


@bp.route("/safety/workers", methods=["GET"])
def list_workers():
    require_roles(*ALL_ROLES)
    records = list(store.workers.values())
    pid = request.args.get("project_id")
    if pid is not None:
        records = [w for w in records if w["project_id"] == pid]
    sid = request.args.get("subcontractor_id")
    if sid is not None:
        records = [w for w in records if w["subcontractor_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        records = [w for w in records if w["status"] == status]
    return paginate(records, ser_worker)


@bp.route("/safety/workers/<workerId>", methods=["GET"])
def get_one_worker(workerId):
    require_roles(*ALL_ROLES)
    return ok(ser_worker(get_worker(workerId)))


@bp.route("/safety/workers/<workerId>/complete-orientation", methods=["POST"])
def complete_orientation(workerId):
    require_roles("SiteSuperintendent")
    worker = get_worker(workerId)
    b = body()
    reject_unknown(b, set())
    if worker["status"] != "PENDING_ORIENTATION":
        raise ApiError(
            "ERR_WORKER_INVALID_STATE",
            409,
            "complete-orientation requires status PENDING_ORIENTATION",
        )
    has_active_plan = any(
        p["project_id"] == worker["project_id"] and p["status"] == "ACTIVE"
        for p in store.plans.values()
    )
    if not has_active_plan:
        raise ApiError(
            "ERR_NO_ACTIVE_SAFETY_PLAN",
            409,
            "Worker orientation requires an ACTIVE SafetyPlan on the project",
        )
    worker["status"] = "ORIENTED"
    worker["orientation_completed_at"] = now()
    bump(worker)
    return ok(ser_worker(worker))


@bp.route("/safety/workers/<workerId>/clear", methods=["POST"])
def clear_worker(workerId):
    require_roles("SiteSuperintendent")
    worker = get_worker(workerId)
    b = body()
    reject_unknown(b, set())
    if worker["status"] != "ORIENTED":
        raise ApiError(
            "ERR_WORKER_INVALID_STATE", 409, "clear requires status ORIENTED"
        )
    # priority 6 (a): training clearance check
    if not training_clearance_ok(worker):
        raise ApiError(
            "ERR_TRAINING_REQUIREMENT_NOT_MET",
            422,
            "Worker lacks a VERIFIED, non-expired certificate of the required OSHA level",
        )
    # priority 6 (b): posture gate
    project = get_project(worker["project_id"])
    if project["safety_posture"] == "FROZEN":
        raise ApiError(
            "ERR_PROJECT_POSTURE_BLOCKED",
            409,
            "Worker clearance is blocked while the project posture is FROZEN",
        )
    # priority 7 (d): subcontractor standing
    if worker["employer_type"] == "SUBCONTRACTOR":
        sub = get_subcontractor(worker["subcontractor_id"])
        if sub["standing"] != "GOOD_STANDING":
            raise ApiError(
                "ERR_SUBCONTRACTOR_NOT_IN_GOOD_STANDING",
                409,
                "Subcontractor worker clearance requires standing GOOD_STANDING",
            )
    worker["status"] = "CLEARED"
    bump(worker)
    return ok(ser_worker(worker))


@bp.route("/safety/workers/<workerId>/suspend", methods=["POST"])
def suspend_worker(workerId):
    require_roles("SafetyManager")
    worker = get_worker(workerId)
    b = body()
    reject_unknown(b, {"reason"})
    reason = f_str(b, "reason")
    if worker["status"] not in ("ORIENTED", "CLEARED"):
        raise ApiError(
            "ERR_WORKER_INVALID_STATE",
            409,
            "suspend requires status ORIENTED or CLEARED",
        )
    was_cleared = worker["status"] == "CLEARED"
    worker["status"] = "SUSPENDED"
    worker["suspension_reason"] = reason
    bump(worker)
    if was_cleared:
        cascade_worker_permits(worker["id"], "CREW_MEMBER_SUSPENDED")
    return ok(ser_worker(worker))


@bp.route("/safety/workers/<workerId>/reinstate", methods=["POST"])
def reinstate_worker(workerId):
    require_roles("SafetyManager")
    worker = get_worker(workerId)
    b = body()
    reject_unknown(b, set())
    if worker["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_WORKER_INVALID_STATE", 409, "reinstate requires status SUSPENDED"
        )
    if worker["employer_type"] == "SUBCONTRACTOR":
        sub = get_subcontractor(worker["subcontractor_id"])
        if sub["standing"] == "REMOVED":
            raise ApiError(
                "ERR_SUBCONTRACTOR_NOT_IN_GOOD_STANDING",
                409,
                "Reinstatement refused: subcontractor has been REMOVED",
            )
    worker["status"] = "ORIENTED"
    worker["suspension_reason"] = ""
    bump(worker)
    return ok(ser_worker(worker))
