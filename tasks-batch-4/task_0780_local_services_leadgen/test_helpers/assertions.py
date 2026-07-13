"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_versioned(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_config_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_customer(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["email"], str) and data["email"], "email must be non-empty"
    assert isinstance(data["full_name"], str)


def assert_pro(data: dict):
    _assert_common_versioned(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["business_name"], str)
    assert data["verification_status"] in ("UNVERIFIED", "PENDING", "VERIFIED", "SUSPENDED")
    assert data["billing_mode"] in ("PAY_PER_LEAD", "SUBSCRIPTION")
    assert isinstance(data["credit_balance_cents"], int) and data["credit_balance_cents"] >= 0
    assert isinstance(data["remaining_lead_credits"], int) and data["remaining_lead_credits"] >= 0


def assert_service_category(data: dict):
    _assert_config_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["base_lead_price_cents"] > 0
    assert data["max_leads_per_request"] >= 1


def assert_subscription_plan(data: dict):
    _assert_config_common(data)
    assert isinstance(data["tier"], str) and data["tier"]
    assert data["monthly_fee_cents"] > 0


def assert_service_request(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("OPEN", "DISTRIBUTED", "BOOKED", "CLOSED")
    assert isinstance(data["distributed_lead_count"], int) and data["distributed_lead_count"] >= 0


def assert_lead(data: dict):
    _assert_common_versioned(data)
    assert data["contact_status"] in ("DISTRIBUTED", "CONTACTED", "QUOTED", "CONVERTED", "CLOSED")
    assert data["billing_status"] in ("CHARGED", "REFUNDED", "DISPUTED")
    assert data["billing_mode"] in ("PAY_PER_LEAD", "SUBSCRIPTION")
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0
    assert data["credits_consumed"] in (0, 1)


def assert_quote(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("SENT", "REVISION_REQUESTED", "ACCEPTED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["amount_cents"] > 0


def assert_booking(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("CONFIRMED", "COMPLETED", "CANCELLED")
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["payout_cents"], int)


def assert_review(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("PENDING", "PUBLISHED")
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5


def assert_dispute(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "RESOLVED_REFUNDED", "RESOLVED_DENIED")
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0


def assert_availability_slot(data: dict):
    _assert_common_versioned(data)
    assert data["status"] in ("OPEN", "BOOKED")
