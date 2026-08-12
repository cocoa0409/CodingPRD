"""Appeals and reversal cascades (PRD §3.9)."""
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from clock import now_dt, now_iso, parse as parse_iso
from errors import raise_error
from middleware import (
    ALL_ROLES,
    body,
    check_operator_owns,
    require_non_empty_string,
    require_roles,
)
from response import success_object
from routes.common import filter_eq, get_or_404, paginate
from services import cascade

bp = Blueprint("appeals", __name__)

TARGET_TYPES = {"APPLICATION_DENIAL", "RENEWAL_DENIAL", "REVOCATION", "FEE_INVOICE"}


def _resolve_target(target_type: str, target_id: str):
    """Return (target_record, decided_at_iso or None, decider_user_id or None).

    Raises ERR_TARGET_NOT_APPEALABLE when the target is missing, of the wrong
    type, or not in an appealable state.
    """
    if target_type == "APPLICATION_DENIAL":
        target = db.get("applications", target_id)
        if target is None or target["status"] != "DENIED":
            raise_error(errors.ERR_TARGET_NOT_APPEALABLE, "Application is not DENIED")
        return target, target.get("updated_at"), target.get("decided_by_user_id")
    if target_type == "RENEWAL_DENIAL":
        target = db.get("renewal_decisions", target_id)
        if target is None or target["status"] != "DECIDED":
            raise_error(errors.ERR_TARGET_NOT_APPEALABLE, "Renewal decision is not DECIDED")
        return target, target.get("decided_at"), target.get("decided_by_user_id")
    if target_type == "REVOCATION":
        target = db.get("contracts", target_id)
        if target is None or target["status"] != "REVOKED":
            raise_error(errors.ERR_TARGET_NOT_APPEALABLE, "Contract is not REVOKED")
        return target, target.get("updated_at"), None
    if target_type == "FEE_INVOICE":
        target = db.get("fee_invoices", target_id)
        if target is None or target["status"] not in ("FINALIZED", "DISPUTED"):
            raise_error(errors.ERR_TARGET_NOT_APPEALABLE, "Invoice is not FINALIZED or DISPUTED")
        return target, target.get("updated_at"), None
    raise_error(errors.ERR_TARGET_NOT_APPEALABLE, "Unknown target_type")


@bp.post("/authorizer/appeals")
def file_appeal():
    user_id, role = require_roles(["SchoolOperator", "Applicant"])
    data = body()
    target_type = require_non_empty_string(data, "target_type")
    if target_type not in TARGET_TYPES:
        raise_error(errors.ERR_INVALID_REQUEST, f"target_type must be one of {sorted(TARGET_TYPES)}")
    target_id = require_non_empty_string(data, "target_id")
    grounds = require_non_empty_string(data, "grounds")
    school_id = data.get("school_id")

    if target_type == "APPLICATION_DENIAL":
        # Filed by Applicant with school_id null (the only appeal without a school).
        if role != "Applicant":
            raise_error(errors.ERR_INSUFFICIENT_PERMISSIONS, "APPLICATION_DENIAL appeals are filed by Applicant")
        school_id = None
    else:
        if role != "SchoolOperator":
            raise_error(errors.ERR_INSUFFICIENT_PERMISSIONS, "Only SchoolOperator may file this appeal type")
        if not isinstance(school_id, str) or school_id == "":
            raise_error(errors.ERR_INVALID_REQUEST, "school_id is required for this appeal type")
        get_or_404("schools", school_id)
        check_operator_owns(user_id, role, school_id)

    target, decided_at, _decider = _resolve_target(target_type, target_id)

    # One open (FILED|HEARING_SCHEDULED) appeal per target.
    for existing in db.all_records("appeals"):
        if (
            existing["target_type"] == target_type
            and existing["target_id"] == target_id
            and existing["status"] in ("FILED", "HEARING_SCHEDULED")
        ):
            raise_error(errors.ERR_APPEAL_ALREADY_OPEN, "An open appeal already exists for the target")

    # Window: filed_at <= target decided_at + 30 days inclusive.
    filed_at = now_dt()
    window_end = parse_iso(decided_at) + timedelta(days=30)
    if filed_at > window_end:
        raise_error(errors.ERR_APPEAL_WINDOW_EXPIRED, "Appeal window has expired")

    record = db.stamp_new({
        "school_id": school_id,
        "target_type": target_type,
        "target_id": target_id,
        "grounds": grounds,
        "filed_by_user_id": user_id,
        "filed_at": now_iso(),
        "hearing_officer_user_id": None,
        "ruling": None,
        "status": "FILED",
    })
    db.insert("appeals", record)

    # Filing a fee appeal moves the invoice FINALIZED -> DISPUTED.
    if target_type == "FEE_INVOICE" and target["status"] == "FINALIZED":
        target["status"] = "DISPUTED"
        db.touch(target)
    return success_object(record, 201)


@bp.get("/authorizer/appeals")
def list_appeals():
    require_roles(ALL_ROLES)
    records = db.all_records("appeals")
    records = filter_eq(records, "school_id", request.args.get("school_id"))
    records = filter_eq(records, "status", request.args.get("status"))
    return paginate(records)


