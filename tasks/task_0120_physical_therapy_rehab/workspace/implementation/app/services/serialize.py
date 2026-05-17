"""Serializers: take a stored row dict and produce a public response dict."""
from __future__ import annotations

from typing import Any

from ..clock import iso_format


def _common(row: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    out["id"] = row["id"]
    out["created_at"] = iso_format(row["created_at"])
    out["updated_at"] = iso_format(row["updated_at"])
    out["version"] = row["version"]
    return out


def therapist_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["full_name"] = row["full_name"]
    out["npi"] = row["npi"]
    out["credential"] = row["credential"]
    out["can_evaluate"] = row["can_evaluate"]
    out["status"] = row.get("status", "ACTIVE")
    return out


def patient_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["full_name"] = row["full_name"]
    out["date_of_birth"] = row["date_of_birth"]
    out["insurance_type"] = row["insurance_type"]
    out["medicare_beneficiary_id"] = row.get("medicare_beneficiary_id")
    out["va_referral_id"] = row.get("va_referral_id")
    out["ytd_capped_amount_cents"] = row.get("ytd_capped_amount_cents", 0)
    out["status"] = row.get("status", "ACTIVE")
    return out


def episode_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["patient_id"] = row["patient_id"]
    out["referring_provider_npi"] = row["referring_provider_npi"]
    out["body_region"] = row["body_region"]
    out["status"] = row.get("status", "DRAFT")
    out["cap_policy"] = row.get("cap_policy")
    out["kx_modifier_required"] = row.get("kx_modifier_required", False)
    out["total_authorized_units"] = row.get("total_authorized_units", 0)
    out["total_committed_units"] = row.get("total_committed_units", 0)
    out["total_reserved_units"] = row.get("total_reserved_units", 0)
    out["discharge_outcome"] = row.get("discharge_outcome")
    return out


def evaluation_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["episode_id"] = row["episode_id"]
    out["evaluation_type"] = row["evaluation_type"]
    out["clinician_id"] = row["clinician_id"]
    out["complexity"] = row["complexity"]
    out["functional_baseline_score"] = row["functional_baseline_score"]
    out["status"] = row.get("status", "DRAFT")
    out["finalized_at"] = iso_format(row.get("finalized_at")) if row.get("finalized_at") else None
    return out


def plan_of_care_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["episode_id"] = row["episode_id"]
    out["evaluation_id"] = row["evaluation_id"]
    out["certifying_physician_npi"] = row["certifying_physician_npi"]
    out["planned_visit_count"] = row["planned_visit_count"]
    out["planned_units_per_visit"] = row["planned_units_per_visit"]
    out["cert_period_start"] = row["cert_period_start"]
    out["cert_period_end"] = row["cert_period_end"]
    out["status"] = row.get("status", "DRAFT")
    out["capped_projection_cents"] = row.get("capped_projection_cents")
    return out


def authorization_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": row["id"],
        "created_at": iso_format(row["created_at"]),
        "episode_id": row["episode_id"],
        "plan_of_care_id": row["plan_of_care_id"],
        "source": row["source"],
        "external_reference": row["external_reference"],
        "unit_quota": row["unit_quota"],
        "valid_from": row["valid_from"],
        "valid_through": row["valid_through"],
        "status": row.get("status", "APPROVED"),
    }
    return out


def visit_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["episode_id"] = row["episode_id"]
    out["plan_of_care_id"] = row["plan_of_care_id"]
    out["authorization_id"] = row["authorization_id"]
    out["clinician_id"] = row["clinician_id"]
    out["scheduled_start"] = iso_format(row["scheduled_start"])
    out["scheduled_end"] = iso_format(row["scheduled_end"])
    out["units_planned"] = row["units_planned"]
    out["timed_minutes"] = row.get("timed_minutes", 0)
    out["units_billed"] = row.get("units_billed", 0)
    out["charge_cents"] = row.get("charge_cents", 0)
    out["kx_applied"] = row.get("kx_applied", False)
    out["status"] = row.get("status", "SCHEDULED")
    return out


def hep_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["episode_id"] = row["episode_id"]
    out["plan_of_care_id"] = row["plan_of_care_id"]
    out["prescribing_clinician_id"] = row["prescribing_clinician_id"]
    out["exercise_items"] = row["exercise_items"]
    out["patient_acknowledged_at"] = iso_format(row.get("patient_acknowledged_at")) if row.get("patient_acknowledged_at") else None
    out["status"] = row.get("status", "DRAFT")
    return out


def mips_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": iso_format(row["created_at"]),
        "episode_id": row["episode_id"],
        "measure_code": row["measure_code"],
        "visit_id": row["visit_id"],
        "numerator_met": row["numerator_met"],
        "exception_reason": row["exception_reason"],
        "scored_at": iso_format(row["scored_at"]),
    }


def discharge_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["episode_id"] = row["episode_id"]
    out["discharging_clinician_id"] = row["discharging_clinician_id"]
    out["discharge_outcome"] = row["discharge_outcome"]
    out["final_functional_score"] = row["final_functional_score"]
    out["functional_delta"] = row.get("functional_delta")
    out["mips_quality_score"] = row.get("mips_quality_score")
    out["status"] = row.get("status", "DRAFT")
    return out


def veteran_referral_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": iso_format(row["created_at"]),
        "patient_id": row["patient_id"],
        "referring_va_facility_code": row["referring_va_facility_code"],
        "authorized_units": row["authorized_units"],
        "valid_from": row["valid_from"],
        "valid_through": row["valid_through"],
        "status": row.get("status", "ACTIVE"),
    }
