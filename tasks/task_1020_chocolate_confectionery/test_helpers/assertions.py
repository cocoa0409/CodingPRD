"""Entity assertions and domain invariant checkers (PRD Sections 2 & 3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id/created_at/updated_at/version present and well-formed (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert data["account_type"] in ("RETAIL", "WHOLESALE", "CORPORATE")
    assert isinstance(data["wallet_credit_cents"], int)


def assert_product(data: dict):
    _assert_common(data)
    assert data["product_type"] in ("SINGLE", "BUNDLE")
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data["base_price_cents"], int)


def assert_bundle_component(data: dict):
    """Immutable junction (PRD §2.4): only id + created_at, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["quantity"], int)


def assert_mold(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "MAINTENANCE", "RETIRED")


def assert_batch(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "RAW", "TEMPERING", "TEMPERED", "RELEASED", "QUARANTINED", "DISCARDED", "EXPIRED",
    )
    assert isinstance(data["available_units"], int)
    assert isinstance(data["initial_units"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "CONFIRMED", "ALLOCATED", "FULFILLED", "BACKORDERED", "CANCELLED",
    )


def assert_custom_order(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "QUOTED", "REVISION_REQUESTED", "ACCEPTED", "IN_PRODUCTION",
        "FULFILLED", "REJECTED", "CANCELLED",
    )


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PAUSED", "CANCELLED")


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "SHIPPED", "CANCELLED")
