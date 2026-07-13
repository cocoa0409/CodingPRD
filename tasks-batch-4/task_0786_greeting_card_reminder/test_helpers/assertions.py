"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_account(data: dict):
    _common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["display_name"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["card_credit_balance"], int)
    assert data["card_credit_balance"] >= 0, "card_credit_balance is never negative"


def assert_subscription(data: dict):
    _common(data)
    assert data["tier"] in ("FREE", "PLUS", "PRO")
    assert data["status"] in ("ACTIVE", "CANCELLED")
    assert isinstance(data["monthly_card_credits"], int)


def assert_credit_transaction(data: dict):
    # Append-only ledger row: only id + created_at among the common fields.
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "CreditTransaction must not carry updated_at"
    assert "version" not in data, "CreditTransaction must not carry version"
    assert data["reason"] in (
        "SUBSCRIPTION_GRANT", "PRORATION_GRANT", "ORDER_HOLD", "ORDER_REFUND", "MANUAL_ADJUST"
    )
    assert isinstance(data["delta"], int)


def assert_contact(data: dict):
    _common(data)
    assert data["address_status"] in ("UNVERIFIED", "VERIFIED", "UNDELIVERABLE")


def assert_important_date(data: dict):
    _common(data)
    assert data["occasion_type"] in ("BIRTHDAY", "ANNIVERSARY", "HOLIDAY", "CUSTOM")
    assert data["recurrence"] in ("NONE", "ANNUAL")
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert is_iso8601_timestamp(data["next_trigger_at"])


def assert_order(data: dict):
    _common(data)
    assert data["status"] in (
        "DRAFT", "PENDING_PROOF", "PROOF_APPROVED", "SCHEDULED",
        "IN_PRODUCTION", "MAILED", "DELIVERED", "CANCELLED",
    )
    assert data["credit_status"] in ("NONE", "HELD", "SETTLED", "REFUNDED")
    assert data["font_style"] in ("SCRIPT", "PRINT", "CASUAL")
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["postage_cents"], int)


def assert_proof(data: dict):
    _common(data)
    assert data["status"] in ("PENDING", "CHANGES_REQUESTED", "APPROVED", "VOIDED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_artist_assignment(data: dict):
    _common(data)
    assert data["status"] in ("RESERVED", "COMPLETED", "RELEASED")


def assert_shipment(data: dict):
    _common(data)
    assert data["status"] in ("LABEL_CREATED", "IN_TRANSIT", "DELIVERED", "RETURNED")
    assert data["carrier"] in ("USPS", "UPS")
    assert isinstance(data["tracking_number"], str) and data["tracking_number"]
