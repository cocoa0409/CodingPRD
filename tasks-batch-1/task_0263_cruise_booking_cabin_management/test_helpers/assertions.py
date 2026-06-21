"""Entity assertions and domain invariant checkers for the Cruise Booking API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an integer >= 1"


def assert_sailing(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "OPEN", "CLOSED", "SAILED", "CANCELLED"
    ], f"unexpected sailing status {data['status']}"
    assert isinstance(data["ship_name"], str) and len(data["ship_name"]) > 0
    assert isinstance(data["itinerary_code"], str) and len(data["itinerary_code"]) > 0
    assert isinstance(data["nights"], int) and data["nights"] >= 1
    assert isinstance(data["total_cabins"], int) and data["total_cabins"] >= 0
    assert isinstance(data["available_cabins"], int) and data["available_cabins"] >= 0


def assert_cabin_category(data: dict):
    _assert_common(data)
    assert data["code"] in ["INTERIOR", "OCEANVIEW", "BALCONY", "SUITE"]
    assert data["deck_high"] >= data["deck_low"]
    assert data["base_fare_per_guest_cents"] > 0
    assert 1 <= data["max_occupancy"] <= 4
    for f in ["total_cabins", "available_cabins", "held_cabins",
              "assigned_cabins", "blocked_cabins"]:
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_cabin(data: dict):
    _assert_common(data)
    assert data["status"] in ["AVAILABLE", "HELD", "ASSIGNED", "BLOCKED"]
    assert isinstance(data["cabin_number"], str) and len(data["cabin_number"]) > 0
    assert isinstance(data["deck"], int)


def assert_group_block(data: dict):
    _assert_common(data)
    assert data["status"] in ["NEGOTIATING", "HELD", "PARTIALLY_MATERIALIZED", "RELEASED"]
    assert data["block_size"] > 0
    assert 0.0 <= data["group_discount_pct"] <= 0.5
    assert isinstance(data["blocked_count"], int) and data["blocked_count"] >= 0
    assert isinstance(data["materialized_count"], int) and data["materialized_count"] >= 0


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "QUOTE", "DEPOSIT_HELD", "CONFIRMED", "EMBARKED",
        "COMPLETED", "CANCELLED", "EXPIRED"
    ], f"unexpected booking status {data['status']}"
    for f in ["guest_count", "fare_total_cents", "tax_port_total_cents",
              "booking_total_cents", "deposit_due_cents", "final_due_cents",
              "amount_paid_cents", "fcc_credit_cents", "cancel_refund_cents"]:
        assert isinstance(data[f], int), f"{f} must be an int"


def assert_guest(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert data["age"] >= 0
    assert data["occupancy_index"] >= 1
    for f in ["base_fare_cents", "final_fare_cents", "tax_port_cents"]:
        assert isinstance(data[f], int) and data[f] >= 0


def assert_add_on(data: dict):
    _assert_common(data)
    assert data["kind"] in ["DINING", "EXCURSION"]
    assert data["status"] in ["RESERVED", "CANCELLED"]
    assert data["price_cents"] >= 0


def assert_dining_reservation(data: dict):
    _assert_common(data)
    assert data["venue_code"] in ["MAIN", "SPECIALTY_A", "SPECIALTY_B"]
    assert data["status"] in ["BOOKED", "CANCELLED"]
    assert data["party_size"] >= 1


def assert_payment(data: dict):
    _assert_common(data)
    assert data["kind"] in ["DEPOSIT", "FINAL", "REFUND"]
    assert data["status"] in ["PENDING", "CAPTURED", "FAILED", "REFUNDED"]
    assert data["amount_cents"] > 0


def assert_folio(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "SETTLED", "VOID"]
    assert data["gratuity_mode"] in ["PROVISIONAL", "FINAL"]
    for f in ["charges_total_cents", "gratuity_total_cents", "balance_due_cents"]:
        assert isinstance(data[f], int)


def assert_folio_charge(data: dict):
    _assert_common(data)
    assert data["status"] in ["POSTED", "REVERSED"]
    assert data["amount_cents"] > 0


def assert_cabin_conservation(category: dict):
    """The cabin partition is conserved: the four status buckets sum to total."""
    total = category["total_cabins"]
    parts = (
        category["available_cabins"]
        + category["held_cabins"]
        + category["assigned_cabins"]
        + category["blocked_cabins"]
    )
    assert parts == total, (
        f"cabin conservation violated: "
        f"available+held+assigned+blocked={parts} != total_cabins={total}"
    )
