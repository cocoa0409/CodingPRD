"""Serializers: convert internal records into API output payloads.

Computed fields that depend on the clock (Prescription expiry, Patient recall
and balance) are evaluated live at serialization time.
"""
import clock
from db import db


def _common(record):
    out = {
        "id": record["id"],
        "created_at": record["created_at"],
    }
    if "updated_at" in record:
        out["updated_at"] = record["updated_at"]
    if "version" in record:
        out["version"] = record["version"]
    return out


# ---- Provider (lean: id + created_at only) ----
def provider(record):
    return {
        "id": record["id"],
        "created_at": record["created_at"],
        "full_name": record["full_name"],
        "role": record["role"],
        "npi": record["npi"],
    }


# ---- Patient ----
def patient(record):
    out = _common(record)
    out.update({
        "full_name": record["full_name"],
        "date_of_birth": record["date_of_birth"],
        "plan_carrier": record["plan_carrier"],
        "medical_insurance_on_file": record["medical_insurance_on_file"],
        "recall_interval_months": record["recall_interval_months"],
        "last_routine_exam_date": record.get("last_routine_exam_date"),
        "recall_due_date": _recall_due_date(record),
        "outstanding_patient_balance_cents": record.get(
            "outstanding_patient_balance_cents", 0),
    })
    return out


def _recall_due_date(p):
    last = p.get("last_routine_exam_date")
    if not last:
        return None
    due = clock.add_months(last, p["recall_interval_months"])
    return due.isoformat()


# ---- Encounter ----
def encounter(record):
    out = _common(record)
    out.update({
        "patient_id": record["patient_id"],
        "provider_id": record["provider_id"],
        "encounter_type": record["encounter_type"],
        "chief_complaint_code": record["chief_complaint_code"],
        "exam_fee_cents": record["exam_fee_cents"],
        "refraction_fee_cents": record["refraction_fee_cents"],
        "status": record["status"],
        "refraction_recorded": record["refraction_recorded"],
    })
    return out


# ---- Prescription (status reflects expiry against clock) ----
def prescription(record):
    out = _common(record)
    out.update({
        "encounter_id": record["encounter_id"],
        "patient_id": record["patient_id"],
        "rx_type": record["rx_type"],
        "sphere_od": record["sphere_od"],
        "sphere_os": record["sphere_os"],
        "issue_date": record["issue_date"],
        "expiry_months": record["expiry_months"],
        "expiry_date": record["expiry_date"],
        "status": effective_rx_status(record),
    })
    return out


def effective_rx_status(record):
    """ACTIVE prescriptions that have passed expiry_date read as EXPIRED.

    SUPERSEDED / REVOKED are durable terminal states unaffected by the clock.
    """
    stored = record["status"]
    if stored == "ACTIVE":
        if clock.current_date() > clock.parse_date(record["expiry_date"]):
            return "EXPIRED"
    return stored


# ---- Eligibility ----
def eligibility(record):
    out = _common(record)
    out.update({
        "patient_id": record["patient_id"],
        "carrier": record["carrier"],
        "benefit_period_start": record["benefit_period_start"],
        "benefit_period_end": record["benefit_period_end"],
        "exam_copay_cents": record["exam_copay_cents"],
        "materials_allowance_cents": record["materials_allowance_cents"],
        "exam_benefit_available": record["exam_benefit_available"],
        "status": record["status"],
    })
    return out


# ---- BenefitPool ----
def benefit_pool(record):
    out = _common(record)
    out.update({
        "eligibility_id": record["eligibility_id"],
        "pool_type": record["pool_type"],
        "allotted_cents": record["allotted_cents"],
        "consumed_cents": record["consumed_cents"],
        "remaining_cents": record["remaining_cents"],
    })
    return out


# ---- LabOrder ----
def lab_order(record):
    out = _common(record)
    out.update({
        "prescription_id": record["prescription_id"],
        "eligibility_id": record.get("eligibility_id"),
        "dispensing_optician_id": record.get("dispensing_optician_id"),
        "expected_eligibility_version": record.get("expected_eligibility_version"),
        "frame_charge_cents": record["frame_charge_cents"],
        "lens_charge_cents": record["lens_charge_cents"],
        "frame_brand_tier": record["frame_brand_tier"],
        "materials_draw_cents": record["materials_draw_cents"],
        "patient_materials_cost_cents": record["patient_materials_cost_cents"],
        "status": record["status"],
        "remake_count": record["remake_count"],
        "dispensed_at": record.get("dispensed_at"),
    })
    return out


# ---- Claim ----
def claim(record):
    out = _common(record)
    out.update({
        "encounter_id": record["encounter_id"],
        "eligibility_id": record.get("eligibility_id"),
        "billing_route": record["billing_route"],
        "billed_amount_cents": record["billed_amount_cents"],
        "plan_paid_cents": record["plan_paid_cents"],
        "patient_responsibility_cents": record["patient_responsibility_cents"],
        "settled_cents": record["settled_cents"],
        "claim_status": record["claim_status"],
        "submission_status": record["submission_status"],
    })
    return out


# ---- RecallReminder ----
def recall_reminder(record):
    out = _common(record)
    out.update({
        "patient_id": record["patient_id"],
        "due_date": record.get("due_date"),
        "channel": record["channel"],
        "status": record["status"],
    })
    return out
