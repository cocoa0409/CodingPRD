"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1"


def assert_membership_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "PLUS", "ELITE"), f"bad tier {data['tier']}"
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["term_months"], int) and data["term_months"] >= 1
    assert isinstance(data["guaranteed_introductions"], int) and data["guaranteed_introductions"] >= 0
    assert isinstance(data["priority_match_enabled"], bool)
    assert isinstance(data["included_coaching_sessions"], int)
    assert isinstance(data["coaching_value_cents"], int)
    assert isinstance(data["background_check_addon_cents"], int)
    assert isinstance(data["archived"], bool)
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["gender"] in ("MALE", "FEMALE", "NONBINARY")
    assert data["status"] in ("PROSPECT", "SCREENING", "ACTIVE", "FROZEN", "EXITED")
    assert data["screening_decision"] in ("NONE", "APPROVED", "REJECTED")


def assert_screening(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert 0 <= data["questionnaire_score"] <= 100
    assert isinstance(data["identity_verified"], bool)
    assert data["decision"] in ("PENDING", "APPROVED", "REJECTED")
    assert data["status"] in ("PENDING", "APPROVED", "REJECTED")


def assert_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["plan_id"])
    assert data["status"] in ("ACTIVE", "FROZEN", "FULFILLED", "CANCELLED", "EXPIRED")
    assert isinstance(data["guaranteed_introductions"], int)
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0


def assert_freeze(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["membership_id"])
    assert data["status"] in ("SCHEDULED", "ACTIVE", "RESUMED", "CANCELLED")


def assert_introduction(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_a_id"])
    assert is_valid_uuid(data["member_b_id"])
    assert data["status"] in ("SUGGESTED", "ONE_SIDED", "MUTUAL", "DECLINED", "CLOSED")
    assert data["a_response"] in ("PENDING", "ACCEPTED", "DECLINED")
    assert data["b_response"] in ("PENDING", "ACCEPTED", "DECLINED")
    assert isinstance(data["credits_consumed"], int)


def assert_date_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["introduction_id"])
    assert is_valid_uuid(data["scheduled_by_member_id"])
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
    assert data["outcome"] in ("NONE", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_coaching_session(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["status"] in ("BOOKED", "HELD", "NO_SHOW", "CANCELLED")


def assert_background_check(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["result"] in ("NONE", "CLEAR", "FLAGGED")
    assert data["status"] in ("ORDERED", "COMPLETED", "CANCELLED")
