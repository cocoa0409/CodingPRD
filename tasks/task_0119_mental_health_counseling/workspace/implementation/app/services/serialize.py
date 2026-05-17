"""Serialization: convert in-memory entity dicts to JSON-safe response payloads.

Internal rows store Decimal for monetary/hour fields; this module renders them for the wire.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from ..clock import iso_format


def _serialize_common(row: dict[str, Any], *, with_version: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {"id": row["id"], "created_at": iso_format(row["created_at"])}
    if with_version:
        out["updated_at"] = iso_format(row["updated_at"])
        out["version"] = row["version"]
    return out


def _hours_to_float(v: Any) -> float:
    if isinstance(v, Decimal):
        return float(v)
    return float(v)


def serialize_therapist(row: dict[str, Any]) -> dict[str, Any]:
    base = _serialize_common(row)
    base.update(
        {
            "full_name": row["full_name"],
            "npi": row["npi"],
            "credential_status": row["credential_status"],
            "supervision_track": row["supervision_track"],
            "supervision_hours_accrued": _hours_to_float(row["supervision_hours_accrued"]),
            "licensure_exam_eligible": row["licensure_exam_eligible"],
            "psypact_enrolled": row["psypact_enrolled"],
            "pricing_rack_90791_cents": row["pricing_rack_90791_cents"],
            "pricing_rack_90834_cents": row["pricing_rack_90834_cents"],
        }
    )
    return base


def serialize_state_license(row: dict[str, Any]) -> dict[str, Any]:
    base = _serialize_common(row)
    base.update(
        {
            "therapist_id": row["therapist_id"],
            "state_code": row["state_code"],
            "license_number": row["license_number"],
            "status": row["status"],
            "issued_on": iso_format(row["issued_on"]),
            "expires_on": iso_format(row["expires_on"]),
        }
    )
    return base


def serialize_supervisor(row: dict[str, Any]) -> dict[str, Any]:
    base = _serialize_common(row)
    base.update(
        {
            "full_name": row["full_name"],
            "home_state_code": row["home_state_code"],
            "active": row["active"],
        }
    )
    return base


def serialize_supervision_assignment(row: dict[str, Any]) -> dict[str, Any]:
    # No updated_at and no version on this entity.
    out: dict[str, Any] = {
        "id": row["id"],
        "created_at": iso_format(row["created_at"]),
        "therapist_id": row["therapist_id"],
        "supervisor_id": row["supervisor_id"],
        "started_on": iso_format(row["started_on"]),
        "ended_on": iso_format(row["ended_on"]) if row.get("ended_on") is not None else None,
        "status": row["status"],
    }
    return out


def serialize_patient(row: dict[str, Any]) -> dict[str, Any]:
    base = _serialize_common(row)
    base.update(
        {
            "full_name": row["full_name"],
            "state_of_residence": row["state_of_residence"],
            "household_income_cents": row["household_income_cents"],
            "household_size": row["household_size"],
            "sliding_fee_tier_pct": row["sliding_fee_tier_pct"],
            "insurance_plan_id": row.get("insurance_plan_id"),
            "deductible_remaining_cents": row["deductible_remaining_cents"],
            "latest_crisis_level": row.get("latest_crisis_level"),
            "safety_plan_required": row["safety_plan_required"],
        }
    )
    return base


def serialize_insurance_plan(row: dict[str, Any]) -> dict[str, Any]:
    base = _serialize_common(row)
    base.update(
        {
            "payer_name": row["payer_name"],
            "plan_code": row["plan_code"],
            "network_status": row["network_status"],
            "contract_mode": row["contract_mode"],
            "allowed_amount_90791_cents": row["allowed_amount_90791_cents"],
            "allowed_amount_90834_cents": row["allowed_amount_90834_cents"],
            "copay_cents": row["copay_cents"],
        }
    )
    return base


def serialize_appointment(row: dict[str, Any]) -> dict[str, Any]:
    base = _serialize_common(row)
    base.update(
        {
            "therapist_id": row["therapist_id"],
            "patient_id": row["patient_id"],
            "cpt_code": row["cpt_code"],
            "modality": row["modality"],
            "patient_state_on_day": row["patient_state_on_day"],
            "scheduled_start": iso_format(row["scheduled_start"]),
            "scheduled_end": iso_format(row["scheduled_end"]),
            "status": row["status"],
            "hold_reason": row.get("hold_reason"),
        }
    )
    return base


def serialize_session(row: dict[str, Any]) -> dict[str, Any]:
    base = _serialize_common(row)
    base.update(
        {
            "appointment_id": row["appointment_id"],
            "type": row["type"],
            "actual_duration_minutes": row["actual_duration_minutes"],
            "supervision_credit_hours": _hours_to_float(row["supervision_credit_hours"]),
            "status": row["status"],
        }
    )
    return base


def serialize_crisis_assessment(row: dict[str, Any]) -> dict[str, Any]:
    # No updated_at; no version.
    out: dict[str, Any] = {
        "id": row["id"],
        "created_at": iso_format(row["created_at"]),
        "patient_id": row["patient_id"],
        "therapist_id": row["therapist_id"],
        "si_score": row["si_score"],
        "pa_score": row["pa_score"],
        "su_score": row["su_score"],
        "so_score": row["so_score"],
        "am_score": row["am_score"],
        "composite_score": float(row["composite_score"]),
        "risk_level": row["risk_level"],
        "assessed_at": iso_format(row["assessed_at"]),
    }
    return out


def serialize_safety_plan(row: dict[str, Any]) -> dict[str, Any]:
    base = _serialize_common(row)
    base.update(
        {
            "patient_id": row["patient_id"],
            "trigger_assessment_id": row["trigger_assessment_id"],
            "warning_signs": row["warning_signs"],
            "coping_strategies": row["coping_strategies"],
            "support_contacts": row["support_contacts"],
            "crisis_hotline": row["crisis_hotline"],
            "means_restriction_plan": row["means_restriction_plan"],
            "status": row["status"],
        }
    )
    return base


def serialize_billing_claim(row: dict[str, Any]) -> dict[str, Any]:
    base = _serialize_common(row)
    base.update(
        {
            "appointment_id": row["appointment_id"],
            "patient_id": row["patient_id"],
            "insurance_plan_id": row.get("insurance_plan_id"),
            "cpt_code": row["cpt_code"],
            "billing_mode": row["billing_mode"],
            "charged_amount_cents": row["charged_amount_cents"],
            "patient_responsibility_cents": row["patient_responsibility_cents"],
            "insurer_paid_cents": row["insurer_paid_cents"],
            "status": row["status"],
            "posted_at": iso_format(row["posted_at"]),
        }
    )
    return base
