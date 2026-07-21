"""Per-resource assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

EVENT_STATUSES = ["DRAFT", "ONSALE", "PAUSED", "SALES_CLOSED", "COMPLETED", "CANCELLED"]
ORDER_PAYMENT_STATUSES = ["PENDING", "PAID", "REFUND_PENDING", "PARTIALLY_REFUNDED",
                          "REFUNDED"]
ORDER_FULFILLMENT_STATUSES = ["HELD", "ISSUED", "EXPIRED", "VOIDED",
                              "CHECKED_IN_PARTIAL", "CHECKED_IN_FULL"]
ATTENDEE_STATUSES = ["ISSUED", "CHECKED_IN", "TRANSFERRED", "VOIDED"]
REFUND_STATUSES = ["REQUESTED", "APPROVED", "REJECTED", "SETTLED"]
TRANSFER_STATUSES = ["DRAFT", "SENT", "ACCEPTED", "DECLINED", "EXPIRED"]
WAITLIST_STATUSES = ["WAITING", "OFFERED", "CLAIMED", "EXPIRED"]
PAYOUT_STATUSES = ["ACCRUING", "ELIGIBLE", "ON_HOLD", "APPROVED", "RELEASED"]


def assert_common_fields(data: dict, label: str = "resource"):
    """Every persisted resource carries a server-minted UUID id and an ISO 8601
    UTC created_at."""
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID string"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"{label}.created_at must be an ISO 8601 UTC timestamp"


def assert_versioned_fields(data: dict, label: str = "resource"):
    """Most resources additionally carry updated_at and an integer version."""
    assert_common_fields(data, label)
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"{label}.updated_at must be an ISO 8601 UTC timestamp"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"{label}.version must be an integer starting at 1"


def assert_three_fractional_digits(value: str, label: str = "timestamp"):
    """Timestamps are ISO 8601 UTC with exactly three fractional digits."""
    assert isinstance(value, str) and "." in value, \
        f"{label} must carry fractional seconds, got {value!r}"
    fraction = value.split(".")[1].rstrip("Z")
    assert len(fraction) == 3, \
        f"{label} must carry exactly three fractional digits, got {value!r}"


def assert_organizer(data: dict):
    assert_versioned_fields(data, "organizer")
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert isinstance(data["contact_email"], str) and data["contact_email"]
    assert isinstance(data["lifetime_gross_cents"], int)
    assert isinstance(data["lifetime_refunds_cents"], int)


def assert_venue(data: dict):
    assert_versioned_fields(data, "venue")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["city"], str)
    assert isinstance(data["seated_capacity"], int) and data["seated_capacity"] >= 1


def assert_buyer(data: dict):
    assert_versioned_fields(data, "buyer")
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["display_name"], str)


def assert_event(data: dict):
    assert_versioned_fields(data, "event")
    assert data["status"] in EVENT_STATUSES, f"unexpected event status {data['status']}"
    assert data["fee_mode"] in ["PASS_ON", "ABSORB"]
    assert data["refund_policy"] in ["FEE_RETAINED", "FEE_INCLUDED"]
    for field in ("gross_cents", "refunds_cents", "issued_count", "checked_in_count"):
        assert isinstance(data[field], int), f"event.{field} must be an integer"
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])


def assert_ticket_type(data: dict):
    assert_versioned_fields(data, "ticket_type")
    assert isinstance(data["tier_rank"], int) and data["tier_rank"] >= 1
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["quantity_total"], int) and data["quantity_total"] >= 1
    assert data["seating_mode"] in ["GA", "RESERVED"]
    assert isinstance(data["sold_count"], int) and data["sold_count"] >= 0
    assert isinstance(data["held_count"], int) and data["held_count"] >= 0


def assert_seat_block(data: dict):
    assert_versioned_fields(data, "seat_block")
    assert isinstance(data["seat_from"], int) and data["seat_from"] >= 1
    assert isinstance(data["seat_to"], int) and data["seat_to"] >= data["seat_from"]
    assert data["seats_total"] == data["seat_to"] - data["seat_from"] + 1, \
        "seats_total must equal seat_to - seat_from + 1"
    assert 0 <= data["seats_taken"] <= data["seats_total"], \
        "seats_taken must stay within the block"


def assert_promo_code(data: dict):
    assert_versioned_fields(data, "promo_code")
    assert data["kind"] in ["PERCENT", "FIXED"]
    assert 0 <= data["percent_bp"] <= 10000
    assert data["amount_cents"] >= 0
    assert data["max_uses"] >= 1
    assert data["uses_count"] >= 0


def assert_order(data: dict):
    assert_versioned_fields(data, "order")
    assert data["payment_status"] in ORDER_PAYMENT_STATUSES
    assert data["fulfillment_status"] in ORDER_FULFILLMENT_STATUSES
    for field in ("subtotal_cents", "discount_cents", "fee_total_cents",
                  "buyer_total_cents", "organizer_gross_cents", "refunded_cents"):
        assert isinstance(data[field], int), f"order.{field} must be integer cents"
    assert data["discount_cents"] <= data["subtotal_cents"], \
        "a discount can never exceed the goods"


def assert_order_item(data: dict):
    assert_versioned_fields(data, "order_item")
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["line_face_cents"] == data["unit_price_cents"] * data["quantity"], \
        "line_face_cents must be unit_price_cents multiplied by quantity"
    assert data["line_fee_cents"] == data["per_ticket_fee_cents"] * data["quantity"], \
        "line_fee_cents must be the rounded per-ticket fee multiplied by quantity"


def assert_attendee(data: dict):
    assert_versioned_fields(data, "attendee")
    assert data["status"] in ATTENDEE_STATUSES
    assert isinstance(data["holder_email"], str) and data["holder_email"]


def assert_scan_record(data: dict):
    """The scan record is append-only: id and created_at only."""
    assert_common_fields(data, "scan_record")
    assert "updated_at" not in data, \
        "the scan record has no updated_at because it is never modified"
    assert "version" not in data, \
        "the scan record has no version because it is never modified"
    assert is_iso8601_timestamp(data["scanned_at"])
    assert isinstance(data["scanned_by_user_id"], str) and data["scanned_by_user_id"]
    assert isinstance(data["gate_code"], str) and data["gate_code"]


def assert_refund_request(data: dict):
    assert_versioned_fields(data, "refund_request")
    assert data["status"] in REFUND_STATUSES
    assert data["policy"] in ["FEE_RETAINED", "FEE_INCLUDED"]
    for field in ("refund_amount_cents", "platform_retained_cents",
                  "organizer_charged_cents"):
        assert isinstance(data[field], int), f"refund_request.{field} must be integer cents"


def assert_transfer_request(data: dict):
    assert_versioned_fields(data, "transfer_request")
    assert data["status"] in TRANSFER_STATUSES
    assert isinstance(data["resend_count"], int) and data["resend_count"] >= 0


def assert_waitlist_entry(data: dict):
    assert_versioned_fields(data, "waitlist_entry")
    assert data["status"] in WAITLIST_STATUSES
    assert 1 <= data["requested_quantity"] <= 10


def assert_payout(data: dict):
    assert_versioned_fields(data, "payout")
    assert data["status"] in PAYOUT_STATUSES
    for field in ("gross_cents", "refunds_cents", "platform_fee_cents",
                  "reserve_basis_cents", "reserve_cents", "net_amount_cents",
                  "reserve_released_cents"):
        assert isinstance(data[field], int), f"payout.{field} must be integer cents"
    assert 0 <= data["reliability_score_snapshot"] <= 100, \
        "the reliability snapshot is an integer between 0 and 100"
    assert data["reserve_cents"] >= 0, "the withheld reserve is never negative"
    assert data["net_amount_cents"] == data["reserve_basis_cents"] - data["reserve_cents"], \
        "net_amount_cents must be reserve_basis_cents minus reserve_cents"


def assert_integer_cents(value, label: str = "amount"):
    assert isinstance(value, int), \
        f"{label} must be an integer number of cents, got {value!r}"


def assert_availability(ticket_type: dict, expected_available: int):
    """The available quantity is quantity_total minus sold minus held."""
    derived = (ticket_type["quantity_total"] - ticket_type["sold_count"]
               - ticket_type["held_count"])
    assert derived == expected_available, (
        f"Expected available {expected_available}, derived {derived} from "
        f"quantity_total={ticket_type['quantity_total']}, "
        f"sold_count={ticket_type['sold_count']}, held_count={ticket_type['held_count']}"
    )
