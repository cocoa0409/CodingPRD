"""Entity assertions and domain invariant checkers.

Each per-entity assert_<entity>() verifies the PRD-declared shape of a
single response payload. Field names mirror PRD prose exactly.
"""
from __future__ import annotations

from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Status value sets — verbatim from PRD entity descriptions.
# ---------------------------------------------------------------------------
PATIENT_STATUSES = {"ACTIVE", "INACTIVE"}
PROVIDER_STATUSES = {"ACTIVE", "INACTIVE"}
PROVIDER_ROLE_TYPES = {"PCP_ONLY", "SPECIALIST_ONLY", "BOTH"}
SEX_AT_BIRTH = {"MALE", "FEMALE", "UNKNOWN"}
SMOKING_STATUSES = {"NEVER", "FORMER", "CURRENT", "UNKNOWN"}
ENCOUNTER_STATUSES = {
    "SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW",
}
ENCOUNTER_TYPES = {"CONSULTATION", "PHYSICAL", "VACCINATION"}
PRESCRIPTION_STATUSES = {
    "DRAFT", "SIGNED", "TRANSMITTED", "DISPENSED", "CANCELLED", "EXPIRED",
}
DEA_SCHEDULES = {"II", "III", "IV", "V"}
REFERRAL_STATUSES = {
    "PENDING", "ACCEPTED", "REJECTED", "COMPLETED", "EXPIRED",
}
REFERRAL_PRIORITIES = {"ROUTINE", "URGENT"}
PORTAL_MESSAGE_STATUSES = {"UNREAD", "READ", "ARCHIVED"}
PORTAL_MESSAGE_TRIAGE_STATUSES = {"NEW", "TRIAGED", "ESCALATED"}
PORTAL_MESSAGE_SENDER_ROLES = {"PATIENT", "PROVIDER"}
HEDIS_MEASURE_IDS = {"AWV", "CBP", "TSC", "CCS"}


# ---------------------------------------------------------------------------
# Patient — PRD §3.1 / §2.4.
# ---------------------------------------------------------------------------
def assert_patient(data: Dict[str, Any]) -> None:
    """PRD §2.4: Patient carries id, created_at, updated_at, version
    plus its own fields. PRD §3.1 fixes the input shape."""
    assert is_valid_uuid(data.get("id", "")), (
        f"Patient.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "Patient.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "Patient.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), (
        "Patient.version must be an integer"
    )
    assert data["version"] >= 1, "Patient.version must be >= 1"
    # Required identifying fields.
    assert isinstance(data.get("mrn"), str) and data["mrn"], (
        "Patient.mrn must be a non-empty string"
    )
    assert isinstance(data.get("first_name"), str) and data["first_name"], (
        "Patient.first_name must be a non-empty string"
    )
    assert isinstance(data.get("last_name"), str) and data["last_name"], (
        "Patient.last_name must be a non-empty string"
    )
    assert isinstance(data.get("date_of_birth"), str), (
        "Patient.date_of_birth must be ISO date string"
    )
    assert data.get("sex_at_birth") in SEX_AT_BIRTH, (
        f"Patient.sex_at_birth must be one of {SEX_AT_BIRTH}, "
        f"got {data.get('sex_at_birth')!r}"
    )
    assert data.get("status") in PATIENT_STATUSES, (
        f"Patient.status must be one of {PATIENT_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert data.get("smoking_status") in SMOKING_STATUSES, (
        f"Patient.smoking_status must be one of {SMOKING_STATUSES}, "
        f"got {data.get('smoking_status')!r}"
    )
    assert isinstance(data.get("portal_enabled"), bool), (
        "Patient.portal_enabled must be a bool"
    )
    assert isinstance(data.get("chronic_conditions"), list), (
        "Patient.chronic_conditions must be a list"
    )
    pcp_provider_id = data.get("pcp_provider_id")
    if pcp_provider_id is not None:
        assert is_valid_uuid(pcp_provider_id), (
            "Patient.pcp_provider_id must be UUID when non-null"
        )


