"""Per-entity assertions and domain invariant checkers (PRD §2.4, §3).

Field-shape and value-range assertions stick to PRD prose. Computed
fields are asserted only where PRD states they are exposed. Common-fields
discipline is split between full (id+created_at+updated_at+version) and
bare (id+created_at only) per PRD §2.4.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-field shape (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_common_fields_full(data: Dict[str, Any], label: str) -> None:
    """Entities that PRD §2.4 lists as carrying id + created_at + updated_at + version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 with three fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 with three fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be a positive integer, got {version!r}"
    )


def _assert_common_fields_bare(data: Dict[str, Any], label: str) -> None:
    """Append-only entities (PRD §2.4): only id + created_at are present."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Owner (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_owner(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Owner")
    assert isinstance(data.get("full_name"), str) and 1 <= len(data["full_name"]) <= 80
    assert isinstance(data.get("phone_e164"), str)
    assert isinstance(data.get("email"), str)
    assert isinstance(data.get("contact_verified"), bool)
    assert isinstance(data.get("deposit_balance_cents"), int)
    assert data["deposit_balance_cents"] >= 0


# ---------------------------------------------------------------------------
# Pet (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_pet(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Pet")
    assert isinstance(data.get("owner_id"), str)
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 60
    assert data.get("species") in {"DOG", "CAT", "RABBIT", "BIRD", "OTHER"}
    assert isinstance(data.get("birth_date"), str)
    assert isinstance(data.get("weight_kg"), (int, float))
    assert 0.05 <= float(data["weight_kg"]) <= 200
    assert isinstance(data.get("medical_history"), list)
    assert isinstance(data.get("archived"), bool)


# ---------------------------------------------------------------------------
# Visit (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_visit(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Visit")
    assert isinstance(data.get("pet_id"), str)
    assert isinstance(data.get("symptom_text"), str)
    assert 1 <= len(data["symptom_text"]) <= 2000
    assert isinstance(data.get("severity_score"), int)
    assert 1 <= data["severity_score"] <= 10
    status = data.get("status")
    assert status in {
        "REGISTERED", "TRIAGED", "IN_CONSULT",
        "CONSULT_DONE", "HOSPITALIZED", "CLOSED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# TreatmentRecord (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_treatment_record(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "TreatmentRecord")
    assert isinstance(data.get("visit_id"), str)
    assert isinstance(data.get("consultation_notes"), str)
    assert 1 <= len(data["consultation_notes"]) <= 4000
    assert isinstance(data.get("diagnosis_code"), str)
    assert isinstance(data.get("treatment_plan"), str)
    assert 1 <= len(data["treatment_plan"]) <= 2000
    assert isinstance(data.get("consent_recorded"), bool)
    assert data.get("status") in {"DRAFT", "FINALIZED", "AMENDED"}


# ---------------------------------------------------------------------------
# LabReport (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_lab_report(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "LabReport")
    assert isinstance(data.get("visit_id"), str)
    assert isinstance(data.get("test_items"), list)
    assert 1 <= len(data["test_items"]) <= 50
    assert isinstance(data.get("results"), list)
    assert isinstance(data.get("abnormal_codes"), list)
    assert data.get("status") in {
        "ORDERED", "SAMPLE_COLLECTED", "SENT_TO_LAB",
        "RESULT_RECEIVED", "FINALIZED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# Drug (PRD §3.7)
# ---------------------------------------------------------------------------
def assert_drug(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Drug")
    assert isinstance(data.get("code"), str)
    assert isinstance(data.get("name"), str) and 1 <= len(data["name"]) <= 80
    assert isinstance(data.get("controlled"), bool)
    assert isinstance(data.get("dosage_min_mg_per_kg"), (int, float))
    assert isinstance(data.get("dosage_max_mg_per_kg"), (int, float))
    assert float(data["dosage_min_mg_per_kg"]) > 0
    assert float(data["dosage_max_mg_per_kg"]) >= float(data["dosage_min_mg_per_kg"])
    assert isinstance(data.get("interactions"), list)
    assert isinstance(data.get("stock_units"), int)
    assert data["stock_units"] >= 0


# ---------------------------------------------------------------------------
# Prescription (PRD §3.7)
# ---------------------------------------------------------------------------
def assert_prescription(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Prescription")
    assert isinstance(data.get("visit_id"), str)
    assert isinstance(data.get("drafting_vet_id"), str)
    assert isinstance(data.get("items"), list)
    assert 1 <= len(data["items"]) <= 20
    assert data.get("interaction_risk") in {"NONE", "MILD", "MODERATE", "SEVERE"}
    assert data.get("status") in {
        "DRAFT", "PENDING_REVIEW", "REJECTED",
        "APPROVED", "DISPENSED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# Cage / Hospitalization (PRD §3.8)
# ---------------------------------------------------------------------------
def assert_cage(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Cage")
    assert isinstance(data.get("cage_code"), str)
    assert data.get("ward_code") in {"ISOLATION", "GENERAL", "ICU"}
    assert isinstance(data.get("capacity"), int)
    assert 1 <= data["capacity"] <= 4
    assert isinstance(data.get("occupancy_count"), int)
    assert 0 <= data["occupancy_count"] <= data["capacity"]


def assert_hospitalization(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Hospitalization")
    assert isinstance(data.get("visit_id"), str)
    assert isinstance(data.get("cage_id"), str)
    assert is_iso8601_timestamp(data.get("admitted_at", ""))
    assert isinstance(data.get("daily_care_log"), list)
    assert data.get("status") in {
        "ADMITTED", "IN_CARE", "DISCHARGE_PENDING",
        "DISCHARGED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# Bill (PRD §3.9)
# ---------------------------------------------------------------------------
def assert_bill(data: Dict[str, Any]) -> None:
    _assert_common_fields_full(data, "Bill")
    assert isinstance(data.get("visit_id"), str)
    assert isinstance(data.get("line_items"), list)
    for li in data["line_items"]:
        assert li.get("kind") in {"CONSULT", "LAB", "DRUG", "HOSPITAL_DAY"}
        assert isinstance(li.get("ref_id"), str)
        assert isinstance(li.get("qty"), int)
        assert isinstance(li.get("unit_price_cents"), int)
        assert isinstance(li.get("line_total_cents"), int)
    for f in (
        "deposit_applied_cents",
        "insurance_estimate_cents",
        "insurance_actual_cents",
        "provisional_total_cents",
        "final_total_cents",
        "paid_amount_cents",
        "refund_amount_cents",
    ):
        v = data.get(f)
        assert isinstance(v, int), f"Bill.{f} must be int, got {type(v).__name__}"
        assert v >= 0, f"Bill.{f} must be non-negative, got {v}"
    assert data.get("status") in {
        "DRAFT", "ISSUED", "PARTIALLY_PAID", "PAID",
        "REFUND_PENDING", "REFUNDED", "INVOICED", "CANCELLED",
    }


# ---------------------------------------------------------------------------
# VaccineSchedule / VaccinationRecord (PRD §3.3, §2.4 — bare common_fields)
# ---------------------------------------------------------------------------
def assert_vaccine_schedule(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "VaccineSchedule")
    assert data.get("species") in {"DOG", "CAT", "RABBIT", "BIRD", "OTHER"}
    assert isinstance(data.get("vaccine_code"), str)
    assert isinstance(data.get("age_min_days"), int)
    assert 0 <= data["age_min_days"] <= 7300
    if data.get("booster_interval_days") is not None:
        assert isinstance(data["booster_interval_days"], int)
        assert 7 <= data["booster_interval_days"] <= 1825


def assert_vaccination_record(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "VaccinationRecord")
    assert isinstance(data.get("pet_id"), str)
    assert isinstance(data.get("vaccine_code"), str)
    assert is_iso8601_timestamp(data.get("administered_at", ""))
    assert isinstance(data.get("batch_id"), str)
    assert data.get("status") in {"ACTIVE", "RECALLED", "SUPERSEDED"}


# ---------------------------------------------------------------------------
# AuditLog (PRD §3.10)
# ---------------------------------------------------------------------------
def assert_audit_log(data: Dict[str, Any]) -> None:
    _assert_common_fields_bare(data, "AuditLog")
    assert data.get("subject_type") in {"PRESCRIPTION", "TREATMENT_RECORD"}
    assert isinstance(data.get("subject_id"), str)
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert data.get("action") in {
        "DRAFT", "SUBMIT", "APPROVE", "REJECT",
        "DISPENSE", "FINALIZE", "AMEND", "CANCEL",
    }
    assert isinstance(data.get("to_state"), str)
    assert isinstance(data.get("payload_hash"), str)
    assert is_iso8601_timestamp(data.get("occurred_at", ""))


# ---------------------------------------------------------------------------
# Domain invariants
# ---------------------------------------------------------------------------
def find_audit_log(
    audit_logs: Iterable[Dict[str, Any]],
    *,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    action: Optional[str] = None,
    to_state: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Return first AuditLog row matching the filter, or None."""
    for log in audit_logs:
        if subject_type is not None and log.get("subject_type") != subject_type:
            continue
        if subject_id is not None and log.get("subject_id") != subject_id:
            continue
        if action is not None and log.get("action") != action:
            continue
        if to_state is not None and log.get("to_state") != to_state:
            continue
        return log
    return None


