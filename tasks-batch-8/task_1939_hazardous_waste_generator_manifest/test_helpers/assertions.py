"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CONTAINER_STATUSES = [
    "ACCUMULATING_AT_SATELLITE", "SATELLITE_LIMIT_EXCEEDED", "IN_CENTRAL_ACCUMULATION",
    "STAGED_FOR_SHIPMENT", "SHIPPED", "EMPTIED", "VOIDED",
]
MANIFEST_STATUSES = [
    "DRAFT", "GENERATOR_SIGNED", "IN_TRANSIT", "DELIVERED", "DISCREPANCY_RAISED",
    "RETURNED", "EXCEPTION_REQUIRED", "EXCEPTION_REPORT_FILED",
]


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into an aware datetime for instant comparison."""
    assert isinstance(value, str), f"Expected ISO timestamp string, got {value!r}"
    assert is_iso8601_timestamp(value), f"Not a valid ISO 8601 UTC timestamp: {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, label: str = "timestamp"):
    """Two serialized timestamps denote the same logical instant."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected instant {expected}, got {actual}")


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601")
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601")
    assert isinstance(data.get("version"), int) and not isinstance(data["version"], bool), (
        f"{entity}.version must be an integer")


def assert_generator_site(data: dict):
    _assert_common(data, "GeneratorSite")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["epa_id_number"], str) and data["epa_id_number"]
    assert isinstance(data["current_month_key"], str) and len(data["current_month_key"]) == 7
    assert isinstance(data["current_month_generated_kg"], (int, float))
    assert data["generator_category"] in ("VSQG", "SQG", "LQG")
    assert isinstance(data["open_exception_count"], int)
    assert isinstance(data["open_discrepancy_count"], int)


def assert_waste_stream(data: dict):
    _assert_common(data, "WasteStream")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["waste_codes"], list)
    assert data["physical_state"] in ("LIQUID", "SOLID", "SLUDGE", "GAS")
    assert data["status"] in ("DRAFT", "CHARACTERIZED", "ACTIVE", "RETIRED")
    assert isinstance(data["characterization_version"], int)
    assert isinstance(data["total_generated_kg"], (int, float))


def assert_accumulation_area(data: dict):
    _assert_common(data, "AccumulationArea")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["area_type"] in ("SATELLITE", "CENTRAL_90DAY")


def assert_container(data: dict):
    _assert_common(data, "Container")
    assert isinstance(data["waste_stream_id"], str) and data["waste_stream_id"]
    assert isinstance(data["accumulation_area_id"], str) and data["accumulation_area_id"]
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert data["quantity_gallons"] > 0, "quantity_gallons must be positive"
    assert data["quantity_kg"] > 0, "quantity_kg must be positive"
    assert data["status"] in CONTAINER_STATUSES
    assert isinstance(data["is_accumulation_overdue"], bool)
    assert isinstance(data["is_move_late"], bool)
    assert isinstance(data["is_labeled"], bool)
    assert isinstance(data["is_inspection_overdue"], bool)


def assert_container_inspection(data: dict):
    _assert_common(data, "ContainerInspection")
    assert isinstance(data["container_id"], str) and data["container_id"]
    assert isinstance(data["inspector_user_id"], str) and data["inspector_user_id"]
    assert is_iso8601_timestamp(data.get("inspected_at", ""))
    assert data["result"] in ("PASS", "FAIL")
    if data["result"] == "FAIL":
        assert isinstance(data["deficiency_note"], str) and data["deficiency_note"]


def assert_waste_partner(data: dict):
    _assert_common(data, "WastePartner")
    assert data["partner_type"] in ("TRANSPORTER", "TSDF")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["epa_id_number"], str) and data["epa_id_number"]
    assert isinstance(data["permitted_waste_codes"], list)
    assert data["status"] in ("PENDING", "APPROVED", "SUSPENDED", "REJECTED")
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert isinstance(data["is_audit_current"], bool)


def assert_compliance_audit(data: dict):
    _assert_common(data, "ComplianceAudit")
    assert isinstance(data["waste_partner_id"], str) and data["waste_partner_id"]
    assert isinstance(data["auditor_user_id"], str) and data["auditor_user_id"]
    assert is_iso8601_timestamp(data.get("audited_at", ""))
    assert is_iso8601_timestamp(data.get("coverage_from", ""))
    assert is_iso8601_timestamp(data.get("coverage_to", ""))
    assert data["outcome"] in ("PASS", "FAIL")


def assert_manifest(data: dict):
    _assert_common(data, "Manifest")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["transporter_id"], str) and data["transporter_id"]
    assert isinstance(data["tsdf_id"], str) and data["tsdf_id"]
    assert isinstance(data["manifest_tracking_number"], str)
    assert isinstance(data["line_items"], list) and len(data["line_items"]) >= 1
    assert data["status"] in MANIFEST_STATUSES
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert isinstance(data["is_return_late"], bool)
    assert isinstance(data["total_quantity_kg"], (int, float))
    assert isinstance(data["tonnage_fee_cents"], int), "fees are integer cents"


def assert_ldr_notification(data: dict):
    # Immutable notice: id + created_at only; no updated_at, no version (PRD §2.4).
    assert is_valid_uuid(data.get("id", "")), "LDRNotification.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "updated_at" not in data, "LDRNotification carries no updated_at"
    assert "version" not in data, "LDRNotification carries no version"
    assert isinstance(data["manifest_id"], str) and data["manifest_id"]
    assert isinstance(data["treatment_standard_codes"], list)
    assert isinstance(data["certification_statement"], str) and data["certification_statement"]
    assert is_iso8601_timestamp(data.get("notified_at", ""))


def assert_biennial_report(data: dict):
    _assert_common(data, "BiennialReport")
    assert isinstance(data["site_id"], str) and data["site_id"]
    assert isinstance(data["report_year"], int)
    assert is_iso8601_timestamp(data.get("period_start", ""))
    assert is_iso8601_timestamp(data.get("period_end", ""))
    assert is_iso8601_timestamp(data.get("due_at", ""))
    assert data["status"] in ("DRAFT", "SUBMITTED", "ACCEPTED")
    assert data["category_snapshot"] in ("VSQG", "SQG", "LQG")
    assert isinstance(data["provisional_shipped_kg"], (int, float))
    assert isinstance(data["final_shipped_kg"], (int, float))
    assert isinstance(data["provisional_fee_cents"], int)
    assert isinstance(data["final_fee_cents"], int)
    assert isinstance(data["is_late"], bool)
    assert isinstance(data["days_late"], int)


def assert_site_category_invariants(site: dict):
    """The category is a pure threshold function of the monthly total (PRD §2.6)."""
    total = site["current_month_generated_kg"]
    category = site["generator_category"]
    if total >= 1000.0:
        assert category == "LQG", f"total {total} >= 1000.0 must be LQG, got {category}"
    elif total > 100.0:
        assert category == "SQG", f"100.0 < total {total} < 1000.0 must be SQG, got {category}"
    else:
        assert category == "VSQG", f"total {total} <= 100.0 must be VSQG, got {category}"
