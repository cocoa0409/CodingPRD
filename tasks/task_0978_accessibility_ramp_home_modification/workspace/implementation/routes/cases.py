"""Case endpoints."""
from flask import Blueprint

from core import (
    db, ApiError, body, ok_object, paginate, new_record, touch, serialize,
    require_roles, get_case_or_404, opt_enum, req_str,
)
from domain import (
    mutate_case, release_pending_allocations_for_quote,
    ACTIVE_RENTAL_STATUSES, NONTERMINAL_JOB_STATUSES,
)

bp = Blueprint("cases", __name__)

REFERRAL_SOURCES = ("PHYSICIAN", "OT", "VA", "SELF", "AGENCY")
CANCELLABLE_STATES = (
    "INTAKE", "ASSESSMENT_SCHEDULED", "ASSESSED", "QUOTE_DRAFTED",
    "QUOTE_SUBMITTED", "FUNDING_PENDING", "FUNDING_APPROVED",
    "INSTALLATION_SCHEDULED",
)


@bp.route("/cases", methods=["POST"])
def create_case():
    require_roles("IntakeCoordinator")
    b = body()
    rec = new_record()
    rec.update({
        "client_name": req_str(b, "client_name"),
        "client_address": req_str(b, "client_address"),
        "client_phone": req_str(b, "client_phone"),
        "referral_source": opt_enum(b, "referral_source", REFERRAL_SOURCES, "SELF"),
        "status": "INTAKE",
        "funding_posture": "UNFUNDED",
        "total_quoted_cents": 0,
        "total_funded_cents": 0,
        "total_billed_cents": 0,
        "total_paid_cents": 0,
        "balance_due_cents": 0,
        "ada_scope_score": 0,
        "caps_scope_score": 0,
        "safety_risk_index": 0.0,
    })
    db["cases"][rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.route("/cases", methods=["GET"])
def list_cases():
    require_roles()
    status = None
    posture = None
    from flask import request
    status = request.args.get("status")
    posture = request.args.get("funding_posture")
    records = list(db["cases"].values())
    if status is not None:
        records = [c for c in records if c["status"] == status]
    if posture is not None:
        records = [c for c in records if c["funding_posture"] == posture]
    return paginate(records)


@bp.route("/cases/<caseId>", methods=["GET"])
def get_case(caseId):
    require_roles()
    return ok_object(serialize(get_case_or_404(caseId)))


@bp.route("/cases/<caseId>/cancel", methods=["POST"])
def cancel_case(caseId):
    require_roles("ProjectManager")
    case = get_case_or_404(caseId)
    if case["status"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_CASE_ALREADY_CLOSED", 409,
                       "Case is already closed or cancelled")
    if case["status"] not in CANCELLABLE_STATES:
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Case cannot be cancelled from its current state")
    for job in db["installation_jobs"].values():
        if job["case_id"] == caseId and job["status"] in NONTERMINAL_JOB_STATUSES:
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Case has a non-terminal installation job")
    for ramp in db["rental_ramps"].values():
        if ramp["case_id"] == caseId and ramp["status"] in ACTIVE_RENTAL_STATUSES:
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Case has an active rental ramp")

    case["status"] = "CANCELLED"
    # Cascade: non-terminal assessments cancelled.
    for a in db["assessments"].values():
        if a["case_id"] == caseId and a["status"] in ("SCHEDULED", "IN_PROGRESS"):
            a["status"] = "CANCELLED"
            touch(a)
    # Cascade: DRAFT/SUBMITTED quotes superseded, pending allocations released.
    for q in db["quotes"].values():
        if q["case_id"] == caseId and q["status"] in ("DRAFT", "SUBMITTED"):
            q["status"] = "SUPERSEDED"
            touch(q)
            release_pending_allocations_for_quote(q["id"])
    # Cascade: PENDING funding sources withdrawn, their pending allocations released.
    for s in db["funding_sources"].values():
        if s["case_id"] == caseId and s["status"] == "PENDING":
            s["status"] = "WITHDRAWN"
            touch(s)
            for a in db["funding_allocations"].values():
                if a["funding_source_id"] == s["id"] and a["status"] == "PENDING":
                    a["status"] = "RELEASED"
                    touch(a)
    # Cascade: SCHEDULED OT consultations cancelled.
    for c in db["ot_consultations"].values():
        if c["case_id"] == caseId and c["status"] == "SCHEDULED":
            c["status"] = "CANCELLED"
            touch(c)
    mutate_case(case)
    return ok_object(serialize(case))


@bp.route("/cases/<caseId>/close", methods=["POST"])
def close_case(caseId):
    require_roles("ProjectManager")
    case = get_case_or_404(caseId)
    if case["status"] in ("CLOSED", "CANCELLED"):
        raise ApiError("ERR_CASE_ALREADY_CLOSED", 409,
                       "Case is already closed or cancelled")
    if case["status"] != "WARRANT_ACTIVE":
        raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                       "Case must be WARRANTY_ACTIVE to close")
    for claim in db["warranty_claims"].values():
        if claim["case_id"] == caseId and claim["status"] == "OPEN":
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Case has an open warranty claim")
    for inv in db["invoices"].values():
        if inv["case_id"] == caseId and inv["status"] not in ("VOID",) and \
                inv["balance_cents"] > 0:
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Case has an unpaid invoice with a balance")
    for ramp in db["rental_ramps"].values():
        if ramp["case_id"] == caseId and ramp["status"] not in ("RETURNED", "CANCELLED"):
            raise ApiError("ERR_INVALID_STATE_TRANSITION", 409,
                           "Case has a rental ramp that is not returned or cancelled")
    case["status"] = "CLOSED"
    mutate_case(case)
    return ok_object(serialize(case))
