"""Claim + ClaimAttachment endpoints and state machine (PRD §3.6, §3.8)."""
from __future__ import annotations

from flask import Blueprint, request

import db
from errors import (
    APIError,
    ERR_CLAIM_HAS_ACTIVE_PAYMENT_PLAN,
    ERR_CLAIM_MISSING_ATTACHMENT,
    ERR_CLAIM_NOT_FOUND,
    ERR_CLAIM_NOT_SUBMITTED,
    ERR_CLAIM_NOT_VOIDABLE,
    ERR_COVERAGE_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ITEM_NOT_COMPLETED,
    ERR_ITEM_NOT_FOUND,
    ERR_PATIENT_NOT_FOUND,
    ERR_PROVIDER_TYPE_MISMATCH,
)
from middleware import ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK, ROLE_PATIENT
from response import ok_array, ok_object
from routes._helpers import apply_filters, enforce_patient_ownership, guard
from services import calculations, clock, common

bp = Blueprint("claims", __name__)


@bp.post("/claims")
def create_claim():
    guard([ROLE_BILLING])
    body = common.get_json_body()
    common.require_fields(body, ["patient_id", "treatment_plan_item_id", "patient_coverage_id"])
    patient_id = common.require_string(body, "patient_id")
    common.resolve(db.patients, patient_id, ERR_PATIENT_NOT_FOUND)
    item_id = common.require_string(body, "treatment_plan_item_id")
    item = common.resolve(db.treatment_plan_items, item_id, ERR_ITEM_NOT_FOUND)
    coverage_id = common.require_string(body, "patient_coverage_id")
    coverage = common.resolve(db.patient_coverages, coverage_id, ERR_COVERAGE_NOT_FOUND)

    # Item must be COMPLETED (priority 10, ERR_ITEM_NOT_COMPLETED).
    if item["status"] != "COMPLETED":
        raise APIError(ERR_ITEM_NOT_COMPLETED, 409, "TreatmentPlanItem must be COMPLETED")
    # Coverage must belong to the claim's patient (priority 7, ERR_PROVIDER_TYPE_MISMATCH).
    if coverage["patient_id"] != patient_id:
        raise APIError(ERR_PROVIDER_TYPE_MISMATCH, 409, "Coverage does not belong to the patient")

    rec = common.new_common_fields()
    rec.update({
        "patient_id": patient_id,
        "treatment_plan_item_id": item_id,
        "patient_coverage_id": coverage_id,
        "billed_fee_cents": item["fee_cents"],
        "carrier_paid_cents": 0,
        "patient_responsibility_cents": 0,
        "submission_status": "DRAFT",
        "adjudication_status": "PENDING",
        "_adjudicated_at_date": None,
        "_deductible_consumed": 0,
    })
    db.claims[rec["id"]] = rec
    return ok_object(common.serialize(rec), 201)


@bp.get("/claims")
def list_claims():
    guard([ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK])
    records = apply_filters(list(db.claims.values()), {
        "patient_id": request.args.get("patient_id"),
        "treatment_plan_item_id": request.args.get("treatment_plan_item_id"),
        "patient_coverage_id": request.args.get("patient_coverage_id"),
        "adjudication_status": request.args.get("adjudication_status"),
        "submission_status": request.args.get("submission_status"),
    })
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


@bp.get("/claims/<claim_id>")
def get_claim(claim_id):
    guard([ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK, ROLE_PATIENT])
    rec = common.resolve(db.claims, claim_id, ERR_CLAIM_NOT_FOUND)
    enforce_patient_ownership(rec["patient_id"])
    return ok_object(common.serialize(rec), 200)


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
@bp.post("/claims/<claim_id>/attachments")
def add_attachment(claim_id):
    guard([ROLE_BILLING])
    claim = common.resolve(db.claims, claim_id, ERR_CLAIM_NOT_FOUND)
    body = common.get_json_body()
    common.require_fields(body, ["attachment_type", "document_ref"])
    attachment_type = common.require_enum(
        body, "attachment_type", {"XRAY", "PERIO_CHART", "NARRATIVE", "PHOTO"}
    )
    document_ref = common.require_string(body, "document_ref")
    # ClaimAttachment is immutable: only id + created_at (PRD §2.4) — no version.
    rec = common.new_common_fields(versioned=False)
    rec.update({
        "claim_id": claim["id"],
        "attachment_type": attachment_type,
        "document_ref": document_ref,
    })
    db.claim_attachments[rec["id"]] = rec
    return ok_object(common.serialize(rec), 201)


