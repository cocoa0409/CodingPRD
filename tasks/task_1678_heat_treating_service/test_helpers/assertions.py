"""Entity assertions and domain invariant checkers (PRD §2.4, §3).

Append-only evidence records (PyrometryRecord, LoadThermocoupleReading,
InspectionTest) carry only id and created_at — both updated_at and version
must be absent (PRD §2.4).
"""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

QUALIFICATION_STATUSES = [
    "UNQUALIFIED",
    "SURVEY_OVERDUE",
    "CALIBRATION_OVERDUE",
    "QUALIFIED",
]
PROCESSING_STATUSES = [
    "RECEIVED",
    "SCHEDULED",
    "IN_PROCESS",
    "PROCESSED",
    "AWAITING_RETREAT",
    "SHIPPED",
    "SCRAPPED",
    "CANCELLED",
]
QUALITY_STATUSES = ["PENDING_TEST", "PASSED", "FAILED", "WAIVED"]
LOAD_STATUSES = ["BUILDING", "HOLD", "RELEASED", "RUNNING", "COMPLETED", "ABORTED"]


def _assert_common_fields(data: dict, entity: str):
    """PRD §2.4: primary resources carry id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def _assert_append_only_fields(data: dict, entity: str):
    """PRD §2.4: evidence records expose id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert "updated_at" not in data, f"{entity} must not expose updated_at"
    assert "version" not in data, f"{entity} must not expose version"


def assert_instant_equals(actual: str, expected_iso: str, label: str = "instant"):
    """Compare two ISO 8601 instants by value, tolerating format variants
    (with/without fractional digits, 'Z' vs '+00:00')."""
    def _parse(v):
        return datetime.fromisoformat(v.replace("Z", "+00:00")).astimezone(timezone.utc)

    assert is_iso8601_timestamp(actual), f"{label} must be ISO 8601, got {actual!r}"
    assert _parse(actual) == _parse(expected_iso), (
        f"{label} expected {expected_iso}, got {actual}"
    )


def assert_customer_account(data: dict):
    _assert_common_fields(data, "CustomerAccount")
    assert isinstance(data["name"], str) and data["name"]
    assert data["liability_tier"] in ["STANDARD", "EXTENDED"]
    assert isinstance(data["credit_hold"], bool)
    assert isinstance(data["outstanding_liability_exposure_cents"], int)
    assert data["outstanding_liability_exposure_cents"] >= 0


def assert_furnace_recipe(data: dict):
    _assert_common_fields(data, "FurnaceRecipe")
    assert isinstance(data["alloy_code"], str) and data["alloy_code"]
    assert isinstance(data["spec_code"], str) and data["spec_code"]
    assert isinstance(data["soak_temp_f"], int)
    assert isinstance(data["soak_tolerance_f"], int)
    assert isinstance(data["min_soak_minutes"], int)
    assert data["quench_media"] in ["OIL", "WATER", "POLYMER", "AIR", "GAS"]
    assert data["required_furnace_class"] in ["CLASS_1", "CLASS_2", "CLASS_3", "CLASS_5"]
    assert isinstance(data["max_retreats"], int)
    assert isinstance(data["fixture_distortion_allowance_in"], (int, float))
    assert isinstance(data["hardness_min_hrc"], int)
    assert isinstance(data["hardness_max_hrc"], int)
    assert data["status"] in ["DRAFT", "APPROVED"]


def assert_furnace(data: dict):
    _assert_common_fields(data, "Furnace")
    assert isinstance(data["furnace_code"], str) and data["furnace_code"]
    assert data["furnace_class"] in ["CLASS_1", "CLASS_2", "CLASS_3", "CLASS_5"]
    assert isinstance(data["max_load_weight_lb"], int)
    assert isinstance(data["quench_media_supported"], list)
    assert data["qualification_status"] in QUALIFICATION_STATUSES
    assert data.get("current_tus_due_at") is None or is_iso8601_timestamp(
        data["current_tus_due_at"]
    )
    assert data.get("current_calibration_due_at") is None or is_iso8601_timestamp(
        data["current_calibration_due_at"]
    )


def assert_pyrometry_record(data: dict):
    _assert_append_only_fields(data, "PyrometryRecord")
    assert is_valid_uuid(data.get("furnace_id", ""))
    assert data["record_type"] in ["TUS", "INSTRUMENT_CALIBRATION"]
    assert is_iso8601_timestamp(data.get("performed_at", ""))
    assert data["result"] in ["PASS", "FAIL"]
    assert is_iso8601_timestamp(data.get("next_due_at", ""))


