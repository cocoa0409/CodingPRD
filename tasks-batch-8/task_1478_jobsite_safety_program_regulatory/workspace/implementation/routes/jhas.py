from flask import Blueprint, request

from db import store
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    ok,
    paginate,
)
from errors import ApiError
from services import get_project, get_huddle, get_jha, new_entity, ser_jha, bump

bp = Blueprint("jhas", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)


@bp.route("/safety/jhas", methods=["POST"])
def create_jha():
    require_roles("SiteSuperintendent")
    b = body()
    # priority 3: FK existence + same-project rule
    raw_pid = b.get("project_id")
    project = get_project(raw_pid) if isinstance(raw_pid, str) else None
    raw_hid = b.get("huddle_id")
    if isinstance(raw_hid, str):
        huddle = get_huddle(raw_hid)
        if project is not None and huddle["project_id"] != project["id"]:
            raise ApiError("ERR_HUDDLE_NOT_FOUND", 404, "No Huddle with the given id")
    # priority 4: shape
    reject_unknown(
        b, {"project_id", "huddle_id", "task_description", "hazards", "controls"}
    )
    project_id = f_str(b, "project_id")
    if project is None:
        project = get_project(project_id)
    huddle_id = f_str(b, "huddle_id")
    huddle = get_huddle(huddle_id)
    if huddle["project_id"] != project_id:
        raise ApiError("ERR_HUDDLE_NOT_FOUND", 404, "No Huddle with the given id")
    task_description = f_str(b, "task_description")
    hazards = f_str(b, "hazards")
    controls = f_str(b, "controls")
    j = new_entity()
    j.update(
        {
            "project_id": project_id,
            "huddle_id": huddle_id,
            "task_description": task_description,
            "hazards": hazards,
            "controls": controls,
            "status": "DRAFT",
        }
    )
    store.jhas[j["id"]] = j
    return ok(ser_jha(j), 201)


@bp.route("/safety/jhas", methods=["GET"])
def list_jhas():
    require_roles(*ALL_ROLES)
    records = list(store.jhas.values())
    pid = request.args.get("project_id")
    if pid is not None:
        records = [j for j in records if j["project_id"] == pid]
    hid = request.args.get("huddle_id")
    if hid is not None:
        records = [j for j in records if j["huddle_id"] == hid]
    status = request.args.get("status")
    if status is not None:
        records = [j for j in records if j["status"] == status]
    return paginate(records, ser_jha)


@bp.route("/safety/jhas/<jhaId>", methods=["GET"])
def get_one_jha(jhaId):
    require_roles(*ALL_ROLES)
    return ok(ser_jha(get_jha(jhaId)))


@bp.route("/safety/jhas/<jhaId>/approve", methods=["POST"])
def approve_jha(jhaId):
    require_roles("SafetyManager")
    jha = get_jha(jhaId)
    b = body()
    reject_unknown(b, set())
    if jha["status"] not in ("DRAFT", "RE_REVIEW_REQUIRED"):
        raise ApiError(
            "ERR_JHA_INVALID_STATE",
            409,
            "approve requires status DRAFT or RE_REVIEW_REQUIRED",
        )
    huddle = get_huddle(jha["huddle_id"])
    if huddle["status"] != "CONDUCTED":
        raise ApiError(
            "ERR_HUDDLE_NOT_CONDUCTED",
            409,
            "JHA approve requires linked Huddle status CONDUCTED",
        )
    jha["status"] = "APPROVED"
    bump(jha)
    return ok(ser_jha(jha))
