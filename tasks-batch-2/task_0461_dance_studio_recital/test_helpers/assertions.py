"""Entity assertions and domain invariant checkers for the Dance Studio Recital API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_family(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["family_name"], str)
    assert isinstance(data["autopay_enabled"], bool)
    assert isinstance(data["payment_method_on_file"], bool)
    assert isinstance(data["account_credit_cents"], int) and data["account_credit_cents"] >= 0, \
        "account_credit_cents must never be negative"
    assert isinstance(data["sibling_count"], int) and data["sibling_count"] >= 0
    assert data["status"] in ("ACTIVE", "DELINQUENT")


def assert_student(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["family_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["birth_date"], str)
    assert isinstance(data["age_as_of_cutoff"], int)
    assert data["level"] in ("PETITE", "NOVICE", "INTERMEDIATE", "ADVANCED", "ELITE")
    assert data["status"] in ("ACTIVE", "WITHDRAWN")


def assert_term(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")
    assert isinstance(data["monthly_billing_day"], int) and 1 <= data["monthly_billing_day"] <= 28


def assert_room(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["turnover_buffer_minutes"], int) and data["turnover_buffer_minutes"] >= 0


def assert_instructor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["max_weekly_sessions"], int) and data["max_weekly_sessions"] >= 1


def assert_section(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["term_id"])
    assert is_valid_uuid(data["room_id"])
    assert is_valid_uuid(data["instructor_id"])
    assert data["discipline"] in ("BALLET", "JAZZ", "TAP", "HIPHOP", "CONTEMPORARY", "ACRO")
    assert data["required_level"] in ("PETITE", "NOVICE", "INTERMEDIATE", "ADVANCED", "ELITE")
    assert isinstance(data["min_age"], int) and data["min_age"] >= 0
    assert isinstance(data["max_age"], int) and data["max_age"] >= data["min_age"]
    assert isinstance(data["monthly_tuition_cents"], int) and data["monthly_tuition_cents"] >= 0
    assert isinstance(data["capacity_cap"], int) and data["capacity_cap"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert data["status"] in ("PLANNED", "SCHEDULED", "OPEN", "FULL", "CANCELLED")


def assert_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["section_id"])
    assert isinstance(data["day_of_week"], int) and 0 <= data["day_of_week"] <= 6
    assert isinstance(data["start_minute"], int) and 0 <= data["start_minute"] <= 1439
    assert isinstance(data["end_minute"], int) and data["end_minute"] > data["start_minute"]


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["section_id"])
    assert is_valid_uuid(data["family_id"])
    assert data["placement_status"] in (
        "PENDING", "CONFIRMED", "WAITLISTED", "WAITLIST_PROMOTED", "DROPPED")
    assert data["billing_status"] in (
        "UNBILLED", "BILLING_ACTIVE", "BILLING_PAUSED", "BILLING_ENDED")
    assert isinstance(data["waitlist_rank"], int) and data["waitlist_rank"] >= 0
    assert isinstance(data["monthly_charge_cents"], int) and data["monthly_charge_cents"] >= 0


def assert_attendance(data: dict):
    # Attendance is append-only (PRD §2.4): only id + created_at, no updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "attendance id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Attendance must not carry updated_at (append-only)"
    assert "version" not in data, "Attendance must not carry version (append-only)"
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["session_id"])
    assert data["result"] in ("PRESENT", "ABSENT_EXCUSED", "ABSENT_UNEXCUSED")
    assert isinstance(data["makeup_eligible"], bool)
    assert isinstance(data["makeup_consumed"], bool)


def assert_costume(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["section_id"])
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["rush_surcharge_cents"], int) and data["rush_surcharge_cents"] >= 0
    assert data["status"] in ("SIZING_OPEN", "ORDERED")


def assert_costume_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["costume_id"])
    assert is_valid_uuid(data["enrollment_id"])
    assert data["size_code"] in ("CHILD_S", "CHILD_M", "CHILD_L", "ADULT_S", "ADULT_M", "ADULT_L")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in ("DRAFT", "SUBMITTED", "CANCELLED")


def assert_recital(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["term_id"])
    assert isinstance(data["total_seats"], int) and data["total_seats"] >= 1
    assert isinstance(data["ticket_price_cents"], int) and data["ticket_price_cents"] >= 0
    assert isinstance(data["free_tickets_per_family"], int) and data["free_tickets_per_family"] >= 0
    assert isinstance(data["seats_sold"], int) and data["seats_sold"] >= 0
    assert data["status"] in ("ANNOUNCED", "ON_SALE", "SOLD_OUT", "COMPLETED")


def assert_seat(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["recital_id"])
    assert is_valid_uuid(data["family_id"])
    assert isinstance(data["seat_label"], str)
    assert isinstance(data["is_complimentary"], bool)
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in ("HELD", "PURCHASED", "RELEASED")


def assert_team(data: dict):
    _assert_common(data)
    assert data["min_level"] in ("PETITE", "NOVICE", "INTERMEDIATE", "ADVANCED", "ELITE")
    assert isinstance(data["roster_cap"], int) and data["roster_cap"] >= 1
    assert isinstance(data["roster_count"], int) and data["roster_count"] >= 0
    assert data["status"] in ("FORMING", "LOCKED")


def assert_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["team_id"])
    assert is_valid_uuid(data["student_id"])
    assert data["status"] in ("ROSTERED", "RELEASED")


def assert_trip(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["team_id"])
    assert isinstance(data["per_member_cost_cents"], int) and data["per_member_cost_cents"] >= 0
    assert isinstance(data["chaperone_ratio"], int) and data["chaperone_ratio"] >= 1
    assert isinstance(data["chaperone_count"], int) and data["chaperone_count"] >= 0
    assert isinstance(data["participant_count"], int) and data["participant_count"] >= 0
    assert data["status"] in ("PROPOSED", "CONFIRMED", "CANCELLED")


def assert_participant(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["trip_id"])
    assert is_valid_uuid(data["membership_id"])
    assert is_valid_uuid(data["family_id"])
    assert data["status"] in ("GOING", "WITHDRAWN")


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["family_id"])
    assert is_valid_uuid(data["term_id"])
    assert isinstance(data["billing_month"], str)
    assert isinstance(data["tuition_cents"], int) and data["tuition_cents"] >= 0
    assert isinstance(data["fees_cents"], int) and data["fees_cents"] >= 0
    assert isinstance(data["credit_applied_cents"], int) and data["credit_applied_cents"] >= 0
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 0
    assert data["status"] in ("OPEN", "PAID", "PAST_DUE", "VOID")
