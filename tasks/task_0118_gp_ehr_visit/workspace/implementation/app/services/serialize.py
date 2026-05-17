"""Serializers for entities — produce the public-facing JSON dict.

These functions take a stored row (an internal dict) and return a dict suitable for
the response body. They DO mutate timestamps via iso_format helpers, but they
do not mutate the input row.
"""
from __future__ import annotations

from typing import Any

from ..clock import iso_format


def _common(row: dict[str, Any], out: dict[str, Any]) -> dict[str, Any]:
    out["id"] = row["id"]
    out["created_at"] = iso_format(row["created_at"])
    out["updated_at"] = iso_format(row["updated_at"])
    out["version"] = row["version"]
    return out


def patient_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["mrn"] = row["mrn"]
    out["first_name"] = row["first_name"]
    out["last_name"] = row["last_name"]
    out["date_of_birth"] = row["date_of_birth"]
    out["sex_at_birth"] = row["sex_at_birth"]
    out["pcp_provider_id"] = row.get("pcp_provider_id")
    out["pcp_bound_at"] = iso_format(row["pcp_bound_at"]) if row.get("pcp_bound_at") else None
    out["portal_enabled"] = row.get("portal_enabled", False)
    out["smoking_status"] = row.get("smoking_status", "UNKNOWN")
    out["chronic_conditions"] = list(row.get("chronic_conditions") or [])
    out["status"] = row.get("status", "ACTIVE")
    return out


def provider_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["npi"] = row["npi"]
    out["full_name"] = row["full_name"]
    out["role_type"] = row["role_type"]
    out["specialty"] = row.get("specialty")
    out["dea_number"] = row.get("dea_number")
    out["epcs_enrolled"] = row.get("epcs_enrolled", False)
    out["panel_size"] = row.get("panel_size", 0)
    out["panel_cap"] = row.get("panel_cap", 2000)
    out["status"] = row.get("status", "ACTIVE")
    return out


def encounter_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["patient_id"] = row["patient_id"]
    out["provider_id"] = row["provider_id"]
    out["encounter_type"] = row["encounter_type"]
    out["scheduled_start"] = iso_format(row["scheduled_start"])
    out["scheduled_end"] = iso_format(row["scheduled_end"])
    out["actual_start"] = iso_format(row["actual_start"]) if row.get("actual_start") else None
    out["actual_end"] = iso_format(row["actual_end"]) if row.get("actual_end") else None
    out["chief_complaint"] = row.get("chief_complaint")
    out["vital_signs"] = row.get("vital_signs")
    out["bmi"] = row.get("bmi")
    out["status"] = row.get("status", "SCHEDULED")
    return out


def cpt_line_item_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": iso_format(row["created_at"]),
        "encounter_id": row["encounter_id"],
        "cpt_code": row["cpt_code"],
        "units": row["units"],
        "list_charge_cents": row["list_charge_cents"],
        "allowed_amount_cents": row.get("allowed_amount_cents"),
        "modifier": row.get("modifier"),
        "is_preventive": row.get("is_preventive", False),
    }


def cpt_fee_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "cpt_code": row["cpt_code"],
        "created_at": iso_format(row["created_at"]),
        "description": row["description"],
        "list_price_cents": row["list_price_cents"],
        "allowed_price_cents": row["allowed_price_cents"],
        "is_preventive": row.get("is_preventive", False),
        "is_telehealth_eligible": row.get("is_telehealth_eligible", False),
    }


def prescription_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["patient_id"] = row["patient_id"]
    out["provider_id"] = row["provider_id"]
    out["encounter_id"] = row["encounter_id"]
    out["drug_name"] = row["drug_name"]
    out["rxnorm_code"] = row["rxnorm_code"]
    out["is_controlled"] = row.get("is_controlled", False)
    out["dea_schedule"] = row.get("dea_schedule")
    out["dose_mg"] = row["dose_mg"]
    out["quantity"] = row["quantity"]
    out["refills_authorized"] = row["refills_authorized"]
    out["refills_remaining"] = row.get("refills_remaining")
    out["status"] = row.get("status", "DRAFT")
    out["signed_at"] = iso_format(row["signed_at"]) if row.get("signed_at") else None
    out["expires_at"] = iso_format(row["expires_at"]) if row.get("expires_at") else None
    return out


def referral_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["patient_id"] = row["patient_id"]
    out["referring_provider_id"] = row["referring_provider_id"]
    out["referred_to_provider_id"] = row["referred_to_provider_id"]
    out["encounter_id"] = row["encounter_id"]
    out["reason"] = row["reason"]
    out["priority"] = row.get("priority", "ROUTINE")
    out["status"] = row.get("status", "PENDING")
    out["accepted_at"] = iso_format(row["accepted_at"]) if row.get("accepted_at") else None
    out["expires_at"] = iso_format(row["expires_at"]) if row.get("expires_at") else None
    out["response_note"] = row.get("response_note")
    return out


def portal_message_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    _common(row, out)
    out["patient_id"] = row["patient_id"]
    out["provider_id"] = row["provider_id"]
    out["sender_role"] = row["sender_role"]
    out["body"] = row["body"]
    out["status"] = row.get("status", "UNREAD")
    out["triage_status"] = row.get("triage_status", "NEW")
    return out


def hedis_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "patient_id": row["patient_id"],
        "measure_id": row["measure_id"],
        "measurement_year": row["measurement_year"],
        "in_denominator": row["in_denominator"],
        "in_numerator": row["in_numerator"],
        "computed_at": iso_format(row["computed_at"]),
    }


def audit_to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "actor_role": row["actor_role"],
        "actor_id": row["actor_id"],
        "action": row["action"],
        "target_entity": row["target_entity"],
        "target_id": row["target_id"],
        "epcs_signature_hash": row.get("epcs_signature_hash"),
        "occurred_at": iso_format(row["occurred_at"]),
    }
