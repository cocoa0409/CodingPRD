from flask import Blueprint, request

from db import store
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_enum,
    f_dt,
    f_list_str,
    ok,
    paginate,
    invalid,
)
from errors import ApiError
from services import (
    get_project,
    get_jha,
    get_permit,
    new_entity,
    ser_permit,
    bump,
    project_bump,
    permit_time_conflicts,
)

bp = Blueprint("permits", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)

PERMIT_TYPES = {"FALL_PROTECTION", "EXCAVATION", "HOT_WORK"}


def _check_workers_exist(project_id, worker_ids):
    for wid in worker_ids:
        if not isinstance(wid, str):
            continue
        w = store.workers.get(wid)
        if w is None or w["project_id"] != project_id:
            raise ApiError("ERR_WORKER_NOT_FOUND", 404, "No Worker with the given id")


def _crew_all_cleared(worker_ids):
    for wid in worker_ids:
        w = store.workers[wid]
        if w["status"] != "CLEARED":
            raise ApiError(
                "ERR_WORKER_NOT_CLEARED",
                409,
                "Permit crew members must be CLEARED",
            )


def _check_jha_approved(permit_or_jha):
    if permit_or_jha["status"] != "APPROVED":
        raise ApiError(
            "ERR_JHA_NOT_APPROVED",
            409,
            "Permit create/issue/reinstate requires linked JHA status APPROVED",
        )


def _check_conflicts(project_id, permit_type, work_start, work_end, crew, exclude_id=None):
    if permit_time_conflicts(
        project_id, permit_type, work_start, work_end, crew, exclude_id=exclude_id
    ):
        raise ApiError(
            "ERR_PERMIT_TIME_CONFLICT",
            409,
            "Excavation half-open overlap, hot-work 60-minute buffer violation, "
            "or crew closed-interval overlap",
        )


@bp.route("/safety/permits", methods=["POST"])
def create_permit():
    require_roles("SiteSuperintendent")
    b = body()
    # priority 3: FK existence + same-project rule
    raw_pid = b.get("project_id")
    project = get_project(raw_pid) if isinstance(raw_pid, str) else None
    raw_jid = b.get("jha_id")
    if isinstance(raw_jid, str):
        jha = get_jha(raw_jid)
        if project is not None and jha["project_id"] != project["id"]:
            raise ApiError("ERR_JHA_NOT_FOUND", 404, "No JobHazardAnalysis with the given id")
    raw_crew = b.get("authorized_worker_ids")
    if isinstance(raw_crew, list) and project is not None:
        _check_workers_exist(project["id"], raw_crew)
    # priority 4: shape
    reject_unknown(
        b,
        {"project_id", "jha_id", "permit_type", "work_start", "work_end", "authorized_worker_ids"},
    )
    project_id = f_str(b, "project_id")
    if project is None:
        project = get_project(project_id)
    jha_id = f_str(b, "jha_id")
    jha = get_jha(jha_id)
    if jha["project_id"] != project_id:
        raise ApiError("ERR_JHA_NOT_FOUND", 404, "No JobHazardAnalysis with the given id")
    permit_type = f_enum(b, "permit_type", PERMIT_TYPES)
    work_start = f_dt(b, "work_start")
    work_end = f_dt(b, "work_end")
    if work_end <= work_start:
        invalid("work_end must be strictly after work_start")
    crew = f_list_str(b, "authorized_worker_ids")
    _check_workers_exist(project_id, crew)
    # priority 7 (a): JHA APPROVED
    _check_jha_approved(jha)
    # priority 7 (e): crew all CLEARED
    _crew_all_cleared(crew)
    # priority 8: temporal conflict rules
    _check_conflicts(project_id, permit_type, work_start, work_end, crew)
    p = new_entity()
    p.update(
        {
            "project_id": project_id,
            "jha_id": jha_id,
            "permit_type": permit_type,
            "work_start": work_start,
            "work_end": work_end,
            "authorized_worker_ids": list(crew),
            "status": "REQUESTED",
            "suspension_reason": "",
        }
    )
    store.permits[p["id"]] = p
    return ok(ser_permit(p), 201)


@bp.route("/safety/permits", methods=["GET"])
def list_permits():
    require_roles(*ALL_ROLES)
    records = list(store.permits.values())
    pid = request.args.get("project_id")
    if pid is not None:
        records = [p for p in records if p["project_id"] == pid]
    jid = request.args.get("jha_id")
    if jid is not None:
        records = [p for p in records if p["jha_id"] == jid]
    ptype = request.args.get("permit_type")
    if ptype is not None:
        records = [p for p in records if p["permit_type"] == ptype]
    status = request.args.get("status")
    if status is not None:
        records = [p for p in records if p["status"] == status]
    return paginate(records, ser_permit)


@bp.route("/safety/permits/<permitId>", methods=["GET"])
def get_one_permit(permitId):
    require_roles(*ALL_ROLES)
    return ok(ser_permit(get_permit(permitId)))


def _revalidate_for_issue(permit):
    """Gates shared by issue and reinstate, in priority order 6 -> 7 -> 8."""
    project = get_project(permit["project_id"])
    if project["safety_posture"] != "NORMAL":
        raise ApiError(
            "ERR_PROJECT_POSTURE_BLOCKED",
            409,
            "Permit issue/reinstate requires project posture NORMAL",
        )
    _check_jha_approved(get_jha(permit["jha_id"]))
    _crew_all_cleared(permit["authorized_worker_ids"])
    _check_conflicts(
        permit["project_id"],
        permit["permit_type"],
        permit["work_start"],
        permit["work_end"],
        permit["authorized_worker_ids"],
        exclude_id=permit["id"],
    )


@bp.route("/safety/permits/<permitId>/issue", methods=["POST"])
def issue_permit(permitId):
    require_roles("SafetyManager")
    permit = get_permit(permitId)
    b = body()
    reject_unknown(b, set())
    if permit["status"] != "REQUESTED":
        raise ApiError(
            "ERR_PERMIT_INVALID_STATE", 409, "issue requires status REQUESTED"
        )
    _revalidate_for_issue(permit)
    permit["status"] = "ISSUED"
    bump(permit)
    project_bump(get_project(permit["project_id"]))
    return ok(ser_permit(permit))


@bp.route("/safety/permits/<permitId>/close", methods=["POST"])
def close_permit(permitId):
    require_roles("SiteSuperintendent")
    permit = get_permit(permitId)
    b = body()
    reject_unknown(b, {"completion_notes"})
    f_str(b, "completion_notes", required=False, default=None)
    if permit["status"] != "ISSUED":
        raise ApiError("ERR_PERMIT_INVALID_STATE", 409, "close requires status ISSUED")
    permit["status"] = "CLOSED"
    bump(permit)
    project_bump(get_project(permit["project_id"]))
    return ok(ser_permit(permit))


@bp.route("/safety/permits/<permitId>/reinstate", methods=["POST"])
def reinstate_permit(permitId):
    require_roles("SafetyManager")
    permit = get_permit(permitId)
    b = body()
    reject_unknown(b, set())
    if permit["status"] != "SUSPENDED":
        raise ApiError(
            "ERR_PERMIT_INVALID_STATE", 409, "reinstate requires status SUSPENDED"
        )
    _revalidate_for_issue(permit)
    permit["status"] = "ISSUED"
    permit["suspension_reason"] = ""
    bump(permit)
    project_bump(get_project(permit["project_id"]))
    return ok(ser_permit(permit))
