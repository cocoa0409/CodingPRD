"""Escalation endpoints: manual open, list (case/estimate), approve, reject."""

from flask import Blueprint

from db import db
from errors import (
    ApiError,
    ERR_INVALID_REQUEST,
    ERR_SOD,
    invalid_state,
    not_found,
)
from middleware import ALL_ROLES, authenticate
from response import ok_list, ok_object
from services import (
    case_escalations,
    create_escalation,
    recompute_case,
    regress_case_if_cleared,
)
from util import (
    get_body,
    opt_str,
    paginate,
    req_enum,
    serialize,
    touch,
)

bp = Blueprint("escalations", __name__)


def get_escalation_or_404(eid):
    rec = db.escalations.get(eid)
    if rec is None:
        raise not_found("escalation not found")
    return rec


@bp.post("/clearance/cases/<cid>/escalations")
def open_escalation(cid):
    uid, _ = authenticate(["FinancialCounselor", "ClearanceSupervisor"])
    case = db.cases.get(cid)
    if case is None:
        raise not_found("case not found")
    b = get_body()
    reason = req_enum(b, "reason", ("HIGH_DOLLAR", "AUTH_EXCEPTION", "GFE_DISPUTE"))
    estimate_id = b.get("estimate_id")
    if estimate_id is not None:
        if not isinstance(estimate_id, str):
            raise ApiError(ERR_INVALID_REQUEST, "estimate_id must be a string", 400)
        est = db.estimates.get(estimate_id)
        if est is None or est["case_id"] != cid:
            raise ApiError(ERR_INVALID_REQUEST, "estimate_id does not reference an estimate of this case", 400)
    opt_str(b, "note")  # accepted at open; decision_note is recorded at approve/reject

    if reason == "AUTH_EXCEPTION":
        estimate_id = None
        trigger_amount = 0
    elif estimate_id is not None:
        est = db.estimates[estimate_id]
        if reason == "HIGH_DOLLAR":
            trigger_amount = est["patient_responsibility_cents"]
        else:  # GFE_DISPUTE manual
            billed = est["finalized_actual_billed_cents"] or 0
            trigger_amount = max(0, billed - est["gfe_total_cents"])
    else:
        trigger_amount = 0

    rec = create_escalation(
        case,
        reason=reason,
        estimate_id=estimate_id,
        trigger_amount_cents=trigger_amount,
        opened_by=uid,
    )
    # an open escalation immediately blocks clearance; a CLEARED case regresses
    recompute_case(case)
    regress_case_if_cleared(case)
    touch(case)
    return ok_object(serialize(rec), 201)


@bp.get("/clearance/cases/<cid>/escalations")
def list_case_escalations(cid):
    authenticate(ALL_ROLES)
    if cid not in db.cases:
        raise not_found("case not found")
    page, meta = paginate(case_escalations(cid))
    return ok_list([serialize(e) for e in page], meta)


@bp.get("/clearance/estimates/<eid>/escalations")
def list_estimate_escalations(eid):
    authenticate(ALL_ROLES)
    if eid not in db.estimates:
        raise not_found("estimate not found")
    items = [e for e in db.escalations.values() if e["estimate_id"] == eid]
    page, meta = paginate(items)
    return ok_list([serialize(e) for e in page], meta)


def _decide_escalation(eid, target_status):
    uid, _ = authenticate(["ClearanceSupervisor"])
    esc = get_escalation_or_404(eid)
    b = get_body()
    decision_note = opt_str(b, "decision_note")
    if esc["status"] != "OPEN":
        raise invalid_state("only an OPEN escalation can be decided")
    # segregation of duties; system-opened escalations are exempt
    if esc["opened_by_user_id"] != "system" and uid == esc["opened_by_user_id"]:
        raise ApiError(ERR_SOD, "the decider must differ from the escalation opener", 403)
    esc["status"] = target_status
    esc["decided_by_user_id"] = uid
    if decision_note is not None:
        esc["decision_note"] = decision_note
    touch(esc)
    case = db.cases[esc["case_id"]]
    if recompute_case(case):
        touch(case)
    return ok_object(serialize(esc))


@bp.post("/clearance/escalations/<eid>/approve")
def approve_escalation(eid):
    return _decide_escalation(eid, "APPROVED")


@bp.post("/clearance/escalations/<eid>/reject")
def reject_escalation(eid):
    return _decide_escalation(eid, "REJECTED")
