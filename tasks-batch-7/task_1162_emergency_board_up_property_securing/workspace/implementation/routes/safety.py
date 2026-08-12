"""Safety assessment endpoints."""
from flask import Blueprint, request
import db
from errors import err
from middleware import require_role, get_body, require_fields, check_enum, paginate_args
from response import success_obj, success_list
from services.common import (
    base_record, touch, get_or_404, serialize_safety_assessment,
    compute_hazard_score, hazard_level, find_current_assignment,
    HAZARD_WEIGHTS,
)

bp = Blueprint("safety", __name__)


def _apply_clearance(job):
    job["safety_cleared"] = True
    if job["work_status"] == "BREACH_HOLD":
        job["work_status"] = "ON_SITE"
    touch(job)


@bp.route("/jobs/<jid>/safety-assessments", methods=["POST"])
def create_assessment(jid):
    user_id, _ = require_role("Subcontractor")
    job = get_or_404(db.jobs, jid, "Job")
    body = get_body()
    require_fields(body, ["hazards"])
    hazards = body["hazards"]
    if not isinstance(hazards, list):
        raise err("ERR_INVALID_REQUEST", "hazards must be an array")
    for h in hazards:
        if h not in HAZARD_WEIGHTS:
            raise err("ERR_INVALID_ENUM", "Invalid hazard: %r" % h)
    if job["work_status"] == "CLOSED":
        raise err("ERR_ALREADY_TERMINAL", "Job is CLOSED")
    if job["work_status"] not in ("ON_SITE", "BREACH_HOLD"):
        raise err("ERR_INVALID_STATE", "Job must be ON_SITE or BREACH_HOLD")
    # creator must be ACTIVE subcontractor
    sub = db.subcontractors.get(user_id)
    if sub is None:
        raise err("ERR_NOT_FOUND", "Subcontractor not found")
    if sub["status"] != "ACTIVE":
        raise err("ERR_SUBCONTRACTOR_SUSPENDED", "Subcontractor is suspended")
    # Segregation of duties: creator must differ from job's assignee — the
    # currently accepted assignment, which in BREACH_HOLD has already advanced
    # to COMPLETED (PRD §2.1, §3.4).
    assignee = find_current_assignment(job["id"])
    if assignee is not None and assignee["subcontractor_id"] == user_id:
        raise err("ERR_SEGREGATION_OF_DUTIES", "Assessor must differ from assignee")
    # Supersede prior open assessments
    for prev in db.safety_assessments.values():
        if prev["job_id"] == job["id"] and prev["status"] in ("SUBMITTED", "MITIGATION_REQUIRED"):
            prev["status"] = "SUPERSEDED"
            touch(prev)
    score = compute_hazard_score(hazards)
    level = hazard_level(score)
    rec = base_record()
    rec.update({
        "job_id": job["id"],
        "assessor_subcontractor_id": user_id,
        "hazards": list(hazards),
        "structural_risk_score": score,
        "hazard_level": level,
        "moderate_ppe_required": (level == "MODERATE"),
        "status": "SUBMITTED",
        "mitigation_note": None,
    })
    db.safety_assessments[rec["id"]] = rec
    # Auto-transition based on score
    if score >= 70:
        rec["status"] = "MITIGATION_REQUIRED"
        touch(rec)
    else:
        rec["status"] = "CLEARED"
        touch(rec)
        _apply_clearance(job)
    return success_obj(serialize_safety_assessment(rec), 201)


@bp.route("/safety-assessments/<aid>", methods=["GET"])
def get_assessment(aid):
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    rec = get_or_404(db.safety_assessments, aid, "SafetyAssessment")
    return success_obj(serialize_safety_assessment(rec))


@bp.route("/safety-assessments", methods=["GET"])
def list_assessments():
    require_role("PlatformAdmin", "Dispatcher", "Customer", "Subcontractor")
    limit, offset = paginate_args()
    items = list(db.safety_assessments.values())
    jid = request.args.get("job_id")
    sid = request.args.get("assessor_subcontractor_id")
    if jid:
        items = [a for a in items if a["job_id"] == jid]
    if sid:
        items = [a for a in items if a["assessor_subcontractor_id"] == sid]
    items.sort(key=lambda a: a["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_safety_assessment(a) for a in page], total, limit, offset)


@bp.route("/safety-assessments/<aid>/mitigate", methods=["POST"])
def mitigate_assessment(aid):
    user_id, _ = require_role("Subcontractor")
    rec = get_or_404(db.safety_assessments, aid, "SafetyAssessment")
    body = get_body()
    require_fields(body, ["mitigation_note"])
    if rec["assessor_subcontractor_id"] != user_id:
        raise err("ERR_FORBIDDEN", "Caller is not the assessment author")
    if rec["status"] in ("CLEARED", "SUPERSEDED"):
        raise err("ERR_ALREADY_TERMINAL", "Assessment is terminal")
    if rec["status"] != "MITIGATION_REQUIRED":
        raise err("ERR_INVALID_STATE", "Assessment must be MITIGATION_REQUIRED")
    rec["mitigation_note"] = body["mitigation_note"]
    rec["status"] = "CLEARED"
    touch(rec)
    job = db.jobs.get(rec["job_id"])
    if job is not None:
        _apply_clearance(job)
    return success_obj(serialize_safety_assessment(rec))
