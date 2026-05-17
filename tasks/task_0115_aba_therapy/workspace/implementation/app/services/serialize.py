"""Serialisation helpers — produce the on-wire shape for each entity.

These functions also recompute derived fields (e.g. Authorization consumption,
Patient progress scores are kept fresh on writes; reads simply return them).
"""
from .calculations import (
    adjudicated_balance,
    authorization_consumption,
    provisional_balance,
)


def serialize_clinic(c: dict) -> dict:
    return {
        "id": c["id"],
        "name": c["name"],
        "now_ts": c["now_ts"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_patient(p: dict) -> dict:
    return {
        "id": p["id"],
        "clinic_id": p["clinic_id"],
        "legal_name": p["legal_name"],
        "date_of_birth": p["date_of_birth"],
        "insurance_member_id": p["insurance_member_id"],
        "clinical_progress_score_provisional": p["clinical_progress_score_provisional"],
        "clinical_progress_score_adjudicated": p["clinical_progress_score_adjudicated"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_therapist(t: dict) -> dict:
    return {
        "id": t["id"],
        "clinic_id": t["clinic_id"],
        "legal_name": t["legal_name"],
        "credential": t["credential"],
        "license_number": t["license_number"],
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def serialize_evaluation(e: dict) -> dict:
    return {
        "id": e["id"],
        "patient_id": e["patient_id"],
        "evaluator_therapist_id": e["evaluator_therapist_id"],
        "scheduled_at": e["scheduled_at"],
        "completed_at": e.get("completed_at"),
        "diagnosis_code": e.get("diagnosis_code"),
        "severity_level": e.get("severity_level"),
        "recommended_weekly_hours": e.get("recommended_weekly_hours"),
        "status": e["status"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_plan(p: dict) -> dict:
    return {
        "id": p["id"],
        "patient_id": p["patient_id"],
        "source_evaluation_id": p["source_evaluation_id"],
        "weekly_direct_hours_target": p["weekly_direct_hours_target"],
        "weekly_supervision_hours_target": p["weekly_supervision_hours_target"],
        "weekly_parent_training_hours_target": p["weekly_parent_training_hours_target"],
        "plan_version": p["plan_version"],
        "superseded_by_id": p.get("superseded_by_id"),
        "activated_at": p.get("activated_at"),
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


def serialize_authorization(a: dict) -> dict:
    prov_used, adj_used = authorization_consumption(a["id"])
    # Keep stored fields in sync (defensive — most call sites also recompute).
    a["provisional_units_consumed"] = prov_used
    a["adjudicated_units_consumed"] = adj_used
    return {
        "id": a["id"],
        "patient_id": a["patient_id"],
        "treatment_plan_id": a["treatment_plan_id"],
        "payer_name": a["payer_name"],
        "cpt_code": a["cpt_code"],
        "approved_units": a["approved_units"],
        "effective_start": a["effective_start"],
        "effective_end": a["effective_end"],
        "provisional_units_consumed": prov_used,
        "adjudicated_units_consumed": adj_used,
        "provisional_balance": provisional_balance(a),
        "adjudicated_balance": adjudicated_balance(a),
        "renewed_from_id": a.get("renewed_from_id"),
        "renewed_to_id": a.get("renewed_to_id"),
        "status": a["status"],
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def serialize_session(s: dict) -> dict:
    return {
        "id": s["id"],
        "patient_id": s["patient_id"],
        "authorization_id": s["authorization_id"],
        "therapist_id": s["therapist_id"],
        "supervising_therapist_id": s.get("supervising_therapist_id"),
        "session_type": s["session_type"],
        "planned_start": s["planned_start"],
        "planned_end": s["planned_end"],
        "actual_start": s.get("actual_start"),
        "actual_end": s.get("actual_end"),
        "planned_units": s["planned_units"],
        "billed_units": s.get("billed_units"),
        "dispute_reason": s.get("dispute_reason"),
        "progress_rating": s.get("progress_rating"),
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_claim(c: dict) -> dict:
    return {
        "id": c["id"],
        "patient_id": c["patient_id"],
        "authorization_id": c["authorization_id"],
        "session_ids": list(c["session_ids"]),
        "appeal_round": c["appeal_round"],
        "submitted_amount_cents": c["submitted_amount_cents"],
        "reimbursed_amount_cents": c["reimbursed_amount_cents"],
        "denial_reason": c.get("denial_reason"),
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def serialize_ledger_entry(e: dict) -> dict:
    return {
        "id": e["id"],
        "authorization_id": e["authorization_id"],
        "session_id": e.get("session_id"),
        "claim_id": e.get("claim_id"),
        "entry_type": e["entry_type"],
        "units_delta": e["units_delta"],
        "reason_code": e["reason_code"],
        "created_at": e["created_at"],
    }
