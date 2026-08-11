"""Inspection endpoints."""
from flask import Blueprint

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, get_child_or_404, require_case_active,
    req_str, req_enum, req_dt, opt_str, opt_array, opt_dt, now_iso, iso,
)

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = ("PRE_INSTALL", "ROUGH", "FINAL", "WARRANTY", "REASSESSMENT")


def _get_inspection(case_id, inspection_id):
    case = get_case_or_404(case_id)
    rec = get_child_or_404("inspections", inspection_id, "case_id", case_id,
                           "ERR_INSPECTION_NOT_FOUND", "Inspection")
    return case, rec


@bp.route("/cases/<caseId>/inspections", methods=["POST"])
def create_inspection(caseId):
    require_roles("Inspector", "ProjectManager")
    case = get_case_or_404(caseId)
    require_case_active(case)
    b = body()
    inspection_type = req_enum(b, "inspection_type", INSPECTION_TYPES)
    inspector_id = req_str(b, "inspector_id")
    scheduled = req_dt(b, "scheduled_date")
    job_id = opt_str(b, "installation_job_id")
    deficiencies = opt_array(b, "deficiencies", [])
    correction_deadline = opt_dt(b, "correction_deadline")

    job = None
    if job_id is not None:
        job = db["installation_jobs"].get(job_id)
        if job is None or job["case_id"] != caseId:
            raise ApiError("ERR_JOB_NOT_FOUND", 404,
                           "Installation job with given ID does not exist")
    if inspection_type == "FINAL" and job is not None:
        if job["actual_end"] is None or not (scheduled > job["_actual_end_dt"]):
            raise ApiError("ERR_INSPECTION_BEFORE_COMPLETION", 422,
                           "Final inspection cannot be scheduled before job "
                           "completion")

    rec = new_record()
    rec.update({
        "case_id": caseId,
        "installation_job_id": job_id,
        "inspection_type": inspection_type,
        "inspector_id": inspector_id,
        "scheduled_date": iso(scheduled),
        "completed_date": None,
        "outcome": "PENDING",
        "deficiencies": deficiencies,
        "correction_deadline": iso(correction_deadline),
        "reinspection_required": False,
        "ada_compliant": None,
        "_scheduled_date_dt": scheduled,
    })
    db["inspections"][rec["id"]] = rec
    if job is not None and inspection_type == "FINAL" and \
            job["inspection_status"] == "NOT_SCHEDULED":
        job["inspection_status"] = "SCHEDULED"
        touch(job)
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/inspections", methods=["GET"])
def list_inspections(caseId):
    require_roles()
    get_case_or_404(caseId)
    records = [i for i in db["inspections"].values() if i["case_id"] == caseId]
    return paginate(records)


@bp.route("/cases/<caseId>/inspections/<inspectionId>", methods=["GET"])
def get_inspection(caseId, inspectionId):
    require_roles()
    _case, rec = _get_inspection(caseId, inspectionId)
    return ok_object(serialize(rec))


@bp.route("/cases/<caseId>/inspections/<inspectionId>/pass", methods=["POST"])
def pass_inspection(caseId, inspectionId):
    require_roles("Inspector")
    case, rec = _get_inspection(caseId, inspectionId)
    require_case_active(case)
    if rec["outcome"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Inspection outcome is already recorded")
    b = body()
    extra = b.get("deficiencies")
    if isinstance(extra, list):
        rec["deficiencies"] = (rec.get("deficiencies") or []) + extra
    deficiencies = rec.get("deficiencies") or []
    if any(isinstance(d, str) and "SAFETY_CRITICAL" in d.upper() for d in deficiencies):
        raise ApiError("ERR_SAFETY_ITEMS_UNRESOLVED", 422,
                       "Safety-critical deficiencies prevent passing")

    rec["outcome"] = "PASSED"
    rec["completed_date"] = now_iso()
    rec["ada_compliant"] = True
    touch(rec)

    if rec["inspection_type"] == "FINAL":
        job = None
        if rec.get("installation_job_id"):
            job = db["installation_jobs"].get(rec["installation_job_id"])
        if job is None:
            jobs = [j for j in db["installation_jobs"].values()
                    if j["case_id"] == caseId and j["status"] == "COMPLETED"]
            if jobs:
                job = max(jobs, key=lambda j: j["_seq"])
        if job is not None:
            job["inspection_status"] = "PASSED"
            touch(job)
        if case["status"] == "INSTALLED":
            case["status"] = "INSPECTED"
        if case["status"] == "INSPECTED":
            case["status"] = "WARRANT_ACTIVE"
        from domain import mutate_case
        mutate_case(case)
    return ok_object(serialize(rec))


@bp.route("/cases/<caseId>/inspections/<inspectionId>/fail", methods=["POST"])
def fail_inspection(caseId, inspectionId):
    require_roles("Inspector")
    case, rec = _get_inspection(caseId, inspectionId)
    require_case_active(case)
    if rec["outcome"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Inspection outcome is already recorded")
    b = body()
    deficiencies = b.get("deficiencies")
    if not isinstance(deficiencies, list):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Missing or invalid required field: deficiencies")
    correction_deadline = req_dt(b, "correction_deadline")

    rec["outcome"] = "FAILED"
    rec["completed_date"] = now_iso()
    rec["deficiencies"] = deficiencies
    rec["correction_deadline"] = iso(correction_deadline)
    rec["_correction_deadline_dt"] = correction_deadline
    rec["reinspection_required"] = True
    touch(rec)

    if rec["inspection_type"] == "FINAL" and rec.get("installation_job_id"):
        job = db["installation_jobs"].get(rec["installation_job_id"])
        if job is not None:
            job["inspection_status"] = "FAILED"
            if job["status"] == "COMPLETED":
                # Failed final inspection: job reverts to IN_PROGRESS for rework.
                job["status"] = "IN_PROGRESS"
            touch(job)
    return ok_object(serialize(rec))