@bp.get("/authorizer/appeals/<id>")
def get_appeal(id):
    require_roles(ALL_ROLES)
    return success_object(get_or_404("appeals", id))


@bp.post("/authorizer/appeals/<id>/schedule-hearing")
def schedule_hearing(id):
    require_roles(["AuthorizerStaff"])
    appeal = get_or_404("appeals", id)
    if appeal["status"] != "FILED":
        raise_error(errors.ERR_APPEAL_INVALID_STATE, "Appeal is not FILED")
    data = body()
    officer = require_non_empty_string(data, "hearing_officer_user_id")
    # Officer must differ from the original decider of the contested target.
    decider = None
    if appeal["target_type"] == "APPLICATION_DENIAL":
        target = db.get("applications", appeal["target_id"])
        decider = target.get("decided_by_user_id") if target else None
    elif appeal["target_type"] == "RENEWAL_DENIAL":
        target = db.get("renewal_decisions", appeal["target_id"])
        decider = target.get("decided_by_user_id") if target else None
    elif appeal["target_type"] == "REVOCATION":
        # The decider lives on the closure plan (the REVOCATION plan for the
        # contract's school).
        contract = db.get("contracts", appeal["target_id"])
        if contract is not None:
            plans = [
                p for p in db.all_records("closure_plans")
                if p["school_id"] == contract["school_id"] and p["reason"] == "REVOCATION"
            ]
            if plans:
                decider = plans[0].get("decided_by_user_id")
    # FEE_INVOICE has no decider: any officer allowed.
    if decider is not None and officer == decider:
        raise_error(errors.ERR_SOD_APPEAL_DECIDER_CONFLICT, "Hearing officer equals the original decider")
    appeal["hearing_officer_user_id"] = officer
    appeal["status"] = "HEARING_SCHEDULED"
    db.touch(appeal)
    return success_object(appeal)


@bp.post("/authorizer/appeals/<id>/rule")
def rule_appeal(id):
    user_id, _role = require_roles(["AppealsOfficer"])
    appeal = get_or_404("appeals", id)
    if appeal["status"] != "HEARING_SCHEDULED":
        raise_error(errors.ERR_APPEAL_INVALID_STATE, "Appeal is not HEARING_SCHEDULED")
    if user_id != appeal["hearing_officer_user_id"]:
        raise_error(errors.ERR_APPEAL_OFFICER_MISMATCH, "Caller is not the assigned hearing officer")
    data = body()
    ruling = require_non_empty_string(data, "ruling")
    if ruling not in ("UPHELD", "OVERTURNED"):
        raise_error(errors.ERR_INVALID_REQUEST, "ruling must be UPHELD or OVERTURNED")
    appeal["ruling"] = ruling
    appeal["status"] = "RULED_UPHELD" if ruling == "UPHELD" else "RULED_OVERTURNED"
    db.touch(appeal)

    tt = appeal["target_type"]
    if ruling == "UPHELD":
        if tt == "FEE_INVOICE":
            invoice = db.get("fee_invoices", appeal["target_id"])
            if invoice is not None and invoice["status"] == "DISPUTED":
                invoice["status"] = "FINALIZED"
                db.touch(invoice)
        return success_object(appeal)

    # OVERTURNED cascades (§3.9).
    if tt == "APPLICATION_DENIAL":
        app_rec = db.get("applications", appeal["target_id"])
        if app_rec is not None and app_rec["status"] == "DENIED":
            app_rec["status"] = "BOARD_REVIEW"
            app_rec["denial_reason"] = None
            app_rec["decided_by_user_id"] = None
            db.touch(app_rec)
    elif tt == "RENEWAL_DENIAL":
        decision = db.get("renewal_decisions", appeal["target_id"])
        if decision is not None and decision["status"] == "DECIDED":
            decision["status"] = "REVERTED"
            db.touch(decision)
    elif tt == "FEE_INVOICE":
        invoice = db.get("fee_invoices", appeal["target_id"])
        if invoice is not None and invoice["status"] == "DISPUTED":
            invoice["status"] = "WAIVED"
            invoice["waived_cents"] = invoice["billed_amount_cents"] - invoice["paid_cents"]
            db.touch(invoice)
    elif tt == "REVOCATION":
        contract = db.get("contracts", appeal["target_id"])
        if contract is not None:
            school = db.get("schools", contract["school_id"])
            # Cancel any closure plan still in INITIATED|TRANSITION_IN_PROGRESS.
            for plan in db.all_records("closure_plans"):
                if (
                    plan["school_id"] == contract["school_id"]
                    and plan["status"] in ("INITIATED", "TRANSITION_IN_PROGRESS")
                ):
                    plan["status"] = "CANCELLED"
                    db.touch(plan)
            if contract["status"] == "REVOKED":
                contract["status"] = "ACTIVE"
                db.touch(contract)
            if school is not None and school["status"] == "CLOSING":
                school["status"] = "OPEN"
                db.touch(school)
    return success_object(appeal)
