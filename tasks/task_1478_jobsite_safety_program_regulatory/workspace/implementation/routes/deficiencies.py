from flask import Blueprint, request

from db import store, now
from helpers import (
    require_roles,
    body,
    reject_unknown,
    f_str,
    f_id,
    f_enum,
    ok,
    paginate,
    invalid,
)
from errors import ApiError
from services import (
    get_inspection,
    get_subcontractor,
    get_deficiency,
    get_project,
    new_entity,
    ser_deficiency,
    bump,
    project_bump,
    recompute_posture,
    SEVERITY_SLA_DAYS,
)
from datetime import timedelta

bp = Blueprint("deficiencies", __name__)

ALL_ROLES = (
    "SafetyManager",
    "SiteSuperintendent",
    "SafetyInspector",
    "SubcontractorRep",
    "ComplianceAuditor",
)

SEVERITIES = {"MINOR", "MAJOR", "CRITICAL", "IMMINENT_DANGER"}


@bp.route("/safety/deficiencies", methods=["POST"])
def create_deficiency():
    uid, _ = require_roles("SafetyInspector")
    b = body()
    # priority 3: FK existence + same-project rule
    raw_iid = b.get("inspection_id")
    inspection = get_inspection(raw_iid) if isinstance(raw_iid, str) else None
    raw_sid = b.get("assigned_subcontractor_id")
    if isinstance(raw_sid, str) and inspection is not None:
        sub = get_subcontractor(raw_sid)
        if sub["project_id"] != inspection["project_id"]:
            raise ApiError(
                "ERR_SUBCONTRACTOR_NOT_FOUND", 404, "No Subcontractor with the given id"
            )
    # priority 4: shape
    reject_unknown(b, {"inspection_id", "description", "severity", "assigned_subcontractor_id"})
    inspection_id = f_str(b, "inspection_id")
    if inspection is None:
        inspection = get_inspection(inspection_id)
    description = f_str(b, "description")
    severity = f_enum(b, "severity", SEVERITIES)
    assigned_subcontractor_id = f_id(b, "assigned_subcontractor_id")
    if assigned_subcontractor_id is not None:
        sub = get_subcontractor(assigned_subcontractor_id)
        if sub["project_id"] != inspection["project_id"]:
            raise ApiError(
                "ERR_SUBCONTRACTOR_NOT_FOUND", 404, "No Subcontractor with the given id"
            )
    # priority 7 (c): parent inspection must be COMPLETED
    if inspection["status"] != "COMPLETED":
        raise ApiError(
            "ERR_INSPECTION_NOT_COMPLETED",
            409,
            "Deficiency create requires parent Inspection status COMPLETED",
        )
    d = new_entity()
    d.update(
        {
            "inspection_id": inspection_id,
            "project_id": inspection["project_id"],
            "description": description,
            "severity": severity,
            "assigned_subcontractor_id": assigned_subcontractor_id,
            "due_at": d["created_at"] + timedelta(days=SEVERITY_SLA_DAYS[severity]),
            "status": "OPEN",
            "correction_notes": "",
            "created_by_user_id": uid,
            "verified_by_user_id": None,
            "closed_disposition": None,
        }
    )
    store.deficiencies[d["id"]] = d
    # open_deficiency_count increments (computed on read); posture recompute
    recompute_posture(get_project(d["project_id"]))
    return ok(ser_deficiency(d), 201)


@bp.route("/safety/deficiencies", methods=["GET"])
def list_deficiencies():
    require_roles(*ALL_ROLES)
    records = list(store.deficiencies.values())
    iid = request.args.get("inspection_id")
    if iid is not None:
        records = [d for d in records if d["inspection_id"] == iid]
    pid = request.args.get("project_id")
    if pid is not None:
        records = [d for d in records if d["project_id"] == pid]
    sid = request.args.get("assigned_subcontractor_id")
    if sid is not None:
        records = [d for d in records if d["assigned_subcontractor_id"] == sid]
    status = request.args.get("status")
    if status is not None:
        records = [d for d in records if d["status"] == status]
    return paginate(records, ser_deficiency)


