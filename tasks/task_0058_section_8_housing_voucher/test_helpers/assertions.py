"""Entity assertions using the framework's generic validators (PRD Section 2.4)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict):
    """The standard server-managed fields for non-immutable resources
    (PRD §2.4): id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data!r}"
    )
    assert "updated_at" in data, f"updated_at missing: {data!r}"
    assert isinstance(data.get("version"), int), f"version must be int: {data!r}"


def assert_immutable_fields(data: dict):
    """RentReasonablenessDetermination carries only id and created_at
    (PRD §2.4): no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data!r}"
    )
