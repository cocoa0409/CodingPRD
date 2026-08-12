"""Installation job endpoints."""
from datetime import timedelta
from flask import Blueprint

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, get_child_or_404, require_case_active,
    req_str, req_dt, opt_str, opt_int, now, now_iso, iso,
)
from domain import mutate_case, make_job_number

bp = Blueprint("jobs", __name__)


def _get_job(case_id, job_id):
    case = get_case_or_404(case_id)
    job = get_child_or_404("installation_jobs", job_id, "case_id", case_id,
                           "ERR_JOB_NOT_FOUND", "Installation job")
    return case, job


@bp.route("/cases/<caseId>/installation-jobs", methods=["POST"])
def create_job(caseId):
    require_roles("ProjectManager")
    case = get_case_or_404(caseId)
    require_case_active(case)
    b = body()
    quote_id = req_str(b, "quote_id")
    quote = db["quotes"].get(quote_id)
    if quote is None or quote["case_id"] != caseId:
        raise ApiError("ERR_QUOTE_NOT_FOUND", 404,
                       "Quote with given ID does not exist")
    scheduled_start = req_dt(b, "scheduled_start")
    scheduled_end = req_dt(b, "scheduled_end")
    crew_lead_id = req_str(b, "crew_lead_id")
    permit_number = opt_str(b, "permit_number")
    warranty_months = opt_int(b, "warranty_months", 12)
    permit_status = b.get("permit_status")
    if permit_status is not None:
        if permit_status not in ("NOT_REQUIRED", "PENDING", "ISSUED", "EXPIRED", "CLOSED"):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Missing or invalid required field: permit_status")
    else:
        permit_status = "ISSUED" if permit_number else "NOT_REQUIRED"

    # Funding precondition: FUNDING_APPROVED or approved self-pay covering the quote.
    self_pay_covers = any(
        s for s in db["funding_sources"].values()
        if s["case_id"] == caseId and s["source_type"] == "SELF_PAY"
        and s["status"] in ("APPROVED", "EXHAUSTED")
        and (s.get("approved_cents") or 0) >= quote["total_cents"])
    if case["status"] != "FUNDING_APPROVED" and not self_pay_covers:
        raise ApiError("ERR_CASE_NOT_FUNDED", 409,
                       "Case must have approved funding before installation")
    if permit_status not in ("NOT_REQUIRED", "ISSUED"):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Permit status must be NOT_REQUIRED or ISSUED to schedule")

    rec = new_record()
    rec.update({
        "case_id": caseId,
        "quote_id": quote_id,
        "job_number": make_job_number(),
        "status": "SCHEDULED",
        "scheduled_start": iso(scheduled_start),
        "scheduled_end": iso(scheduled_end),
        "actual_start": None,
        "actual_end": None,
        "crew_lead_id": crew_lead_id,
        "permit_number": permit_number,
        "permit_status": permit_status,
        "inspection_required": True,
        "inspection_status": "NOT_SCHEDULED",
        "warranty_start_date": None,
        "warranty_months": warranty_months,
        "progress_pct": 0,
        "_scheduled_start_dt": scheduled_start,
        "_scheduled_end_dt": scheduled_end,
    })
    db["installation_jobs"][rec["id"]] = rec
    if case["status"] == "FUNDING_APPROVED":
        case["status"] = "INSTALLATION_SCHEDULED"
    mutate_case(case)
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/installation-jobs", methods=["GET"])
def list_jobs(caseId):
    require_roles()
    get_case_or_404(caseId)
    records = [j for j in db["installation_jobs"].values() if j["case_id"] == caseId]
    return paginate(records)


@bp.route("/cases/<caseId>/installation-jobs/<jobId>", methods=["GET"])
def get_job(caseId, jobId):
    require_roles()
    _case, job = _get_job(caseId, jobId)
    return ok_object(serialize(job))


@bp.route("/cases/<caseId>/installation-jobs/<jobId>/order-materials", methods=["POST"])
def order_materials(caseId, jobId):
    require_roles("ProjectManager")
    case, job = _get_job(caseId, jobId)
    require_case_active(case)
    if job["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Job must be SCHEDULED to order materials")
    job["status"] = "MATERIALS_ORDERED"
    touch(job)
    return ok_object(serialize(job))


