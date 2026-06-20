"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (is_valid_uuid, is_iso8601_timestamp)
internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1 int"


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["deposit_held_cents"], int)
    assert data["deposit_held_cents"] >= 0, "deposit_held_cents never negative"
    assert isinstance(data["account_balance_cents"], int)
    assert isinstance(data["standing_score"], int)
    assert 0 <= data["standing_score"] <= 100, "standing_score in 0..100"
    assert isinstance(data["provisional_standing_score"], int)
    assert 0 <= data["provisional_standing_score"] <= 100
    assert data["status"] in ("ACTIVE", "DELINQUENT")


def assert_waiver(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("owner_id", "")), "owner_id is a UUID"
    assert data["status"] in ("PENDING", "SIGNED", "EXPIRED", "SUPERSEDED")


def assert_stall(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert data["kind"] in ("STALL", "PASTURE")
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["daily_rate_cents"], int)
    assert isinstance(data["occupied_count"], int) and data["occupied_count"] >= 0
    assert data["occupied_count"] <= data["capacity"], "occupied_count never exceeds capacity"


def assert_horse(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("owner_id", "")), "owner_id is a UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0


def assert_boarding_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("horse_id", "")), "horse_id is a UUID"
    assert is_valid_uuid(data.get("stall_id", "")), "stall_id is a UUID"
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "ENDED")
    assert isinstance(data["suspended_days"], int) and data["suspended_days"] >= 0
    assert isinstance(data["provisional_charge_cents"], int)
    assert isinstance(data["final_charge_cents"], int)


def assert_lesson(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("horse_id", "")), "horse_id is a UUID"
    assert isinstance(data["lesson_fee_cents"], int)
    assert isinstance(data["billed_fee_cents"], int)
    assert isinstance(data["invoiced"], bool)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")


def assert_service_visit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("horse_id", "")), "horse_id is a UUID"
    assert data["visit_type"] in ("FARRIER", "VET", "DENTIST")
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert isinstance(data["fee_cents"], int)
    assert isinstance(data["invoiced"], bool)
    assert data["status"] in ("REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED")


def assert_show_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("horse_id", "")), "horse_id is a UUID"
    assert isinstance(data["entry_fee_cents"], int)
    assert isinstance(data["invoiced"], bool)
    assert data["status"] in ("SUBMITTED", "CONFIRMED", "SCRATCHED", "WITHDRAWN")


def assert_turnout(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("horse_id", "")), "horse_id is a UUID"
    assert is_valid_uuid(data.get("pasture_id", "")), "pasture_id is a UUID"
    assert data["status"] in ("BOOKED", "CANCELLED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("owner_id", "")), "owner_id is a UUID"
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["multi_horse_discount_cents"], int)
    assert isinstance(data["deposit_applied_cents"], int)
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 0
    assert isinstance(data["paid_amount_cents"], int)
    assert data["status"] in ("OPEN", "FINALIZED", "PAID", "VOID")
