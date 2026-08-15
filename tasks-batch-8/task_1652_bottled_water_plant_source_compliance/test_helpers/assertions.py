"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """Every resource carries id/created_at/updated_at/version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an integer >= 1, got {data.get('version')!r}"
    )


def assert_plant(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["compliance_posture"] in ("GREEN", "WATCH", "BREACH")
    assert isinstance(data["ops_run_index"], int) and data["ops_run_index"] >= 0
    assert isinstance(data["bottle_gross_pool_units"], int) and data["bottle_gross_pool_units"] >= 0
    assert isinstance(data["bottle_sanitized_pool_units"], int) and data["bottle_sanitized_pool_units"] >= 0


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["permit_number"], str) and len(data["permit_number"]) > 0
    assert data["source_classification"] in ("SPRING", "WELL", "MUNICIPAL")
    assert isinstance(data["daily_cap_gallons"], int) and data["daily_cap_gallons"] > 0
    assert isinstance(data["monthly_cap_gallons"], int)
    assert data["monthly_cap_gallons"] >= data["daily_cap_gallons"]
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED", "CLOSED")
    assert data.get("suspension_reason") in (None, "MANUAL", "SOURCE_TEST_FAIL", "TEST_OVERDUE")
    for field in (
        "withdrawn_today_provisional_gallons",
        "withdrawn_today_certified_gallons",
        "withdrawn_month_provisional_gallons",
        "withdrawn_month_certified_gallons",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, field


def assert_withdrawal_event(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["withdrawal_date"], str) and len(data["withdrawal_date"]) > 0
    assert isinstance(data["gallons"], int) and data["gallons"] > 0
    assert isinstance(data["meter_reading_start_gallons"], int) and data["meter_reading_start_gallons"] >= 0
    assert isinstance(data["meter_reading_end_gallons"], int)
    assert data["meter_reading_end_gallons"] - data["meter_reading_start_gallons"] == data["gallons"]
    assert data["status"] in ("RECORDED", "FINALIZED", "VOIDED")


def assert_treatment_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "VALIDATED", "FAILED", "REPROCESSING", "CANCELLED")
    assert isinstance(data["validation_round"], int) and data["validation_round"] >= 0


def assert_lab_test(data: dict):
    _assert_common_fields(data)
    assert data["test_type"] in ("SOURCE_RAW", "FINISHED_PRODUCT", "BOTTLE_SANITATION")
    assert data["result"] in ("PENDING", "PASS", "FAIL")
    assert data["status"] in ("SCHEDULED", "DUE", "OVERDUE", "COMPLETED_PASS", "COMPLETED_FAIL")
    assert data["origin"] in ("MANUAL", "AUTO")


def assert_bottling_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_code"], str) and len(data["line_code"]) > 0
    assert isinstance(data["daily_capacity_units"], int) and data["daily_capacity_units"] > 0
    assert isinstance(data["preform_on_hand_units"], int) and data["preform_on_hand_units"] >= 0
    assert isinstance(data["preform_reserved_units"], int) and data["preform_reserved_units"] >= 0
    # Derived ledger identity: free = on_hand - reserved (PRD §3.5)
    assert data["preform_free_units"] == data["preform_on_hand_units"] - data["preform_reserved_units"], (
        f"preform_free_units {data['preform_free_units']} != "
        f"{data['preform_on_hand_units']} - {data['preform_reserved_units']}"
    )


def assert_preform_delivery(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["supplier"], str) and len(data["supplier"]) > 0
    assert isinstance(data["delivered_units"], int) and data["delivered_units"] > 0
    assert data["status"] in ("PENDING_QC", "ACCEPTED", "REJECTED")
    if data["status"] == "PENDING_QC":
        assert data.get("accepted_units") is None
    elif data["status"] == "REJECTED":
        assert data.get("accepted_units") == 0
    else:
        assert isinstance(data.get("accepted_units"), int) and 0 < data["accepted_units"] <= data["delivered_units"]


def assert_production_lot(data: dict):
    _assert_common_fields(data)
    assert data["label_classification"] in ("SPRING", "PURIFIED")
    assert isinstance(data["planned_units"], int) and data["planned_units"] > 0
    assert data["status"] in ("PLANNED", "IN_PRODUCTION", "QA_HOLD", "RELEASED", "REWORK", "RECALLED", "CANCELLED")
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0


def assert_recall(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ("INITIATED", "RECOVERING", "CLOSED")
    assert isinstance(data["units_in_scope"], int) and data["units_in_scope"] >= 0
    assert isinstance(data["units_recovered"], int) and data["units_recovered"] >= 0
    assert data["units_recovered"] <= data["units_in_scope"]


def assert_bottle(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bottle_code"], str) and len(data["bottle_code"]) > 0
    assert isinstance(data["wash_cycle_count"], int) and data["wash_cycle_count"] >= 0
    assert data["status"] in (
        "SANITIZED", "FILLED", "WITH_CUSTOMER", "RETURNED_DIRTY", "IN_WASH", "QUARANTINED", "RETIRED",
    )


def assert_wash_batch(data: dict):
    _assert_common_fields(data)
    assert data["washer_unit"] in ("WASHER_A", "WASHER_B")
    assert data["status"] in ("SCHEDULED", "RUNNING", "PASSED", "FAILED", "CANCELLED")
    assert isinstance(data["bottle_count"], int) and data["bottle_count"] >= 0


def assert_community_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["period_year"], int)
    assert isinstance(data["period_month"], int) and 1 <= data["period_month"] <= 12
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data["total_withdrawn_gallons"], int) and data["total_withdrawn_gallons"] >= 0
    assert isinstance(data["total_acre_feet"], (int, float))
    assert isinstance(data["per_source_breakdown"], list)


def assert_bottle_pool_consistency(plant_data: dict):
    """The sanitized pool can never exceed the gross pool (PRD §2.11)."""
    assert plant_data["bottle_sanitized_pool_units"] <= plant_data["bottle_gross_pool_units"], (
        f"sanitized pool {plant_data['bottle_sanitized_pool_units']} exceeds "
        f"gross pool {plant_data['bottle_gross_pool_units']}"
    )


def assert_permit_view_consistency(permit_data: dict):
    """Certified (FINALIZED-only) totals never exceed provisional totals (PRD §2.11)."""
    assert permit_data["withdrawn_today_certified_gallons"] <= permit_data["withdrawn_today_provisional_gallons"]
    assert permit_data["withdrawn_month_certified_gallons"] <= permit_data["withdrawn_month_provisional_gallons"]
