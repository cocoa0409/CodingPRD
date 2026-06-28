"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


SESSION_STATUSES = ["DRAFT", "OPEN", "RESTRICTED", "FULL", "CANCELLED", "COMPLETED"]
MEMBERSHIP_STATUSES = ["PENDING", "ACTIVE", "PAUSED", "CANCELLED"]
ATTENDANCE_STATUSES = ["RESERVED", "CHECKED_IN", "ATTENDED", "NO_SHOW", "CANCELLED"]
BILLING_STATUSES = ["UNBILLED", "CHARGED", "COVERED", "REFUNDED", "FORFEITED"]
SHOWCASE_STATUSES = ["DRAFT", "OPEN", "JUDGING", "COMPLETED", "CANCELLED"]
ENTRY_STATUSES = ["SUBMITTED", "ACCEPTED", "REJECTED", "WITHDRAWN", "SCORED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_center(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["device_count"], int) and data["device_count"] >= 1
    assert isinstance(data["min_student_instructor_ratio"], int)
    assert data["min_student_instructor_ratio"] >= 1


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["code"], str)
    assert isinstance(data["min_age"], int) and data["min_age"] >= 4
    assert isinstance(data["max_age"], int) and data["max_age"] >= data["min_age"]
    assert isinstance(data["drop_in_fee_cents"], int) and data["drop_in_fee_cents"] >= 0


def assert_belt_level(data: dict):
    _assert_common(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["rank"], int) and data["rank"] >= 1
    assert isinstance(data["required_badge_count"], int) and data["required_badge_count"] >= 0


def assert_badge(data: dict):
    _assert_common(data)
    assert isinstance(data["belt_level_id"], str)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_guardian(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet_credit_cents must never be negative"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["guardian_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["current_belt_level_id"], str)
    assert isinstance(data["active_badge_count"], int) and data["active_badge_count"] >= 0


def assert_membership(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["included_sessions_per_cycle"], int)
    assert isinstance(data["sessions_used_this_cycle"], int)
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 0
    assert data["status"] in MEMBERSHIP_STATUSES


def assert_session(data: dict):
    _assert_common(data)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["program_id"], str)
    assert data["format"] in ["AFTER_SCHOOL", "WEEKLY", "CAMP"]
    assert isinstance(data["week_count"], int) and data["week_count"] >= 1
    assert isinstance(data["device_seats_requested"], int)
    assert isinstance(data["assigned_instructor_count"], int)
    assert data["status"] in SESSION_STATUSES
    assert isinstance(data["confirmed_seat_count"], int) and data["confirmed_seat_count"] >= 0


def assert_enrollment(data: dict):
    _assert_common(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["member_id"], str)
    assert data["coverage"] in ["DROP_IN", "MEMBERSHIP"]
    assert isinstance(data["sibling_index"], int) and data["sibling_index"] >= 1
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["wallet_applied_cents"], int) and data["wallet_applied_cents"] >= 0
    assert data["attendance_status"] in ATTENDANCE_STATUSES
    assert data["billing_status"] in BILLING_STATUSES


def assert_badge_award(data: dict):
    _assert_common(data)
    assert isinstance(data["enrollment_id"], str)
    assert isinstance(data["badge_id"], str)
    assert data["status"] in ["ACTIVE", "REVOKED"]


def assert_showcase(data: dict):
    _assert_common(data)
    assert isinstance(data["center_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["min_belt_rank"], int) and data["min_belt_rank"] >= 1
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert data["status"] in SHOWCASE_STATUSES
    assert isinstance(data["accepted_entry_count"], int) and data["accepted_entry_count"] >= 0


def assert_showcase_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["showcase_id"], str)
    assert isinstance(data["member_id"], str)
    assert data["status"] in ENTRY_STATUSES
