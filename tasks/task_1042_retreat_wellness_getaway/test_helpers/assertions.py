"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_retreat(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["DRAFT", "PUBLISHED", "FULL", "CANCELLED", "COMPLETED"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert isinstance(data["schedule_ready"], bool)
    assert data["reserved_count"] <= data["capacity"], "reserved_count must never exceed capacity"


def assert_room(data: dict):
    _assert_versioned(data)
    assert data["kind"] in ["LODGING", "COMMON"]
    assert isinstance(data["bed_count"], int) and data["bed_count"] >= 0
    assert isinstance(data["reserved_beds"], int) and data["reserved_beds"] >= 0
    assert data["reserved_beds"] <= data["bed_count"], "reserved_beds must never exceed bed_count"


def assert_guest(data: dict):
    _assert_versioned(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0


def assert_facilitator(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["ACTIVE", "WITHDRAWN"]
    assert isinstance(data["payout_cents"], int) and data["payout_cents"] >= 0


def assert_booking(data: dict):
    _assert_versioned(data)
    assert data["status"] in [
        "PENDING_DEPOSIT", "DEPOSIT_PAID", "CONFIRMED", "CHECKED_IN", "CANCELLED", "COMPLETED"
    ]
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    for field in ["subtotal_cents", "discount_cents", "special_diet_surcharge_cents",
                  "total_cents", "tax_cents", "grand_total_cents", "deposit_cents",
                  "balance_due_cents", "amount_paid_cents", "refund_cents"]:
        assert isinstance(data[field], int), f"{field} must be int"
    assert data["balance_due_cents"] == data["grand_total_cents"] - data["deposit_cents"]


def assert_waiver(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["PENDING", "SIGNED", "CLEARED", "REJECTED"]


def assert_activity_slot(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["SCHEDULED", "CANCELLED", "COMPLETED"]


def assert_shuttle(data: dict):
    _assert_versioned(data)
    assert data["direction"] in ["ARRIVAL", "DEPARTURE"]
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["reserved_seats"], int) and data["reserved_seats"] >= 0
    assert data["reserved_seats"] <= data["seat_capacity"], "reserved_seats must never exceed seat_capacity"


def assert_transport_segment(data: dict):
    _assert_versioned(data)
    assert data["status"] in ["BOOKED", "CANCELLED", "COMPLETED"]
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 0


def assert_payment(data: dict):
    _assert_common(data)
    assert data["type"] in ["DEPOSIT", "BALANCE", "REFUND"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_addon(data: dict):
    _assert_common(data)
    assert data["category"] in ["SPA", "EXCURSION", "MEAL", "GEAR"]
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0


def assert_booking_addon(data: dict):
    _assert_common(data)
    assert isinstance(data["price_cents_snapshot"], int) and data["price_cents_snapshot"] >= 0
