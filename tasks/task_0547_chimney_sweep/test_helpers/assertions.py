"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_log_common(data: dict):
    """Append-only logs carry only id + created_at (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["service_address"], str) and len(data["service_address"]) > 0
    assert isinstance(data["phone"], str)


def assert_chimney(data: dict):
    _assert_common(data)
    assert data["chimney_type"] in ("MASONRY", "PREFAB_METAL", "FACTORY_BUILT")
    assert data["appliance_type"] in ("WOOD_STOVE", "OPEN_FIREPLACE", "GAS_INSERT", "PELLET")
    assert isinstance(data["flue_count"], int) and data["flue_count"] >= 1
    assert data["liner_type"] in ("NONE", "CLAY", "STAINLESS", "ALUMINUM")
    assert data["damper_type"] in ("THROAT", "TOP_MOUNT", "NONE")
    assert isinstance(data["cap_installed"], bool)


def assert_technician(data: dict):
    _assert_common(data)
    assert data["cert_level"] in ("CSIA_BASIC", "CSIA_ADVANCED", "MASTER")


def assert_route_day(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity_minutes"], int) and data["capacity_minutes"] >= 0
    assert isinstance(data["booked_minutes"], int) and data["booked_minutes"] >= 0


def assert_service_job(data: dict):
    _assert_common(data)
    assert data["job_status"] in ("DRAFT", "SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert data["safety_posture"] in ("PENDING", "SAFE", "CONDITIONS", "UNSAFE", "CONDEMNED")
    assert data["flue_assessment"] in ("UNASSESSED", "PASS", "DEFECTS", "BLOCKED")
    assert isinstance(data["sweep_provisional_cost_cents"], int)
    assert isinstance(data["committed_cost_cents"], int)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "EN_ROUTE", "ON_SITE", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert isinstance(data["on_site_minutes"], int)


def assert_sweep_log(data: dict):
    _assert_log_common(data)
    assert data["measured_creosote_class"] in (1, 2, 3)
    assert isinstance(data["billed_cost_cents"], int)


def assert_safety_check(data: dict):
    _assert_log_common(data)
    assert isinstance(data["co_ppm"], int) and data["co_ppm"] >= 0
    assert data["outcome"] in ("PASS", "CONDITIONS", "FAIL", "CONDEMN")


def assert_repair_order(data: dict):
    _assert_common(data)
    assert data["repair_type"] in ("CAP", "LINER", "DAMPER", "GAS_LOG_CONVERSION")
    assert data["status"] in (
        "PROPOSED", "APPROVED", "IN_PROGRESS", "BLOCKED", "COMPLETED", "REJECTED", "CANCELLED"
    )
    assert isinstance(data["provisional_cost_cents"], int)


def assert_warranty(data: dict):
    _assert_common(data)
    assert data["coverage_type"] in ("LABOR_ONLY", "PARTS_INCLUSIVE")
    assert data["status"] in ("ISSUED", "CLAIMED", "VOIDED")
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1


def assert_reminder_schedule(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DEACTIVATED")
    assert isinstance(data["cadence_months"], int) and data["cadence_months"] >= 1
    assert isinstance(data["acknowledged_count"], int)
    assert isinstance(data["is_due"], bool)