# ---------------------------------------------------------------------------
# Provider — PRD §3.2 / §2.4.
# ---------------------------------------------------------------------------
def assert_provider(data: Dict[str, Any]) -> None:
    """PRD §3.2 fixes the input shape; PRD §2.4 fixes the common
    fields."""
    assert is_valid_uuid(data.get("id", "")), (
        f"Provider.id must be UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert isinstance(data.get("npi"), str) and data["npi"]
    assert isinstance(data.get("full_name"), str) and data["full_name"]
    assert data.get("role_type") in PROVIDER_ROLE_TYPES, (
        f"Provider.role_type must be one of {PROVIDER_ROLE_TYPES}, "
        f"got {data.get('role_type')!r}"
    )
    assert data.get("status") in PROVIDER_STATUSES
    assert isinstance(data.get("epcs_enrolled"), bool)
    assert isinstance(data.get("panel_size"), int)
    assert data["panel_size"] >= 0
    assert isinstance(data.get("panel_cap"), int)
    assert data["panel_cap"] >= 0


# ---------------------------------------------------------------------------
# Encounter — PRD §3.3 / §2.4.
# ---------------------------------------------------------------------------
def assert_encounter(data: Dict[str, Any]) -> None:
    """PRD §3.3."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("patient_id", "")), (
        "Encounter.patient_id must be a UUID"
    )
    assert is_valid_uuid(data.get("provider_id", "")), (
        "Encounter.provider_id must be a UUID"
    )
    assert data.get("encounter_type") in ENCOUNTER_TYPES, (
        f"Encounter.encounter_type must be one of {ENCOUNTER_TYPES}"
    )
    assert is_iso8601_timestamp(data.get("scheduled_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end", ""))
    assert data.get("status") in ENCOUNTER_STATUSES, (
        f"Encounter.status must be one of {ENCOUNTER_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# CptLineItem — PRD §3.3 / §2.4 (append-only).
# ---------------------------------------------------------------------------
def assert_cpt_line_item(data: Dict[str, Any]) -> None:
    """PRD §2.4: CptLineItem carries only id and created_at — no
    updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"CptLineItem.id must be UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", ""))
    # PRD §2.4: CptLineItem does not carry updated_at or version.
    assert "updated_at" not in data or data.get("updated_at") is None or \
        is_iso8601_timestamp(data["updated_at"]), (
        "If present, CptLineItem.updated_at must be ISO 8601"
    )
    assert is_valid_uuid(data.get("encounter_id", "")), (
        "CptLineItem.encounter_id must be UUID"
    )
    assert isinstance(data.get("cpt_code"), str)
    assert isinstance(data.get("units"), int)
    assert data["units"] >= 1
    assert isinstance(data.get("list_charge_cents"), int), (
        "CptLineItem.list_charge_cents must be an integer"
    )
    assert data["list_charge_cents"] >= 0
    aac = data.get("allowed_amount_cents")
    if aac is not None:
        assert isinstance(aac, int) and aac >= 0, (
            "CptLineItem.allowed_amount_cents must be a non-negative "
            "integer when set"
        )
    assert isinstance(data.get("is_preventive"), bool)


# ---------------------------------------------------------------------------
# CptFeeCatalog — PRD §3.7 / §2.4 (cpt_code is PK, no id).
# ---------------------------------------------------------------------------
def assert_cpt_fee_catalog(data: Dict[str, Any]) -> None:
    """PRD §3.7: cpt_code is the primary key in place of id."""
    assert isinstance(data.get("cpt_code"), str) and data["cpt_code"], (
        "CptFeeCatalog.cpt_code must be a non-empty string"
    )
    assert isinstance(data.get("description"), str)
    assert isinstance(data.get("list_price_cents"), int)
    assert data["list_price_cents"] >= 0
    assert isinstance(data.get("allowed_price_cents"), int)
    assert data["allowed_price_cents"] >= 0
    assert isinstance(data.get("is_preventive"), bool)
    assert isinstance(data.get("is_telehealth_eligible"), bool)


