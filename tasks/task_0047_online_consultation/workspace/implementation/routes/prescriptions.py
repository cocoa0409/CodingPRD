"""Prescription endpoints."""

from __future__ import annotations

from flask import Blueprint, request, g

import db
from middleware import require_role
from response import success, success_list, parse_pagination
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_REF_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PRESCRIPTION_INELIGIBLE,
    ERR_PRESCRIPTION_AMOUNT_INVALID,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_DISPATCH_TARGET_INVALID,
)
from config import (
    ROLE_PATIENT, ROLE_DOCTOR, ROLE_PHARMACIST, ROLE_ADMIN,
    PRESCRIPTION_ALLOWED_DISEASES, MAX_REVISIONS,
)
from services.serializers import serialize
from services.occ import check_version
from services.audit import append_audit


bp = Blueprint("prescriptions", __name__, url_prefix="/consultation/prescriptions")


def _rx_or_404(rid):
    row = db.find_by_id("prescriptions", rid)
    if not row:
        raise AppError(ERR_NOT_FOUND, "Prescription not found.", 404)
    return row


def _validate_items(items):
    if not isinstance(items, list) or not items:
        raise AppError(ERR_PRESCRIPTION_AMOUNT_INVALID, "items required.", 422)
    for it in items:
        try:
            q = int(it.get("quantity", 0))
            up = int(it.get("unit_price_cents", 0))
        except (TypeError, ValueError):
            raise AppError(ERR_PRESCRIPTION_AMOUNT_INVALID, "invalid item.", 422)
        if q < 1 or up < 1:
            raise AppError(ERR_PRESCRIPTION_AMOUNT_INVALID, "quantity/unit_price must be >=1.", 422)


def _has_prior_history(patient_id, doctor_id):
    """True if patient has any COMPLETED consultation with this doctor (including the current one).

    PRD §3.6 informal definition: 'the patient has a prior history with this doctor'.
    A completed consultation (the parent itself, plus any other) counts as the patient
    having seen this doctor before.
    """
    for c in db.all_rows("consultations"):
        if c.get("patient_id") == patient_id and c.get("doctor_id") == doctor_id:
            if c.get("session_status") == "COMPLETED":
                return True
    return False


def _compute_eligibility(consultation, disease_codes):
    """
    ELIGIBLE iff:
      (consultation has prior_history AND every disease in disease_codes is in PRESCRIPTION_ALLOWED_DISEASES)
      OR (consultation.mode == APPOINTMENT AND prior_history)
    """
    prior = _has_prior_history(
        consultation.get("patient_id"),
        consultation.get("doctor_id"),
    )
    codes_set = set(disease_codes or [])
    return_visit_ok = prior and bool(codes_set) and codes_set.issubset(PRESCRIPTION_ALLOWED_DISEASES)
    appointment_ok = (consultation.get("mode") == "APPOINTMENT") and prior
    return "ELIGIBLE" if (return_visit_ok or appointment_ok) else "INELIGIBLE"


@bp.post("")
def draft():
    require_role(ROLE_DOCTOR)
    body = request.get_json(silent=True) or {}
    cid = body.get("consultation_id")
    consultation = db.find_by_id("consultations", cid)
    if not consultation:
        raise AppError(ERR_REF_NOT_FOUND, "consultation_id not found.", 422)
    if g.user_id != consultation.get("doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Only the attending doctor may draft.", 403)
    items = body.get("items") or []
    _validate_items(items)
    disease_codes = body.get("disease_codes") or []
    elig = _compute_eligibility(consultation, disease_codes)
    record = {
        "consultation_id": cid,
        "patient_id": consultation.get("patient_id"),
        "drafting_doctor_id": consultation.get("doctor_id"),
        "reviewing_pharmacist_id": None,
        "disease_codes": disease_codes,
        "items": items,
        "gross_amount_cents": 0,
        "eligibility_flag": elig,
        "status": "DRAFT",
        "rejection_reason": None,
        "dispatch_target_kind": body.get("dispatch_target_kind") or "PHARMACY",
        "dispatch_target_id": body.get("dispatch_target_id"),
        "dispensing_status": "NONE",
        "revision_count": 0,
    }
    row = db.insert("prescriptions", record)
    return success(serialize(row), 201)


