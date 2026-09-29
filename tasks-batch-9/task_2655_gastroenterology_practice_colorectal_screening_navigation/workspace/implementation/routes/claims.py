"""Billing claim reads and the finalize / dispute / reprice lifecycle."""
from flask import Blueprint

from core import by_seq, db, fail, touch
from core import respond_list, respond_object
from validation import (
    apply_page,
    auth,
    body,
    filter_enum,
    filter_value,
    pagination,
    req_string,
)
from services import apply_final_pricing, get_claim

bp = Blueprint("claims", __name__)

CLAIM_STATUSES = ("PROVISIONAL_PRICED", "REPRICED", "FINALIZED", "DISPUTED", "VOIDED")
CLASSIFICATIONS = ("SCREENING_PREVENTIVE", "DIAGNOSTIC")


def _claim_patient(claim):
    booking = db.bookings.get(claim["booking_id"])
    if booking is None:
        return None
    episode = db.episodes.get(booking["episode_id"])
    if episode is None:
        return None
    return db.patients.get(episode["patient_id"])


@bp.get("/billing-claims/<claim_id>")
def read_claim(claim_id):
    auth("BillingSpecialist", "PracticeAdmin")
    return respond_object(get_claim(claim_id))


@bp.get("/billing-claims")
def list_claims():
    auth("BillingSpecialist", "PracticeAdmin")
    limit, offset = pagination()
    booking_id = filter_value("booking_id")
    insurance_plan_id = filter_value("insurance_plan_id")
    status = filter_enum("status", CLAIM_STATUSES)
    classification = filter_enum("classification", CLASSIFICATIONS)
    rows = by_seq(list(db.claims.values()))
    if booking_id is not None:
        rows = [r for r in rows if r["booking_id"] == booking_id]
    if insurance_plan_id is not None:
        rows = [r for r in rows if r["insurance_plan_id"] == insurance_plan_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if classification is not None:
        rows = [r for r in rows if r["classification"] == classification]
    page, meta = apply_page(rows, limit, offset)
    return respond_list(page, meta)


@bp.post("/billing-claims/<claim_id>/finalize")
def finalize_claim(claim_id):
    auth("BillingSpecialist")
    claim = get_claim(claim_id)
    if claim["status"] != "REPRICED":
        fail("ERR_INVALID_CLAIM_STATE",
             "Finalization is not admitted from %s." % claim["status"])
    claim["status"] = "FINALIZED"
    touch(claim)
    patient = _claim_patient(claim)
    if patient is not None:
        patient["deductible_applied_cents"] = (
            int(patient["deductible_applied_cents"]) + int(claim["deductible_applied_cents"])
        )
        patient["oop_applied_cents"] = (
            int(patient["oop_applied_cents"]) + int(claim["patient_responsibility_cents"])
        )
        touch(patient)
    return respond_object(claim)


@bp.post("/billing-claims/<claim_id>/dispute")
def dispute_claim(claim_id):
    auth("BillingSpecialist")
    data = body()
    dispute_reason = req_string(data, "dispute_reason")
    claim = get_claim(claim_id)
    if claim["status"] != "FINALIZED":
        fail("ERR_INVALID_CLAIM_STATE", "A dispute is not admitted from %s." % claim["status"])
    claim["status"] = "DISPUTED"
    claim["dispute_reason"] = dispute_reason
    touch(claim)
    patient = _claim_patient(claim)
    if patient is not None:
        patient["deductible_applied_cents"] = (
            int(patient["deductible_applied_cents"]) - int(claim["deductible_applied_cents"])
        )
        patient["oop_applied_cents"] = (
            int(patient["oop_applied_cents"]) - int(claim["patient_responsibility_cents"])
        )
        touch(patient)
    return respond_object(claim)


@bp.post("/billing-claims/<claim_id>/reprice")
def reprice_claim(claim_id):
    auth("BillingSpecialist")
    claim = get_claim(claim_id)
    if claim["status"] != "DISPUTED":
        fail("ERR_INVALID_CLAIM_STATE", "A reprice is not admitted from %s." % claim["status"])
    apply_final_pricing(claim, touch_booking=True)
    return respond_object(claim)
