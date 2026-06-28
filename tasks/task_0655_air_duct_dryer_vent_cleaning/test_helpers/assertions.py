"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_pricing_config(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    for f in ("duct_base_cents", "duct_per_system_cents", "dryer_vent_flat_cents",
              "sanitize_per_system_cents", "addon_sanitizer_cents", "addon_uv_cents",
              "addon_coil_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_home(data: dict):
    _assert_common(data)
    assert isinstance(data["active_system_count"], int) and data["active_system_count"] >= 0
    assert isinstance(data["has_active_plan"], bool)
    assert isinstance(data["zone_code"], str) and len(data["zone_code"]) > 0


def assert_hvac_system(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "DECOMMISSIONED")
    assert isinstance(data["register_count"], int) and data["register_count"] > 0


def assert_work_order(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "INSPECTED", "QUOTED", "SCHEDULED",
        "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["service_lines"], list) and len(data["service_lines"]) >= 1


def assert_route_plan(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "LOCKED", "CLOSED")
    assert isinstance(data["committed_minutes"], int) and data["committed_minutes"] >= 0


def assert_recurring_plan(data: dict):
    _assert_common(data)
    assert data["reminder_status"] in ("WAITING", "DUE", "ACKNOWLEDGED")
    assert data["lifecycle_status"] in ("ACTIVE", "PAUSED", "CANCELLED")
    assert data["cadence_months"] in (6, 12, 24)


def assert_upsell_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "DECLINED", "EXPIRED")


def assert_callback_ticket(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "RESOLVED", "REOPENED")
