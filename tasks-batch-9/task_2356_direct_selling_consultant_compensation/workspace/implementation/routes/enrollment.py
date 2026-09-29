"""Enrollment applications: three independent gates and one compound status."""

from flask import Blueprint

from common import (
    apply_bp,
    clock_str,
    new_row,
    opt_str,
    pagination,
    paginate,
    q_enum,
    q_str,
    raw_body,
    req_enum,
    req_int,
    req_str,
    touch,
)
from db import db
from errors import ApiError
from middleware import actor_role, auth, own_application
from response import created, ok, ok_list
from services import planlib
from services.genealogy import by_created, recompute_direct_downline_count
from services.lookup import fetch, jurisdiction_by_state, peek

bp = Blueprint("enrollment", __name__)

TERMINAL_STATUSES = ("APPROVED", "REJECTED", "WITHDRAWN")
APPLICATION_STATUSES = ("DRAFT", "READY_FOR_APPROVAL") + TERMINAL_STATUSES
IDENTITY_STATUSES = ("UNVERIFIED", "PENDING_REVIEW", "VERIFIED", "FAILED")
DEFAULT_AGREEMENT_VERSION = "AGR-2026-01"


def derive_status(application):
    if application["status"] in TERMINAL_STATUSES:
        return
    if (
        application["agreement_status"] == "ACCEPTED"
        and application["identity_status"] == "VERIFIED"
        and application["kit_status"] == "PAID"
    ):
        application["status"] = "READY_FOR_APPROVAL"
    else:
        application["status"] = "DRAFT"


def _state_guards(application, include_not_draft=True):
    if application["status"] in TERMINAL_STATUSES:
        raise ApiError("ERR_APPLICATION_TERMINAL")
    if include_not_draft and application["status"] == "READY_FOR_APPROVAL":
        raise ApiError("ERR_APPLICATION_NOT_DRAFT")


def _ownership_precheck(application_id):
    own_application(peek("application", application_id))


# --------------------------------------------------------------------------
# Create
# --------------------------------------------------------------------------

@bp.post("/enrollment-applications")
def create_application():
    auth(["Applicant", "PlatformAdmin"])
    body = raw_body()

    applicant_email = req_str(body, "applicant_email", min_len=1)
    applicant_full_name = req_str(body, "applicant_full_name", min_len=1)
    applicant_state_code = req_str(body, "applicant_state_code", min_len=1)
    compensation_plan_id = req_str(body, "compensation_plan_id", min_len=1)
    starter_kit_product_id = req_str(body, "starter_kit_product_id", min_len=1)
    sponsor_consultant_id = opt_str(body, "sponsor_consultant_id")
    agreement_version = opt_str(body, "agreement_version", DEFAULT_AGREEMENT_VERSION)
    identity_document_reference = opt_str(body, "identity_document_reference")

    # Body references resolve left to right in declared field order.
    jurisdiction = jurisdiction_by_state(applicant_state_code)
    plan = fetch("plan", compensation_plan_id)
    product = fetch("product", starter_kit_product_id)
    sponsor = None
    if sponsor_consultant_id is not None:
        sponsor = fetch("consultant", sponsor_consultant_id)

    # Domain rules, in PRD order.
    if not product["is_starter_kit"]:
        raise ApiError("ERR_STARTER_KIT_INVALID")
    if sponsor is not None and sponsor["status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_SPONSOR_NOT_ELIGIBLE")
    if sponsor is None and actor_role() != "PlatformAdmin":
        raise ApiError("ERR_ROOT_ENROLLMENT_FORBIDDEN")
    for existing in db.applications.values():
        if existing["applicant_email"] == applicant_email and existing["status"] in (
            "DRAFT",
            "READY_FOR_APPROVAL",
            "APPROVED",
        ):
            raise ApiError("ERR_DUPLICATE_APPLICATION_EMAIL")

    kit_charge = int(product["wholesale_price_cents"])
    basis = (
        int(product["srp_cents"])
        if jurisdiction["facilitator_agreement_active"]
        else int(product["wholesale_price_cents"])
    )
    kit_tax = apply_bp(basis, jurisdiction["tax_rate_bp"])

    row = new_row()
    row.update(
        {
            "applicant_email": applicant_email,
            "applicant_full_name": applicant_full_name,
            "applicant_state_code": applicant_state_code,
            "sponsor_consultant_id": sponsor_consultant_id,
            "compensation_plan_id": compensation_plan_id,
            "starter_kit_product_id": starter_kit_product_id,
            "agreement_version": agreement_version,
            "identity_document_reference": identity_document_reference,
            "status": "DRAFT",
            "agreement_status": "NOT_ACCEPTED",
            "agreement_accepted_at": None,
            "identity_status": "PENDING_REVIEW" if identity_document_reference else "UNVERIFIED",
            "identity_attempt_count": 1 if identity_document_reference else 0,
            "identity_failure_reason": None,
            "kit_status": "UNPAID",
            "kit_charge_cents": kit_charge,
            "kit_tax_cents": kit_tax,
            "kit_total_cents": kit_charge + kit_tax,
            "kit_payment_reference": None,
            "created_consultant_id": None,
            "rejection_reason": None,
        }
    )
    db.applications[row["id"]] = row
    return created(row)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

