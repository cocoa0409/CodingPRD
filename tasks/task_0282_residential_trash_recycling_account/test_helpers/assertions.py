"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_service_plan(data: dict):
    _common(data)
    assert data["tier"] in {"BASIC", "STANDARD", "PREMIUM"}, f"bad tier {data['tier']!r}"
    assert data["trash_cart_size_gallons"] in {35, 65, 96}
    assert data["recycling_cart_size_gallons"] in {35, 65, 96}
    for f in ("monthly_base_cents", "extra_cart_monthly_cents",
              "extra_pickup_base_cents", "bulk_item_cents"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be int >= 0"
    assert isinstance(data["archived"], bool)


def assert_service_account(data: dict):
    _common(data)
    assert data["status"] in {"PENDING_START", "ACTIVE", "SUSPENDED", "STOPPED", "TRANSFERRED_OUT"}
    assert data["billing_status"] in {"CURRENT", "PAST_DUE", "IN_COLLECTIONS"}
    assert isinstance(data["autopay_enabled"], bool)
    assert isinstance(data["account_balance_cents"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["service_address"], str) and len(data["service_address"]) > 0


def assert_collection_zone(data: dict):
    _common(data)
    assert 0 <= data["base_pickup_weekday"] <= 6
    assert data["recycling_week_parity"] in {"EVEN", "ODD"}


def assert_holiday(data: dict):
    """Holiday is immutable (PRD §2.4): id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "holiday id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "Holiday must NOT carry a version key"
    assert "updated_at" not in data, "Holiday must NOT carry an updated_at key"
    assert data["shift_direction"] in {"DELAY_ONE_DAY", "NONE"}


def assert_cart_assignment(data: dict):
    _common(data)
    assert data["cart_type"] in {"TRASH", "RECYCLING"}
    assert data["size_gallons"] in {35, 65, 96}
    assert isinstance(data["is_extra"], bool)
    assert data["status"] in {"ACTIVE", "REMOVED"}


def assert_pickup_schedule(data: dict):
    _common(data)
    assert data["stream"] in {"TRASH", "RECYCLING"}
    assert data["status"] in {"PLANNED", "COMPLETED", "MISSED", "CANCELLED"}
    assert is_iso8601_timestamp(data["service_date"])
    assert is_iso8601_timestamp(data["effective_pickup_date"])


def assert_pickup_event(data: dict):
    _common(data)
    assert data["outcome"] in {"COLLECTED", "MISSED", "CONTAMINATED"}


def assert_extra_pickup_request(data: dict):
    _common(data)
    assert data["status"] in {"REQUESTED", "SCHEDULED", "COMPLETED", "CANCELLED"}
    assert isinstance(data["bulk_item_count"], int) and data["bulk_item_count"] >= 0
    assert isinstance(data["charge_cents"], int)


def assert_invoice(data: dict):
    _common(data)
    assert data["status"] in {"OPEN", "PAID", "PAST_DUE", "VOID"}
    assert isinstance(data["gross_amount_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["amount_due_cents"], int)
    assert data["amount_due_cents"] >= 0, "amount_due_cents floored at 0 must never be negative"


def assert_payment(data: dict):
    _common(data)
    assert data["status"] == "APPLIED", "payments always settle on creation"
    assert data["method"] in {"MANUAL", "AUTOPAY"}
    assert isinstance(data["amount_cents"], int)


def assert_missed_pickup_credit(data: dict):
    _common(data)
    assert data["status"] in {"ISSUED", "APPLIED", "EXPIRED"}
    assert isinstance(data["amount_cents"], int)


def assert_contamination_notice(data: dict):
    _common(data)
    assert data["status"] in {"OPEN", "ACKNOWLEDGED", "WAIVED"}
    assert data["severity"] in {"MINOR", "MAJOR"}
    assert isinstance(data["fee_cents"], int)
