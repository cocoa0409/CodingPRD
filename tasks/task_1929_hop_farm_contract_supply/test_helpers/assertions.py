"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    Variety, PlantingPlanStatus, ContractStatus, HarvestLotStatus, LabTestType,
    PelletInventoryStatus, PelletAgeClass, AllocationStatus, SpotSaleStatus,
    SampleStatus, InsuranceClaimStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_field(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["acreage"], int) and data["acreage"] > 0


def assert_kiln(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0


def assert_planting_plan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("field_id", "")), "field_id must be a valid UUID"
    assert isinstance(data["crop_year"], int)
    assert data["variety"] in [v.value for v in Variety]
    assert isinstance(data["planned_acreage"], int) and data["planned_acreage"] >= 1
    assert isinstance(data["projected_yield_lbs"], int)
    assert data.get("actual_yield_lbs") is None or isinstance(data["actual_yield_lbs"], int)
    assert data["status"] in [s.value for s in PlantingPlanStatus]


def assert_contract(data: dict):
    _assert_common(data)
    assert isinstance(data["brewery_name"], str) and len(data["brewery_name"]) > 0
    assert data["variety"] in [v.value for v in Variety]
    assert isinstance(data["term_start_year"], int)
    assert isinstance(data["term_end_year"], int)
    assert data["term_end_year"] >= data["term_start_year"]
    assert isinstance(data["annual_volume_lbs"], int) and data["annual_volume_lbs"] > 0
    assert isinstance(data["base_price_cents_per_lb"], int) and data["base_price_cents_per_lb"] > 0
    assert data["alpha_floor_pct"] > 0
    assert isinstance(data["alpha_premium_cents_per_point"], int)
    assert data["alpha_premium_cents_per_point"] >= 0
    assert isinstance(data["alpha_discount_cents_per_point"], int)
    assert data["alpha_discount_cents_per_point"] >= 0
    assert isinstance(data["consecutive_shortfall_years"], int)
    assert data["consecutive_shortfall_years"] >= 0
    assert data["status"] in [s.value for s in ContractStatus]


def assert_harvest_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("planting_plan_id", "")), "planting_plan_id must be a valid UUID"
    assert data.get("kiln_id") is None or is_valid_uuid(data["kiln_id"])
    assert data["variety"] in [v.value for v in Variety]
    assert isinstance(data["crop_year"], int)
    assert isinstance(data["wet_lbs"], int) and data["wet_lbs"] > 0
    assert data.get("dried_lbs") is None or isinstance(data["dried_lbs"], int)
    assert data.get("moisture_pct") is None or isinstance(data["moisture_pct"], (int, float))
    assert data.get("alpha_pct_provisional") is None or isinstance(
        data["alpha_pct_provisional"], (int, float))
    assert data.get("alpha_pct_final") is None or isinstance(
        data["alpha_pct_final"], (int, float))
    assert data.get("kiln_window_start") is None or isinstance(data["kiln_window_start"], str)
    assert data.get("kiln_window_end") is None or isinstance(data["kiln_window_end"], str)
    assert data["status"] in [s.value for s in HarvestLotStatus]


