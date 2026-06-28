"""Entity assertions and domain invariant checkers for the Yoga & Pilates Studio API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id/created_at/updated_at/version present on every primary resource (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_member(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["home_studio_state"], str)
    assert isinstance(data["is_new_student"], bool)
    assert isinstance(data["lifetime_attended_count"], int)
    assert isinstance(data["no_show_strike_count"], int)
    assert data["account_status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["outstanding_fee_cents"], int)


def assert_room(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert data["room_type"] in ("REFORMER", "MAT")
    assert isinstance(data["station_capacity"], int) and data["station_capacity"] >= 1
    assert data["status"] in ("OPEN", "CLOSED")


def assert_teacher(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["certifications"], list)
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_intro_offer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["credits_total"], int) and data["credits_total"] >= -1
    assert isinstance(data["window_days"], int) and data["window_days"] >= 1
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_class_session(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["room_id"])
    assert is_valid_uuid(data["teacher_id"])
    assert data["discipline"] in ("VINYASA", "YIN", "REFORMER", "MAT_PILATES")
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert isinstance(data["published_capacity"], int) and data["published_capacity"] >= 1
    assert isinstance(data["waitlist_capacity"], int) and data["waitlist_capacity"] >= 0
    assert data["status"] in (
        "SCHEDULED", "OPEN", "FULL", "IN_PROGRESS", "COMPLETED", "CANCELLED",
    )
    assert isinstance(data["booked_count"], int) and data["booked_count"] >= 0
    assert isinstance(data["waitlisted_count"], int) and data["waitlisted_count"] >= 0


def assert_entitlement(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert data["kind"] in ("MEMBERSHIP", "CLASS_PACK", "INTRO")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["credits_total"], int) and data["credits_total"] >= -1
    assert isinstance(data["credits_used"], int)
    assert isinstance(data["credits_remaining"], int)
    assert is_iso8601_timestamp(data["cycle_start_utc"])
    assert is_iso8601_timestamp(data["cycle_end_utc"])
    assert isinstance(data["auto_renew"], bool)
    assert isinstance(data["rollover_cap"], int) and data["rollover_cap"] >= 0
    assert data["lifecycle_status"] in ("PENDING", "ACTIVE", "EXPIRED", "CANCELLED")
    assert data["freeze_status"] in ("UNFROZEN", "FROZEN")
    assert isinstance(data["frozen_days_consumed"], int)


def assert_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["class_session_id"])
    assert is_valid_uuid(data["entitlement_id"])
    assert data["status"] in (
        "BOOKED", "WAITLISTED", "CHECKED_IN", "ATTENDED",
        "CANCELLED_EARLY", "CANCELLED_LATE", "NO_SHOW",
    )
    assert isinstance(data["credit_charged"], bool)


def assert_workshop(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["room_id"])
    assert is_valid_uuid(data["lead_teacher_id"])
    assert isinstance(data["title"], str)
    assert data["kind"] in ("WORKSHOP", "TEACHER_TRAINING")
    assert is_iso8601_timestamp(data["start_utc"])
    assert is_iso8601_timestamp(data["end_utc"])
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in ("DRAFT", "OPEN", "FULL", "CLOSED", "CANCELLED")
    assert isinstance(data["confirmed_seat_count"], int) and data["confirmed_seat_count"] >= 0


def assert_enrollment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["workshop_id"])
    assert data["status"] in (
        "APPLIED", "CONFIRMED", "WAITLISTED", "WITHDRAWN", "CANCELLED_BY_STUDIO",
    )
    assert isinstance(data["deposit_paid_cents"], int)
    assert isinstance(data["balance_due_cents"], int)


def assert_fee_charge(data: dict):
    """FeeCharge is immutable in shape: id + created_at only, no version/updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["reservation_id"])
    assert data["fee_type"] in ("LATE_CANCEL", "NO_SHOW")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("UNPAID", "PAID", "WAIVED")


def assert_no_version_field(data: dict):
    """FeeCharge has neither updated_at nor version (PRD §2.4)."""
    assert "version" not in data, "FeeCharge must not expose a version field"
    assert "updated_at" not in data, "FeeCharge must not expose an updated_at field"
