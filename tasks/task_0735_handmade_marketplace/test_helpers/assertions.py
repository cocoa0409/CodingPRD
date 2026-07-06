"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Every checker verifies only the
fields the PRD promises on the response for that resource.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    ShopStatus, ListingStatus, MaterialStatus, OrderPaymentStatus,
    OrderFulfillmentStatus, ReviewStatus, CaseStatus, PayoutStatus,
)

_SHOP_STATUSES = {s.value for s in ShopStatus}
_LISTING_STATUSES = {s.value for s in ListingStatus}
_MATERIAL_STATUSES = {s.value for s in MaterialStatus}
_PAYMENT_STATUSES = {s.value for s in OrderPaymentStatus}
_FULFILLMENT_STATUSES = {s.value for s in OrderFulfillmentStatus}
_REVIEW_STATUSES = {s.value for s in ReviewStatus}
_CASE_STATUSES = {s.value for s in CaseStatus}
_PAYOUT_STATUSES = {s.value for s in PayoutStatus}


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version for common_fields:true entities."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must be >= 1, got {data['version']}"


def assert_shop(data: dict):
    assert_common_fields(data)
    assert data["status"] in _SHOP_STATUSES, f"unexpected shop status {data.get('status')!r}"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["max_concurrent_production"] >= 1
    for money in ("available_balance_cents", "pending_balance_cents",
                  "lifetime_gross_cents", "lifetime_fees_cents"):
        assert isinstance(data[money], int), f"{money} must be an integer"


def assert_shipping_profile(data: dict):
    assert_common_fields(data)
    assert data["base_cost_cents"] >= 0
    assert data["per_item_cost_cents"] >= 0
    assert data["free_shipping_threshold_cents"] >= 0
    assert data["processing_time_days"] >= 0


def assert_material(data: dict):
    assert_common_fields(data)
    assert data["status"] in _MATERIAL_STATUSES, f"unexpected material status {data.get('status')!r}"
    assert data["stock_qty"] >= 0


def assert_listing(data: dict):
    assert_common_fields(data)
    assert data["status"] in _LISTING_STATUSES, f"unexpected listing status {data.get('status')!r}"
    assert data["price_cents"] >= 1
    assert data["fulfillment_type"] in ("READY_TO_SHIP", "MADE_TO_ORDER")


def assert_order(data: dict):
    assert_common_fields(data)
    assert data["payment_status"] in _PAYMENT_STATUSES, f"unexpected payment_status {data.get('payment_status')!r}"
    assert data["fulfillment_status"] in _FULFILLMENT_STATUSES, f"unexpected fulfillment_status {data.get('fulfillment_status')!r}"
    assert data["quantity"] >= 1
    for money in ("item_subtotal_cents", "shipping_cents", "order_total_cents"):
        assert isinstance(data[money], int), f"{money} must be an integer"


def assert_review(data: dict):
    assert_common_fields(data)
    assert data["status"] in _REVIEW_STATUSES
    assert 1 <= data["rating"] <= 5


def assert_case(data: dict):
    assert_common_fields(data)
    assert data["status"] in _CASE_STATUSES


def assert_payout(data: dict):
    assert_common_fields(data)
    assert data["status"] in _PAYOUT_STATUSES


def assert_vacation_period(data: dict):
    """VacationPeriod is append-only (common_fields:false): id + created_at only.
    It carries NO updated_at and NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data.get("status") == "SCHEDULED"
