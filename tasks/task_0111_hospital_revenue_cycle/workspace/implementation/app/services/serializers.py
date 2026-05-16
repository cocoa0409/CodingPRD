"""Entity → response-dict serializers.

Encounter serialization includes the derived outstanding_balance_cents and
overpayment_cents per PRD §3.7.
"""
from __future__ import annotations

from typing import Any

from ..calculations import outstanding_balance_calc


def serialize_patient(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p["id"],
        "mrn": p["mrn"],
        "full_name": p["full_name"],
        "date_of_birth": p["date_of_birth"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_policy(pol: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": pol["id"],
        "patient_id": pol["patient_id"],
        "payer_name": pol["payer_name"],
        "policy_number": pol["policy_number"],
        "plan_year": pol["plan_year"],
        "deductible_cents": pol["deductible_cents"],
        "deductible_met_cents": pol["deductible_met_cents"],
        "coinsurance_rate_bps": pol["coinsurance_rate_bps"],
        "oop_max_cents": pol["oop_max_cents"],
        "oop_accumulated_cents": pol["oop_accumulated_cents"],
        "status": pol["status"],
        "verified_at": pol.get("verified_at"),
        "created_at": pol["created_at"],
        "updated_at": pol["updated_at"],
        "version": pol["version"],
    }


def serialize_encounter(enc: dict[str, Any]) -> dict[str, Any]:
    bal = outstanding_balance_calc(enc)
    return {
        "id": enc["id"],
        "patient_id": enc["patient_id"],
        "policy_id": enc["policy_id"],
        "admission_at": enc["admission_at"],
        "discharge_at": enc.get("discharge_at"),
        "billed_at": enc.get("billed_at"),
        "status": enc["status"],
        "total_charges_cents": enc.get("total_charges_cents", 0),
        "payer_responsibility_cents": enc.get("payer_responsibility_cents", 0),
        "patient_responsibility_cents": enc.get("patient_responsibility_cents", 0),
        "estimated_patient_responsibility_cents": enc.get(
            "estimated_patient_responsibility_cents", 0
        ),
        "write_off_cents": enc.get("write_off_cents", 0),
        "outstanding_balance_cents": bal["outstanding_balance_cents"],
        "overpayment_cents": bal["overpayment_cents"],
        "created_at": enc["created_at"],
        "updated_at": enc["updated_at"],
        "version": enc["version"],
    }


def serialize_charge(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": c["id"],
        "encounter_id": c["encounter_id"],
        "cpt_code": c["cpt_code"],
        "description": c["description"],
        "quantity": c["quantity"],
        "unit_price_cents": c["unit_price_cents"],
        "amount_cents": c["amount_cents"],
        "status": c["status"],
        "posted_at": c.get("posted_at"),
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_coding(cr: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": cr["id"],
        "encounter_id": cr["encounter_id"],
        "primary_icd10": cr["primary_icd10"],
        "secondary_icd10": cr.get("secondary_icd10", []),
        "cpt_codes": cr["cpt_codes"],
        "coder_id": cr["coder_id"],
        "status": cr["status"],
        "created_at": cr["created_at"],
        "updated_at": cr["updated_at"],
        "version": cr["version"],
    }


def serialize_clearance(cd: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": cd["id"],
        "encounter_id": cd["encounter_id"],
        "decision": cd["decision"],
        "allowed_amount_cents": cd["allowed_amount_cents"],
        "denial_reason_code": cd.get("denial_reason_code"),
        "decided_at": cd["decided_at"],
        "created_at": cd["created_at"],
    }


def serialize_payment(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": p["id"],
        "encounter_id": p["encounter_id"],
        "amount_cents": p["amount_cents"],
        "method": p["method"],
        "posted_at": p["posted_at"],
        "created_at": p["created_at"],
    }


def serialize_bad_debt(b: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": b["id"],
        "encounter_id": b["encounter_id"],
        "write_off_cents": b["write_off_cents"],
        "days_since_billed": b["days_since_billed"],
        "written_off_at": b["written_off_at"],
        "created_at": b["created_at"],
    }
