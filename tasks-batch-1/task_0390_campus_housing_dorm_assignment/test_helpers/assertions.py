"""Entity assertions and domain invariant checkers.

Each assert_{entity} validates the response structure against the PRD contract
using the framework's generic format validators internally.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_audit(data: dict):
    """Common audit fields carried by every (mutable) entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_building(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["building_type"] in ("TRADITIONAL", "SUITE", "APARTMENT")
    assert isinstance(data["offers_break_housing"], bool)
    assert isinstance(data["break_housing_capacity"], int) and data["break_housing_capacity"] >= 0
    assert isinstance(data["total_bed_count"], int) and data["total_bed_count"] >= 0
    assert isinstance(data["occupied_bed_count"], int) and data["occupied_bed_count"] >= 0


def assert_room(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("building_id", "")), "building_id must be a valid UUID"
    assert isinstance(data["room_number"], str) and len(data["room_number"]) > 0
    assert data["room_type"] in ("SINGLE", "DOUBLE", "TRIPLE", "SUITE_DOUBLE")
    assert isinstance(data["bed_capacity"], int) and data["bed_capacity"] >= 1
    assert data["gender_inclusivity"] in ("SINGLE_GENDER", "ALL_GENDER")
    assert isinstance(data["occupied_bed_count"], int) and data["occupied_bed_count"] >= 0
    assert isinstance(data["open_incident_count"], int) and data["open_incident_count"] >= 0
    assert data["status"] in ("OPEN", "RESTRICTED", "OFFLINE")


def assert_student(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["class_year"] in ("FRESHMAN", "SOPHOMORE", "JUNIOR", "SENIOR")
    assert data["gender_identity"] in ("MALE", "FEMALE", "NONBINARY")
    assert isinstance(data["lottery_number"], int) and data["lottery_number"] >= 1
    assert isinstance(data["account_balance_cents"], int)
    assert data["account_balance_cents"] >= 0, "account_balance_cents is never below 0 (PRD §3.6)"
    assert data["status"] in ("ACTIVE", "HOLD")


def assert_cycle(data: dict):
    _assert_common_audit(data)
    assert isinstance(data["term_label"], str) and len(data["term_label"]) > 0
    assert data["phase"] in ("APPLICATION_OPEN", "LOTTERY_RUN", "ASSIGNMENT_OPEN", "CLOSED")
    assert isinstance(data["lottery_run_index"], int) and data["lottery_run_index"] >= 0


def assert_application(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a valid UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a valid UUID"
    assert data["preferred_building_type"] in (
        "TRADITIONAL", "SUITE", "APARTMENT", "NO_PREFERENCE")
    assert data["preferred_room_type"] in (
        "SINGLE", "DOUBLE", "TRIPLE", "SUITE_DOUBLE", "NO_PREFERENCE")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "OFFERED", "WAITLISTED",
        "ACCEPTED", "DECLINED", "WITHDRAWN", "EXPIRED")


def assert_roommate_group(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a valid UUID"
    assert is_valid_uuid(data.get("owner_student_id", "")), "owner_student_id must be a valid UUID"
    assert isinstance(data["target_size"], int) and 2 <= data["target_size"] <= 3
    assert isinstance(data["accepted_member_count"], int) and data["accepted_member_count"] >= 0
    assert data["status"] in ("FORMING", "LOCKED", "DISBANDED")


def assert_membership(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("group_id", "")), "group_id must be a valid UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a valid UUID"
    assert data["membership_status"] in ("INVITED", "ACCEPTED", "DECLINED", "REMOVED")


def assert_assignment(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be a valid UUID"
    assert is_valid_uuid(data.get("student_id", "")), "student_id must be a valid UUID"
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a valid UUID"
    assert data["status"] in ("ACTIVE", "SWAP_PENDING", "VACATED", "CHECKED_OUT")


def assert_meal_plan(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert data["tier"] in ("NONE", "COMMUTER", "STANDARD", "UNLIMITED")
    assert isinstance(data["weekly_fee_cents"], int) and data["weekly_fee_cents"] >= 0
    assert data["status"] in ("ACTIVE", "CANCELLED")


def assert_waitlist_entry(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a valid UUID"
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be a valid UUID"
    assert isinstance(data["priority_rank_snapshot"], int)
    assert isinstance(data["lottery_number_snapshot"], int)
    assert data["status"] in ("QUEUED", "PROMOTED", "CANCELLED")


def assert_damage_charge(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be a valid UUID"
    assert data["category"] in ("CLEANING", "REPAIR", "REPLACEMENT", "LOST_KEY")
    assert isinstance(data["assessed_cents"], int)
    assert data["split_basis"] in ("SOLE", "SHARED")
    assert data["status"] in ("PENDING", "BILLED", "WAIVED", "PAID")


def assert_incident_report(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be a valid UUID"
    assert is_valid_uuid(data.get("reporter_student_id", "")), "reporter_student_id must be a valid UUID"
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["status"] in ("OPEN", "ESCALATED", "RESOLVED")


def assert_break_request(data: dict):
    _assert_common_audit(data)
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a valid UUID"
    assert is_valid_uuid(data.get("room_id", "")), "room_id must be a valid UUID"
    assert isinstance(data["night_count"], int)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "CANCELLED")
