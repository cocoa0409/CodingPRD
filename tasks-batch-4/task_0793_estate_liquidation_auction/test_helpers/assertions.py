"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ESTATE_STATUSES = ["CATALOGING", "LIVE", "CLOSED", "SETTLED", "CLEANED_OUT"]
LOT_STATUSES = ["DRAFT", "CATALOGED", "LISTED", "SELLING", "SOLD",
                "PASSED", "DONATED", "WITHDRAWN"]
BUYER_STATUSES = ["REGISTERED", "VERIFIED", "SUSPENDED"]
ORDER_PAYMENT_STATUSES = ["UNPAID", "PAID", "REFUNDED"]
ORDER_PICKUP_STATUSES = ["PENDING", "SCHEDULED", "PICKED_UP", "NO_SHOW"]
DISPUTE_STATUSES = ["OPEN", "UNDER_REVIEW", "NEEDS_INFO", "RESOLVED", "REJECTED"]


def assert_common_fields(data: dict):
    """id / created_at / updated_at / version for common_fields entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_append_only_fields(data: dict):
    """id / created_at only; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"


def assert_estate(data: dict):
    assert_common_fields(data)
    assert data["status"] in ESTATE_STATUSES, f"bad estate status {data['status']}"
    assert isinstance(data["seller_name"], str)
    assert isinstance(data["seller_email"], str)
    for f in ("commission_bps", "buyer_premium_bps", "soft_close_seconds",
              "extended_count", "lot_count", "provisional_gross_cents",
              "gross_sales_cents", "commission_cents", "seller_payout_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_lot(data: dict):
    assert_common_fields(data)
    assert data["status"] in LOT_STATUSES, f"bad lot status {data['status']}"
    assert data["condition_grade"] in ["A", "B", "C", "D"]
    for f in ("starting_bid_cents", "current_bid_cents", "bid_count",
              "photo_count"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_buyer(data: dict):
    assert_common_fields(data)
    assert data["status"] in BUYER_STATUSES, f"bad buyer status {data['status']}"
    for f in ("no_show_strikes", "gross_owed_cents", "net_owed_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_order(data: dict):
    assert_common_fields(data)
    assert data["payment_status"] in ORDER_PAYMENT_STATUSES
    assert data["pickup_status"] in ORDER_PICKUP_STATUSES
    assert isinstance(data["lot_ids"], list)
    for f in ("subtotal_cents", "buyer_premium_cents", "sales_tax_cents",
              "total_cents", "amount_paid_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_pickup_window(data: dict):
    assert_common_fields(data)
    for f in ("capacity", "booked_count"):
        assert isinstance(data[f], int), f"{f} must be an integer"


def assert_dispute(data: dict):
    assert_common_fields(data)
    assert data["status"] in DISPUTE_STATUSES, f"bad dispute status {data['status']}"


def assert_photo(data: dict):
    assert_append_only_fields(data)
    assert "updated_at" not in data, "append-only Photo must omit updated_at"
    assert "version" not in data, "append-only Photo must omit version"
    assert isinstance(data["image_url"], str)


def assert_bid(data: dict):
    assert_append_only_fields(data)
    assert "updated_at" not in data, "append-only Bid must omit updated_at"
    assert "version" not in data, "append-only Bid must omit version"
    assert data["status"] in ["ACCEPTED", "OUTBID"]


def assert_payment(data: dict):
    assert_append_only_fields(data)
    assert data["kind"] in ["CHARGE", "REFUND"]
    assert isinstance(data["amount_cents"], int)


def assert_donation(data: dict):
    assert_append_only_fields(data)
    assert data["disposition"] in ["DONATED", "RECYCLED"]


def assert_payout_split_invariant(estate: dict):
    """PRD §3.7: seller_payout_cents + commission_cents == gross_sales_cents."""
    assert estate["seller_payout_cents"] + estate["commission_cents"] \
        == estate["gross_sales_cents"], (
        f"payout split invariant violated: "
        f"{estate['seller_payout_cents']} + {estate['commission_cents']} "
        f"!= {estate['gross_sales_cents']}")
