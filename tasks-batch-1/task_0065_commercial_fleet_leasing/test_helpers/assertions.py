"""Entity assertions and domain invariant checkers (commercial fleet leasing)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """Common fields on entities with common_fields: true (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be int: {data.get('version')}"
    )


def assert_vehicle(data: dict):
    assert_common_fields(data)
    assert data["status"] in (
        "AVAILABLE", "ALLOCATED", "IN_MAINTENANCE", "IN_REPAIR", "RETIRED"
    ), f"unexpected vehicle status: {data['status']}"
    assert isinstance(data["odometer_miles"], int)
    assert isinstance(data["open_block_count"], int)
