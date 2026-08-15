"""Entity assertions and domain invariant checkers (PRD §2.6)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_customer_site(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str) and len(data["state_code"]) == 2
    assert data["site_posture"] in ("NORMAL", "ATTENTION", "CRITICAL")
    assert isinstance(data["contract_discount_pct"], (int, float))
    assert isinstance(data["capital_threshold_cents"], int)
    assert isinstance(data["credit_hold"], bool)


def assert_technician(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["weekly_capacity_hours"] > 0
    assert isinstance(data["active"], bool)
    assert isinstance(data["remaining_capacity_hours"], (int, float))


def assert_vessel(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert is_valid_uuid(data.get("site_id", "")), "site_id must be valid UUID"
    assert data["vessel_kind"] in ("SILO", "BIN", "HOPPER")
    assert data["capacity_tons"] > 0
    assert data["flow_posture"] in ("NORMAL", "PENDING_REPLENISHMENT", "FLOW_IMPAIRED")
    assert data["scale_status"] in ("IN_TOLERANCE", "OUT_OF_TOLERANCE")
    assert isinstance(data["current_inventory_tons"], (int, float))


def assert_level_reading(data: dict):
    """Immutable measurement record: id + created_at only (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "LevelReading must not carry updated_at"
    assert "version" not in data, "LevelReading must not carry version"
    assert is_valid_uuid(data.get("vessel_id", "")), "vessel_id must be valid UUID"
    assert 0 <= data["level_pct"] <= 100


def assert_quality_report(data: dict):
    """Immutable measurement record: id + created_at only (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "MaterialQualityReport must not carry updated_at"
    assert "version" not in data, "MaterialQualityReport must not carry version"
    assert data["flowability_grade"] in ("GOOD", "MARGINAL", "POOR")


def assert_scale_calibration(data: dict):
    """Immutable measurement record: id + created_at only (PRD §2.6)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ScaleCalibration must not carry updated_at"
    assert "version" not in data, "ScaleCalibration must not carry version"
    assert data["result"] in ("PASS", "FAIL")
    assert data["error_basis_used"] in ("OF_READING", "OF_FULL_SCALE")


def assert_replenishment_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("TRIGGERED", "DISPATCHED", "RECEIVED", "CANCELLED", "VOIDED")
    assert data["policy_used"] in ("TARGET_FILL", "DAYS_OF_COVER")
    assert data["order_quantity_tons"] >= 0


def assert_service_ticket(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in (
        "DRAFT", "QUOTED", "APPROVED", "SCHEDULED",
        "IN_PROGRESS", "ON_HOLD", "COMPLETED", "DECLINED",
    )
    assert data["job_type"] in (
        "DIAGNOSIS", "CLEANOUT", "INSPECTION",
        "RETROFIT_AERATION", "RETROFIT_VIBRATOR",
    )
    assert isinstance(data["requires_entry"], bool)
    assert data["est_hours"] > 0
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1


def assert_entry_permit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in (
        "DRAFT", "ISSUED", "ACTIVE", "SUSPENDED", "CLOSED", "VOIDED",
    )
    assert data["void_reason"] in ("NONE", "AUTO_QUALITY_HAZARD")
