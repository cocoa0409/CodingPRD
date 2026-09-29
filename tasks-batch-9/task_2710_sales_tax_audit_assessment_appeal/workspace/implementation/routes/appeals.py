"""AppealProceeding endpoints (PRD 3.8)."""
from flask import Blueprint, g

import db
from errors import ApiError
from middleware import (
    bad,
    body,
    guard,
    opt_date,
    opt_str,
    present,
    req_date,
    req_enum,
    req_id,
    req_int,
    req_str,
)
from routes.common import (
    FORUMS,
    OUTCOMES,
    PROCEEDING_STATUSES,
    apply_filter,
    body_fk,
    listing,
    one,
    path_get,
    require_owner,
)
from services import calc, derive

bp = Blueprint("appeals", __name__)

DECISION_OUTCOMES = ("SUSTAINED", "REDUCED", "REMANDED")
FORUM_ROLES = {
    "INFORMAL_CONFERENCE": "AppealsOfficer",
    "ADMINISTRATIVE_APPEAL": "AppealsOfficer",
    "TAX_TRIBUNAL": "TaxTribunalJudge",
}


@bp.post("/appeal-proceedings")
@guard("Taxpayer")
def file_proceeding():
    data = body()
    assessment_id = req_id(data, "assessment_id")
    forum = req_enum(data, "forum", FORUMS)
    protest_basis = req_str(data, "protest_basis", 1, 500)
    opt_date(data, "filed_date")  # accepted for symmetry with the paper form, then ignored
    predecessor_id = data.get("predecessor_proceeding_id")
    if predecessor_id is not None and not isinstance(predecessor_id, str):
        bad("predecessor_proceeding_id must be a string.")

    assessment = body_fk("assessments", assessment_id)
    holder = derive.taxpayer_of_assessment(assessment)
    require_owner(holder["id"] if holder else None)
    predecessor = (
        body_fk("appeal_proceedings", predecessor_id) if predecessor_id is not None else None
    )

    if assessment["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE")

    today = db.clock_date()
    existing = derive.proceedings_of_assessment(assessment["id"])
    rung = calc.FORUM_LADDER.index(forum)

    if rung == 0:
        deadline = db.parse_date(assessment.get("protest_deadline_date"))
        if deadline is None or today > deadline:
            raise ApiError("ERR_PROTEST_WINDOW_CLOSED")
    else:
        if predecessor is None:
            raise ApiError("ERR_FORUM_SEQUENCE_INVALID")
        if predecessor["status"] != "DECIDED":
            raise ApiError("ERR_PREDECESSOR_NOT_DECIDED")
        escalation = db.parse_date(predecessor.get("escalation_deadline_date"))
        if escalation is None or today > escalation:
            raise ApiError("ERR_ESCALATION_WINDOW_CLOSED")
        if predecessor["forum"] != calc.FORUM_LADDER[rung - 1]:
            raise ApiError("ERR_FORUM_SEQUENCE_INVALID")

    for other in existing:
        if other["forum"] == forum:
            raise ApiError("ERR_FORUM_SEQUENCE_INVALID")

    rec = db.new_record(
        {
            "assessment_id": assessment["id"],
            "predecessor_proceeding_id": predecessor["id"] if predecessor else None,
            "forum": forum,
            "status": "OPEN",
            "outcome": "NONE",
            "protest_basis": protest_basis,
            "filed_date": db.format_date(today),
            "decided_date": None,
            "tolled_days": 0,
            "presiding_officer_user_id": None,
            "reduction_amount_cents": None,
            "escalation_deadline_date": None,
            "decision_rationale": None,
        }
    )
    db.insert("appeal_proceedings", rec)
    assessment["collection_hold"] = True
    db.touch(assessment)
    return one("appeal_proceedings", rec, 201)


@bp.get("/appeal-proceedings")
@guard("AppealsOfficer", "TaxTribunalJudge", "AuditSupervisor", "CollectionsAgent", "Taxpayer")
def list_proceedings():
    rows = db.all_of("appeal_proceedings")
    rows = apply_filter(rows, "assessment_id")
    rows = apply_filter(rows, "predecessor_proceeding_id")
    rows = apply_filter(rows, "forum", FORUMS)
    rows = apply_filter(rows, "status", PROCEEDING_STATUSES)
    rows = apply_filter(rows, "outcome", OUTCOMES)
    return listing("appeal_proceedings", rows)


