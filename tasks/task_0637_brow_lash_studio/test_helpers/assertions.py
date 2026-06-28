"""Entity assertions and domain invariant checkers for the Brow & Lash Studio API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id + created_at + updated_at + version present on common_fields:true entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_studio(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 0 <= data["deposit_rate_pct"] <= 1
    assert data["late_cancel_cutoff_hours"] >= 0
    assert data["status"] in ("OPEN", "CLOSED")


def assert_service_type(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("studio_id", "")), "studio_id FK must be a UUID"
    assert data["code"] in ("FULL_SET", "FILL", "LIFT", "TINT")
    assert data["category"] in ("PREMIUM", "STANDARD")
    assert data["duration_minutes"] > 0
    assert data["base_price_cents"] >= 0
    assert data["credit_cost"] >= 0
    assert isinstance(data["active"], bool)


def assert_membership_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("ESSENTIAL", "PREMIER", "LUXE")
    assert data["monthly_credit_allotment"] > 0
    assert data["monthly_fee_cents"] >= 0


def assert_lash_tech(data: dict):
    _assert_common(data)
    assert 1 <= data["skill_level"] <= 3
    assert data["station_number"] >= 1
    assert data["status"] in ("AVAILABLE", "OFF_DUTY")


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert data["noshow_strike_count"] >= 0


def assert_membership(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED")
    assert data["credit_balance"] >= 0, "credit_balance is never negative (PRD §2.6)"
    assert data["cycles_closed"] >= 0


def assert_patch_test(data: dict):
    _assert_common(data)
    assert data["status"] in ("VALID", "EXPIRED", "REVOKED")
    assert isinstance(data["consent_signed"], bool)


def assert_appointment(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "COMPLETED", "NO_SHOW", "LATE_CANCELLED", "CANCELLED")
    assert is_iso8601_timestamp(data.get("start_utc", "")), "start_utc must be ISO 8601"
    assert data["deposit_cents"] >= 0
    assert data["credits_charged"] >= 0


def assert_retail_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("PAID", "VOIDED")
    assert data["subtotal_cents"] >= 0
    assert data["peak_surcharge_cents"] >= 0
    assert data["total_cents"] == data["subtotal_cents"] + data["peak_surcharge_cents"]


def assert_recurring_schedule(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PAUSED", "ENDED")
    assert data["spawned_count"] >= 0


def assert_sanitation_log(data: dict):
    _assert_common(data)
    assert data["status"] in ("COMPLETED", "VOIDED")
    assert is_iso8601_timestamp(data.get("sanitized_at_utc", ""))
    assert is_iso8601_timestamp(data.get("valid_through_utc", ""))


def assert_credit_ledger_entry(data: dict):
    """CreditLedgerEntry is append-only: only id + created_at, NO updated_at / version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a bare UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries carry no updated_at (PRD §2.5)"
    assert "version" not in data, "ledger entries carry no version (PRD §2.5)"
    assert data["reason"] in ("GRANT", "ROLLOVER", "ROLLOVER_FORFEIT", "CONSUME", "REFUND")
    assert isinstance(data["delta"], int)
