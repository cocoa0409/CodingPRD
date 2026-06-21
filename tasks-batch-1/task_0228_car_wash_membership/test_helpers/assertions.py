"""Entity assertions and domain invariant checkers for the Car Wash Membership API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


# ─── Per-entity structural assertions ──────────────────────────────────────

def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "account id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert data["account_type"] in ("INDIVIDUAL", "FLEET")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["wallet_balance_cents"], int)
    assert data["wallet_balance_cents"] >= 0, "wallet_balance_cents must never be negative"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "plan id must be valid UUID"
    assert data["tier_type"] in ("UNLIMITED", "SINGLE_WASH")
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 0
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_location(data: dict):
    assert is_valid_uuid(data.get("id", "")), "location id must be valid UUID"
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["daily_wash_capacity"], int) and data["daily_wash_capacity"] >= 1
    assert isinstance(data["in_network"], bool)


def assert_addon(data: dict):
    assert is_valid_uuid(data.get("id", "")), "addon id must be valid UUID"
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["recurring_fee_cents"], int) and data["recurring_fee_cents"] >= 0


def assert_vehicle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "vehicle id must be valid UUID"
    assert data["status"] in ("ACTIVE", "REMOVED")
    assert isinstance(data["license_plate"], str) and len(data["license_plate"]) > 0


def assert_membership(data: dict):
    assert is_valid_uuid(data.get("id", "")), "membership id must be valid UUID"
    assert data["status"] in (
        "PENDING", "ACTIVE", "PAST_DUE", "FROZEN", "CANCEL_SCHEDULED", "CANCELLED",
    )
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["credit_balance"], int)
    assert isinstance(data["credits_granted"], int)
    assert isinstance(data["credits_consumed"], int)


def assert_membership_addon(data: dict):
    assert is_valid_uuid(data.get("id", "")), "membership addon id must be valid UUID"
    assert data["status"] in ("ACTIVE", "PAUSED", "DETACHED")
    assert isinstance(data["locked_fee_cents"], int) and data["locked_fee_cents"] >= 0


def assert_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "invoice id must be valid UUID"
    assert data["status"] in (
        "DRAFT", "ISSUED", "PAID", "FAILED", "RETRYING", "WRITTEN_OFF", "VOID",
    )
    assert data["kind"] in ("CYCLE", "PRORATION", "TOPUP")
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 0


def assert_wash_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "wash event id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("REQUESTED", "ADMITTED", "REJECTED", "COMPLETED")
    # Append-only audit record: no updated_at, no version.
    assert "version" not in data, "WashEvent must not carry a version field"
    assert "updated_at" not in data, "WashEvent must not carry an updated_at field"


def assert_freeze(data: dict):
    assert is_valid_uuid(data.get("id", "")), "freeze id must be valid UUID"
    assert data["status"] in ("SCHEDULED", "ACTIVE", "ENDED", "CANCELLED")
    assert isinstance(data["refund_cents"], int)


def assert_wallet_transaction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "wallet txn id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["reason"] in (
        "CANCEL_REFUND", "FREEZE_REFUND", "TOPUP_DEBIT", "INVOICE_CHARGE", "MANUAL_ADJUSTMENT",
    )
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_after_cents"], int)
    # Append-only audit record: no updated_at, no version.
    assert "version" not in data, "WalletTransaction must not carry a version field"
    assert "updated_at" not in data, "WalletTransaction must not carry an updated_at field"
