"""Entity assertions and domain invariant checkers.

Each assert_* function validates the system-managed fields of PRD section 2.4
plus the entity's declared field surface and enum membership.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AtticValuationMethod,
    ClaimStatus,
    ClaimType,
    DeliveryStatus,
    DispositionType,
    KitStatus,
    LedgerStatus,
    ProgramStatus,
    PrototypeStatus,
    ReservationStatus,
    SignoffStatus,
    UtilizationPosture,
    WaveStatus,
)


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{entity}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{entity}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), \
        f"{entity}.version must be an integer"


def assert_rollout_program(data: dict):
    _assert_common_fields(data, "RolloutProgram")
    assert data["status"] in [s.value for s in ProgramStatus]
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert isinstance(data["retailer_code"], str) and data["retailer_code"]
    assert isinstance(data["budget_total_cents"], int)
    assert isinstance(data["contingency_budget_cents"], int)
    assert isinstance(data["recalled_part_numbers"], list)
    assert data["attic_valuation_method"] in \
        [m.value for m in AtticValuationMethod]
    assert isinstance(data["remaining_budget_cents"], int)
    assert isinstance(data["contingency_spent_cents"], int)
    assert isinstance(data["fulfilled_kit_count"], int)
    assert isinstance(data["closeout_recovery_cents"], int)
    assert "final_reconciliation_cents" in data


def assert_fixture_prototype(data: dict):
    _assert_common_fields(data, "FixturePrototype")
    assert data["status"] in [s.value for s in PrototypeStatus]
    assert isinstance(data["program_id"], str)
    assert isinstance(data["fixture_code"], str) and data["fixture_code"]
    assert isinstance(data["bom_lines"], list)
    for line in data["bom_lines"]:
        assert isinstance(line["part_number"], str)
        assert isinstance(line["quantity"], int) and line["quantity"] >= 1
        assert isinstance(line["list_unit_cost_cents"], int)
    assert isinstance(data["target_cost_cents"], int)
    assert isinstance(data["provisional_cost_cents"], int)
    assert isinstance(data["engineered_cost_cents"], int)
    assert "final_cost_cents" in data
    assert isinstance(data["ve_round_count"], int)
    assert "submitted_by_user_id" in data
    assert "approved_by_user_id" in data


def assert_store_kit_config(data: dict):
    _assert_common_fields(data, "StoreKitConfig")
    assert data["status"] in [s.value for s in KitStatus]
    assert isinstance(data["program_id"], str)
    assert isinstance(data["prototype_id"], str)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["config_lines"], list)
    for line in data["config_lines"]:
        assert isinstance(line["part_number"], str)
        assert isinstance(line["quantity"], int) and line["quantity"] >= 1
        assert isinstance(line["unit_cost_cents"], int)
    assert isinstance(data["total_components"], int)
    assert isinstance(data["kit_total_cost_cents"], int)
    assert "wave_release_charge_cents" in data
    assert "wave_id" in data


def assert_production_wave(data: dict):
    _assert_common_fields(data, "ProductionWave")
    assert data["status"] in [s.value for s in WaveStatus]
    assert isinstance(data["program_id"], str)
    assert isinstance(data["wave_label"], str) and data["wave_label"]
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert isinstance(data["capacity_units"], int) \
        and data["capacity_units"] >= 1
    assert isinstance(data["committed_units"], int)
    assert isinstance(data["utilization_pct"], (int, float))
    assert data["utilization_posture"] in [p.value for p in UtilizationPosture]


def assert_staging_reservation(data: dict):
    _assert_common_fields(data, "StagingReservation")
    assert data["status"] in [s.value for s in ReservationStatus]
    assert isinstance(data["kit_id"], str)
    assert isinstance(data["staging_bay_code"], str) \
        and data["staging_bay_code"]
    assert isinstance(data["start_ts"], str)
    assert isinstance(data["end_ts"], str)


def assert_install_delivery(data: dict):
    _assert_common_fields(data, "InstallDelivery")
    assert data["status"] in [s.value for s in DeliveryStatus]
    assert isinstance(data["kit_id"], str)
    assert isinstance(data["crew_code"], str) and data["crew_code"]
    assert isinstance(data["delivery_date"], str)
    assert isinstance(data["estimated_install_hours"], int) \
        and data["estimated_install_hours"] >= 1


def assert_damage_claim(data: dict):
    _assert_common_fields(data, "DamageClaim")
    assert data["status"] in [s.value for s in ClaimStatus]
    assert isinstance(data["delivery_id"], str)
    assert isinstance(data["part_number"], str)
    assert data["claim_type"] in [t.value for t in ClaimType]
    assert isinstance(data["replacement_component_count"], int) \
        and data["replacement_component_count"] >= 1
    assert isinstance(data["replacement_cost_cents"], int) \
        and data["replacement_cost_cents"] >= 0


def assert_install_signoff(data: dict):
    _assert_common_fields(data, "InstallSignoff")
    assert data["status"] in [s.value for s in SignoffStatus]
    assert isinstance(data["delivery_id"], str)
    assert isinstance(data["photo_urls"], list) and len(data["photo_urls"]) >= 1
    assert isinstance(data["submission_count"], int) \
        and data["submission_count"] >= 1
    assert "submitted_by_user_id" in data
    assert "reviewed_by_user_id" in data
    assert "rejection_reason" in data


def assert_attic_stock_ledger(data: dict):
    _assert_common_fields(data, "AtticStockLedger")
    assert data["status"] in [s.value for s in LedgerStatus]
    assert isinstance(data["kit_id"], str)
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["quantity_on_hand"], int) \
        and data["quantity_on_hand"] >= 0
    assert isinstance(data["reorder_point"], int)
    assert isinstance(data["reorder_required"], bool)
    assert isinstance(data["unit_cost_cents"], int)
    assert "disposition_type" in data
    if data["disposition_type"] is not None:
        assert data["disposition_type"] in [d.value for d in DispositionType]
    assert "recovery_value_cents" in data
