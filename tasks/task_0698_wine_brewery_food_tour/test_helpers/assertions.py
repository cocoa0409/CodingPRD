"""Entity assertions and domain invariant checkers.

Each assert_{entity}(data) validates the system-managed common fields plus the
entity's own fields against the PRD's declared shapes.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """id, created_at, updated_at, version present and well-typed (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version must be >= 1, got {data['version']}"


def assert_tour_product(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["theme"] in ["WINE", "BREWERY", "FOOD", "MIXED"]
    assert isinstance(data["base_price_per_person_cents"], int)
    assert data["base_price_per_person_cents"] > 0
    assert 0.0 <= data["gratuity_pct"] <= 0.30
    assert data["charter_fee_cents"] >= 0
    assert isinstance(data["min_guest_age"], int)
    assert data["status"] in ["DRAFT", "PUBLISHED", "RETIRED"]


def assert_add_on(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tour_product_id"])
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["price_per_person_cents"] >= 0
    assert data["status"] == "ACTIVE"


def assert_vehicle(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str) and len(data["label"]) > 0
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] > 0
    assert data["status"] in ["AVAILABLE", "OUT_OF_SERVICE"]


def assert_partner_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["kind"] in ["WINERY", "BREWERY", "RESTAURANT"]
    assert 0.0 <= data["commission_pct"] <= 0.50
    assert data["tasting_cost_per_guest_cents"] >= 0
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_pickup_point(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["address"], str) and len(data["address"]) > 0
    assert data["status"] == "ACTIVE"


def assert_departure(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["tour_product_id"])
    assert is_valid_uuid(data["vehicle_id"])
    assert is_iso8601_timestamp(data["depart_at"])
    assert is_iso8601_timestamp(data["return_at"])
    assert isinstance(data["is_private_charter"], bool)
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] > 0
    assert isinstance(data["seats_taken"], int) and data["seats_taken"] >= 0
    assert isinstance(data["expected_headcount"], int) and data["expected_headcount"] >= 0
    assert data["status"] in [
        "SCHEDULED", "CONFIRMED", "DEPARTED", "COMPLETED",
        "CANCELLED_WEATHER", "CANCELLED_OPS",
    ]


def assert_stop(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["departure_id"])
    assert is_valid_uuid(data["partner_venue_id"])
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["dwell_minutes"], int) and data["dwell_minutes"] > 0
    assert isinstance(data["estimated_commission_cents"], int)
    assert isinstance(data["settled_commission_cents"], int)
    assert data["status"] in ["PLANNED", "VISITED"]


def assert_venue_confirmation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["stop_id"])
    assert is_valid_uuid(data["partner_venue_id"])
    assert isinstance(data["requested_headcount"], int)
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0
    assert data["status"] in [
        "REQUESTED", "CONFIRMED", "CHANGES_REQUESTED", "DECLINED", "RELEASED",
    ]


def assert_guest(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert is_iso8601_timestamp(data["birth_date"])
    assert isinstance(data["age_verified"], bool)
    assert isinstance(data["waiver_signed"], bool)


def assert_booking(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["departure_id"])
    assert is_valid_uuid(data["lead_guest_id"])
    assert is_valid_uuid(data["pickup_point_id"])
    assert isinstance(data["party_size"], int) and data["party_size"] > 0
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["gratuity_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["refund_cents"], int)
    assert data["status"] in [
        "DRAFT", "RESERVED", "PAID", "CHECKED_IN", "COMPLETED", "CANCELLED",
    ]
    assert data["payment_status"] in ["UNPAID", "CAPTURED", "REFUNDED"]


def assert_booking_quote(data: dict):
    """total_cents == subtotal_cents + gratuity_cents (PRD §3.7)."""
    assert data["total_cents"] == data["subtotal_cents"] + data["gratuity_cents"], (
        f"total_cents {data['total_cents']} != subtotal {data['subtotal_cents']} "
        f"+ gratuity {data['gratuity_cents']}"
    )
