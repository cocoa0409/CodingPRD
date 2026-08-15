"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from datetime import datetime

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_instant_eq(actual: str, expected: str):
    """Compare two ISO 8601 instants regardless of fractional-digit formatting."""
    def _parse(value: str) -> datetime:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    assert _parse(actual) == _parse(expected), (
        f"Expected instant {expected}, got {actual}"
    )


def assert_common_fields(data: dict):
    """Every resource carries id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), (
        f"version must be an int, got {data.get('version')!r}"
    )


def _assert_optional_instant(data: dict, field: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{field} must be null or ISO 8601 UTC, got {value!r}"
    )


def assert_season(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    for f in ("start_date", "end_date", "resident_opens_at", "general_opens_at",
              "registration_closes_at"):
        assert is_iso8601_timestamp(data.get(f, "")), f"{f} must be ISO 8601 UTC"
    assert isinstance(data["family_discount_threshold"], int)
    assert data["family_discount_threshold"] >= 2
    assert isinstance(data["family_discount_pct"], int)
    assert 0 <= data["family_discount_pct"] <= 100
    assert isinstance(data["scholarship_budget_cents"], int)
    assert data["scholarship_budget_cents"] >= 0
    assert isinstance(data["scholarship_committed_cents"], int)
    assert data["scholarship_committed_cents"] >= 0
    assert data["status"] in ("DRAFT", "PUBLISHED", "CLOSED")


def assert_program(data: dict):
    assert_common_fields(data)
    assert isinstance(data["season_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["category"], str) and data["category"]
    assert isinstance(data["min_age"], int) and data["min_age"] >= 0
    assert isinstance(data["max_age"], int) and data["max_age"] >= data["min_age"]


def assert_room(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert data["status"] in ("ACTIVE", "MAINTENANCE")


def assert_instructor(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]


def assert_class_session(data: dict):
    assert_common_fields(data)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["instructor_id"], str)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["capacity"], int) and data["capacity"] > 0
    assert isinstance(data["min_enrollment"], int)
    assert 1 <= data["min_enrollment"] <= data["capacity"]
    assert isinstance(data["fee_resident_cents"], int) and data["fee_resident_cents"] >= 0
    assert isinstance(data["fee_nonresident_cents"], int)
    assert data["fee_nonresident_cents"] >= 0
    assert is_iso8601_timestamp(data.get("enrollment_check_at", ""))
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0
    assert isinstance(data["waitlist_count"], int) and data["waitlist_count"] >= 0
    assert data["status"] in ("DRAFT", "PUBLISHED", "ACTIVE", "COMPLETED", "CANCELLED")
    reason = data.get("cancellation_reason")
    if data["status"] == "CANCELLED":
        assert reason in ("LOW_ENROLLMENT", "ADMIN")
    else:
        assert reason is None


def assert_class_meeting(data: dict):
    assert_common_fields(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["room_id"], str)
    assert is_iso8601_timestamp(data.get("starts_at", ""))
    assert is_iso8601_timestamp(data.get("ends_at", ""))
    assert data["ends_at"] > data["starts_at"]


def assert_instructor_contract(data: dict):
    assert_common_fields(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["instructor_id"], str)
    assert isinstance(data["revenue_share_bp"], int)
    assert 0 <= data["revenue_share_bp"] <= 10000
    assert isinstance(data["guarantee_min_cents"], int)
    assert data["guarantee_min_cents"] >= 0
    assert isinstance(data["cancellation_guarantee_cents"], int)
    assert data["cancellation_guarantee_cents"] >= 0
    assert data["settlement_basis"] in ("ENROLLMENT_BASIS", "ATTENDANCE_BASIS")
    assert data["status"] in ("OFFERED", "ACCEPTED", "DECLINED", "VOID",
                              "TERMINATED", "SETTLED")
    if data["status"] in ("OFFERED", "ACCEPTED"):
        assert data.get("settlement_headcount") is None
        assert data.get("settlement_amount_cents") is None
        assert data.get("payout_cents") is None
    if data["status"] == "SETTLED":
        assert isinstance(data["settlement_headcount"], int)
        assert data["settlement_headcount"] >= 0
        assert isinstance(data["settlement_amount_cents"], int)
        assert data["settlement_amount_cents"] >= 0
        assert data["payout_cents"] == data["settlement_amount_cents"]


def assert_household(data: dict):
    assert_common_fields(data)
    assert isinstance(data["account_name"], str) and data["account_name"]
    assert data["residency_status"] in ("PENDING", "RESIDENT", "NONRESIDENT")
    assert isinstance(data["account_credit_cents"], int)


def assert_participant(data: dict):
    assert_common_fields(data)
    assert isinstance(data["household_id"], str)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert is_iso8601_timestamp(data.get("birth_date", ""))


def assert_safety_form(data: dict):
    assert_common_fields(data)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["season_id"], str)
    assert isinstance(data["emergency_contact_name"], str)
    assert data["emergency_contact_name"]
    assert isinstance(data["emergency_contact_phone"], str)
    assert data["emergency_contact_phone"]
    assert isinstance(data["signer_name"], str) and data["signer_name"]
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED")


def assert_scholarship_application(data: dict):
    assert_common_fields(data)
    assert isinstance(data["household_id"], str)
    assert isinstance(data["season_id"], str)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["annual_income_cents"], int)
    assert data["annual_income_cents"] >= 0
    assert data["status"] in ("SUBMITTED", "UNDER_REVIEW", "MORE_INFO_REQUESTED",
                              "RESUBMITTED", "APPROVED", "DENIED", "WITHDRAWN",
                              "REVOKED")
    pct = data.get("approved_pct")
    if pct is not None:
        assert pct in (25, 50, 75, 100)
    commitment = data.get("estimated_commitment_cents")
    if commitment is not None:
        assert isinstance(commitment, int) and commitment >= 0


def assert_registration(data: dict):
    assert_common_fields(data)
    assert isinstance(data["session_id"], str)
    assert isinstance(data["participant_id"], str)
    assert isinstance(data["household_id"], str)
    assert data["residency_at_registration"] in ("RESIDENT", "NONRESIDENT")
    assert isinstance(data["scholarship_pct_applied"], int)
    assert data["scholarship_pct_applied"] in (0, 25, 50, 75, 100)
    assert isinstance(data["family_discount_applied"], bool)
    assert isinstance(data["fee_charged_cents"], int) and data["fee_charged_cents"] >= 0
    assert isinstance(data["net_paid_cents"], int) and data["net_paid_cents"] >= 0
    assert isinstance(data["refund_total_cents"], int)
    assert data["refund_total_cents"] >= 0
    assert data["enrollment_status"] in ("ENROLLED", "WAITLISTED", "DROPPED",
                                         "EXPIRED", "CANCELLED")
    assert data["payment_status"] in ("PENDING", "PAID", "WAIVED", "REFUND_PENDING",
                                      "REFUNDED", "VOID")
    reason = data.get("drop_reason")
    if reason is not None:
        assert reason in ("VOLUNTARY", "NO_SHOW", "PAYMENT_TIMEOUT",
                          "LOW_ENROLLMENT", "ADMIN")
    _assert_optional_instant(data, "waitlisted_at")
    _assert_optional_instant(data, "promoted_at")
    _assert_optional_instant(data, "payment_due_at")
    assert isinstance(data["consecutive_absences"], int)
    assert data["consecutive_absences"] >= 0


def assert_payment_transaction(data: dict):
    assert_common_fields(data)
    assert isinstance(data["registration_id"], str)
    assert data["type"] in ("CHARGE", "REFUND")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["method"] in ("EXTERNAL", "ACCOUNT_CREDIT")
    assert data["status"] in ("PENDING", "COMPLETED")
    if data["type"] == "CHARGE":
        assert data["status"] == "COMPLETED"


def assert_attendance_record(data: dict):
    assert_common_fields(data)
    assert isinstance(data["meeting_id"], str)
    assert isinstance(data["registration_id"], str)
    assert data["status"] in ("PRESENT", "ABSENT", "EXCUSED")


def assert_session_counters(data: dict):
    """Derived counters must respect the seat pool (PRD §2.10)."""
    assert data["enrolled_count"] >= 0
    assert data["waitlist_count"] >= 0
    assert data["enrolled_count"] <= data["capacity"]