def find_line_item(
    line_items: Iterable[Dict[str, Any]],
    *,
    kind: Optional[str] = None,
    ref_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    for li in line_items:
        if kind is not None and li.get("kind") != kind:
            continue
        if ref_id is not None and li.get("ref_id") != ref_id:
            continue
        return li
    return None


def count_line_items(
    line_items: Iterable[Dict[str, Any]],
    *,
    kind: Optional[str] = None,
) -> int:
    if kind is None:
        return sum(1 for _ in line_items)
    return sum(1 for li in line_items if li.get("kind") == kind)


def assert_bill_provisional_invariants(data: Dict[str, Any]) -> None:
    """Invariants per PRD §2.8 / §3.9: integer cents, non-negative, floor at 0."""
    for f in ("provisional_total_cents", "deposit_applied_cents",
              "insurance_estimate_cents", "insurance_actual_cents",
              "paid_amount_cents", "refund_amount_cents"):
        assert isinstance(data[f], int) and data[f] >= 0


__all__ = [
    "assert_owner",
    "assert_pet",
    "assert_visit",
    "assert_treatment_record",
    "assert_lab_report",
    "assert_drug",
    "assert_prescription",
    "assert_cage",
    "assert_hospitalization",
    "assert_bill",
    "assert_vaccine_schedule",
    "assert_vaccination_record",
    "assert_audit_log",
    "assert_bill_provisional_invariants",
    "find_audit_log",
    "find_line_item",
    "count_line_items",
]
