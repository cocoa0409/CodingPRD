"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the response shape against the PRD contract
using the framework's generic format helpers.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common mutable-resource fields: id, created_at, updated_at, version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["discipline"] in ("KARATE", "BJJ", "TAEKWONDO", "JUDO", "MUAY_THAI")
    assert isinstance(data["base_monthly_tuition_cents"], int) and data["base_monthly_tuition_cents"] >= 0
    assert isinstance(data["test_fee_cents"], int) and data["test_fee_cents"] >= 0
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_belt_rank(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["rank_order"], int)


def assert_family(data: dict):
    _assert_common(data)
    assert isinstance(data["surname"], str) and len(data["surname"]) > 0
    assert "@" in data["billing_email"]
    assert isinstance(data["active_member_count"], int) and data["active_member_count"] >= 0


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert "@" in data["email"]
    assert data["account_status"] in ("ACTIVE", "FROZEN", "SUSPENDED", "WITHDRAWN")
    assert isinstance(data["waiver_signed"], bool)
    assert isinstance(data["outstanding_balance_cents"], int) and data["outstanding_balance_cents"] >= 0


def assert_instructor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert "@" in data["email"]
    assert data["rank_level"] in ("INSTRUCTOR", "CHIEF_INSTRUCTOR")
    assert isinstance(data["is_available"], bool)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert isinstance(data["member_id"], str)
    assert isinstance(data["program_id"], str)
    assert isinstance(data["rank_attendance_count"], int) and data["rank_attendance_count"] >= 0
    assert data["status"] in ("ACTIVE", "ON_HOLD", "COMPLETED", "DROPPED")


def assert_class_session(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["confirmed_count"], int) and data["confirmed_count"] >= 0
    assert data["status"] in ("SCHEDULED", "CANCELLED", "COMPLETED")


def assert_attendance(data: dict):
    _assert_common(data)
    assert data["status"] in ("CONFIRMED", "CANCELLED")
    assert isinstance(data["counts_toward_rank"], bool)


def assert_promotion_test(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "SCHEDULED", "PASSED_PENDING_SIGNOFF", "PASSED", "FAILED", "CANCELLED"
    )


def assert_contract(data: dict):
    _assert_common(data)
    assert data["term_months"] in (3, 6, 12, 24)
    assert 1 <= data["billing_anchor_day"] <= 28
    assert isinstance(data["months_billed"], int) and data["months_billed"] >= 0
    assert data["status"] in ("ACTIVE", "PAST_DUE", "FULFILLED", "TERMINATED")
    assert isinstance(data["locked_family_discount_pct"], (int, float))


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["kind"] in ("TUITION", "TEST_FEE", "PRO_SHOP", "BUYOUT", "PRIVATE_LESSON")
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 0
    assert data["status"] in ("DUE", "PAID", "OVERDUE", "WAIVED", "VOID")


def assert_private_lesson(data: dict):
    _assert_common(data)
    assert isinstance(data["hourly_rate_cents"], int) and data["hourly_rate_cents"] >= 0
    assert data["status"] in ("REQUESTED", "CONFIRMED", "COMPLETED", "CANCELLED")


def assert_tournament_registration(data: dict):
    _assert_common(data)
    assert data["division"] in ("YOUTH", "TEEN", "ADULT", "MASTERS")
    assert data["status"] in ("REGISTERED", "WITHDRAWN")


def assert_pro_shop_order(data: dict):
    _assert_common(data)
    assert isinstance(data["line_items"], list)
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 0
    assert isinstance(data["net_cents"], int) and data["net_cents"] >= 0
    assert data["status"] in ("PLACED", "FULFILLED", "CANCELLED")