@bp.get("/enrollment-applications")
def list_applications():
    auth(["Applicant", "ComplianceOfficer", "PlatformAdmin"])
    limit, offset = pagination()
    filters = {
        "sponsor_consultant_id": q_str("sponsor_consultant_id"),
        "compensation_plan_id": q_str("compensation_plan_id"),
        "starter_kit_product_id": q_str("starter_kit_product_id"),
        "created_consultant_id": q_str("created_consultant_id"),
        "applicant_email": q_str("applicant_email"),
        "status": q_enum("status", APPLICATION_STATUSES),
        "identity_status": q_enum("identity_status", IDENTITY_STATUSES),
    }
    rows = by_created(list(db.applications.values()))
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/enrollment-applications/<application_id>")
def read_application(application_id):
    auth(["Applicant", "ComplianceOfficer", "PlatformAdmin"])
    _ownership_precheck(application_id)
    return ok(fetch("application", application_id))


# --------------------------------------------------------------------------
# Dimension writes
# --------------------------------------------------------------------------

@bp.post("/enrollment-applications/<application_id>/accept-agreement")
def accept_agreement(application_id):
    auth(["Applicant"])
    _ownership_precheck(application_id)
    body = raw_body()
    agreement_version = req_str(body, "agreement_version", min_len=1)

    application = fetch("application", application_id)
    _state_guards(application)
    if application["agreement_status"] != "NOT_ACCEPTED":
        raise ApiError("ERR_AGREEMENT_ALREADY_ACCEPTED")
    if agreement_version != application["agreement_version"]:
        raise ApiError("ERR_AGREEMENT_VERSION_MISMATCH")

    application["agreement_status"] = "ACCEPTED"
    application["agreement_accepted_at"] = clock_str()
    derive_status(application)
    touch(application)
    return ok(application)


@bp.post("/enrollment-applications/<application_id>/identity-submission")
def identity_submission(application_id):
    auth(["Applicant", "PlatformAdmin"])
    _ownership_precheck(application_id)
    body = raw_body()
    reference = req_str(body, "identity_document_reference", min_len=1)

    application = fetch("application", application_id)
    _state_guards(application)
    if application["identity_status"] not in ("UNVERIFIED", "FAILED"):
        raise ApiError("ERR_IDENTITY_NOT_RESUBMITTABLE")
    plan = db.plans.get(application["compensation_plan_id"])
    max_attempts = int(plan["max_identity_attempts"]) if plan else 0
    if int(application["identity_attempt_count"]) >= max_attempts:
        raise ApiError("ERR_IDENTITY_ATTEMPTS_EXHAUSTED")

    application["identity_document_reference"] = reference
    application["identity_attempt_count"] = int(application["identity_attempt_count"]) + 1
    application["identity_status"] = "PENDING_REVIEW"
    application["identity_failure_reason"] = None
    derive_status(application)
    touch(application)
    return ok(application)


@bp.post("/enrollment-applications/<application_id>/identity-decision")
def identity_decision(application_id):
    auth(["ComplianceOfficer"])
    body = raw_body()
    decision = req_enum(body, "decision", ("VERIFY", "FAIL"))
    failure_reason = opt_str(body, "failure_reason")

    application = fetch("application", application_id)
    _state_guards(application)
    if application["identity_status"] != "PENDING_REVIEW":
        raise ApiError("ERR_IDENTITY_NOT_PENDING")

    if decision == "VERIFY":
        application["identity_status"] = "VERIFIED"
        derive_status(application)
    else:
        plan = db.plans.get(application["compensation_plan_id"])
        max_attempts = int(plan["max_identity_attempts"]) if plan else 0
        application["identity_status"] = "FAILED"
        application["identity_failure_reason"] = failure_reason
        if int(application["identity_attempt_count"]) >= max_attempts:
            application["status"] = "REJECTED"
            application["rejection_reason"] = "IDENTITY_ATTEMPTS_EXHAUSTED"
        else:
            derive_status(application)
    touch(application)
    return ok(application)


