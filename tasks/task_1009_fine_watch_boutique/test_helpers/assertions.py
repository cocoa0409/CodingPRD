"""Entity assertions and domain invariant checkers.

Uses the framework generic validators internally. ProvenanceEvent is
append-only: it carries only id + created_at (no updated_at, no version).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

_CONDITIONS = ["NEW", "MINT", "EXCELLENT", "GOOD", "FAIR"]


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_customer(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["kyc_verified"], bool)
    assert isinstance(data["store_credit_cents"], int)
    assert data["store_credit_cents"] >= 0, "store_credit_cents is never negative"


def assert_watch_model(data: dict):
    _common(data)
    assert isinstance(data["msrp_cents"], int)
    assert data["lifecycle"] in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data["allocation_controlled"], bool)


def assert_watchmaker(data: dict):
    _common(data)
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["specialties"], list)
    assert isinstance(data["active"], bool)


def assert_watch(data: dict):
    _common(data)
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert data["condition_grade"] in _CONDITIONS
    assert data["source"] in ("PURCHASE", "TRADE_IN", "CONSIGNMENT")
    assert data["authentication_status"] in ("UNVERIFIED", "AUTHENTICATED", "FLAGGED")
    assert data["status"] in (
        "IN_STOCK", "OFFERED", "RESERVED", "IN_SERVICE", "CONSIGNED", "SOLD",
    )
    assert isinstance(data["list_price_cents"], int)


def assert_waitlist_entry(data: dict):
    _common(data)
    assert data["priority_tier"] in ("STANDARD", "PREMIER", "VIP")
    assert data["status"] in ("WAITING", "OFFERED", "ALLOCATED", "EXPIRED", "DECLINED")
    assert isinstance(data["deposit_cents"], int)


def assert_service_ticket(data: dict):
    _common(data)
    assert data["service_type"] in ("BATTERY", "MOVEMENT_OVERHAUL", "WATER_RESISTANCE")
    assert data["status"] in ("RECEIVED", "DIAGNOSED", "READY", "COLLECTED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "PARTIALLY_PAID", "PAID")
    assert isinstance(data["amount_paid_cents"], int)


def assert_appraisal(data: dict):
    _common(data)
    assert data["purpose"] in ("WARRANTY", "INSURANCE", "SALE")
    assert data["valuation_basis"] in ("MARKET", "INSURANCE_REPLACEMENT")
    assert isinstance(data["market_value_cents"], int)
    assert isinstance(data["replacement_value_cents"], int)
    assert isinstance(data["appraised_value_cents"], int)


def assert_trade_in_offer(data: dict):
    _common(data)
    assert data["disposition"] in ("TRADE_IN", "CONSIGNMENT")
    assert data["status"] in ("QUOTED", "ACCEPTED", "SETTLED", "DECLINED", "REVERSED")
    assert isinstance(data["appraised_market_cents"], int)
    assert isinstance(data["quoted_credit_cents"], int)


def assert_layaway_plan(data: dict):
    _common(data)
    assert data["status"] in (
        "ACTIVE", "PAID_OFF", "FULFILLED", "DEFAULTED", "CANCELLED", "VOIDED",
    )
    assert isinstance(data["total_price_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["remaining_cents"] >= 0, "remaining_cents is never negative"


def assert_provenance_event(data: dict):
    """Append-only record: only id + created_at, plus its own fields."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ProvenanceEvent has no updated_at"
    assert "version" not in data, "ProvenanceEvent has no version"
    assert data["event_type"] in (
        "INTAKE", "AUTHENTICATED", "FLAGGED", "APPRAISED", "SERVICED",
        "LAYAWAY_RESERVED", "ALLOCATED", "TRADE_IN_INTAKE", "REVERSED",
    )
