"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_landowner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["tax_id"], str) and data["tax_id"]
    assert isinstance(data["cost_share_eligible"], bool)


def assert_seed_zone(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["min_elevation_ft"], int)
    assert isinstance(data["max_elevation_ft"], int)
    assert data["min_elevation_ft"] < data["max_elevation_ft"]
    assert data["band_midpoint_ft"] == (data["min_elevation_ft"] + data["max_elevation_ft"]) / 2


def assert_seed_lot(data: dict):
    _assert_common_fields(data)
    assert data["species"] in ("DOUGLAS_FIR", "LOBLOLLY_PINE", "WHITE_OAK")
    assert isinstance(data["quantity_grams"], int) and data["quantity_grams"] > 0
    assert 0 < data["germination_pct"] <= 1
    assert isinstance(data["remaining_grams"], int) and data["remaining_grams"] >= 0
    assert data["status"] in ("AVAILABLE", "QUARANTINED", "DEPLETED")


def assert_crop_batch(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("PLANNED", "SOWN", "LIFTED", "GRADED", "DEPLETED")


def assert_seedling_order(data: dict):
    _assert_common_fields(data)
    assert data["species"] in ("DOUGLAS_FIR", "LOBLOLLY_PINE", "WHITE_OAK")
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["total_price_cents"], int)
    assert isinstance(data["allocated_quantity"], int) and data["allocated_quantity"] >= 0
    assert isinstance(data["shipped_quantity"], int) and data["shipped_quantity"] >= 0
    assert data["status"] in (
        "PENDING_REVIEW", "CONFIRMED", "ALLOCATED", "FULFILLED", "CANCELLED",
    )


def assert_allocation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_storage_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["unit_code"], str) and data["unit_code"]
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] > 0
    assert data["temp_max_c"] > data["temp_min_c"]
    assert isinstance(data["current_load"], int) and data["current_load"] >= 0


def assert_storage_placement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["withdrawn_quantity"], int) and data["withdrawn_quantity"] >= 0
    assert data["withdrawn_quantity"] <= data["quantity"]
    assert data["status"] in ("ACTIVE", "WITHDRAWN", "DISCARDED")


def assert_planting_contract(data: dict):
    _assert_common_fields(data)
    assert data["acres"] > 0
    assert 200 <= data["trees_per_acre"] <= 800
    assert 0 <= data["contingency_pct"] <= 0.25
    assert isinstance(data["required_seedlings"], int) and data["required_seedlings"] > 0
    assert data["site_prep_status"] in ("NONE", "RECORDED", "VERIFIED", "STALE")
    assert data["status"] in (
        "DRAFT", "SITE_PREP", "READY_TO_PLANT", "BLOCKED", "PLANTING",
        "PLANTED", "SURVEYED", "REPLANT_REQUIRED", "CLOSED", "CANCELLED",
    )


def assert_crew(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["crew_code"], str) and data["crew_code"]
    assert isinstance(data["capacity_per_day"], int) and data["capacity_per_day"] > 0
    assert isinstance(data["active"], bool)


def assert_crew_assignment(data: dict):
    _assert_common_fields(data)
    assert data["start_date"] < data["end_date"]
    assert isinstance(data["planned_seedlings"], int) and data["planned_seedlings"] > 0
    assert data["status"] in ("SCHEDULED", "CONFIRMED", "COMPLETED", "RELEASED")


def assert_shipment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert is_iso8601_timestamp(data["dispatched_at"])
    assert is_iso8601_timestamp(data["handling_deadline"])
    assert data["status"] in ("DISPATCHED", "DELIVERED", "PLANTED", "SPOILED")


def assert_survival_survey(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["planted_count_snapshot"], int)
    assert isinstance(data["alive_count"], int) and data["alive_count"] >= 0
    assert data["alive_count"] <= data["planted_count_snapshot"]
    assert isinstance(data["survival_pct"], (int, float))
    assert isinstance(data["threshold_pct"], (int, float))
    assert isinstance(data["below_threshold"], bool)
    assert isinstance(data["owed_quantity"], int) and data["owed_quantity"] >= 0
    assert data["obligation_status"] in ("NONE", "OPEN", "SCHEDULED", "FULFILLED", "WAIVED")


def assert_cost_share_enrollment(data: dict):
    _assert_common_fields(data)
    assert data["enrolled_acres"] > 0
    assert isinstance(data["rate_per_acre_cents"], int) and data["rate_per_acre_cents"] > 0
    assert isinstance(data["cap_cents"], int) and data["cap_cents"] > 0
    assert data["status"] in ("DRAFT", "UNDER_REVIEW", "APPROVED", "PAYMENT_HELD", "PAID")
