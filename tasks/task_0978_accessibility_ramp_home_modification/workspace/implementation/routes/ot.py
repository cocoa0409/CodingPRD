"""OT consultation endpoints."""
from flask import Blueprint

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, get_child_or_404, require_case_active,
    req_str, req_enum, req_dt, req_array, opt_array, opt_bool, now_iso, iso,
)

bp = Blueprint("ot", __name__)

CONSULTATION_TYPES = ("INITIAL_EVAL", "FOLLOW_UP", "DISCHARGE_PLANNING", "HOME_SAFETY")


def _get_consult(case_id, consult_id):
    case = get_case_or_404(case_id)
    rec = get_child_or_404("ot_consultations", consult_id, "case_id", case_id,
                           "ERR_CONSULT_NOT_FOUND", "OT consultation")
    return case, rec


@bp.route("/cases/<caseId>/ot-consultations", methods=["POST"])
def create_consultation(caseId):
    require_roles("IntakeCoordinator", "Assessor")
    case = get_case_or_404(caseId)
    require_case_active(case)
    b = body()
    scheduled = req_dt(b, "scheduled_date")
    rec = new_record()
    rec.update({
        "case_id": caseId,
        "ot_provider_id": req_str(b, "ot_provider_id"),
        "consultation_type": req_enum(b, "consultation_type", CONSULTATION_TYPES),
        "scheduled_date": iso(scheduled),
        "completed_date": None,
        "status": "SCHEDULED",
        "goals": req_array(b, "goals"),
        "recommendations": None,
        "clearance_given": None,
        "_scheduled_date_dt": scheduled,
    })
    db["ot_consultations"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/ot-consultations", methods=["GET"])
def list_consultations(caseId):
    require_roles()
    get_case_or_404(caseId)
    records = [c for c in db["ot_consultations"].values() if c["case_id"] == caseId]
    return paginate(records)


@bp.route("/cases/<caseId>/ot-consultations/<consultId>", methods=["GET"])
def get_consultation(caseId, consultId):
    require_roles()
    _case, rec = _get_consult(caseId, consultId)
    return ok_object(serialize(rec))


@bp.route("/cases/<caseId>/ot-consultations/<consultId>/complete", methods=["POST"])
def complete_consultation(caseId, consultId):
    require_roles("Assessor")
    case, rec = _get_consult(caseId, consultId)
    require_case_active(case)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Consultation must be SCHEDULED to complete")
    b = body()
    recommendations = req_array(b, "recommendations")
    rec["status"] = "COMPLETED"
    rec["completed_date"] = now_iso()
    rec["recommendations"] = recommendations
    rec["clearance_given"] = opt_bool(b, "clearance_given", False)
    touch(rec)
    return ok_object(serialize(rec))


@bp.route("/cases/<caseId>/ot-consultations/<consultId>/cancel", methods=["POST"])
def cancel_consultation(caseId, consultId):
    require_roles("IntakeCoordinator")
    case, rec = _get_consult(caseId, consultId)
    require_case_active(case)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Consultation must be SCHEDULED to cancel")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(serialize(rec))