def assert_lab_test(data: dict):
    """LabTest is an append-only record (PRD §2.4): only id + created_at from
    the common fields; updated_at and version must be absent."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "LabTest must not carry a version key"
    assert "updated_at" not in data, "LabTest must not carry an updated_at key"
    assert is_valid_uuid(data.get("harvest_lot_id", "")), "harvest_lot_id must be a valid UUID"
    assert data["test_type"] in [t.value for t in LabTestType]
    assert isinstance(data["alpha_pct"], (int, float))
    assert 0 < data["alpha_pct"] <= 25


def assert_pellet_lot(data: dict):
    _assert_common(data)
    assert isinstance(data["source_lot_ids"], list) and len(data["source_lot_ids"]) >= 1
    for lot_id in data["source_lot_ids"]:
        assert is_valid_uuid(lot_id), "source_lot_ids entries must be valid UUIDs"
    assert data["variety"] in [v.value for v in Variety]
    assert isinstance(data["crop_year"], int)
    assert isinstance(data["qty_lbs"], int) and data["qty_lbs"] >= 0
    assert data.get("blended_alpha_pct") is None or isinstance(
        data["blended_alpha_pct"], (int, float))
    assert isinstance(data["storage_room"], str) and len(data["storage_room"]) > 0
    assert is_iso8601_timestamp(data.get("entered_storage_at", "")), (
        "entered_storage_at must be ISO 8601")
    assert data["inventory_status"] in [s.value for s in PelletInventoryStatus]
    assert data["age_class"] in [a.value for a in PelletAgeClass]


def assert_allocation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a valid UUID"
    assert isinstance(data["crop_year"], int)
    assert data["variety"] in [v.value for v in Variety]
    assert isinstance(data["allocated_lbs"], int) and data["allocated_lbs"] >= 0
    assert isinstance(data["shortfall_lbs"], int) and data["shortfall_lbs"] >= 0
    assert isinstance(data["reserved_lot_ids"], list)
    assert isinstance(data["delivered_lot_ids"], list)
    assert isinstance(data["delivered_lbs"], int) and data["delivered_lbs"] >= 0
    assert data.get("delivered_alpha_pct") is None or isinstance(
        data["delivered_alpha_pct"], (int, float))
    assert data.get("estimated_unit_price_cents") is None or isinstance(
        data["estimated_unit_price_cents"], int)
    assert data.get("delivery_shortfall_lbs") is None or isinstance(
        data["delivery_shortfall_lbs"], int)
    assert data.get("unit_price_cents") is None or isinstance(data["unit_price_cents"], int)
    assert data.get("settlement_total_cents") is None or isinstance(
        data["settlement_total_cents"], int)
    assert data["status"] in [s.value for s in AllocationStatus]


def assert_spot_sale(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pellet_lot_id", "")), "pellet_lot_id must be a valid UUID"
    assert isinstance(data["buyer_name"], str) and len(data["buyer_name"]) > 0
    assert isinstance(data["price_cents_per_lb"], int) and data["price_cents_per_lb"] > 0
    assert isinstance(data["buyer_credit_limit_cents"], int)
    assert data["buyer_credit_limit_cents"] >= 0
    assert isinstance(data["qty_lbs"], int) and data["qty_lbs"] > 0
    assert data.get("sale_total_cents") is None or isinstance(data["sale_total_cents"], int)
    assert data["status"] in [s.value for s in SpotSaleStatus]


def assert_brewery_sample(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("pellet_lot_id", "")), "pellet_lot_id must be a valid UUID"
    assert isinstance(data["brewery_name"], str) and len(data["brewery_name"]) > 0
    assert isinstance(data["sample_round"], int) and data["sample_round"] >= 1
    assert data["status"] in [s.value for s in SampleStatus]


def assert_insurance_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("planting_plan_id", "")), (
        "planting_plan_id must be a valid UUID")
    assert isinstance(data["price_election_cents_per_lb"], int)
    assert data["price_election_cents_per_lb"] > 0
    assert 0 < data["coverage_pct"] <= 1
    assert isinstance(data["guarantee_lbs"], int) and data["guarantee_lbs"] >= 0
    assert isinstance(data["indemnity_estimate_cents"], int)
    assert data["indemnity_estimate_cents"] >= 0
    assert isinstance(data["filed_by_user_id"], str) and len(data["filed_by_user_id"]) > 0
    assert data.get("indemnity_final_cents") is None or isinstance(
        data["indemnity_final_cents"], int)
    assert data["status"] in [s.value for s in InsuranceClaimStatus]


def assert_allocation_volume_invariants(allocation: dict, contract_volume_lbs: int):
    """PRD §3.6 run invariants: allocated plus shortfall equals the contract's
    annual volume for every allocation produced by a run."""
    assert allocation["allocated_lbs"] + allocation["shortfall_lbs"] == contract_volume_lbs, (
        f"allocated {allocation['allocated_lbs']} + shortfall {allocation['shortfall_lbs']} "
        f"must equal annual volume {contract_volume_lbs}")
