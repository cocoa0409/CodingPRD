"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_buyer(data: dict):
    _common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0


def assert_event(data: dict):
    _common(data)
    assert data["status"] in [
        "DRAFT", "ANNOUNCED", "PRESALE", "ONSALE", "POSTPONED", "CANCELED", "COMPLETED",
    ]
    for f in ("total_capacity", "seats_available", "seats_held", "seats_sold"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"
    assert isinstance(data["pct_sold"], (int, float))
    assert_seat_conservation(data)


def assert_seat_conservation(event: dict):
    """PRD Section 2.8 invariant: available + held + sold == total_capacity."""
    total = event["seats_available"] + event["seats_held"] + event["seats_sold"]
    assert total == event["total_capacity"], (
        f"seat conservation violated: {event['seats_available']} + {event['seats_held']} "
        f"+ {event['seats_sold']} != total_capacity {event['total_capacity']}"
    )


def assert_price_level(data: dict):
    _common(data)
    assert isinstance(data["base_face_value_cents"], int) and data["base_face_value_cents"] > 0
    assert isinstance(data["is_platinum"], bool)
    assert isinstance(data["dynamic_pricing_enabled"], bool)


def assert_seat(data: dict):
    _common(data)
    assert data["status"] in ["AVAILABLE", "HELD", "SOLD"]
    assert isinstance(data["current_face_value_cents"], int)


def assert_queue_token(data: dict):
    _common(data)
    assert data["status"] in ["WAITING", "ADMITTED", "EXPIRED"]
    assert isinstance(data["position"], int)


def assert_hold(data: dict):
    _common(data)
    assert data["status"] in ["ACTIVE", "CONVERTED", "RELEASED", "EXPIRED"]
    assert isinstance(data["seat_ids"], list) and len(data["seat_ids"]) > 0
    assert isinstance(data["face_subtotal_cents"], int)
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_order(data: dict):
    _common(data)
    assert data["status"] in ["PENDING", "PAID", "PARTIALLY_REFUNDED", "REFUNDED", "CANCELED"]
    assert data["delivery_method"] in ["MOBILE", "PRINT", "WILL_CALL"]
    for f in ("face_total_cents", "service_fee_cents", "order_total_cents",
              "paid_amount_cents", "refunded_amount_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"
    assert data["order_total_cents"] == data["face_total_cents"] + data["service_fee_cents"]


def assert_ticket(data: dict):
    _common(data)
    assert data["status"] in ["VALID", "REFUNDED", "VOID"]
    assert data["delivery_status"] in ["PENDING", "DELIVERED"]
    assert data["scan_status"] in ["UNSCANNED", "SCANNED"]
    assert isinstance(data["face_value_cents"], int)


def assert_transfer(data: dict):
    _common(data)
    assert data["status"] in ["INITIATED", "ACCEPTED", "DECLINED"]
    assert data["kind"] in ["GIFT", "RESALE"]


def assert_refund_request(data: dict):
    _common(data)
    assert data["status"] in ["REQUESTED", "COMPLETED", "REJECTED"]
    assert isinstance(data["amount_cents"], int)


def assert_settlement(data: dict):
    _common(data)
    assert data["status"] in ["PENDING", "FINALIZED"]
    for f in ("gross_face_cents", "net_to_promoter_cents", "service_fees_cents", "refunds_cents"):
        assert isinstance(data[f], int), f"{f} must be an integer number of cents"
