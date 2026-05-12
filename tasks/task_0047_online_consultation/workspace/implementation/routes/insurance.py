"""InsuranceClaim endpoints."""

from __future__ import annotations

from flask import Blueprint, request, g
from decimal import Decimal, ROUND_HALF_UP

import db
from middleware import require_role
from response import success
from errors import (
    AppError,
    ERR_NOT_FOUND,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
    ERR_INSURANCE_INVARIANT_VIOLATION,
)
from config import (
    ROLE_PATIENT, ROLE_ADMIN,
    DEDUCTIBLE_CENTS,
)
from services.serializers import serialize
from services.occ import check_version
from services.calculations import insurance_reimbursement


bp = Blueprint("insurance", __name__, url_prefix="/consultation/insurance-claims")


def _claim_or_404(cid):
    row = db.find_by_id("insurance_claims", cid)
    if not row:
        raise AppError(ERR_NOT_FOUND, "InsuranceClaim not found.", 404)
    return row


def _ytd_reimbursed_for_patient(patient_id) -> int:
    """Sum reimbursed_cents for this patient's prior SETTLED claims (this calendar year)."""
    now = db.now_dt()
    year = now.year
    total = 0
    for c in db.all_rows("insurance_claims"):
        if c.get("patient_id") != patient_id:
            continue
        if c.get("status") != "SETTLED":
            continue
        ca = c.get("created_at")
        try:
            yr = db.parse_iso(ca).year
        except Exception:
            yr = year
        if yr == year:
            total += int(c.get("reimbursed_cents") or 0)
    return total


@bp.post("/<cid>/verify-eligibility")
def verify_eligibility(cid):
    require_role(ROLE_ADMIN)
    row = _claim_or_404(cid)
    body = request.get_json(silent=True) or {}
    if row.get("status") != "ELIGIBILITY_PENDING":
        raise AppError(ERR_INVALID_STATE, "Not in ELIGIBILITY_PENDING.", 409)
    consultation = db.find_by_id("consultations", row.get("consultation_id"))
    if not consultation or consultation.get("session_status") != "COMPLETED":
        raise AppError(ERR_INVALID_STATE, "Parent consultation not COMPLETED.", 409)
    check_version(row, body)
    new_status = body.get("insurance_status", "UNKNOWN")
    patient = db.find_by_id("patients", row.get("patient_id"))
    # Update patient's insurance_status cache
    if patient:
        db.update("patients", patient["id"], {"insurance_status": new_status})

    # Compute claim_amount_cents
    consult_fee_yuan = consultation.get("total_fee", 0)
    consult_cents = int(Decimal(str(consult_fee_yuan)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100)
    rx_cents = 0
    if row.get("prescription_id"):
        rx = db.find_by_id("prescriptions", row.get("prescription_id"))
        if rx:
            rx_cents = int(rx.get("gross_amount_cents") or 0)
    claim_amount = consult_cents + rx_cents

    if new_status == "ELIGIBLE":
        row = db.update("insurance_claims", cid, {
            "status": "VERIFIED",
            "deductible_cents": DEDUCTIBLE_CENTS,
            "claim_amount_cents": claim_amount,
        })
    else:
        row = db.update("insurance_claims", cid, {
            "status": "INELIGIBLE",
            "claim_amount_cents": claim_amount,
            "self_pay_cents": claim_amount,
        })
    return success(serialize(row), 200)


@bp.post("/<cid>/settle")
def settle(cid):
    require_role(ROLE_ADMIN)
    row = _claim_or_404(cid)
    body = request.get_json(silent=True) or {}
    if row.get("status") != "VERIFIED":
        raise AppError(ERR_INVALID_STATE, "Not in VERIFIED.", 409)
    check_version(row, body)
    # Determine disease scope from linked prescription
    rx = None
    if row.get("prescription_id"):
        rx = db.find_by_id("prescriptions", row.get("prescription_id"))
    disease_codes = (rx or {}).get("disease_codes") if rx else None
    ytd = _ytd_reimbursed_for_patient(row.get("patient_id"))
    reimbursed = insurance_reimbursement(
        int(row.get("claim_amount_cents") or 0),
        int(row.get("deductible_cents") or 0),
        disease_codes,
        has_prescription=bool(rx),
        ytd_reimbursed_cents=ytd,
    )
    self_pay = int(row.get("claim_amount_cents") or 0) - reimbursed
    row = db.update("insurance_claims", cid, {
        "status": "SETTLING",
        "reimbursed_cents": reimbursed,
        "self_pay_cents": self_pay,
    })
    return success(serialize(row), 200)


@bp.post("/<cid>/collect-self-pay")
def collect_self_pay(cid):
    require_role(ROLE_ADMIN)
    row = _claim_or_404(cid)
    body = request.get_json(silent=True) or {}
    if row.get("status") != "SETTLED":
        raise AppError(ERR_INVALID_STATE, "Not in SETTLED.", 409)
    if int(row.get("self_pay_collected_cents") or 0) != 0:
        raise AppError(ERR_INVALID_STATE, "Self-pay already collected.", 409)
    check_version(row, body)
    row = db.update("insurance_claims", cid, {
        "self_pay_collected_cents": int(row.get("self_pay_cents") or 0),
    })
    return success(serialize(row), 200)


@bp.get("/<cid>")
def get_claim(cid):
    require_role(ROLE_ADMIN, ROLE_PATIENT)
    row = _claim_or_404(cid)
    if g.role == ROLE_PATIENT and g.user_id != row.get("patient_id"):
        raise AppError(ERR_FORBIDDEN, "Not the owner.", 403)
    return success(serialize(row), 200)
