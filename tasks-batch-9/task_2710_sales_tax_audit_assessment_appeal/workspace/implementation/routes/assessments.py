"""Assessment endpoints (PRD 3.6, 3.7, 3.9)."""
from flask import Blueprint, g

import db
from errors import ApiError
from middleware import bad, body, guard, opt_str, req_date, req_id
from routes.common import (
    ABATEMENT_FACTORS,
    ARRANGEMENT_STATUSES,
    ARRANGEMENT_TYPES,
    ASSESSMENT_STATUSES,
    COLLECTION_STATUSES,
    apply_filter,
    body_fk,
    listing,
    one,
    path_get,
    require_owner,
)
from services import calc, derive, rollup

bp = Blueprint("assessments", __name__)

LIVE_NOTICE_STATUSES = ("DRAFT", "DRAFT_STALE", "ISSUED")


@bp.post("/assessments")
@guard("AuditSupervisor")
def create_assessment():
    data = body()
    audit_id = req_id(data, "audit_id")
    supersedes_id = data.get("supersedes_assessment_id")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        bad("supersedes_assessment_id must be a string.")

    audit = body_fk("audits", audit_id)
    superseded = body_fk("assessments", supersedes_id) if supersedes_id is not None else None

    if audit["status"] != "REVIEW_COMPLETE":
        raise ApiError("ERR_INVALID_STATE")
    if audit["projection_status"] != "CURRENT":
        raise ApiError("ERR_PROJECTION_STALE")

    live = [
        a for a in derive.assessments_of_audit(audit["id"])
        if a["status"] in LIVE_NOTICE_STATUSES
    ]
    for existing in live:
        if superseded is None or existing["id"] != superseded["id"]:
            raise ApiError("ERR_ASSESSMENT_ALREADY_OPEN")
    if superseded is not None and superseded["status"] not in LIVE_NOTICE_STATUSES:
        raise ApiError("ERR_INVALID_STATE")

    figures = rollup.compute(audit)
    rec = db.new_record(
        {
            "audit_id": audit["id"],
            "supersedes_assessment_id": superseded["id"] if superseded else None,
            "status": "DRAFT",
            "collection_status": "NOT_DUE",
            "collection_hold": False,
            "tax_deficiency_cents": figures["tax_deficiency_cents"],
            "penalty_rate_bp": figures["penalty_rate_bp"],
            "penalty_cents": figures["penalty_cents"],
            "interest_days": figures["interest_days"],
            "interest_cents": figures["interest_cents"],
            "provisional_total_due_cents": figures["provisional_total_due_cents"],
            "penalty_waived_small_balance": figures["penalty_waived_small_balance"],
            "total_due_cents": figures["total_due_cents"],
            "total_adjustments_cents": 0,
            "total_abated_cents": 0,
            "amount_paid_cents": 0,
            "balance_due_cents": figures["total_due_cents"],
            "notice_mailed_date": None,
            "protest_deadline_date": None,
            "issued_at": None,
        }
    )
    db.insert("assessments", rec)
    if superseded is not None:
        superseded["status"] = "SUPERSEDED"
        db.touch(superseded)
    return one("assessments", rec, 201)


@bp.get("/assessments")
@guard("AuditSupervisor", "CollectionsAgent", "AppealsOfficer", "TaxTribunalJudge", "Taxpayer")
def list_assessments():
    rows = db.all_of("assessments")
    if g.role == "Taxpayer":
        rows = [
            a for a in rows
            if (derive.taxpayer_of_assessment(a) or {}).get("id") == g.user_id
        ]
    rows = apply_filter(rows, "audit_id")
    rows = apply_filter(rows, "supersedes_assessment_id")
    rows = apply_filter(rows, "status", ASSESSMENT_STATUSES)
    rows = apply_filter(rows, "collection_status", COLLECTION_STATUSES)
    return listing("assessments", rows)


@bp.get("/assessments/<sid>")
@guard("AuditSupervisor", "CollectionsAgent", "AppealsOfficer", "TaxTribunalJudge", "Taxpayer")
def read_assessment(sid):
    assessment = path_get("assessments", sid)
    holder = derive.taxpayer_of_assessment(assessment)
    require_owner(holder["id"] if holder else None)
    return one("assessments", assessment)


@bp.post("/assessments/<sid>/recompute")
@guard("AuditSupervisor")
def recompute_assessment(sid):
    assessment = path_get("assessments", sid)
    body()
    if assessment["status"] != "DRAFT_STALE":
        raise ApiError("ERR_INVALID_STATE")
    audit = derive.audit_of_assessment(assessment)
    if audit is None or audit["projection_status"] != "CURRENT":
        raise ApiError("ERR_PROJECTION_STALE")

    rollup.apply_to(assessment, audit)
    assessment["status"] = "DRAFT"
    db.touch(assessment)
    return one("assessments", assessment)


