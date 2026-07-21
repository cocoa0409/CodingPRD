"""Entity assertions and domain invariant checkers.

Only fields the PRD explicitly declares are asserted here. Every resource in
this system carries id, created_at, updated_at and version.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{label}.created_at must be an ISO 8601 timestamp"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{label}.updated_at must be an ISO 8601 timestamp"
    assert isinstance(data.get("version"), int), f"{label}.version must be an integer"
    assert data["version"] >= 1, f"{label}.version starts at 1"


def assert_gala_event(data: dict):
    _assert_common(data, "GalaEvent")
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ("DRAFT", "PUBLISHED", "LIVE", "SETTLING", "CLOSED")
    assert data["posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    for field in (
        "match_cap_cents",
        "match_awarded_cents",
        "gross_collected_cents",
        "open_lot_count",
        "unpaid_invoice_count",
    ):
        assert isinstance(data[field], int), f"GalaEvent.{field} must be an integer"
        assert data[field] >= 0, f"GalaEvent.{field} must never be negative"


def assert_ticket_table(data: dict):
    _assert_common(data, "TicketTable")
    assert isinstance(data["table_name"], str) and data["table_name"]
    assert data["seat_count"] >= 1
    assert data["table_price_cents"] >= 0
    assert data["seat_price_cents"] >= 0
    assert 0 <= data["seats_reserved"] <= data["seat_count"]
    assert data["status"] in ("AVAILABLE", "SOLD_OUT")


def assert_table_hold(data: dict):
    _assert_common(data, "TableHold")
    assert is_valid_uuid(data["table_id"])
    assert is_valid_uuid(data["bidder_id"])
    assert data["hold_end_utc"] > data["hold_start_utc"]
    assert data["status"] in ("HELD", "CONSUMED", "RELEASED")


def assert_ticket_order(data: dict):
    _assert_common(data, "TicketOrder")
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["bidder_id"])
    assert is_valid_uuid(data["table_id"])
    assert data["order_type"] in ("TABLE", "SEAT")
    assert data["seat_count"] >= 1
    assert data["unit_price_cents"] >= 0
    assert data["subtotal_cents"] >= 0
    assert data["benefit_value_cents"] >= 0
    assert isinstance(data["early_bird_applied"], bool)
    assert data["payment_status"] in ("UNBILLED", "INVOICED", "PAID", "REFUNDED")
    assert data["seating_status"] in ("UNSEATED", "SEATED", "RELEASED")


def assert_bidder(data: dict):
    _assert_common(data, "Bidder")
    assert is_valid_uuid(data["event_id"])
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["paddle_number"] >= 1
    assert isinstance(data["payment_method_on_file"], bool)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_sponsor(data: dict):
    _assert_common(data, "Sponsor")
    assert is_valid_uuid(data["event_id"])
    assert isinstance(data["org_name"], str) and data["org_name"]
    assert data["tier"] in ("GOLD", "SILVER", "BRONZE")
    assert data["commitment_cents"] >= 1
    assert data["paid_amount_cents"] >= 0
    assert data["placed_ad_count"] >= 0
    assert data["status"] in ("PENDING", "CONFIRMED", "WITHDRAWN")


def assert_program_ad(data: dict):
    _assert_common(data, "ProgramAd")
    assert is_valid_uuid(data["sponsor_id"])
    assert is_valid_uuid(data["event_id"])
    assert data["ad_size"] in ("FULL_PAGE", "HALF_PAGE", "QUARTER_PAGE")
    assert isinstance(data["artwork_ref"], str) and data["artwork_ref"]
    assert data["revision_count"] >= 0
    assert data["status"] in (
        "SUBMITTED",
        "IN_REVIEW",
        "CHANGES_REQUESTED",
        "APPROVED",
        "REJECTED",
        "PLACED",
    )


def assert_auction_item(data: dict):
    _assert_common(data, "AuctionItem")
    assert is_valid_uuid(data["event_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["item_type"] in ("SILENT", "LIVE")
    assert data["min_increment_cents"] >= 1
    assert data["close_at_utc"] > data["open_at_utc"]
    assert data["listing_status"] in ("DRAFT", "OPEN", "AWARDED", "PASSED")
    assert data["settlement_status"] in ("UNSETTLED", "INVOICED", "PAID")
    assert data["current_leading_amount_cents"] >= 0


def assert_bid(data: dict):
    _assert_common(data, "Bid")
    assert is_valid_uuid(data["item_id"])
    assert is_valid_uuid(data["bidder_id"])
    assert data["amount_cents"] >= 1
    assert data["proxy_max_cents"] >= 0
    assert data["status"] in ("ACTIVE", "WON", "LOST", "RETRACTED")
    assert_bid_effective_max(data)


def assert_bid_effective_max(data: dict):
    """A bid's effective_max_cents is the larger of its amount and its proxy."""
    expected = max(data["amount_cents"], data["proxy_max_cents"])
    assert data["effective_max_cents"] == expected, (
        f"effective_max_cents should be max(amount_cents, proxy_max_cents)="
        f"{expected}, got {data['effective_max_cents']}"
    )