@bp.post("/<rid>/submit")
def submit(rid):
    require_role(ROLE_DOCTOR)
    row = _rx_or_404(rid)
    body = request.get_json(silent=True) or {}
    if g.user_id != row.get("drafting_doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Only drafting doctor may submit.", 403)
    if row.get("status") != "DRAFT":
        raise AppError(ERR_INVALID_STATE, "Not in DRAFT.", 409)
    check_version(row, body)
    consultation = db.find_by_id("consultations", row.get("consultation_id"))
    if not consultation or consultation.get("session_status") != "COMPLETED":
        raise AppError(ERR_INVALID_STATE, "Parent consultation not COMPLETED.", 409)
    if row.get("eligibility_flag") != "ELIGIBLE":
        raise AppError(ERR_PRESCRIPTION_INELIGIBLE, "Prescription ineligible.", 422)
    row = db.update("prescriptions", rid, {"status": "UNDER_REVIEW"})
    append_audit("PRESCRIPTION_SUBMITTED", "Prescription", rid, body)
    return success(serialize(row), 200)


@bp.post("/<rid>/approve")
def approve(rid):
    require_role(ROLE_PHARMACIST)
    row = _rx_or_404(rid)
    body = request.get_json(silent=True) or {}
    # PRD §2.6: state-machine check (priority 5) precedes business rules,
    # so ERR_INVALID_STATE shadows ERR_SEGREGATION_OF_DUTIES when both
    # apply.
    if row.get("status") != "UNDER_REVIEW":
        raise AppError(ERR_INVALID_STATE, "Not in UNDER_REVIEW.", 409)
    # Segregation-of-duties (business-rule) — surfaces before OCC.
    if g.user_id == row.get("drafting_doctor_id"):
        raise AppError(ERR_SEGREGATION_OF_DUTIES, "Pharmacist cannot be drafter.", 403)
    check_version(row, body)
    # Compute gross_amount_cents
    gross = 0
    for it in row.get("items") or []:
        gross += int(it.get("unit_price_cents", 0)) * int(it.get("quantity", 0))
    row = db.update("prescriptions", rid, {
        "status": "APPROVED",
        "reviewing_pharmacist_id": g.user_id,
        "gross_amount_cents": gross,
    })
    append_audit("PRESCRIPTION_APPROVED", "Prescription", rid, body)
    return success(serialize(row), 200)


@bp.post("/<rid>/reject")
def reject(rid):
    require_role(ROLE_PHARMACIST)
    row = _rx_or_404(rid)
    body = request.get_json(silent=True) or {}
    # PRD §2.6: state precedes business rules.
    if row.get("status") != "UNDER_REVIEW":
        raise AppError(ERR_INVALID_STATE, "Not in UNDER_REVIEW.", 409)
    if g.user_id == row.get("drafting_doctor_id"):
        raise AppError(ERR_SEGREGATION_OF_DUTIES, "Pharmacist cannot be drafter.", 403)
    reason = body.get("rejection_reason")
    if not reason:
        raise AppError(ERR_INVALID_STATE, "rejection_reason required.", 409)
    check_version(row, body)
    row = db.update("prescriptions", rid, {
        "status": "REJECTED",
        "reviewing_pharmacist_id": g.user_id,
        "rejection_reason": reason,
    })
    append_audit("PRESCRIPTION_REJECTED", "Prescription", rid, body)
    return success(serialize(row), 200)


@bp.post("/<rid>/revise")
def revise(rid):
    require_role(ROLE_DOCTOR)
    row = _rx_or_404(rid)
    body = request.get_json(silent=True) or {}
    if g.user_id != row.get("drafting_doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Only drafting doctor may revise.", 403)
    if row.get("status") != "REJECTED":
        raise AppError(ERR_INVALID_STATE, "Not in REJECTED.", 409)
    check_version(row, body)
    new_rev = int(row.get("revision_count") or 0) + 1
    if new_rev > MAX_REVISIONS:
        # auto-transition to FAILED
        row = db.update("prescriptions", rid, {
            "status": "FAILED",
            "revision_count": int(row.get("revision_count") or 0),
        })
        append_audit("PRESCRIPTION_FAILED", "Prescription", rid, body)
        return success(serialize(row), 200)
    # Update items / disease_codes if present
    updates = {
        "status": "DRAFT",
        "rejection_reason": None,
        "revision_count": new_rev,
    }
    if "items" in body:
        _validate_items(body["items"])
        updates["items"] = body["items"]
    if "disease_codes" in body:
        updates["disease_codes"] = body["disease_codes"]
    # Recompute eligibility_flag if disease_codes/items changed
    if "disease_codes" in updates or "items" in updates:
        consultation = db.find_by_id("consultations", row.get("consultation_id"))
        if consultation:
            new_dc = updates.get("disease_codes", row.get("disease_codes") or [])
            updates["eligibility_flag"] = _compute_eligibility(consultation, new_dc)
    row = db.update("prescriptions", rid, updates)
    append_audit("PRESCRIPTION_REVISED", "Prescription", rid, body)
    return success(serialize(row), 200)


