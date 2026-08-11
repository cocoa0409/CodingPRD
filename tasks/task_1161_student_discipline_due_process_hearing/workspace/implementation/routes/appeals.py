"""Appeals (PRD §3.4)."""
from flask import Blueprint

from db import db, stamp, touch, serialize, clock
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_APPEAL_WINDOW_CLOSED,
    ERR_APPEAL_ALREADY_OPEN,
)
from middleware import endpoint
from response import success
from routes.common import get_or_404, guardian_owns, render_list
from services.calc import current_issued_notice
from services.cascade import appeal_reversal_cascade

bp = Blueprint("appeals", __name__)


@bp.post("/cases/<cid>/appeals")
@endpoint("ParentGuardian")
def file_appeal(ctx, cid):
    case = get_or_404(db.cases, cid, "case")
    guardian_owns(ctx, db.students[case["student_id"]])
    grounds = ctx.body.get("grounds")
    if not isinstance(grounds, str):
        raise_err(ERR_INVALID_REQUEST, "grounds is required")
    if case["status"] != "NOTICE_ISSUED":
        raise_err(ERR_INVALID_STATE, "case must be NOTICE_ISSUED to file an appeal")
    notice = current_issued_notice(cid)
    if notice is None:
        raise_err(ERR_INVALID_STATE, "case has no issued notice")
    if clock() > notice["appeal_deadline"]:
        raise_err(ERR_APPEAL_WINDOW_CLOSED, "appeal filing window has closed")
    if any(a["case_id"] == cid and a["status"] == "FILED" for a in db.appeals.values()):
        raise_err(ERR_APPEAL_ALREADY_OPEN, "an appeal is already open for this case")

    appeal = stamp(
        {
            "case_id": cid,
            "filed_by": ctx.user_id,
            "grounds": grounds,
            "filed_at": clock(),
            "status": "FILED",
            "decided_at": None,
            "decision_rationale": None,
        }
    )
    db.appeals[appeal["id"]] = appeal
    return success(serialize(appeal), 201)


@bp.get("/cases/<cid>/appeals")
@endpoint("DistrictAdmin", "SchoolAdministrator", "ParentGuardian")
def list_appeals(ctx, cid):
    case = get_or_404(db.cases, cid, "case")
    if ctx.role == "ParentGuardian":
        guardian_owns(ctx, db.students[case["student_id"]])
    appeals = {k: v for k, v in db.appeals.items() if v["case_id"] == cid}
    return render_list(appeals)


@bp.post("/appeals/<aid>/decision")
@endpoint("DistrictAdmin")
def decide_appeal(ctx, aid):
    appeal = get_or_404(db.appeals, aid, "appeal")
    case = db.cases[appeal["case_id"]]
    # Segregation of duties (rung 4): decider must not be referrer or classifier
    if ctx.user_id in (case["referrer_id"], case["classified_by"]):
        raise_err(ERR_SEGREGATION_OF_DUTIES, "decider participated in an earlier step of this case")
    b = ctx.body
    outcome = b.get("outcome")
    rationale = b.get("rationale")
    if outcome not in ("UPHELD", "REVERSED", "REMANDED"):
        raise_err(ERR_INVALID_REQUEST, "outcome must be UPHELD, REVERSED, or REMANDED")
    if rationale is not None and not isinstance(rationale, str):
        raise_err(ERR_INVALID_REQUEST, "rationale must be a string")
    if appeal["status"] != "FILED":
        raise_err(ERR_INVALID_STATE, "appeal is not FILED")

    appeal["status"] = outcome
    appeal["decided_at"] = clock()
    appeal["decision_rationale"] = rationale
    touch(appeal)

    if outcome == "REVERSED":
        appeal_reversal_cascade(case, remanded=False)
    elif outcome == "REMANDED":
        appeal_reversal_cascade(case, remanded=True)
    # UPHELD leaves the case untouched
    return success(serialize(appeal))
