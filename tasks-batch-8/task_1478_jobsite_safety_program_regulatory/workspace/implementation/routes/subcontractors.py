from flask import Blueprint, request

from db import store
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_enum,
    ok,
    paginate,
)
from errors import ApiError
from services import (
    get_project,
    get_subcontractor,
    new_entity,
    ser_subcontractor,
    bump,
    compliance_score_realtime,
    cascade_subcontractor_removed,
    DEMOTE_THRESHOLD,
)

bp = Blueprint("subcontractors", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)


@bp.route("/safety/subcontractors", methods=["POST"])
def create_subcontractor():
    require_roles("SafetyManager")
    b = body()
    raw_pid = b.get("project_id")
    if isinstance(raw_pid, str):
        get_project(raw_pid)
    reject_unknown(b, {"project_id", "company_name", "trade"})
    project_id = f_str(b, "project_id")
    get_project(project_id)
    company_name = f_str(b, "company_name")
    trade = f_str(b, "trade")
    s = new_entity()
    s.update(
        {
            "project_id": project_id,
            "company_name": company_name,
            "trade": trade,
            "standing": "GOOD_STANDING",
        }
    )
    store.subcontractors[s["id"]] = s
    return ok(ser_subcontractor(s), 201)


@bp.route("/safety/subcontractors", methods=["GET"])
def list_subcontractors():
    require_roles(*ALL_ROLES)
    records = list(store.subcontractors.values())
    pid = request.args.get("project_id")
    if pid is not None:
        records = [s for s in records if s["project_id"] == pid]
    standing = request.args.get("standing")
    if standing is not None:
        records = [s for s in records if s["standing"] == standing]
    return paginate(records, ser_subcontractor)


@bp.route("/safety/subcontractors/<subcontractorId>", methods=["GET"])
def get_one_subcontractor(subcontractorId):
    require_roles(*ALL_ROLES)
    return ok(ser_subcontractor(get_subcontractor(subcontractorId)))


@bp.route("/safety/subcontractors/<subcontractorId>/probation-review", methods=["POST"])
def probation_review(subcontractorId):
    require_roles("SafetyManager")
    sub = get_subcontractor(subcontractorId)
    b = body()
    reject_unknown(b, {"action"})
    action = f_enum(b, "action", {"DEMOTE", "RESTORE"})
    if action == "DEMOTE":
        if sub["standing"] != "GOOD_STANDING":
            raise ApiError(
                "ERR_SUBCONTRACTOR_INVALID_STANDING",
                409,
                "DEMOTE requires standing GOOD_STANDING",
            )
        if not compliance_score_realtime(sub["id"]) < DEMOTE_THRESHOLD:
            raise ApiError(
                "ERR_SCORE_THRESHOLD_NOT_MET",
                409,
                "DEMOTE requires compliance_score_realtime < 80 (strict)",
            )
        sub["standing"] = "PROBATION"
    else:  # RESTORE
        if sub["standing"] != "PROBATION":
            raise ApiError(
                "ERR_SUBCONTRACTOR_INVALID_STANDING",
                409,
                "RESTORE requires standing PROBATION",
            )
        if not compliance_score_realtime(sub["id"]) >= DEMOTE_THRESHOLD:
            raise ApiError(
                "ERR_SCORE_THRESHOLD_NOT_MET",
                409,
                "RESTORE requires compliance_score_realtime >= 80 (inclusive)",
            )
        sub["standing"] = "GOOD_STANDING"
    bump(sub)
    return ok(ser_subcontractor(sub))


@bp.route("/safety/subcontractors/<subcontractorId>/remove", methods=["POST"])
def remove_subcontractor(subcontractorId):
    require_roles("SafetyManager")
    sub = get_subcontractor(subcontractorId)
    b = body()
    reject_unknown(b, {"reason"})
    f_str(b, "reason")
    if sub["standing"] != "PROBATION":
        raise ApiError(
            "ERR_SUBCONTRACTOR_INVALID_STANDING",
            409,
            "remove requires standing PROBATION",
        )
    sub["standing"] = "REMOVED"
    bump(sub)
    cascade_subcontractor_removed(sub)
    return ok(ser_subcontractor(sub))
