"""AssessmentAdjustment endpoints (PRD 3.7)."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import bad, body, guard, req_enum, req_id, req_int, req_str
from routes.common import (
    ADJUSTMENT_KINDS,
    ADJUSTMENT_STATUSES,
    SYSTEM_ONLY_KINDS,
    apply_filter,
    body_fk,
    listing,
    one,
    path_get,
)
from services import derive

bp = Blueprint("adjustments", __name__)

LEDGER_CLOSED_STATUSES = ("SUPERSEDED", "WITHDRAWN")


@bp.post("/assessment-adjustments")
@guard("AuditSupervisor", "CollectionsAgent")
def create_adjustment():
    data = body()
    assessment_id = req_id(data, "assessment_id")
    expected_version = req_int(data, "expected_assessment_version", 0)
    kind = req_enum(data, "kind", ADJUSTMENT_KINDS)
    amount = req_int(data, "amount_cents", 0)
    if "abatement_factors" in data:
        bad("abatement_factors is not accepted on this endpoint.")

    assessment = body_fk("assessments", assessment_id)
    if assessment["status"] in LEDGER_CLOSED_STATUSES:
        raise ApiError("ERR_INVALID_STATE")
    if expected_version != assessment["version"]:
        raise ApiError("ERR_STALE_ASSESSMENT_VERSION")

    derive.refresh_assessment(assessment)
    if amount > int(assessment["balance_due_cents"]):
        raise ApiError("ERR_ADJUSTMENT_EXCEEDS_BALANCE")
    if kind in SYSTEM_ONLY_KINDS:
        raise ApiError("ERR_ADJUSTMENT_KIND_SYSTEM_ONLY")

    rec = derive.post_adjustment(assessment, kind, amount, "MANUAL")
    derive.settle_balance(assessment)
    db.touch(assessment)
    return one("assessment_adjustments", rec, 201)


@bp.get("/assessment-adjustments")
@guard("AuditSupervisor", "CollectionsAgent", "AppealsOfficer", "Taxpayer")
def list_adjustments():
    rows = db.all_of("assessment_adjustments")
    rows = apply_filter(rows, "assessment_id")
    rows = apply_filter(rows, "appeal_proceeding_id")
    rows = apply_filter(rows, "kind", ADJUSTMENT_KINDS)
    rows = apply_filter(rows, "status", ADJUSTMENT_STATUSES)
    return listing("assessment_adjustments", rows)


@bp.get("/assessment-adjustments/<jid>")
@guard("AuditSupervisor", "CollectionsAgent", "AppealsOfficer", "Taxpayer")
def read_adjustment(jid):
    return one("assessment_adjustments", path_get("assessment_adjustments", jid))


@bp.post("/assessment-adjustments/<jid>/reverse")
@guard("AuditSupervisor")
def reverse_adjustment(jid):
    rec = path_get("assessment_adjustments", jid)
    data = body()
    reason = req_str(data, "reversal_reason", 1, None)

    if rec["status"] != "POSTED":
        raise ApiError("ERR_INVALID_STATE")

    rec["status"] = "REVERSED"
    rec["reversal_reason"] = reason
    db.touch(rec)
    assessment = db.get("assessments", rec["assessment_id"])
    if assessment is not None:
        derive.settle_balance(assessment)
        db.touch(assessment)
    return one("assessment_adjustments", rec)
