"""Entity assertions and domain invariant checkers for the Auction House API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id/created_at/updated_at/version present per PRD §2.4."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_consignor(data: dict):
    _assert_common(data)
    assert isinstance(data["display_name"], str) and len(data["display_name"]) > 0
    assert data["payout_method"] in ("CHECK", "ACH", "STORE_CREDIT")


def assert_bidder(data: dict):
    _assert_common(data)
    assert isinstance(data["paddle_number"], str) and len(data["paddle_number"]) > 0
    assert isinstance(data["deposit_cents"], int) and data["deposit_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_auction(data: dict):
    _assert_common(data)
    assert data["sale_type"] in ("LIVE", "ONLINE", "TIMED")
    assert data["status"] in ("SCHEDULED", "OPEN", "CLOSED")


def assert_consignment(data: dict):
    _assert_common(data)
    assert 0 <= data["commission_rate"] < 1
    assert data["status"] in ("SUBMITTED", "APPRAISED", "ACCEPTED", "DECLINED")


def assert_lot(data: dict):
    _assert_common(data)
    assert data["sale_status"] in (
        "CATALOGED", "OPEN", "HAMMERED", "PASSED", "RESCINDED",
    )
    assert isinstance(data["current_high_bid_cents"], int)
    assert data["current_high_bid_cents"] >= 0


def assert_bid(data: dict):
    _assert_common(data)
    assert data["bid_type"] in ("ABSENTEE", "LIVE", "ONLINE")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in ("ACTIVE", "OUTBID", "WINNING", "RETRACTED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["payment_status"] in ("UNPAID", "PARTIALLY_PAID", "PAID")
    assert data["fulfillment_status"] in ("PENDING", "READY", "PICKED_UP", "SHIPPED")
    for f in (
        "hammer_subtotal_cents", "premium_subtotal_cents", "storage_fee_cents",
        "shipping_fee_cents", "total_due_cents", "amount_paid_cents",
        "total_refunded_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_invoice_line(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "VOID")
    for f in ("hammer_price_cents", "buyers_premium_cents", "line_total_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "APPROVED", "PAID")
    for f in (
        "gross_hammer_cents", "seller_commission_cents", "net_payout_cents", "lot_count",
    ):
        assert isinstance(data[f], int), f"{f} must be integer"


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "UNDER_REVIEW", "UPHELD", "REJECTED")
    assert isinstance(data["refund_cents"], int) and data["refund_cents"] >= 0


def assert_invoice_totals_consistent(data: dict):
    """total_due = hammer_subtotal + premium_subtotal + storage_fee + shipping_fee
    (PRD §3.5 / §3.6)."""
    expected = (
        data["hammer_subtotal_cents"]
        + data["premium_subtotal_cents"]
        + data["storage_fee_cents"]
        + data["shipping_fee_cents"]
    )
    assert data["total_due_cents"] == expected, (
        f"total_due {data['total_due_cents']} != components sum {expected}"
    )


def assert_line_total_consistent(data: dict):
    """line_total = hammer_price + buyers_premium (PRD §3.5)."""
    expected = data["hammer_price_cents"] + data["buyers_premium_cents"]
    assert data["line_total_cents"] == expected, (
        f"line_total {data['line_total_cents']} != {expected}"
    )