@bp.post("/enrollment-applications/<application_id>/pay-starter-kit")
def pay_starter_kit(application_id):
    auth(["Applicant", "PlatformAdmin"])
    _ownership_precheck(application_id)
    body = raw_body()
    amount_cents = req_int(body, "amount_cents", minimum=0)
    payment_reference = req_str(body, "payment_reference", min_len=1)

    application = fetch("application", application_id)
    _state_guards(application)
    if application["agreement_status"] != "ACCEPTED":
        raise ApiError("ERR_AGREEMENT_REQUIRED")
    if application["kit_status"] == "PAID":
        raise ApiError("ERR_KIT_ALREADY_PAID")
    if amount_cents != int(application["kit_total_cents"]):
        raise ApiError("ERR_KIT_AMOUNT_MISMATCH")

    application["kit_status"] = "PAID"
    application["kit_payment_reference"] = payment_reference
    derive_status(application)
    touch(application)
    return ok(application)


@bp.post("/enrollment-applications/<application_id>/withdraw")
def withdraw_application(application_id):
    auth(["Applicant", "PlatformAdmin"])
    _ownership_precheck(application_id)
    body = raw_body()
    reason = req_str(body, "reason", min_len=1)

    application = fetch("application", application_id)
    _state_guards(application, include_not_draft=False)
    if application["kit_status"] != "UNPAID":
        raise ApiError("ERR_KIT_PAID_NOT_WITHDRAWABLE")

    application["status"] = "WITHDRAWN"
    application["rejection_reason"] = reason
    touch(application)
    return ok(application)


# --------------------------------------------------------------------------
# Approval mints the consultant
# --------------------------------------------------------------------------

@bp.post("/enrollment-applications/<application_id>/approve")
def approve_application(application_id):
    auth(["ComplianceOfficer"])
    application = fetch("application", application_id)

    # Sponsor eligibility is re-checked before the state guards.
    sponsor = None
    if application["sponsor_consultant_id"] is not None:
        sponsor = db.consultants.get(application["sponsor_consultant_id"])
        if sponsor is None or sponsor["status"] not in ("ACTIVE", "PROBATION"):
            raise ApiError("ERR_SPONSOR_NOT_ELIGIBLE")

    if application["status"] in TERMINAL_STATUSES:
        raise ApiError("ERR_APPLICATION_TERMINAL")
    if application["status"] != "READY_FOR_APPROVAL":
        raise ApiError("ERR_ENROLLMENT_INCOMPLETE")

    plan = db.plans.get(application["compensation_plan_id"])
    base_rung = planlib.base_rung(plan) if plan else None

    if sponsor is not None:
        upline_path = list(sponsor.get("upline_path") or []) + [sponsor["id"]]
    else:
        upline_path = []

    consultant = new_row()
    consultant.update(
        {
            "full_name": application["applicant_full_name"],
            "email": application["applicant_email"],
            "state_code": application["applicant_state_code"],
            "compensation_plan_id": application["compensation_plan_id"],
            "enrollment_application_id": application["id"],
            "sponsor_consultant_id": application["sponsor_consultant_id"],
            "upline_path": upline_path,
            "genealogy_depth": len(upline_path),
            "direct_downline_count": 0,
            "status": "ACTIVE",
            "rank_code": base_rung["rank_code"] if base_rung else None,
            "rank_order": base_rung["rank_order"] if base_rung else 0,
            "rank_source": "ENROLLMENT",
            "consecutive_qualified_count": 0,
            "grace_periods_used": 0,
            "lifetime_commission_paid_cents": 0,
            "carry_forward_cents": 0,
            "clawback_balance_cents": 0,
            "payout_hold": False,
            "enrollment_completed_at": clock_str(),
            "terminated_at": None,
            "termination_reason": None,
            "reinstated_at": None,
            "reinstatement_count": 0,
            "reassigned_from_sponsor_consultant_id": None,
            "reassignment_count": 0,
            "open_case_count": 0,
            "highest_sanction_order": 0,
            "active_sanction_level": None,
            "active_sanction_until": None,
        }
    )
    db.consultants[consultant["id"]] = consultant

    if sponsor is not None:
        sponsor["direct_downline_count"] = int(sponsor["direct_downline_count"]) + 1
        touch(sponsor)
    if plan is not None:
        plan["consultant_count"] = int(plan["consultant_count"]) + 1
        touch(plan)

    application["created_consultant_id"] = consultant["id"]
    application["status"] = "APPROVED"
    touch(application)

    return created(consultant)
