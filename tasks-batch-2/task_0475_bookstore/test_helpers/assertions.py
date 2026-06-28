"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_title(data: dict):
    _assert_common(data)
    assert isinstance(data["isbn13"], str) and len(data["isbn13"]) == 13
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["category"] in ("BOOK", "CAFE", "SIDELINE")
    assert isinstance(data["list_price_cents"], int) and data["list_price_cents"] >= 0
    assert isinstance(data["returnable"], bool)
    assert data["demand_flag"] in ("HIGH", "NORMAL")
    assert isinstance(data["pod_eligible"], bool)
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["reserved_qty"], int) and data["reserved_qty"] >= 0
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_stock_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["title_id"])
    assert data["source"] in ("DISTRIBUTOR", "BUYBACK", "CONSIGNMENT")
    assert isinstance(data["cost_cents"], int) and data["cost_cents"] >= 0
    assert data["state"] in ("AVAILABLE", "RESERVED", "SOLD", "RETURNED_TO_PUBLISHER")


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["tier"] in ("REGULAR", "GOLD")
    assert isinstance(data["store_credit_cents"], int) and data["store_credit_cents"] >= 0
    assert isinstance(data["loyalty_points"], int) and data["loyalty_points"] >= 0
    assert isinstance(data["is_local_author"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_credit_ledger_entry(data: dict):
    """Append-only ledger row: id + created_at only (no updated_at, no version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "CreditLedgerEntry must not carry updated_at"
    assert "version" not in data, "CreditLedgerEntry must not carry version"
    assert isinstance(data["delta_cents"], int)
    assert data["reason"] in ("BUYBACK", "REDEMPTION", "EVENT_REFUND", "ADJUSTMENT")


def assert_sales_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("OPEN", "RESERVED", "FULFILLED", "CANCELLED")
    assert isinstance(data["credit_redeemed_cents"], int) and data["credit_redeemed_cents"] >= 0


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["title_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_special_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["title_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["fulfillment_method"] in ("DISTRIBUTOR", "POD")
    assert data["state"] in ("DRAFT", "QUOTED", "CONFIRMED", "RECEIVED", "CANCELLED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_publisher_return(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["title_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["state"] in ("DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED")


def assert_author_event(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["title_id"])
    assert isinstance(data["name"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["tickets_sold"], int) and data["tickets_sold"] >= 0
    assert data["state"] in ("SCHEDULED", "CANCELLED")


def assert_event_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["price_paid_cents"], int) and data["price_paid_cents"] >= 0
    assert data["state"] in ("BOOKED", "CHECKED_IN", "REFUNDED")


def assert_buyback_transaction(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["state"] in ("PENDING", "OFFERED", "COMPLETED", "VOIDED")


def assert_buyback_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["buyback_id"])
    assert is_valid_uuid(data["title_id"])
    assert data["condition_grade"] in ("LIKE_NEW", "GOOD", "FAIR")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


def assert_consignment_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["author_member_id"])
    assert is_valid_uuid(data["title_id"])
    assert isinstance(data["units_sold_to_date"], int) and data["units_sold_to_date"] >= 0
    assert isinstance(data["total_payout_cents"], int) and data["total_payout_cents"] >= 0
    assert data["state"] in ("ACTIVE", "TERMINATED")


def assert_consignment_copy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"])
    assert isinstance(data["sale_price_cents"], int) and data["sale_price_cents"] >= 0
    assert data["state"] in ("ON_SHELF", "SOLD", "RETURNED_TO_AUTHOR")


# ---- Domain invariant checkers --------------------------------------------
def assert_store_credit_nonnegative(member: dict):
    """A member's store_credit_cents is never allowed to be negative (§2.8)."""
    assert member["store_credit_cents"] >= 0, "store_credit_cents must never be negative"
