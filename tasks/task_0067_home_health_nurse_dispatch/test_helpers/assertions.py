"""Entity assertions and invariant checkers (Home Health Nurse Dispatch)."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def assert_episode(data):
    assert is_valid_uuid(data.get("id", "")), f"episode id not uuid: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in [
        "DRAFT", "ACTIVE", "RECERT_PENDING", "DISCHARGED", "CANCELLED",
    ], f"bad episode status {data.get('status')!r}"
    return data


def assert_visit(data):
    assert is_valid_uuid(data.get("id", "")), "visit id not uuid"
    assert data["status"] in [
        "SCHEDULED", "CONFIRMED", "COMPLETED", "MISSED", "CANCELLED",
    ], f"bad visit status {data.get('status')!r}"
    return data


def assert_money_2dp(value):
    """A monetary amount carried to 2 decimal places (PRD §2.8)."""
    assert isinstance(value, (int, float)), f"money not numeric: {value!r}"
    assert round(float(value), 2) == float(value), f"money not 2dp: {value!r}"
    return value