@bp.post("/assessments/<sid>/issue")
@guard("AuditSupervisor")
def issue_assessment(sid):
    assessment = path_get("assessments", sid)
    data = body()
    mailed = req_date(data, "notice_mailed_date")

    if assessment["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE")
    audit = derive.audit_of_assessment(assessment)
    if audit is None or audit["status"] != "REVIEW_COMPLETE":
        raise ApiError("ERR_INVALID_STATE")
    if mailed != db.clock_date():
        raise ApiError("ERR_NOTICE_DATE_INVALID")
    if derive.audit_statute_status(audit) == "EXPIRED":
        raise ApiError("ERR_STATUTE_EXPIRED")

    assessment["status"] = "ISSUED"
    assessment["notice_mailed_date"] = db.format_date(mailed)
    assessment["protest_deadline_date"] = db.format_date(
        db.add_days(mailed, calc.PROTEST_WINDOW_DAYS)
    )
    assessment["issued_at"] = db.clock_instant_str()
    assessment["collection_status"] = "DUE"
    db.touch(assessment)
    audit["status"] = "ASSESSED"
    db.touch(audit)
    return one("assessments", assessment)


@bp.post("/assessments/<sid>/abate-penalty")
@guard("AuditSupervisor")
def abate_penalty(sid):
    assessment = path_get("assessments", sid)
    data = body()
    factors = data.get("abatement_factors")
    if not isinstance(factors, list) or isinstance(factors, bool) or not factors:
        bad("abatement_factors must be a non-empty array.")
    for factor in factors:
        if not isinstance(factor, str) or factor not in ABATEMENT_FACTORS:
            bad("abatement_factors may only name recognized factors.")

    if assessment["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    if derive.has_open_proceeding(assessment["id"]):
        raise ApiError("ERR_APPEAL_PENDING")

    audit = derive.audit_of_assessment(assessment)
    holder = derive.taxpayer_of_assessment(assessment)
    if audit is not None and audit.get("fraud_indicator"):
        raise ApiError("ERR_ABATEMENT_NOT_ALLOWED")
    delinquent = bool(holder and holder["compliance_status"] == "DELINQUENT")
    pct = calc.abatement_pct(factors, delinquent)
    if assessment["penalty_waived_small_balance"]:
        raise ApiError("ERR_ABATEMENT_NOT_ALLOWED")
    if int(assessment["penalty_cents"]) <= 0:
        raise ApiError("ERR_ABATEMENT_NOT_ALLOWED")

    amount = calc.rhu(int(assessment["penalty_cents"]) * pct, 100)
    derive.post_adjustment(
        assessment,
        "PENALTY_ABATEMENT",
        amount,
        "SYSTEM",
        abatement_factors=list(factors),
        abatement_pct=pct,
    )
    derive.settle_balance(assessment)
    db.touch(assessment)
    return one("assessments", assessment)


@bp.post("/assessments/<sid>/finalize")
@guard("AuditSupervisor")
def finalize_assessment(sid):
    assessment = path_get("assessments", sid)
    body()
    if assessment["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    if derive.has_open_proceeding(assessment["id"]):
        raise ApiError("ERR_APPEAL_PENDING")

    today = db.clock_date()
    deadline = db.parse_date(assessment.get("protest_deadline_date"))
    if deadline is None or today <= deadline:
        raise ApiError("ERR_ASSESSMENT_NOT_FINALIZABLE")
    for prc in derive.proceedings_of_assessment(assessment["id"]):
        if prc["status"] != "DECIDED":
            continue
        escalation = db.parse_date(prc.get("escalation_deadline_date"))
        if escalation is not None and today <= escalation:
            raise ApiError("ERR_ASSESSMENT_NOT_FINALIZABLE")

    derive.finalize_notice(assessment)
    return one("assessments", assessment)


@bp.post("/assessments/<sid>/collection-referral")
@guard("CollectionsAgent")
def refer_assessment(sid):
    assessment = path_get("assessments", sid)
    data = body()
    opt_str(data, "referral_note", 1, None, None)

    if assessment["collection_status"] not in ("DUE", "ARRANGED"):
        raise ApiError("ERR_INVALID_STATE")
    if assessment["collection_hold"]:
        raise ApiError("ERR_INVALID_STATE")

    derive.refresh_assessment(assessment)
    # collection_fee already returns the negative charge
    fee = calc.collection_fee(int(assessment["balance_due_cents"]))
    assessment["collection_status"] = "REFERRED"
    derive.post_adjustment(assessment, "COLLECTION_FEE", fee, "SYSTEM")
    derive.refresh_assessment(assessment)
    db.touch(assessment)
    holder = derive.taxpayer_of_assessment(assessment)
    if holder is not None and holder["compliance_status"] != "DELINQUENT":
        holder["compliance_status"] = "DELINQUENT"
        db.touch(holder)
    return one("assessments", assessment)


@bp.get("/assessments/<sid>/payment-arrangements")
@guard("CollectionsAgent", "AuditSupervisor", "Taxpayer")
def list_arrangements_of_assessment(sid):
    assessment = path_get("assessments", sid)
    rows = derive.arrangements_of_assessment(assessment["id"])
    rows = apply_filter(rows, "arrangement_type", ARRANGEMENT_TYPES)
    rows = apply_filter(rows, "status", ARRANGEMENT_STATUSES)
    return listing("payment_arrangements", rows)
