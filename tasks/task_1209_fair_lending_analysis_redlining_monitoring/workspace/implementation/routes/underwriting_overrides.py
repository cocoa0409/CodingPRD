"""Underwriting overrides."""
from flask import Blueprint, g, request

import db
from errors import already_terminal, err, invalid_state
from middleware import (
    body, check_enum, get_or_404, list_page, require_field, require_roles,
)
from response import success_list, success_obj
from services.officer import refresh_officer

bp = Blueprint("underwriting_overrides", __name__)

DECISIONS = ("APPROVE", "DENY")
LIST_ROLES = ("LoanOfficer", "FairLendingAnalyst", "FairLendingOfficer", "ComplianceDirector")


@bp.post("/fair-lending/underwriting-overrides")
@require_roles("LoanOfficer")
def create_override():
    data = body()
    application_id = require_field(data, "application_id")
    original = check_enum(
        require_field(data, "original_decision"), DECISIONS, "original_decision"
    )
    overridden = check_enum(
        require_field(data, "overridden_decision"), DECISIONS, "overridden_decision"
    )
    justification = require_field(data, "justification")
    app = get_or_404("applications", application_id, "Application")
    if g.user_id != app["loan_officer_id"]:
        raise err(
            "ERR_OWNERSHIP_MISMATCH",
            "LoanOfficer may only record overrides on own applications",
        )
    if app["status"] != "VALIDATED":
        raise invalid_state("Application must be VALIDATED to record an override")
    officer = db.STORES["officers"].get(app["loan_officer_id"])
    if officer is None:
        raise err("ERR_NOT_FOUND", "LoanOfficer does not exist")
    if officer["status"] != "ACTIVE":
        raise err("ERR_OFFICER_SUSPENDED", "Owning loan officer is SUSPENDED")
    if original == overridden:
        raise err(
            "ERR_INVALID_DECISION_PAIR",
            "original_decision and overridden_decision must differ",
        )
    rec = db.new_record(
        {
            "application_id": app["id"],
            "loan_officer_id": app["loan_officer_id"],
            "original_decision": original,
            "overridden_decision": overridden,
            "justification": justification,
            "status": "RECORDED",
        }
    )
    db.STORES["overrides"][rec["id"]] = rec
    return success_obj(db.public(rec), 201)


@bp.get("/fair-lending/underwriting-overrides")
@require_roles(*LIST_ROLES)
def list_overrides():
    page, total, limit, offset = list_page(
        "overrides",
        {
            "application_id": request.args.get("application_id"),
            "loan_officer_id": request.args.get("loan_officer_id"),
            "status": request.args.get("status"),
        },
    )
    return success_list([db.public(r) for r in page], total, limit, offset)


@bp.get("/fair-lending/underwriting-overrides/<overrideId>")
@require_roles(*LIST_ROLES)
def get_override(overrideId):
    rec = get_or_404("overrides", overrideId, "UnderwritingOverride")
    return success_obj(db.public(rec))


@bp.post("/fair-lending/underwriting-overrides/<overrideId>/confirm")
@require_roles("FairLendingOfficer")
def confirm_override(overrideId):
    rec = get_or_404("overrides", overrideId, "UnderwritingOverride")
    if rec["status"] in ("CONFIRMED", "REVERSED"):
        raise already_terminal("UnderwritingOverride is in terminal state %s" % rec["status"])
    if rec["status"] != "RECORDED":
        raise invalid_state("UnderwritingOverride is not RECORDED")
    rec["status"] = "CONFIRMED"
    db.touch(rec)
    officer = db.STORES["officers"].get(rec["loan_officer_id"])
    if officer is not None:
        officer["confirmed_override_count"] += 1
        # Risk recompute; upward RED crossing escalates REQUESTED exceptions.
        refresh_officer(officer, force_touch=True)
    return success_obj(db.public(rec))


@bp.post("/fair-lending/underwriting-overrides/<overrideId>/reverse")
@require_roles("FairLendingOfficer", "ComplianceDirector")
def reverse_override(overrideId):
    rec = get_or_404("overrides", overrideId, "UnderwritingOverride")
    if rec["status"] in ("CONFIRMED", "REVERSED") and rec["status"] == "REVERSED":
        raise already_terminal("UnderwritingOverride is REVERSED")
    if rec["status"] not in ("RECORDED", "CONFIRMED"):
        raise invalid_state("UnderwritingOverride cannot be reversed from %s" % rec["status"])
    was_confirmed = rec["status"] == "CONFIRMED"
    rec["status"] = "REVERSED"
    db.touch(rec)
    if was_confirmed:
        officer = db.STORES["officers"].get(rec["loan_officer_id"])
        if officer is not None:
            officer["confirmed_override_count"] -= 1
            refresh_officer(officer, force_touch=True)
    return success_obj(db.public(rec))
