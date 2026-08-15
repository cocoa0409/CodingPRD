"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """PRD §2.5: id, created_at, updated_at, version on standard resources."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_event_fields(data: dict):
    """PRD §2.5: append-only event records carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert "updated_at" not in data, "append-only event records must not carry updated_at"
    assert "version" not in data, "append-only event records must not carry version"


def assert_term(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["starts_on"], str)
    assert isinstance(data["ends_on"], str)
    assert data["status"] in ("UPCOMING", "ACTIVE", "CLOSED")


def assert_dorm(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["gender_policy"] in ("MALE_ONLY", "FEMALE_ONLY", "ANY")
    assert isinstance(data["curfew_weekday"], str)
    assert isinstance(data["curfew_weekend"], str)
    assert data["posture"] in ("OPEN", "CLOSED_FOR_BREAK")
    # PRD §3.1: occupancy counters exposed on dorm reads.
    for field in ("beds_total", "occupancy_physical", "occupancy_projected", "beds_available"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["dorm_id"], str)
    assert isinstance(data["room_number"], str) and data["room_number"]
    assert 1 <= data["beds"] <= 4
    assert data["status"] in ("AVAILABLE", "FULL", "BLOCKED")
    assert isinstance(data["beds_assigned"], int)
    assert isinstance(data["beds_available"], int)


def assert_parent(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_guardian(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["city"], str)
    assert 1 <= data["max_wards"] <= 10
    assert isinstance(data["wards_assigned"], int)
    assert data["status"] in ("PENDING", "APPROVED", "SUSPENDED")


def assert_staff_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["staff_role"] in ("DORM_PARENT", "NURSE", "DEAN", "FRONT_DESK")
    assert isinstance(data["is_active"], bool)


def assert_student(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert 9 <= data["grade"] <= 12
    assert data["gender"] in ("MALE", "FEMALE")
    assert isinstance(data["is_international"], bool)
    assert isinstance(data["parent_id"], str)
    for field in ("sleep_schedule", "cleanliness", "noise_tolerance", "guests_comfort"):
        assert 1 <= data[field] <= 5, f"{field} must be in 1..5"
    assert data["enrollment_status"] in ("ENROLLED", "ON_LEAVE", "WITHDRAWN", "GRADUATED")
    # PRD §2.8: standing and both demerit totals are exposed on the student record.
    assert data["discipline_standing"] in ("GOOD", "PROBATION", "SUSPENDED")
    assert isinstance(data["demerit_points"], int)
    assert isinstance(data["demerit_points_provisional"], int)
    assert isinstance(data["weekend_leaves_used"], int)
    assert isinstance(data["weekend_leave_allowance"], int)


def assert_dorm_assignment(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["room_id"], str)
    assert isinstance(data["term_id"], str)
    assert data["status"] in ("PROPOSED", "CONFIRMED", "SUPERSEDED", "ENDED")


def assert_leave_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert data["leave_type"] in ("WEEKEND_OVERNIGHT", "DAY_PASS", "BREAK_TRAVEL")
    assert isinstance(data["destination"], str)
    assert isinstance(data["departs_at"], str)
    assert isinstance(data["returns_at"], str)
    assert data["status"] in (
        "REQUESTED", "PARENT_APPROVED", "APPROVED", "DENIED", "CANCELLED",
        "EXPIRED", "SIGNED_OUT", "OVERDUE", "RETURNED",
    )
    assert isinstance(data["late_return_minutes"], int)


def assert_sign_event(data: dict):
    _assert_event_fields(data)
    assert isinstance(data["student_id"], str)
    assert data["event_type"] in ("SIGN_OUT", "SIGN_IN")
    assert isinstance(data["occurred_at"], str)
    assert isinstance(data["recorded_by_staff_id"], str)
    assert isinstance(data["minutes_late"], int)


def assert_duty_shift(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["dorm_id"], str)
    assert isinstance(data["staff_id"], str)
    assert isinstance(data["duty_date"], str)
    assert data["shift_slot"] in ("WEEKDAY_NIGHT", "WEEKEND_DAY", "WEEKEND_NIGHT")
    assert data["status"] in ("SCHEDULED", "SWAP_PENDING", "COMPLETED", "MISSED", "CANCELLED")


def assert_night_check(data: dict):
    _assert_event_fields(data)
    assert isinstance(data["duty_shift_id"], str)
    assert isinstance(data["student_id"], str)
    assert data["check_kind"] in ("BED_CHECK", "STUDY_HALL")
    assert data["result"] in ("PRESENT", "LATE_ARRIVAL", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED")
    assert isinstance(data["checked_at"], str)
    assert isinstance(data["points_assessed"], int)


def assert_medication_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["medication_name"], str) and data["medication_name"]
    assert data["slot"] in ("MORNING", "NOON", "EVENING", "BEDTIME")
    assert data["doses_total"] >= 1
    assert isinstance(data["doses_remaining"], int)
    assert isinstance(data["refill_threshold"], int)
    assert isinstance(data["low_stock"], bool)
    assert isinstance(data["is_controlled"], bool)
    assert isinstance(data["prescriber_name"], str)
    assert data["status"] in ("ACTIVE", "HOLD", "DISCONTINUED", "COMPLETED")


def assert_medication_administration(data: dict):
    _assert_event_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["scheduled_date"], str)
    assert data["outcome"] in ("ADMINISTERED", "REFUSED", "OMITTED_HOLD")
    assert isinstance(data["administered_by_staff_id"], str)


def assert_discipline_case(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["reported_by_staff_id"], str)
    assert data["category"] in ("MINOR", "MAJOR")
    assert isinstance(data["description"], str)
    assert isinstance(data["points_proposed"], int)
    assert data["status"] in (
        "REPORTED", "UNDER_REVIEW", "HEARING_SCHEDULED", "SANCTIONED",
        "APPEALED", "DISMISSED", "CLOSED",
    )
    assert isinstance(data["points_assessed"], int)
    assert isinstance(data["appeal_count"], int)


def assert_break_period(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["kind"] in ("THANKSGIVING", "WINTER", "SPRING", "SUMMER")
    assert isinstance(data["starts_on"], str)
    assert isinstance(data["ends_on"], str)
    assert isinstance(data["housing_available"], bool)
    assert data["status"] in ("UPCOMING", "ACTIVE", "CLOSED")


def assert_break_housing_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["break_period_id"], str)
    assert data["status"] in (
        "REQUESTED", "APPROVED", "DENIED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED",
    )
    # PRD §3.8: the pinned fee breakdown fields.
    for field in ("room_charge_cents", "storage_total_cents", "deposit_credit_cents", "fee_cents"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_storage_unit(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str) and data["label"]
    assert data["capacity_cuft"] >= 1
    assert data["status"] in ("OPEN", "SEALED")
    assert isinstance(data["used_cuft"], int)


def assert_storage_reservation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["storage_unit_id"], str)
    assert isinstance(data["student_id"], str)
    assert isinstance(data["break_period_id"], str)
    assert data["volume_cuft"] >= 1
    assert data["weeks"] >= 1
    assert isinstance(data["items_description"], str)
    assert isinstance(data["early_bird"], bool)
    assert isinstance(data["fee_cents"], int)
    assert data["status"] in ("RESERVED", "CHECKED_IN", "RETRIEVED", "CANCELLED", "EXPIRED")


def assert_standing_matches_points(student: dict):
    """PRD §2.8: >=20 SUSPENDED; >=10 PROBATION; else GOOD (inclusive lower bounds)."""
    points = student["demerit_points"]
    expected = "SUSPENDED" if points >= 20 else ("PROBATION" if points >= 10 else "GOOD")
    assert student["discipline_standing"] == expected, (
        f"standing {student['discipline_standing']} inconsistent with "
        f"demerit_points {points} (expected {expected})"
    )
