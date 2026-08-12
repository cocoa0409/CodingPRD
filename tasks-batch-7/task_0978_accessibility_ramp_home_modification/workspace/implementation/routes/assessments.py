"""Assessment endpoints."""
from decimal import Decimal
from flask import Blueprint

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, get_child_or_404, require_case_active,
    req_str, req_enum, req_dt, req_int, req_array, opt_str, opt_array,
    opt_bool, opt_num, now, now_iso, iso,
)
from domain import (
    mutate_case, safety_risk_index, ada_compliance_pct, ADA_WEIGHTS,
)

bp = Blueprint("assessments", __name__)

ASSESSOR_ROLES = ("OT", "CAPS", "BOTH")
ASSESSMENT_TYPES = ("INITIAL", "REASSESSMENT", "POST_INSTALL")


def _get_assessment(case_id, assessment_id):
    case = get_case_or_404(case_id)
    rec = get_child_or_404("assessments", assessment_id, "case_id", case_id,
                           "ERR_ASSESSMENT_NOT_FOUND", "Assessment")
    return case, rec


def _factor_scores(b, mobility_score):
    factors = {}
    for name, _w in ADA_WEIGHTS:
        v = b.get(name)
        if v is None:
            v = b.get(name + "_score")
        if v is None:
            factors[name] = None
        else:
            d = opt_num(b, name)
            if d is None:
                d = opt_num(b, name + "_score")
            factors[name] = d if d is not None else Decimal(str(mobility_score))
    return factors


@bp.route("/cases/<caseId>/assessments", methods=["POST"])
def create_assessment(caseId):
    require_roles("IntakeCoordinator", "Assessor")
    case = get_case_or_404(caseId)
    require_case_active(case)
    b = body()
    assessor_id = req_str(b, "assessor_id")
    assessor_role = req_enum(b, "assessor_role", ASSESSOR_ROLES)
    assessment_type = req_enum(b, "assessment_type", ASSESSMENT_TYPES)
    scheduled = req_dt(b, "scheduled_date")
    mobility = req_int(b, "mobility_score")
    hazards = req_int(b, "hazard_count")
    mods = opt_array(b, "recommended_modifications", [])
    notes = opt_str(b, "notes")
    if scheduled < now():
        raise ApiError("ERR_INVALID_SCHEDULE_DATE", 422,
                       "Scheduled date is in the past or invalid")

    rec = new_record()
    rec.update({
        "case_id": caseId,
        "assessor_id": assessor_id,
        "assessor_role": assessor_role,
        "assessment_type": assessment_type,
        "scheduled_date": iso(scheduled),
        "completed_date": None,
        "mobility_score": mobility,
        "hazard_count": hazards,
        "ada_compliance_pct": None,
        "caps_recommendation_score": None,
        "recommended_modifications": mods,
        "rental_eligible": None,
        "purchase_required": None,
        "status": "SCHEDULED",
        "notes": notes,
        "_scheduled_date_dt": scheduled,
    })
    db["assessments"][rec["id"]] = rec
    if case["status"] == "INTAKE":
        case["status"] = "ASSESSMENT_SCHEDULED"
        mutate_case(case)
    return ok_object(serialize(rec), 201)


@bp.route("/cases/<caseId>/assessments", methods=["GET"])
def list_assessments(caseId):
    require_roles()
    get_case_or_404(caseId)
    records = [a for a in db["assessments"].values() if a["case_id"] == caseId]
    return paginate(records)


@bp.route("/cases/<caseId>/assessments/<assessmentId>", methods=["GET"])
def get_assessment(caseId, assessmentId):
    require_roles()
    _case, rec = _get_assessment(caseId, assessmentId)
    return ok_object(serialize(rec))


