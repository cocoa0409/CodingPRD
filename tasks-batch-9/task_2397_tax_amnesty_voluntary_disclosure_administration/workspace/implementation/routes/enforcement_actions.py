"""Post-program enforcement escalation."""

from flask import Blueprint

import calc
import clock
import db
import middleware as mw
import response
import services
import validate
from errors import err
from middleware import (COMPLIANCE_AUDITOR, DISCLOSURE_OFFICER,
                        PROGRAM_ADMINISTRATOR)

bp = Blueprint("enforcement_actions", __name__)

READERS = [PROGRAM_ADMINISTRATOR, DISCLOSURE_OFFICER, COMPLIANCE_AUDITOR]


@bp.post("/amnesty/enforcement-actions")
def create_action():
    user_id, _ = mw.identity([COMPLIANCE_AUDITOR])
    body = validate.get_body()
    taxpayer = mw.body_fk(body, "taxpayer_id", db.taxpayers, "ERR_TAXPAYER_NOT_FOUND")
    program = mw.body_fk(body, "program_id", db.programs, "ERR_PROGRAM_NOT_FOUND")
    mw.body_fk(body, "agreement_id", db.agreements, "ERR_AGREEMENT_NOT_FOUND")

    taxpayer_id = validate.vid(body, "taxpayer_id")
    program_id = validate.vid(body, "program_id")
    action_type = validate.venum(body, "action_type", validate.ACTION_TYPES)
    base_tax = validate.vint(body, "base_tax_cents", minimum=1)
    agreement_id = validate.vid(body, "agreement_id", required=False)

    # the posture is snapshotted so later record changes cannot move the penalty
    tier = services.escalation_tier(taxpayer)
    score = services.historical_score(taxpayer)
    multiplier = (program["post_program_penalty_multiplier"]
                  if taxpayer["nonparticipant_flag"] else 1.00)
    adjustment = calc.BEHAVIOR_ADJUSTMENT_RATE if score < calc.BEHAVIOR_SCORE_FLOOR else calc.dec(0)
    penalty = calc.post_program_penalty(base_tax, tier, adjustment, multiplier)

    rec = db.insert(db.enforcement_actions, {
        "taxpayer_id": taxpayer_id,
        "program_id": program_id,
        "agreement_id": agreement_id,
        "action_type": action_type,
        "base_tax_cents": base_tax,
        "escalation_tier_applied": tier,
        "multiplier_applied": float(calc.dec(multiplier)),
        "behavior_adjustment_applied": calc.pct_out(adjustment),
        "assessed_penalty_cents": penalty,
        "status": "DRAFT",
        "origin": "MANUAL",
        "created_by_user_id": user_id,
        "issued_by_user_id": None,
        "issued_at": None,
        "abatement_reason": None,
    })
    return response.created(services.action_out(rec))


@bp.get("/amnesty/enforcement-actions")
def list_actions():
    mw.identity(READERS)
    limit, offset = response.pagination()
    rows = db.ordered(list(db.enforcement_actions.values()))
    for field in ("taxpayer_id", "program_id", "agreement_id", "status", "origin"):
        rows = mw.filter_equals(rows, field)
    return response.paginate(rows, limit, offset, services.action_out)


@bp.get("/amnesty/enforcement-actions/<action_id>")
def read_action(action_id):
    mw.identity(READERS)
    rec = mw.find(db.enforcement_actions, action_id, "ERR_ENFORCEMENT_ACTION_NOT_FOUND")
    return response.ok(services.action_out(rec))


@bp.post("/amnesty/enforcement-actions/<action_id>/issue")
def issue_action(action_id):
    user_id, _ = mw.identity([COMPLIANCE_AUDITOR])
    rec = mw.find(db.enforcement_actions, action_id, "ERR_ENFORCEMENT_ACTION_NOT_FOUND")
    program = db.programs.get(rec["program_id"])
    if program is None or program["status"] not in ("CLOSED", "RECONCILED"):
        raise err("ERR_PROGRAM_NOT_CLOSED")
    if rec["status"] != "DRAFT":
        raise err("ERR_ACTION_NOT_DRAFT")
    mw.require_segregation(rec["created_by_user_id"], user_id)

    rec["status"] = "ISSUED"
    rec["issued_by_user_id"] = user_id
    rec["issued_at"] = clock.now_iso()
    db.touch(rec)
    return response.ok(services.action_out(rec))


@bp.post("/amnesty/enforcement-actions/<action_id>/abate")
def abate_action(action_id):
    mw.identity([COMPLIANCE_AUDITOR])
    rec = mw.find(db.enforcement_actions, action_id, "ERR_ENFORCEMENT_ACTION_NOT_FOUND")
    body = validate.get_body()
    abatement_reason = validate.vstr(body, "abatement_reason")
    if rec["status"] != "ISSUED":
        raise err("ERR_ACTION_NOT_ISSUED")
    rec["status"] = "ABATED"
    rec["abatement_reason"] = abatement_reason
    db.touch(rec)
    return response.ok(services.action_out(rec))