def assert_work_order(data: dict):
    _assert_common_fields(data, "WorkOrder")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("recipe_id", ""))
    assert isinstance(data["part_quantity"], int)
    assert isinstance(data["received_weight_lb"], (int, float))
    assert isinstance(data["declared_value_cents"], int)
    assert isinstance(data["processing_charge_cents"], int)
    assert data["service_lane"] in ["STANDARD", "RUSH"]
    assert is_iso8601_timestamp(data.get("received_at", ""))
    assert data.get("promised_due_at") is None or is_iso8601_timestamp(
        data["promised_due_at"]
    )
    assert data.get("shipped_at") is None or is_iso8601_timestamp(data["shipped_at"])
    assert isinstance(data["turnaround_breached"], bool)
    assert isinstance(data["rush_surcharge_quoted_cents"], int)
    assert data.get("rush_surcharge_final_cents") is None or isinstance(
        data["rush_surcharge_final_cents"], int
    )
    assert data.get("energy_surcharge_cents") is None or isinstance(
        data["energy_surcharge_cents"], int
    )
    assert isinstance(data["retreat_count"], int)
    assert data["processing_status"] in PROCESSING_STATUSES
    assert data["quality_status"] in QUALITY_STATUSES


def assert_load_batch(data: dict):
    _assert_common_fields(data, "LoadBatch")
    assert is_valid_uuid(data.get("furnace_id", ""))
    assert is_valid_uuid(data.get("recipe_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_start_at", ""))
    assert is_iso8601_timestamp(data.get("scheduled_end_at", ""))
    assert data["status"] in LOAD_STATUSES
    assert isinstance(data["total_weight_lb"], (int, float))
    assert isinstance(data["out_of_spec"], bool)
    assert data.get("total_energy_surcharge_cents") is None or isinstance(
        data["total_energy_surcharge_cents"], int
    )
    assert data.get("started_at") is None or is_iso8601_timestamp(data["started_at"])
    assert data.get("completed_at") is None or is_iso8601_timestamp(data["completed_at"])


def assert_load_assignment(data: dict):
    _assert_common_fields(data, "LoadAssignment")
    assert is_valid_uuid(data.get("load_batch_id", ""))
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert data["status"] in ["ACTIVE", "REMOVED"]
    assert is_iso8601_timestamp(data.get("assigned_at", ""))


def assert_thermocouple_reading(data: dict):
    _assert_append_only_fields(data, "LoadThermocoupleReading")
    assert is_valid_uuid(data.get("load_batch_id", ""))
    assert isinstance(data["channel"], str) and data["channel"]
    assert is_iso8601_timestamp(data.get("recorded_at", ""))
    assert isinstance(data["temp_f"], int)


def assert_inspection_test(data: dict):
    _assert_append_only_fields(data, "InspectionTest")
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert isinstance(data["recorded_by_user_id"], str) and data["recorded_by_user_id"]
    assert isinstance(data["hardness_readings"], list) and len(data["hardness_readings"]) >= 1
    assert isinstance(data["measured_distortion_in"], (int, float))
    assert isinstance(data["avg_hardness_hrc"], (int, float))
    assert data["result"] in ["PASS", "FAIL"]


def assert_disposition_case(data: dict):
    _assert_common_fields(data, "DispositionCase")
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert is_valid_uuid(data.get("inspection_test_id", ""))
    assert data["status"] in ["OPEN", "DECIDED"]


def assert_liability_claim(data: dict):
    _assert_common_fields(data, "LiabilityClaim")
    assert is_valid_uuid(data.get("work_order_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["payout_cents"], int) and data["payout_cents"] >= 0
    assert data["status"] in ["PENDING", "ACCEPTED", "PAID", "REJECTED"]


def assert_audit_package(data: dict):
    _assert_common_fields(data, "AuditPackage")
    assert is_valid_uuid(data.get("furnace_id", ""))
    assert isinstance(data["load_batch_ids"], list)
    assert isinstance(data["evidence_manifest"], dict)
    assert data["status"] in ["DRAFT", "ISSUED"]
    assert data.get("issued_at") is None or is_iso8601_timestamp(data["issued_at"])
