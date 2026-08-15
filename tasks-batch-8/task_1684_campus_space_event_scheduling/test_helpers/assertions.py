"""Entity assertions and domain invariant checkers.

Each assert_* function validates the PRD-declared shape of one entity:
common resource properties (PRD section 2.5) plus entity-specific fields.
"""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def assert_same_instant(actual: str, expected_iso: str):
    """Assert two ISO 8601 timestamps denote the same instant, regardless of
    fractional-second formatting (the PRD pins the instant, not the rendering)."""
    assert is_iso8601_timestamp(actual), f"not an ISO 8601 timestamp: {actual!r}"
    parsed = _parse_instant(actual)
    assert parsed == _parse_instant(expected_iso), (
        f"instant mismatch: {actual!r} != {expected_iso!r}"
    )

ORG_TYPES = ["INTERNAL_DEPARTMENT", "STUDENT_GROUP", "EXTERNAL"]
ORG_STANDINGS = ["GOOD", "PROBATION", "SUSPENDED"]
ROOM_FEATURES = [
    "PROJECTOR",
    "VIDEO_CONF",
    "SOUND_SYSTEM",
    "STAGE",
    "PIANO",
    "LAB_BENCHES",
    "KITCHEN_ACCESS",
    "ADA_LIFT",
]
ROOM_STATUSES = ["ACTIVE", "OUT_OF_SERVICE"]
TERM_STATUSES = ["DRAFT", "SCHEDULING", "GENERAL", "CLOSED"]
BLOCK_STATUSES = ["UNPLACED", "PLACED"]
RUN_STATUSES = ["DRAFT", "FINALIZED", "SUPERSEDED"]
EVENT_STATUSES = [
    "REQUESTED",
    "APPROVED",
    "CONFIRMED",
    "IN_PROGRESS",
    "COMPLETED",
    "NO_SHOW",
    "CANCELLED",
    "DECLINED",
    "EXPIRED",
    "BUMPED",
]
SERVICE_CATEGORIES = ["AV", "CATERING", "CUSTODIAL", "SECURITY"]
ORDER_STATUSES = [
    "REQUESTED",
    "QUOTED",
    "NEEDS_REVISION",
    "APPROVED",
    "SCHEDULED",
    "FULFILLED",
    "INVOICED",
    "CANCELLED",
]
INVOICE_STATUSES = [
    "PROVISIONAL",
    "FINALIZED",
    "PARTIALLY_PAID",
    "PAID",
    "VOIDED",
    "REFUNDED",
]
GRANT_TYPES = ["PHYSICAL_KEY", "CARD_ACCESS"]
GRANT_STATUSES = ["REQUESTED", "ISSUED", "OVERDUE", "RETURNED", "LOST", "REVOKED"]
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def _assert_common(data: dict):
    """Common resource properties from PRD section 2.5."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_organization(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["org_type"] in ORG_TYPES
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["no_show_count"], int) and data["no_show_count"] >= 0
    assert data["standing"] in ORG_STANDINGS
    assert isinstance(data["deposit_held_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["building_code"], str) and data["building_code"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 0
    assert isinstance(data["features"], list)
    for feature in data["features"]:
        assert feature in ROOM_FEATURES, f"unknown feature {feature!r}"
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert isinstance(data["internal_hourly_rate_cents"], int)
    assert isinstance(data["student_hourly_rate_cents"], int)
    assert isinstance(data["external_hourly_rate_cents"], int)
    assert isinstance(data["peak_multiplier_bps"], int)
    assert data["status"] in ROOM_STATUSES
    assert isinstance(data["key_count"], int) and data["key_count"] >= 0
    assert isinstance(data["keys_issued"], int) and data["keys_issued"] >= 0
    assert isinstance(data["keys_lost_total"], int) and data["keys_lost_total"] >= 0
    assert isinstance(data["outage_windows"], list)


def assert_term(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert is_iso8601_timestamp(data["term_start_date"])
    assert is_iso8601_timestamp(data["term_end_date"])
    assert is_iso8601_timestamp(data["priority_open_at"])
    assert is_iso8601_timestamp(data["general_open_at"])
    assert data["status"] in TERM_STATUSES
    assert "current_draft_run_id" in data


def assert_academic_block(data: dict):
    _assert_common(data)
    assert isinstance(data["term_id"], str)
    assert isinstance(data["course_code"], str) and data["course_code"]
    assert isinstance(data["instructor_name"], str) and data["instructor_name"]
    assert isinstance(data["enrollment"], int) and data["enrollment"] >= 0
    assert isinstance(data["required_features"], list)
    assert isinstance(data["days_of_week"], list) and len(data["days_of_week"]) > 0
    for day in data["days_of_week"]:
        assert day in WEEKDAYS, f"unknown weekday {day!r}"
    assert isinstance(data["start_time"], str)
    assert isinstance(data["end_time"], str)
    assert isinstance(data["priority_score"], int)
    assert data["status"] in BLOCK_STATUSES
    assert "assigned_room_id" in data
    assert "scheduling_run_id" in data


def assert_scheduling_run(data: dict):
    _assert_common(data)
    assert isinstance(data["term_id"], str)
    assert data["status"] in RUN_STATUSES
    assert isinstance(data["placed_count"], int)
    assert isinstance(data["bumped_event_ids"], list)
    assert isinstance(data["unplaced_block_ids"], list)
    assert "finalized_at" in data


def assert_event(data: dict):
    _assert_common(data)
    assert isinstance(data["requester_org_id"], str)
    assert "room_id" in data
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["expected_attendance"], int) and data["expected_attendance"] >= 1
    assert isinstance(data["required_features"], list)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["setup_minutes"], int)
    assert isinstance(data["teardown_minutes"], int)
    assert isinstance(data["precedence_tier"], int)
    assert data["status"] in EVENT_STATUSES
    assert is_iso8601_timestamp(data["decision_deadline"])


def assert_service_order(data: dict):
    _assert_common(data)
    assert isinstance(data["event_id"], str)
    assert data["category"] in SERVICE_CATEGORIES
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert is_iso8601_timestamp(data["service_start_at"])
    assert is_iso8601_timestamp(data["service_end_at"])
    assert data["status"] in ORDER_STATUSES
    assert isinstance(data["fee_waived"], bool)


def assert_service_crew(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in SERVICE_CATEGORIES
    assert isinstance(data["concurrent_capacity"], int) and data["concurrent_capacity"] >= 1
    assert isinstance(data["shift_start"], str)
    assert isinstance(data["shift_end"], str)


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["org_id"], str)
    assert data["status"] in INVOICE_STATUSES
    for field in (
        "room_charge_cents",
        "service_charge_cents",
        "insurance_surcharge_cents",
        "cancellation_fee_cents",
        "no_show_fee_cents",
        "deposit_charge_cents",
        "total_cents",
        "paid_cents",
        "waived_cents",
        "refunded_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be int cents"


def assert_invoice_total_invariant(data: dict):
    """PRD section 3.6: total_cents is always the sum of the six charge lines."""
    expected = (
        data["room_charge_cents"]
        + data["service_charge_cents"]
        + data["insurance_surcharge_cents"]
        + data["cancellation_fee_cents"]
        + data["no_show_fee_cents"]
        + data["deposit_charge_cents"]
    )
    assert data["total_cents"] == expected, (
        f"total_cents {data['total_cents']} != component sum {expected}"
    )


def assert_access_grant(data: dict):
    _assert_common(data)
    assert isinstance(data["event_id"], str)
    assert isinstance(data["room_id"], str)
    assert data["grant_type"] in GRANT_TYPES
    assert data["status"] in GRANT_STATUSES
    assert is_iso8601_timestamp(data["return_deadline"])


def assert_room_key_invariant(data: dict, original_key_count: int):
    """PRD section 3.2/3.7: key_count + keys_lost_total is invariant."""
    assert data["key_count"] + data["keys_lost_total"] == original_key_count, (
        f"key inventory drifted: {data['key_count']} + {data['keys_lost_total']} "
        f"!= {original_key_count}"
    )