# ---------------------------------------------------------------------------
# Prescription — PRD §3.4 / §2.4.
# ---------------------------------------------------------------------------
def assert_prescription(data: Dict[str, Any]) -> None:
    """PRD §3.4."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert is_valid_uuid(data.get("encounter_id", ""))
    assert isinstance(data.get("drug_name"), str)
    assert isinstance(data.get("rxnorm_code"), str)
    assert isinstance(data.get("is_controlled"), bool)
    if data["is_controlled"]:
        assert data.get("dea_schedule") in DEA_SCHEDULES, (
            "Controlled Prescription.dea_schedule must be one of "
            f"{DEA_SCHEDULES}"
        )
    else:
        assert data.get("dea_schedule") in (None, ""), (
            "Non-controlled Prescription.dea_schedule must be null"
        )
    assert isinstance(data.get("dose_mg"), (int, float))
    assert isinstance(data.get("quantity"), int)
    assert isinstance(data.get("refills_authorized"), int)
    assert data.get("status") in PRESCRIPTION_STATUSES, (
        f"Prescription.status must be one of {PRESCRIPTION_STATUSES}, "
        f"got {data.get('status')!r}"
    )


# ---------------------------------------------------------------------------
# Referral — PRD §3.5 / §2.4.
# ---------------------------------------------------------------------------
def assert_referral(data: Dict[str, Any]) -> None:
    """PRD §3.5."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("referring_provider_id", ""))
    assert is_valid_uuid(data.get("referred_to_provider_id", ""))
    assert is_valid_uuid(data.get("encounter_id", ""))
    assert isinstance(data.get("reason"), str)
    assert data.get("priority") in REFERRAL_PRIORITIES
    assert data.get("status") in REFERRAL_STATUSES, (
        f"Referral.status must be one of {REFERRAL_STATUSES}, "
        f"got {data.get('status')!r}"
    )
    assert is_iso8601_timestamp(data.get("expires_at", "")), (
        "Referral.expires_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# PortalMessage — PRD §3.6 / §2.4 — two parallel dimensions.
# ---------------------------------------------------------------------------
def assert_portal_message(data: Dict[str, Any]) -> None:
    """PRD §3.6."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data.get("version"), int) and data["version"] >= 1
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("provider_id", ""))
    assert data.get("sender_role") in PORTAL_MESSAGE_SENDER_ROLES, (
        f"PortalMessage.sender_role must be one of "
        f"{PORTAL_MESSAGE_SENDER_ROLES}, got {data.get('sender_role')!r}"
    )
    assert isinstance(data.get("body"), str)
    assert data.get("status") in PORTAL_MESSAGE_STATUSES, (
        f"PortalMessage.status must be one of {PORTAL_MESSAGE_STATUSES}"
    )
    assert data.get("triage_status") in PORTAL_MESSAGE_TRIAGE_STATUSES, (
        "PortalMessage.triage_status must be one of "
        f"{PORTAL_MESSAGE_TRIAGE_STATUSES}"
    )


# ---------------------------------------------------------------------------
# HedisMeasurement — PRD §3.8 / §2.4 (append-only).
# ---------------------------------------------------------------------------
def assert_hedis_measurement(data: Dict[str, Any]) -> None:
    """PRD §2.4: HedisMeasurement carries only id and the equivalent
    computed_at snapshot timestamp — no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"HedisMeasurement.id must be UUID, got {data.get('id')!r}"
    )
    assert is_valid_uuid(data.get("patient_id", ""))
    assert data.get("measure_id") in HEDIS_MEASURE_IDS, (
        f"HedisMeasurement.measure_id must be one of "
        f"{HEDIS_MEASURE_IDS}, got {data.get('measure_id')!r}"
    )
    assert isinstance(data.get("measurement_year"), int)
    assert isinstance(data.get("in_denominator"), bool)
    assert isinstance(data.get("in_numerator"), bool)
    assert is_iso8601_timestamp(data.get("computed_at", "")), (
        "HedisMeasurement.computed_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# AuditLog — PRD §2.10 / §3.9 (append-only).
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    """PRD §2.10: each row records actor_role, actor_id, action,
    target_entity, target_id, occurred_at, epcs_signature_hash."""
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("action"), str)
    assert isinstance(data.get("target_entity"), str)
    assert isinstance(data.get("target_id"), str)
    assert is_iso8601_timestamp(data.get("occurred_at", "")), (
        "AuditLog.occurred_at must be ISO 8601"
    )


# ---------------------------------------------------------------------------
# Version helpers — PRD §2.4 / §2.11.
# ---------------------------------------------------------------------------
def assert_version_incremented_by_one(new_version: int,
                                      old_version: int) -> None:
    """PRD §2.4: "increments by exactly one on every successful
    mutation"."""
    assert new_version == old_version + 1, (
        f"version expected to advance by exactly 1, "
        f"got old={old_version} new={new_version}"
    )


__all__ = [
    "PATIENT_STATUSES",
    "PROVIDER_STATUSES",
    "PROVIDER_ROLE_TYPES",
    "SEX_AT_BIRTH",
    "SMOKING_STATUSES",
    "ENCOUNTER_STATUSES",
    "ENCOUNTER_TYPES",
    "PRESCRIPTION_STATUSES",
    "DEA_SCHEDULES",
    "REFERRAL_STATUSES",
    "REFERRAL_PRIORITIES",
    "PORTAL_MESSAGE_STATUSES",
    "PORTAL_MESSAGE_TRIAGE_STATUSES",
    "PORTAL_MESSAGE_SENDER_ROLES",
    "HEDIS_MEASURE_IDS",
    "assert_patient",
    "assert_provider",
    "assert_encounter",
    "assert_cpt_line_item",
    "assert_cpt_fee_catalog",
    "assert_prescription",
    "assert_referral",
    "assert_portal_message",
    "assert_hedis_measurement",
    "assert_audit_log",
    "assert_version_incremented_by_one",
]