@bp.route("/cases/<caseId>/assessments/<assessmentId>/start", methods=["POST"])
def start_assessment(caseId, assessmentId):
    require_roles("Assessor")
    case, rec = _get_assessment(caseId, assessmentId)
    require_case_active(case)
    if rec["status"] != "SCHEDULED":
        raise ApiError("ERR_ASSESSMENT_NOT_SCHEDULED", 409,
                       "Assessment must be SCHEDULED to start")
    if rec["_scheduled_date_dt"] > now():
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Assessment scheduled date has not been reached")
    rec["status"] = "IN_PROGRESS"
    touch(rec)
    return ok_object(serialize(rec))


@bp.route("/cases/<caseId>/assessments/<assessmentId>/complete", methods=["POST"])
def complete_assessment(caseId, assessmentId):
    require_roles("Assessor")
    case, rec = _get_assessment(caseId, assessmentId)
    require_case_active(case)
    if rec["status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Assessment must be IN_PROGRESS to complete")
    b = body()
    mobility = req_int(b, "mobility_score")
    hazards = req_int(b, "hazard_count")
    mods = req_array(b, "recommended_modifications")
    notes = opt_str(b, "notes")

    factors = _factor_scores(b, mobility)
    ada_pct = opt_num(b, "ada_compliance_pct")
    if ada_pct is not None:
        ada_pct_val = float(ada_pct)
    else:
        ada_pct_val = ada_compliance_pct(factors, mobility)
    caps = opt_num(b, "caps_recommendation_score")
    if caps is not None:
        caps_val = int(caps)
    else:
        caps_val = int(Decimal(str(ada_pct_val)).quantize(Decimal("1")))
    rental_eligible = opt_bool(b, "rental_eligible", True)
    purchase_required = opt_bool(b, "purchase_required", False)

    rec["mobility_score"] = mobility
    rec["hazard_count"] = hazards
    rec["recommended_modifications"] = mods
    if notes is not None:
        rec["notes"] = notes
    rec["status"] = "COMPLETED"
    rec["completed_date"] = now_iso()
    rec["ada_compliance_pct"] = ada_pct_val
    rec["caps_recommendation_score"] = caps_val
    rec["rental_eligible"] = rental_eligible
    rec["purchase_required"] = purchase_required
    touch(rec)

    # Case re-evaluation: all INITIAL assessments completed -> ASSESSED.
    if case["status"] == "ASSESSMENT_SCHEDULED":
        initials = [a for a in db["assessments"].values()
                    if a["case_id"] == caseId and a["assessment_type"] == "INITIAL"]
        if initials and all(a["status"] == "COMPLETED" for a in initials):
            case["status"] = "ASSESSED"
            latest = max(
                (a for a in db["assessments"].values()
                 if a["case_id"] == caseId and a["status"] == "COMPLETED"),
                key=lambda a: (a["_seq"],), default=rec)
            case["ada_scope_score"] = int(
                Decimal(str(latest["ada_compliance_pct"] or 0)).quantize(
                    Decimal("1"), rounding="ROUND_HALF_UP"))
            case["caps_scope_score"] = latest["caps_recommendation_score"] or 0
    case["safety_risk_index"] = safety_risk_index(hazards, mobility)
    mutate_case(case)

    # Reassessment schedules: link and complete on reassessment completion.
    if rec["assessment_type"] in ("REASSESSMENT", "POST_INSTALL"):
        open_schedules = [s for s in db["reassessment_schedules"].values()
                          if s["case_id"] == caseId
                          and s["status"] in ("PENDING", "SCHEDULED")]
        if open_schedules:
            open_schedules.sort(key=lambda s: (s["_due_date_dt"], s["_seq"]))
            sched = open_schedules[0]
            sched["status"] = "COMPLETED"
            sched["linked_assessment_id"] = rec["id"]
            touch(sched)

    return ok_object(serialize(rec))


@bp.route("/cases/<caseId>/assessments/<assessmentId>/cancel", methods=["POST"])
def cancel_assessment(caseId, assessmentId):
    require_roles("IntakeCoordinator")
    case, rec = _get_assessment(caseId, assessmentId)
    require_case_active(case)
    if rec["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Assessment cannot be cancelled from its current state")
    rec["status"] = "CANCELLED"
    touch(rec)
    return ok_object(serialize(rec))
