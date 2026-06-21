"""Entity assertions and domain invariant checkers.

These validate the common envelope shape and per-entity field types, plus the
arithmetic invariants of the dose/waste and prior-auth calculations.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common(data: dict):
    """Every entity carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["mrn"], str) and len(data["mrn"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["status"] in ("ACTIVE", "DECEASED"), f"unexpected status {data['status']!r}"
    assert isinstance(data["bsa_m2"], (int, float)) and data["bsa_m2"] > 0


def assert_regimen_protocol(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["status"] in ("DRAFT", "PUBLISHED")
    assert data["cycle_length_days"] >= 1
    assert data["total_cycles"] >= 1


def assert_order_set_item(data: dict):
    _assert_common(data)
    assert data["role"] in ("CHEMO", "PREMED")
    assert data["dosing_method"] in ("BSA", "AUC", "FLAT")
    assert data["vial_size_mg"] > 0
    assert data["day_offset"] >= 1


def assert_chair(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["is_isolation"], bool)


def assert_nurse(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["is_chemo_certified"], bool)
    assert data["max_acuity_load"] >= 1


def assert_prior_authorization(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "EXHAUSTED")
    assert data["consumed_units_mg"] >= 0


def assert_treatment_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in ("PLANNED", "ACTIVE", "ON_HOLD", "COMPLETED", "ABANDONED")
    assert data["current_cycle_number"] >= 1


def assert_drug_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("ORDERED", "PREPARED", "VERIFIED", "ADMINISTERED", "CANCELLED")
    assert data["ordered_dose_mg"] >= 0
    assert data["vials_drawn"] >= 0
    assert isinstance(data["jw_modifier"], bool)


def assert_infusion_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED")
    assert 1 <= data["acuity"] <= 5


def assert_toxicity_event(data: dict):
    _assert_common(data)
    assert 1 <= data["ctcae_grade"] <= 5
    assert isinstance(data["triggered_hold"], bool)


def assert_dose_waste_invariants(data: dict):
    """Arithmetic invariants of the dose/vial/waste computation (PRD §3.7).

    supplied_mg = vials_drawn * vial_size; waste_mg = supplied - ordered;
    jw_modifier <=> waste_mg > 0.
    """
    assert data["supplied_mg"] >= data["ordered_dose_mg"], "supplied must cover ordered dose"
    assert data["waste_mg"] == data["supplied_mg"] - data["ordered_dose_mg"], (
        f"waste_mg {data['waste_mg']} != supplied {data['supplied_mg']} - ordered {data['ordered_dose_mg']}"
    )
    assert data["jw_modifier"] == (data["waste_mg"] > 0), (
        "jw_modifier must be true exactly when waste_mg > 0"
    )


def assert_prior_auth_conserved(data: dict, authorized: float):
    """authorized == remaining + consumed, where remaining = authorized - consumed (PRD §3.8)."""
    consumed = data["consumed_units_mg"]
    remaining = data["authorized_units_mg"] - consumed
    assert data["authorized_units_mg"] == authorized
    assert remaining + consumed == authorized, "PA units must be conserved (no drift)"
