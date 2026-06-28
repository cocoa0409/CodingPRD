"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"version must be int, got {data.get('version')!r}"


def assert_camp(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["counselor_camper_ratio"], int)
    assert isinstance(data["cit_counts_as_half"], bool)
    assert isinstance(data["deposit_cents"], int)
    assert isinstance(data["deposit_grace_days"], int)
    assert isinstance(data["canteen_low_balance_cents"], int)


def assert_session(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert is_iso8601_timestamp(data["starts_on"])
    assert is_iso8601_timestamp(data["ends_on"])
    assert isinstance(data["capacity"], int)
    assert isinstance(data["enrolled_count"], int)
    assert isinstance(data["committed_count"], int)
    assert isinstance(data["waitlist_length"], int)
    assert data["ratio_posture"] in ("STAFFED", "MARGINAL", "UNDERSTAFFED")
    assert data["status"] in ("PLANNING", "ENROLLING", "RUNNING", "CLOSED")


def assert_cabin(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["session_id"])
    assert data["gender_band"] in ("BOYS", "GIRLS", "ALL")
    assert isinstance(data["min_age"], int)
    assert isinstance(data["max_age"], int)
    assert isinstance(data["bunk_capacity"], int)
    assert isinstance(data["occupied_bunks"], int)
    assert isinstance(data["staff_weight_x10"], int)
    assert isinstance(data["is_staffable"], bool)


def assert_staff_member(data: dict):
    _assert_common(data)
    assert data["role_kind"] in ("COUNSELOR", "CIT")
    assert isinstance(data["is_background_cleared"], bool)


def assert_cabin_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["cabin_id"])
    assert is_valid_uuid(data["staff_member_id"])
    assert data["status"] in ("ACTIVE", "RELEASED")


def assert_camper(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["age"], int)
    assert data["gender"] in ("BOY", "GIRL")
    assert data["health_status"] in ("NONE", "PENDING", "CLEARED", "FLAGGED")


def assert_guardian(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)


def assert_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["camper_id"])
    assert is_valid_uuid(data["session_id"])
    assert data["enroll_status"] in (
        "DRAFT", "SUBMITTED", "WAITLISTED", "OFFERED",
        "DEPOSIT_PAID", "ENROLLED", "WITHDRAWN",
    )
    assert data["payment_status"] in (
        "UNBILLED", "DEPOSIT_DUE", "DEPOSIT_SETTLED",
        "BALANCE_DUE", "PAID_IN_FULL", "REFUND_DUE",
    )
    assert isinstance(data["list_tuition_cents"], int)
    assert isinstance(data["aid_cents"], int)
    assert isinstance(data["estimated_balance_cents"], int)
    assert isinstance(data["settled_balance_cents"], int)
    assert isinstance(data["deposit_paid_cents"], int)


def assert_health_form(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["camper_id"])
    assert isinstance(data["has_life_threatening_allergy"], bool)
    assert isinstance(data["epipen_on_file"], bool)
    assert isinstance(data["daily_medication_count"], int)
    assert data["status"] in ("DRAFT", "SUBMITTED", "CLEARED", "FLAGGED")


def assert_financial_aid(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert data["kind"] in ("NEED_GRANT", "MERIT_SCHOLARSHIP")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED", "REVOKED")


def assert_payment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert data["kind"] in ("DEPOSIT", "BALANCE")
    assert isinstance(data["amount_cents"], int)
    assert data["status"] in ("APPLIED", "REVERSED")


def assert_activity_offering(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["session_id"])
    assert isinstance(data["slot_day"], int)
    assert isinstance(data["starts_minute"], int)
    assert isinstance(data["ends_minute"], int)
    assert isinstance(data["setup_buffer_minutes"], int)
    assert isinstance(data["seat_capacity"], int)
    assert isinstance(data["requires_swim_test"], bool)
    assert isinstance(data["seats_taken"], int)


def assert_activity_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["offering_id"])
    assert is_valid_uuid(data["application_id"])
    assert data["status"] in ("BOOKED", "DROPPED")


def assert_canteen_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["application_id"])
    assert isinstance(data["balance_cents"], int)
    assert isinstance(data["is_low"], bool)


def assert_canteen_transaction(data: dict):
    """Append-only event: id + created_at only. No updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["kind"] in ("DEPOSIT", "PURCHASE")
    assert isinstance(data["amount_cents"], int)
