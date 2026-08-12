"""Pricing exceptions."""
from flask import Blueprint, g, request

import db
from errors import already_terminal, err, invalid_state
from middleware import (
    body, check_enum, check_int, get_or_404, list_page, require_field, require_roles,
)
from response import success_list, success_obj
from services.analysis import app_frozen
from services.officer import refresh_officer

bp = Blueprint("pricing_exceptions", __name__)

KINDS = ("RATE_ABOVE_CAP", "RATE_BELOW_FLOOR", "FEE_WAIVER")
TERMINAL = ("DENIED", "WITHDRAWN", "EXPIRED", "RESCINDED")
LIST_ROLES = ("LoanOfficer", "FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector")


@bp.post("/fair-lending/pricing-exceptions")
@require_roles("LoanOfficer")
def create_exception():
    data = body()
    application_id = require_field(data, "application_id")
    kind = check_enum(require_field(data, "kind"), KINDS, "kind")
    requested_rate_bps = check_int(
        require_field(data, "requested_rate_bps"), "requested_rate_bps"
    )
    justification = require_field(data, "justification")
    app = get_or_404("applications", application_id, "Application")
    # Ownership: entity-backed LoanOfficer may act only on own applications.
    if g.user_id != app["loan_officer_id"]:
        raise err(
            "ERR_OWNERSHIP_MISMATCH",
            "LoanOfficer may only request exceptions on own applications",
        )
    if app["status"] != "VALIDATED":
        raise invalid_state("Application must be VALIDATED to request a pricing exception")
    officer = db.STORES["officers"].get(app["loan_officer_id"])
    if officer is None:
        raise err("ERR_NOT_FOUND", "LoanOfficer does not exist")
    if officer["status"] != "ACTIVE":
        raise err("ERR_OFFICER_SUSPENDED", "Owning loan officer is SUSPENDED")
    rec = db.new_record(
        {
            "application_id": app["id"],
            "loan_officer_id": app["loan_officer_id"],
            "kind": kind,
            "requested_rate_bps": requested_rate_bps,
            "justification": justification,
            "status": "REQUESTED",
            "decided_by_user_id": None,
            "decided_at": None,
        }
    )
    db.STORES["exceptions"][rec["id"]] = rec
    app["has_exception"] = "REQUESTED"
    db.touch(app)
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/pricing-exceptions")
@require_roles(*LIST_ROLES)
def list_exceptions():
    page, total, limit, offset = list_page(
        "exceptions",
        {
            "application_id": request.args.get("application_id"),
            "loan_officer_id": request.args.get("loan_officer_id"),
            "status": request.args.get("status"),
        },
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/pricing-exceptions/<exceptionId>")
@require_roles(*LIST_ROLES)
def get_exception(exceptionId):
    rec = get_or_404("exceptions", exceptionId, "PricingException")
    return success_obj(db.public(rec))


def _load_and_state(exceptionId):
    rec = get_or_404("exceptions", exceptionId, "PricingException")
    if rec["status"] in TERMINAL:
        raise already_terminal("PricingException is in terminal state %s" % rec["status"])
    return rec


def _decide(rec):
    rec["decided_by_user_id"] = g.user_id
    rec["decided_at"] = db.now_iso()


@bp.post("/fair-lending/pricing-exceptions/<exceptionId>/approve")
@require_roles("FairLendingOfficer", "ComplianceDirector")
def approve_exception(exceptionId):
    rec = _load_and_state(exceptionId)
    if rec["status"] != "REQUESTED" and rec["status"] != "ESCALATED":
        raise invalid_state("PricingException is not approvable in state %s" % rec["status"])
    officer = db.STORES["officers"].get(rec["loan_officer_id"])
    if officer is None:
        raise err("ERR_NOT_FOUND", "LoanOfficer does not exist")
    if officer["status"] != "ACTIVE":
        raise err("ERR_OFFICER_SUSPENDED", "Owning loan officer is SUSPENDED")
    # Conditional authority: ESCALATED exceptions or RED-tier owners require
    # the ComplianceDirector.
    if rec["status"] == "ESCALATED" or officer["monitoring_tier"] == "RED":
        if g.role != "ComplianceDirector":
            raise err(
                "ERR_DIRECTOR_APPROVAL_REQUIRED",
                "This exception requires ComplianceDirector approval",
            )
    app = db.STORES["applications"].get(rec["application_id"])
    rec["status"] = "APPROVED"
    _decide(rec)
    db.touch(rec)
    if app is not None:
        app["has_exception"] = "APPROVED"
        db.touch(app)
    officer["approved_exception_count"] += 1
    # Risk recompute; upward RED crossing escalates the officer's other
    # REQUESTED exceptions (one-way ratchet).
    refresh_officer(officer, force_touch=True)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/pricing-exceptions/<exceptionId>/deny")
@require_roles("FairLendingOfficer", "ComplianceDirector")
def deny_exception(exceptionId):
    rec = _load_and_state(exceptionId)
    if rec["status"] != "REQUESTED" and rec["status"] != "ESCALATED":
        raise invalid_state("PricingException is not deniable in state %s" % rec["status"])
    rec["status"] = "DENIED"
    _decide(rec)
    db.touch(rec)
    app = db.STORES["applications"].get(rec["application_id"])
    if app is not None:
        app["has_exception"] = "NONE"
        db.touch(app)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/pricing-exceptions/<exceptionId>/rescind")
@require_roles("FairLendingOfficer", "ComplianceDirector")
def rescind_exception(exceptionId):
    rec = _load_and_state(exceptionId)
    if rec["status"] != "APPROVED":
        raise invalid_state("Only an APPROVED exception can be rescinded")
    if app_frozen(rec["application_id"]):
        raise err(
            "ERR_APPLICATION_LOCKED",
            "Application is frozen in a FINALIZED/ARCHIVED analysis-run snapshot",
        )
    rec["status"] = "RESCINDED"
    db.touch(rec)
    app = db.STORES["applications"].get(rec["application_id"])
    if app is not None:
        app["has_exception"] = "NONE"
        db.touch(app)
    officer = db.STORES["officers"].get(rec["loan_officer_id"])
    if officer is not None:
        officer["approved_exception_count"] -= 1
        # Compensating recompute; de-escalation never un-escalates ESCALATED
        # exceptions (one-way ratchet).
        refresh_officer(officer, force_touch=True)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/pricing-exceptions/<exceptionId>/withdraw")
@require_roles("LoanOfficer")
def withdraw_exception(exceptionId):
    rec = get_or_404("exceptions", exceptionId, "PricingException")
    if g.user_id != rec["loan_officer_id"]:
        raise err(
            "ERR_OWNERSHIP_MISMATCH",
            "Only the owning loan officer may withdraw this exception",
        )
    if rec["status"] in TERMINAL:
        raise already_terminal("PricingException is in terminal state %s" % rec["status"])
    if rec["status"] != "REQUESTED" and rec["status"] != "ESCALATED":
        raise invalid_state("PricingException is not withdrawable in state %s" % rec["status"])
    rec["status"] = "WITHDRAWN"
    db.touch(rec)
    app = db.STORES["applications"].get(rec["application_id"])
    if app is not None:
        app["has_exception"] = "NONE"
        db.touch(app)
    return success_obj(db.public(rec))
