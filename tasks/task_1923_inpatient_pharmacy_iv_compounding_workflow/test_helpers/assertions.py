"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    BatchStatus,
    DiscrepancyCaseStatus,
    DiversionCaseStatus,
    DrugSchedule,
    DrugStatus,
    FulfillmentStatus,
    HoodSessionStatus,
    InterventionType,
    InventoryEventType,
    IsoClass,
    OpenedVia,
    PocketStatus,
    PreparationStatus,
    ProtocolStatus,
    RenalDosingPolicy,
    Route,
    StaffRole,
    StorageCondition,
    UspRiskLevel,
    VerificationStatus,
)


def _enum_values(enum_cls):
    return [e.value for e in enum_cls]


def assert_common_versioned(data: dict):
    """Common fields of a versioned resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_common_append_only(data: dict):
    """Append-only records carry only id + created_at (PRD §2.4, §3.9)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_staff_member(data: dict):
    assert_common_versioned(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["staff_role"] in _enum_values(StaffRole)
    if data.get("hd_compounding_certified") is not None:
        assert isinstance(data["hd_compounding_certified"], bool)
    assert isinstance(data.get("active"), bool)


def assert_patient_profile(data: dict):
    assert_common_versioned(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["sex"] in ("M", "F")
    assert isinstance(data["height_cm"], (int, float))
    assert isinstance(data["weight_kg"], (int, float))
    assert isinstance(data["scr_mg_dl"], (int, float))
    assert isinstance(data.get("allergy_drug_product_ids", []), list)
    assert isinstance(data.get("age_years"), int)
    assert isinstance(data.get("bmi"), (int, float))
    assert isinstance(data.get("ibw_kg"), (int, float))


def assert_drug_product(data: dict):
    assert_common_versioned(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["schedule"] in _enum_values(DrugSchedule)
    assert data["status"] in _enum_values(DrugStatus)
    assert isinstance(data["concentration_mg_per_ml"], (int, float))
    assert isinstance(data["vial_size_ml"], (int, float))


def assert_hood(data: dict):
    assert_common_versioned(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["iso_class"] in _enum_values(IsoClass)
    assert isinstance(data.get("is_hd_rated"), bool)


def assert_hood_session(data: dict):
    assert_common_versioned(data)
    assert data["status"] in _enum_values(HoodSessionStatus)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])


def assert_coverage_shift(data: dict):
    assert_common_versioned(data)
    assert isinstance(data["staff_id"], str)
    assert isinstance(data["zone"], str) and data["zone"]
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])


def assert_medication_order(data: dict):
    assert_common_versioned(data)
    assert data["route"] in _enum_values(Route)
    assert data["verification_status"] in _enum_values(VerificationStatus)
    assert data["fulfillment_status"] in _enum_values(FulfillmentStatus)
    assert isinstance(data["ordered_dose_mg"], (int, float))
    assert isinstance(data["frequency_per_day"], int)
    assert isinstance(data.get("substitution_pending"), bool)


def assert_clinical_intervention(data: dict):
    assert_common_append_only(data)
    assert data["intervention_type"] in _enum_values(InterventionType)
    assert isinstance(data["note"], str)
    assert isinstance(data.get("placed_on_hold"), bool)
    assert isinstance(data.get("pharmacist_staff_id"), str)


def assert_batch(data: dict):
    assert_common_versioned(data)
    assert data["status"] in _enum_values(BatchStatus)
    assert data["usp_risk_level"] in _enum_values(UspRiskLevel)
    assert isinstance(data.get("rework_count"), int)


def assert_preparation(data: dict):
    assert_common_versioned(data)
    assert data["status"] in _enum_values(PreparationStatus)
    if data.get("storage_condition") is not None:
        assert data["storage_condition"] in _enum_values(StorageCondition)
    if data.get("bud_expiry") is not None:
        assert is_iso8601_timestamp(data["bud_expiry"])


def assert_adc_station(data: dict):
    assert_common_versioned(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["zone"], str) and data["zone"]


def assert_adc_pocket(data: dict):
    assert_common_versioned(data)
    assert data["status"] in _enum_values(PocketStatus)
    assert isinstance(data["max_units"], int)
    assert isinstance(data["on_hand_units"], int)
    assert isinstance(data.get("pick_blocked"), bool)


def assert_inventory_event(data: dict):
    assert_common_append_only(data)
    assert data["event_type"] in _enum_values(InventoryEventType)
    assert isinstance(data["units_delta"], int)
    assert isinstance(data.get("expected_on_hand_after"), int)


def assert_discrepancy_case(data: dict):
    assert_common_versioned(data)
    assert data["status"] in _enum_values(DiscrepancyCaseStatus)
    assert isinstance(data.get("variance_units"), int)


def assert_diversion_case(data: dict):
    assert_common_versioned(data)
    assert data["status"] in _enum_values(DiversionCaseStatus)
    assert data["opened_via"] in _enum_values(OpenedVia)


def assert_substitution_protocol(data: dict):
    assert_common_versioned(data)
    assert data["status"] in _enum_values(ProtocolStatus)
    assert isinstance(data["conversion_factor"], (int, float))
    assert isinstance(data["max_dose_mg"], (int, float))
    assert is_iso8601_timestamp(data["expires_at"])


def assert_waste_record(data: dict):
    assert_common_append_only(data)
    assert isinstance(data.get("reason"), str)


def assert_batch_mass_invariant(batch: dict):
    """PRD §3.5: total_drawn_ml equals delivered_ml plus waste_ml at every read."""
    total = batch.get("total_drawn_ml")
    delivered = batch.get("delivered_ml")
    waste = batch.get("waste_ml")
    if total is None or delivered is None or waste is None:
        return
    assert abs(total - (delivered + waste)) < 1e-6, (
        f"mass invariant violated: total_drawn_ml {total} != "
        f"delivered_ml {delivered} + waste_ml {waste}"
    )


def assert_pocket_ledger_consistent(pocket: dict, events: list):
    """PRD §3.6: on_hand_units equals the chronological replay of units_delta."""
    replay = sum(e["units_delta"] for e in events)
    assert pocket["on_hand_units"] == replay, (
        f"on_hand_units {pocket['on_hand_units']} != ledger replay {replay}"
    )