@bp.route("/safety/deficiencies/<deficiencyId>", methods=["GET"])
def get_one_deficiency(deficiencyId):
    require_roles(*ALL_ROLES)
    return ok(ser_deficiency(get_deficiency(deficiencyId)))


@bp.route("/safety/deficiencies/<deficiencyId>/submit-correction", methods=["POST"])
def submit_correction(deficiencyId):
    uid, role = require_roles("SiteSuperintendent", "SubcontractorRep")
    # priority 2 ownership clause for SubcontractorRep (resource-resolvable case)
    d = store.deficiencies.get(deficiencyId)
    if (
        role == "SubcontractorRep"
        and d is not None
        and d["assigned_subcontractor_id"] != uid
    ):
        raise ApiError(
            "ERR_INSUFFICIENT_PERMISSIONS",
            403,
            "SubcontractorRep may submit corrections only for deficiencies assigned to their subcontractor",
        )
    if d is None:
        raise ApiError("ERR_DEFICIENCY_NOT_FOUND", 404, "No Deficiency with the given id")
    b = body()
    reject_unknown(b, {"correction_notes"})
    correction_notes = f_str(b, "correction_notes")
    if d["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError(
            "ERR_DEFICIENCY_INVALID_STATE",
            409,
            "submit-correction requires status OPEN or OVERDUE",
        )
    was_overdue = d["status"] == "OVERDUE"
    d["status"] = "CORRECTION_SUBMITTED"
    d["correction_notes"] = correction_notes
    bump(d)
    if was_overdue:
        # leaving the OVERDUE bucket recomputes posture
        recompute_posture(get_project(d["project_id"]))
    return ok(ser_deficiency(d))


@bp.route("/safety/deficiencies/<deficiencyId>/verify", methods=["POST"])
def verify_deficiency(deficiencyId):
    uid, _ = require_roles("SafetyInspector")
    d = get_deficiency(deficiencyId)
    b = body()
    # priority 4: shape + conditional disposition rule
    reject_unknown(b, {"outcome", "disposition", "notes"})
    outcome = f_enum(b, "outcome", {"CLOSED", "REJECTED"})
    disposition = b.get("disposition")
    if outcome == "CLOSED":
        if disposition is None:
            invalid("disposition is required when outcome is CLOSED")
        if disposition not in ("CONFIRMED", "NOT_SUB_FAULT"):
            invalid("disposition must be one of CONFIRMED, NOT_SUB_FAULT")
    else:  # REJECTED
        if disposition is not None:
            invalid("disposition is forbidden when outcome is REJECTED")
    f_str(b, "notes", required=False, default=None)
    # priority 5: state
    if d["status"] != "CORRECTION_SUBMITTED":
        raise ApiError(
            "ERR_DEFICIENCY_INVALID_STATE",
            409,
            "verify requires status CORRECTION_SUBMITTED",
        )
    # priority 6 (d): segregation of duties
    if uid == d["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES_VIOLATION",
            403,
            "Deficiency verifier must differ from its creator",
        )
    if outcome == "CLOSED":
        d["status"] = "VERIFIED_CLOSED"
        d["verified_by_user_id"] = uid
        d["closed_disposition"] = disposition
        bump(d)
        project = get_project(d["project_id"])
        project_bump(project)  # open_deficiency_count decrements; version increments
        recompute_posture(project, bump_version_on_change=False)
    else:  # REJECTED
        d["verified_by_user_id"] = None
        reflipped = now() > d["due_at"]
        d["status"] = "OVERDUE" if reflipped else "OPEN"
        bump(d)
        if reflipped:
            recompute_posture(get_project(d["project_id"]))
    return ok(ser_deficiency(d))