def _resolve_dispatch_target(kind, target_id):
    """Validate dispatch target. Per tests: implementations may seed a minimal
    directory OR accept any non-empty string and verify on dispatch. We accept
    any non-empty string, but if a directory entry exists with a non-ACTIVE
    status, reject it.
    """
    if not target_id or not isinstance(target_id, str):
        return False
    if kind not in ("PHARMACY", "ECOMMERCE"):
        return False
    table = "pharmacy_directory" if kind == "PHARMACY" else "ecommerce_directory"
    row = db.find_by_id(table, target_id)
    if row and row.get("status") and row.get("status") != "ACTIVE":
        return False
    return True


@bp.post("/<rid>/dispatch")
def dispatch(rid):
    require_role(ROLE_PHARMACIST)
    row = _rx_or_404(rid)
    body = request.get_json(silent=True) or {}
    if row.get("status") != "APPROVED":
        raise AppError(ERR_INVALID_STATE, "Not in APPROVED.", 409)
    check_version(row, body)
    kind = row.get("dispatch_target_kind")
    tgt = row.get("dispatch_target_id")
    if not _resolve_dispatch_target(kind, tgt):
        raise AppError(ERR_DISPATCH_TARGET_INVALID, "dispatch target invalid.", 422)
    row = db.update("prescriptions", rid, {
        "status": "DISPATCHED",
        "dispensing_status": "NONE",
    })
    append_audit("PRESCRIPTION_DISPATCHED", "Prescription", rid, body)
    # Trigger InsuranceClaim if patient has insurance_policy_no
    patient = db.find_by_id("patients", row.get("patient_id"))
    if patient and patient.get("insurance_policy_no"):
        claim = {
            "consultation_id": row.get("consultation_id"),
            "prescription_id": row["id"],
            "patient_id": row.get("patient_id"),
            "claim_amount_cents": 0,
            "deductible_cents": 0,
            "reimbursed_cents": 0,
            "self_pay_cents": 0,
            "self_pay_collected_cents": 0,
            "status": "ELIGIBILITY_PENDING",
            "bureau_ref": None,
        }
        new_claim = db.insert("insurance_claims", claim)
        # Audit so tests can locate the claim via audit log filter.
        append_audit("CLAIM_CREATED", "InsuranceClaim", new_claim["id"], {"prescription_id": row["id"]})
    return success(serialize(row), 200)


@bp.get("/<rid>")
def get_rx(rid):
    require_role(ROLE_DOCTOR, ROLE_PHARMACIST, ROLE_PATIENT, ROLE_ADMIN)
    row = _rx_or_404(rid)
    if g.role == ROLE_PATIENT and g.user_id != row.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Not the owner.", 403)
    if g.role == ROLE_DOCTOR and g.user_id != row.get("drafting_doctor_id"):
        raise AppError(ERR_FORBIDDEN, "Not the drafting doctor.", 403)
    return success(serialize(row), 200)


@bp.get("")
def list_rx():
    require_role(ROLE_DOCTOR, ROLE_PHARMACIST, ROLE_PATIENT, ROLE_ADMIN)
    limit, offset = parse_pagination(request.args)
    filters = {}
    for k in ("patient_id", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    rows = db.all_rows("prescriptions")
    if filters:
        rows = [r for r in rows if all(r.get(k) == v for k, v in filters.items())]
    if g.role == ROLE_PATIENT:
        rows = [r for r in rows if r.get("patient_id") == g.user_id]
    elif g.role == ROLE_DOCTOR:
        rows = [r for r in rows if r.get("drafting_doctor_id") == g.user_id]
    rows.sort(key=lambda r: (r.get("created_at") or "", r.get("_seq") or 0))
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([serialize(r) for r in page], total, limit, offset)