def assert_paddle_raise(data: dict):
    _assert_common(data, "PaddleRaise")
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["bidder_id"])
    assert data["level_cents"] >= 1
    assert data["match_cents"] >= 0
    assert data["settlement_status"] in ("UNSETTLED", "INVOICED", "PAID")


def assert_pledge(data: dict):
    _assert_common(data, "Pledge")
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["bidder_id"])
    assert data["total_amount_cents"] >= 1
    assert data["installment_count"] >= 1
    assert data["received_amount_cents"] >= 0
    assert data["status"] in (
        "PROMISED",
        "PARTIALLY_FULFILLED",
        "FULFILLED",
        "LAPSED",
    )


def assert_checkout_invoice(data: dict):
    _assert_common(data, "CheckoutInvoice")
    assert is_valid_uuid(data["event_id"])
    assert is_valid_uuid(data["bidder_id"])
    assert isinstance(data["cover_processing_fee"], bool)
    assert isinstance(data["line_items"], list)
    for line in data["line_items"]:
        assert line["line_type"] in (
            "AUCTION_ITEM",
            "TICKET",
            "PADDLE_RAISE",
            "PROCESSING_FEE",
        )
        assert isinstance(line["amount_cents"], int)
    assert data["status"] in (
        "OPEN",
        "PENDING_PAYMENT",
        "PARTIALLY_PAID",
        "PAID",
        "VOID",
    )
    assert_invoice_totals_consistent(data)


def assert_invoice_totals_consistent(data: dict):
    """balance_due_cents is total_due_cents less amount_paid_cents, and the
    pre-fee subtotal excludes the PROCESSING_FEE line."""
    non_fee = sum(
        line["amount_cents"]
        for line in data["line_items"]
        if line["line_type"] != "PROCESSING_FEE"
    )
    assert data["line_subtotal_cents"] == non_fee, (
        f"line_subtotal_cents should sum every line except PROCESSING_FEE "
        f"({non_fee}), got {data['line_subtotal_cents']}"
    )
    assert (
        data["balance_due_cents"] == data["total_due_cents"] - data["amount_paid_cents"]
    ), "balance_due_cents must equal total_due_cents less amount_paid_cents"


def assert_payment_transaction(data: dict):
    _assert_common(data, "PaymentTransaction")
    assert is_valid_uuid(data["invoice_id"])
    assert data["amount_cents"] >= 1
    assert data["method"] in ("CARD", "CASH", "CHECK")
    assert data["status"] in ("CAPTURED", "VOIDED")
    assert isinstance(data["captured_by_user_id"], str) and data["captured_by_user_id"]


def assert_receipt(data: dict):
    _assert_common(data, "Receipt")
    assert is_valid_uuid(data["invoice_id"])
    assert is_valid_uuid(data["bidder_id"])
    assert is_iso8601_timestamp(data["issued_at_utc"])
    assert data["total_paid_cents"] >= 0
    assert data["benefit_value_cents"] >= 0
    assert data["tax_deductible_cents"] >= 0


def assert_reconciliation_run(data: dict):
    _assert_common(data, "ReconciliationRun")
    assert is_valid_uuid(data["event_id"])
    assert data["revenue_basis"] in ("BOOKED", "CASH_BASIS")
    assert isinstance(data["prepared_by_user_id"], str) and data["prepared_by_user_id"]
    assert data["status"] in ("PREPARED", "FINALIZED", "SUPERSEDED")
    assert isinstance(data["is_material_variance"], bool)
    assert_channel_breakdown(data)
    assert (
        data["variance_cents"]
        == data["expected_total_cents"] - data["collected_total_cents"]
    ), "variance_cents must equal expected_total_cents less collected_total_cents"


def assert_channel_breakdown(data: dict):
    """channel_breakdown carries the five channels in fixed order and sums to
    expected_total_cents."""
    breakdown = data["channel_breakdown"]
    assert [entry["channel"] for entry in breakdown] == [
        "TICKETS",
        "AUCTION",
        "PADDLE",
        "PLEDGE",
        "SPONSORSHIP",
    ], f"channel_breakdown order is fixed, got {breakdown}"
    total = sum(entry["expected_cents"] for entry in breakdown)
    assert total == data["expected_total_cents"], (
        f"channel_breakdown should sum to expected_total_cents "
        f"({data['expected_total_cents']}), got {total}"
    )


def channel_amount(data: dict, channel: str) -> int:
    """Pull one channel's expected_cents out of a run's channel_breakdown."""
    for entry in data["channel_breakdown"]:
        if entry["channel"] == channel:
            return entry["expected_cents"]
    raise AssertionError(f"channel {channel} missing from channel_breakdown")


def invoice_lines_of_type(data: dict, line_type: str) -> list:
    """Every line of the given line_type on an invoice."""
    return [line for line in data["line_items"] if line["line_type"] == line_type]