@bp.route("/cases/<caseId>/installation-jobs/<jobId>/start", methods=["POST"])
def start_job(caseId, jobId):
    require_roles("CrewLead")
    case, job = _get_job(caseId, jobId)
    require_case_active(case)
    if job["status"] != "MATERIALS_ORDERED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Job must be MATERIALS_ORDERED to start")
    if now() < job["_scheduled_start_dt"]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Job cannot start before its scheduled start date")
    job["status"] = "IN_PROGRESS"
    job["actual_start"] = now_iso()
    touch(job)
    return ok_object(serialize(job))


@bp.route("/cases/<caseId>/installation-jobs/<jobId>/punch-list", methods=["POST"])
def punch_list(caseId, jobId):
    require_roles("CrewLead")
    case, job = _get_job(caseId, jobId)
    require_case_active(case)
    if job["status"] != "IN_PROGRESS":
        raise ApiError("ERR_JOB_NOT_IN_PROGRESS", 409,
                       "Installation job must be IN_PROGRESS")
    job["status"] = "PUNCH_LIST"
    touch(job)
    return ok_object(serialize(job))


@bp.route("/cases/<caseId>/installation-jobs/<jobId>/complete", methods=["POST"])
def complete_job(caseId, jobId):
    require_roles("CrewLead")
    case, job = _get_job(caseId, jobId)
    require_case_active(case)
    if job["status"] not in ("IN_PROGRESS", "PUNCH_LIST"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Job must be IN_PROGRESS or PUNCH_LIST to complete")
    b = body()
    # Optional progress / safety signals supplied with the completion call.
    progress = b.get("progress_pct")
    if progress is not None:
        if not isinstance(progress, int) or isinstance(progress, bool):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Missing or invalid required field: progress_pct")
        job["progress_pct"] = progress
    else:
        job["progress_pct"] = 100
    unresolved = 0
    for key in ("unresolved_safety_items", "unresolved_safety_critical_items",
                "safety_critical_unresolved", "open_safety_critical_items"):
        v = b.get(key)
        if isinstance(v, bool) and v:
            unresolved = max(unresolved, 1)
        elif isinstance(v, int) and not isinstance(v, bool):
            unresolved = max(unresolved, v)
    if unresolved > 0:
        raise ApiError("ERR_SAFETY_ITEMS_UNRESOLVED", 422,
                       "Safety-critical punch list items remain unresolved")
    if job["progress_pct"] != 100:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "progress_pct must be 100 to complete the job")

    ts = now()
    job["status"] = "COMPLETED"
    job["actual_end"] = iso(ts)
    job["_actual_end_dt"] = ts
    job["warranty_start_date"] = iso(ts)
    job["_warranty_start_dt"] = ts
    touch(job)

    # Case: INSTALLATION_SCHEDULED -> INSTALLED.
    if case["status"] == "INSTALLATION_SCHEDULED":
        case["status"] = "INSTALLED"
    mutate_case(case)

    # Auto-create POST_INSTALL reassessment schedule due 30 days after completion.
    sched = new_record()
    due = ts + timedelta(days=30)
    sched.update({
        "case_id": caseId,
        "trigger_event": "POST_INSTALL",
        "due_date": iso(due),
        "status": "PENDING",
        "linked_assessment_id": None,
        "priority": "ROUTINE",
        "auto_generated": True,
        "_due_date_dt": due,
    })
    db["reassessment_schedules"][sched["id"]] = sched
    return ok_object(serialize(job))


@bp.route("/cases/<caseId>/installation-jobs/<jobId>/cancel", methods=["POST"])
def cancel_job(caseId, jobId):
    require_roles("ProjectManager")
    case, job = _get_job(caseId, jobId)
    require_case_active(case)
    if job["status"] not in ("SCHEDULED", "MATERIALS_ORDERED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Job cannot be cancelled from its current state")
    if job["actual_start"] is not None:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Job has already started and cannot be cancelled")
    job["status"] = "CANCELLED"
    touch(job)
    # Reverse committed funding allocations tied to this job's quote.
    for a in db["funding_allocations"].values():
        if a["quote_id"] == job["quote_id"] and a["status"] == "COMMITTED":
            a["status"] = "REVERSED"
            touch(a)
            src = db["funding_sources"].get(a["funding_source_id"])
            if src is not None:
                src["remaining_cents"] = (src.get("remaining_cents") or 0) + \
                    a["amount_cents"]
                touch(src)
    mutate_case(case)
    return ok_object(serialize(job))
