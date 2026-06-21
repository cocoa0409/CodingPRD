"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}() validate the response shape against the PRD contract.
Append-only entities (Watch, Payment, Feedback) carry only id + created_at and
must NOT be asserted for updated_at / version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .constants import FEE_SUSPEND_THRESHOLD_CENTS


def _assert_common(data: dict):
    """id + created_at + updated_at + version for full entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_light(data: dict):
    """id + created_at for append-only / soft-deletable entities (no version, no updated_at)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["display_name"], str)
    assert isinstance(data["roles"], list) and len(data["roles"]) > 0
    assert all(r in ("SELLER", "BUYER") for r in data["roles"])
    assert isinstance(data["fee_balance_cents"], int)
    assert isinstance(data["feedback_score"], int)
    assert data["standing"] in ("GOOD", "SUSPENDED")
    assert data["status"] in ("ACTIVE", "CLOSED")
    # Standing is derived from the fee balance (PRD §2.8).
    if data["fee_balance_cents"] <= FEE_SUSPEND_THRESHOLD_CENTS:
        assert data["standing"] == "GOOD", "standing must be GOOD at/below threshold"
    else:
        assert data["standing"] == "SUSPENDED", "standing must be SUSPENDED above threshold"


def assert_listing(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("seller_account_id", "")), "seller_account_id must be a UUID"
    assert isinstance(data["title"], str)
    assert data["format"] in ("AUCTION", "BUY_NOW", "HYBRID")
    assert data["status"] in (
        "DRAFT", "ACTIVE", "ENDED_MET", "ENDED_RESERVE_NOT_MET",
        "ENDED_NO_BIDS", "SOLD", "CANCELLED",
    )
    assert isinstance(data["bid_count"], int) and data["bid_count"] >= 0
    assert isinstance(data["accepts_offers"], bool)


def assert_bid(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert is_valid_uuid(data.get("bidder_account_id", "")), "bidder_account_id must be a UUID"
    assert isinstance(data["max_proxy_cents"], int)
    assert isinstance(data["current_price_cents"], int)
    assert data["current_price_cents"] <= data["max_proxy_cents"], (
        "a bid is never committed above its max_proxy_cents"
    )
    assert isinstance(data["is_winning"], bool)
    assert data["status"] in ("ACCEPTED", "OUTBID", "RETRACTED")


def assert_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert is_valid_uuid(data.get("buyer_account_id", "")), "buyer_account_id must be a UUID"
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["round_no"], int) and data["round_no"] >= 1
    assert data["last_actor"] in ("BUYER", "SELLER")
    assert data["status"] in (
        "PENDING", "COUNTERED", "ACCEPTED", "DECLINED", "EXPIRED", "WITHDRAWN",
    )


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert is_valid_uuid(data.get("buyer_account_id", "")), "buyer_account_id must be a UUID"
    assert is_valid_uuid(data.get("seller_account_id", "")), "seller_account_id must be a UUID"
    assert data["source"] in ("AUCTION_WIN", "BUY_NOW", "OFFER_ACCEPT")
    assert isinstance(data["item_price_cents"], int)
    assert isinstance(data["shipping_cents"], int)
    assert isinstance(data["total_cents"], int)
    # total = item + shipping (PRD §3.6).
    assert data["total_cents"] == data["item_price_cents"] + data["shipping_cents"], (
        "total_cents must equal item_price_cents + shipping_cents"
    )
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED", "PARTIALLY_REFUNDED")
    assert data["fulfillment_status"] in (
        "AWAITING_PAYMENT", "READY_TO_SHIP", "SHIPPED", "DELIVERED", "RETURNED", "CANCELLED",
    )
    assert isinstance(data["paid_amount_cents"], int)
    assert data["paid_amount_cents"] >= 0, "paid_amount_cents is a conserved non-negative quantity"


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("seller_account_id", "")), "seller_account_id must be a UUID"
    assert isinstance(data["gross_item_cents"], int)
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["settlement_status"] in ("INVOICED", "PAID", "CREDITED")


def assert_dispute(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("opener_account_id", "")), "opener_account_id must be a UUID"
    assert data["reason"] in ("ITEM_NOT_RECEIVED", "NOT_AS_DESCRIBED", "DAMAGED")
    assert isinstance(data["requested_amount_cents"], int)
    assert isinstance(data["resolved_amount_cents"], int)
    assert data["status"] in (
        "OPEN", "SELLER_RESPONDED", "ESCALATED",
        "RESOLVED_REFUND", "RESOLVED_NO_REFUND", "CLOSED",
    )


def assert_watch(data: dict):
    _assert_light(data)
    assert is_valid_uuid(data.get("listing_id", "")), "listing_id must be a UUID"
    assert is_valid_uuid(data.get("watcher_account_id", "")), "watcher_account_id must be a UUID"
    assert isinstance(data["active"], bool)
    assert "version" not in data, "Watch is append-only/soft-delete; it has no version"
    assert "updated_at" not in data, "Watch has no updated_at"


def assert_payment(data: dict):
    _assert_light(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert data["kind"] in ("CHARGE", "REFUND")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 1
    assert "version" not in data, "Payment is an append-only event; it has no version"
    assert "updated_at" not in data, "Payment has no updated_at"


def assert_feedback(data: dict):
    _assert_light(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("rater_account_id", "")), "rater_account_id must be a UUID"
    assert is_valid_uuid(data.get("ratee_account_id", "")), "ratee_account_id must be a UUID"
    assert data["role"] in ("BUYER", "SELLER")
    assert data["rating"] in ("POSITIVE", "NEUTRAL", "NEGATIVE")
    assert "version" not in data, "Feedback is immutable; it has no version"
    assert "updated_at" not in data, "Feedback has no updated_at"