@bp.get("/appeal-proceedings/<pid>")
@guard("AppealsOfficer", "TaxTribunalJudge", "AuditSupervisor", "CollectionsAgent", "Taxpayer")
def read_proceeding(pid):
    return one("appeal_proceedings", path_get("appeal_proceedings", pid))


@bp.post("/appeal-proceedings/<pid>/decision")
@guard("AppealsOfficer", "TaxTribunalJudge")
def decide_proceeding(pid):
    proceeding = path_get("appeal_proceedings", pid)
    data = body()
    outcome = req_enum(data, "outcome", DECISION_OUTCOMES)
    rationale = opt_str(data, "decision_rationale", 1, None, None)
    reduction = None
    if present(data, "reduction_amount_cents"):
        reduction = req_int(data, "reduction_amount_cents", 1)
    if outcome == "REDUCED":
        if reduction is None:
            bad("reduction_amount_cents is required on a REDUCED decision.")
    elif reduction is not None:
        bad("reduction_amount_cents is only accepted on a REDUCED decision.")

    if proceeding["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")

    assessment = db.get("assessments", proceeding["assessment_id"])
    audit = derive.audit_of_assessment(assessment) if assessment else None

    # tier 8 — segregation of duties
    if g.role != FORUM_ROLES[proceeding["forum"]]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if audit is not None and g.user_id == audit.get("lead_auditor_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    predecessor = db.get("appeal_proceedings", proceeding.get("predecessor_proceeding_id"))
    if predecessor is not None and g.user_id == predecessor.get("presiding_officer_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    if assessment is not None:
        derive.refresh_assessment(assessment)
    if outcome == "REDUCED" and assessment is not None:
        if reduction > int(assessment["balance_due_cents"]):
            raise ApiError("ERR_REDUCTION_EXCEEDS_BALANCE")
    if outcome == "REMANDED" and proceeding["forum"] == "TAX_TRIBUNAL":
        raise ApiError("ERR_FORUM_SEQUENCE_INVALID")

    today = db.clock_date()
    filed = db.parse_date(proceeding["filed_date"])
    proceeding["status"] = "DECIDED"
    proceeding["outcome"] = outcome
    proceeding["decided_date"] = db.format_date(today)
    proceeding["tolled_days"] = max(0, db.days_between(filed, today)) if filed else 0
    proceeding["presiding_officer_user_id"] = g.user_id
    proceeding["decision_rationale"] = rationale
    proceeding["reduction_amount_cents"] = reduction
    if proceeding["forum"] == "TAX_TRIBUNAL" or outcome == "REMANDED":
        proceeding["escalation_deadline_date"] = None
    else:
        proceeding["escalation_deadline_date"] = db.format_date(
            db.add_days(today, calc.ESCALATION_WINDOW_DAYS)
        )
    db.touch(proceeding)

    if assessment is not None:
        derive.clear_hold_if_settled(assessment)

        if outcome == "REDUCED":
            derive.post_adjustment(
                assessment,
                "APPEAL_REDUCTION",
                reduction,
                "SYSTEM",
                appeal_proceeding_id=proceeding["id"],
            )
            derive.settle_balance(assessment)
        elif outcome == "REMANDED":
            derive.post_adjustment(
                assessment,
                "ASSESSMENT_VACATED",
                int(assessment["balance_due_cents"]),
                "SYSTEM",
                appeal_proceeding_id=proceeding["id"],
            )
            derive.refresh_assessment(assessment)
            assessment["status"] = "WITHDRAWN"
            assessment["collection_status"] = "NOT_DUE"
            assessment["collection_hold"] = False
            for arr in derive.arrangements_of_assessment(assessment["id"]):
                if arr["status"] in ("REQUESTED", "APPROVED"):
                    arr["status"] = "CANCELLED"
                    db.touch(arr)

        if outcome in ("SUSTAINED", "REDUCED") and proceeding["forum"] == "TAX_TRIBUNAL":
            if assessment["status"] == "ISSUED":
                derive.finalize_notice(assessment)
            else:
                db.touch(assessment)
        else:
            db.touch(assessment)

    if audit is not None:
        if outcome == "REMANDED" and audit["status"] == "ASSESSED":
            audit["status"] = "FIELDWORK"
            audit["reopen_count"] = int(audit.get("reopen_count") or 0) + 1
            derive.mark_projection_stale(audit)
        derive.rewrite_statute(audit)
        db.touch(audit)
    return one("appeal_proceedings", proceeding)