@bp.get("/claims/<claim_id>/attachments")
def list_attachments(claim_id):
    guard([ROLE_BILLING, ROLE_CLINICIAN, ROLE_FRONT_DESK])
    common.resolve(db.claims, claim_id, ERR_CLAIM_NOT_FOUND)
    records = [a for a in db.claim_attachments.values() if a["claim_id"] == claim_id]
    items, limit, offset, total = common.paginate(records)
    return ok_array(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Submission dimension
# ---------------------------------------------------------------------------
@bp.post("/claims/<claim_id>/submit")
def submit_claim(claim_id):
    guard([ROLE_BILLING])
    claim = common.resolve(db.claims, claim_id, ERR_CLAIM_NOT_FOUND)
    if claim["submission_status"] != "DRAFT":
        raise APIError(ERR_INVALID_STATE, 409, "Claim submission_status must be DRAFT to submit")
    has_attachment = any(a["claim_id"] == claim_id for a in db.claim_attachments.values())
    if not has_attachment:
        raise APIError(ERR_CLAIM_MISSING_ATTACHMENT, 409, "Claim has no attachments")
    claim["submission_status"] = "SUBMITTED"
    common.touch(claim)
    return ok_object(common.serialize(claim), 200)


# ---------------------------------------------------------------------------
# Adjudication dimension
# ---------------------------------------------------------------------------
@bp.post("/claims/<claim_id>/adjudicate")
def adjudicate_claim(claim_id):
    guard([ROLE_BILLING])
    claim = common.resolve(db.claims, claim_id, ERR_CLAIM_NOT_FOUND)
    if claim["submission_status"] != "SUBMITTED":
        raise APIError(ERR_CLAIM_NOT_SUBMITTED, 409, "Claim must be SUBMITTED to adjudicate")
    if claim["adjudication_status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Claim adjudication_status must be PENDING")

    coverage = db.patient_coverages[claim["patient_coverage_id"]]
    plan = db.insurance_plans[coverage["insurance_plan_id"]]

    carrier, gross = calculations.adjudicated_benefit(claim)
    deductible_consumed = calculations.deductible_consumed(
        claim["billed_fee_cents"], plan, coverage["deductible_met_cents"]
    )

    claim["carrier_paid_cents"] = carrier
    claim["patient_responsibility_cents"] = claim["billed_fee_cents"] - carrier
    claim["adjudication_status"] = "PAID" if carrier == gross else "PARTIALLY_PAID"
    claim["_adjudicated_at_date"] = clock.now().date()
    claim["_deductible_consumed"] = deductible_consumed
    common.touch(claim)

    # CASCADE depth-1: coverage accumulator.
    coverage["annual_benefit_used_cents"] += carrier
    coverage["deductible_met_cents"] += deductible_consumed
    was_reached = coverage["annual_max_reached"]
    # CASCADE depth-2: annual_max flag (>= boundary).
    calculations.recompute_annual_max_reached(coverage)
    common.touch(coverage)

    # CASCADE depth-3: false->true flip revalidates APPROVED predeterminations.
    if (not was_reached) and coverage["annual_max_reached"]:
        for pre in db.predeterminations.values():
            if pre["patient_coverage_id"] == coverage["id"] and pre["status"] == "APPROVED":
                pre["status"] = "REQUIRES_REVALIDATION"
                common.touch(pre)

    calculations.recompute_patient_balance(claim["patient_id"])
    if db.patients.get(claim["patient_id"]) is not None:
        common.touch(db.patients[claim["patient_id"]])

    return ok_object(common.serialize(claim), 200)


@bp.post("/claims/<claim_id>/deny")
def deny_claim(claim_id):
    guard([ROLE_BILLING])
    claim = common.resolve(db.claims, claim_id, ERR_CLAIM_NOT_FOUND)
    if claim["adjudication_status"] != "PENDING":
        raise APIError(ERR_INVALID_STATE, 409, "Claim adjudication_status must be PENDING to deny")
    claim["carrier_paid_cents"] = 0
    claim["patient_responsibility_cents"] = claim["billed_fee_cents"]
    claim["adjudication_status"] = "DENIED"
    common.touch(claim)
    calculations.recompute_patient_balance(claim["patient_id"])
    if db.patients.get(claim["patient_id"]) is not None:
        common.touch(db.patients[claim["patient_id"]])
    return ok_object(common.serialize(claim), 200)


@bp.post("/claims/<claim_id>/void")
def void_claim(claim_id):
    guard([ROLE_BILLING])
    claim = common.resolve(db.claims, claim_id, ERR_CLAIM_NOT_FOUND)
    if claim["adjudication_status"] not in ("PAID", "PARTIALLY_PAID"):
        raise APIError(ERR_CLAIM_NOT_VOIDABLE, 409, "Claim must be PAID/PARTIALLY_PAID to void")
    # No ACTIVE payment plan may reference this claim.
    for pp in db.payment_plans.values():
        if pp["claim_id"] == claim_id and pp["status"] == "ACTIVE":
            raise APIError(ERR_CLAIM_HAS_ACTIVE_PAYMENT_PLAN, 409,
                           "Claim has an ACTIVE payment plan")

    coverage = db.patient_coverages[claim["patient_coverage_id"]]
    # COMPENSATION: restore the conserved accumulator.
    coverage["annual_benefit_used_cents"] -= claim["carrier_paid_cents"]
    coverage["deductible_met_cents"] -= claim["_deductible_consumed"]
    calculations.recompute_annual_max_reached(coverage)
    common.touch(coverage)

    claim["adjudication_status"] = "VOID"
    # Voided claim contributes nothing to patient responsibility (PRD §3.6: conserved
    # round-trip; balance recompute excludes VOID claims).
    common.touch(claim)

    calculations.recompute_patient_balance(claim["patient_id"])
    if db.patients.get(claim["patient_id"]) is not None:
        common.touch(db.patients[claim["patient_id"]])

    return ok_object(common.serialize(claim), 200)
