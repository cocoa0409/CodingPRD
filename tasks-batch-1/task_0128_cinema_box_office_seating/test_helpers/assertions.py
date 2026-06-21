"""Entity assertions and domain invariant checkers.

Built on the framework's generic validators (is_valid_uuid, is_iso8601_timestamp).
Each assert_{entity} checks structural shape; the invariant checkers enforce
domain-level rules that must hold after any operation.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _common_full(data: dict):
    """id + created_at + updated_at + version (full common-field entities)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _common_lean(data: dict):
    """id + created_at only (Distributor, Seat)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data or data.get("updated_at") is None, (
        "lean entity must not carry updated_at"
    )
    assert "version" not in data or data.get("version") is None, (
        "lean entity must not carry version"
    )


def assert_auditorium(data: dict):
    _common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1
    assert isinstance(data["turnaround_minutes"], int) and data["turnaround_minutes"] >= 0
    assert data["status"] == "ACTIVE"


def assert_film(data: dict):
    _common_full(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["runtime_minutes"], int) and data["runtime_minutes"] >= 1
    assert is_valid_uuid(data["distributor_id"])
    assert isinstance(data["split_schedule"], list) and len(data["split_schedule"]) > 0
    assert data["status"] in ("BOOKING", "RUNNING", "ENDED")


def assert_distributor(data: dict):
    _common_lean(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["minimum_guarantee_cents"], int) and data["minimum_guarantee_cents"] >= 0


def assert_showtime(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["auditorium_id"])
    assert is_valid_uuid(data["film_id"])
    assert is_iso8601_timestamp(data["starts_at"])
    assert is_iso8601_timestamp(data["ends_at"])
    assert data["pricing_profile"] in ("STANDARD", "MATINEE", "PEAK")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert data["status"] in ("SCHEDULED", "ON_SALE", "CANCELLED", "CLOSED")
    assert data["rental_basis"] in ("BOX_OFFICE", "RENTAL")
    assert isinstance(data["private_rental_fee_cents"], int) and data["private_rental_fee_cents"] >= 0
    assert isinstance(data["seats_sold"], int) and data["seats_sold"] >= 0
    assert isinstance(data["seats_held"], int) and data["seats_held"] >= 0


def assert_seat(data: dict):
    _common_lean(data)
    assert is_valid_uuid(data["showtime_id"])
    assert isinstance(data["seat_number"], int) and data["seat_number"] >= 1
    assert data["seat_class"] in ("STANDARD", "PREMIUM", "ACCESSIBLE")
    assert data["occupancy"] in ("FREE", "HELD", "SOLD")


def assert_member(data: dict):
    _common_full(data)
    assert isinstance(data["email"], str)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["loyalty_points"], int)
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_combo(data: dict):
    _common_full(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert 0 <= data["member_discount_pct"] <= 1
    assert data["status"] == "AVAILABLE"


def assert_order(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["showtime_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["seat_ids"], list)
    assert data["status"] in ("HELD", "PAID", "EXCHANGED", "REFUNDED", "EXPIRED", "CANCELLED")


def assert_ticket(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["order_id"])
    assert is_valid_uuid(data["showtime_id"])
    assert is_valid_uuid(data["seat_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["state"] in ("HELD", "SOLD", "VOIDED")


def assert_payment(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["order_id"])
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["refunded_cents"], int) and data["refunded_cents"] >= 0
    assert data["status"] in ("CAPTURED", "REFUNDED")


def assert_settlement(data: dict):
    _common_full(data)
    assert is_valid_uuid(data["showtime_id"])
    assert is_valid_uuid(data["film_id"])
    assert is_valid_uuid(data["distributor_id"])
    assert isinstance(data["gross_receipts_cents"], int)
    assert isinstance(data["distributor_share_cents"], int)
    assert isinstance(data["house_share_cents"], int)


# --- Domain invariant checkers ---

def assert_seat_conservation(seats: list, seat_count: int):
    """Across a showtime's full seat map, FREE + HELD + SOLD == seat_count."""
    assert len(seats) == seat_count, f"expected {seat_count} seats, got {len(seats)}"
    free = sum(1 for s in seats if s["occupancy"] == "FREE")
    held = sum(1 for s in seats if s["occupancy"] == "HELD")
    sold = sum(1 for s in seats if s["occupancy"] == "SOLD")
    assert free + held + sold == seat_count, (
        f"seat occupancy must partition the map: FREE {free} + HELD {held} "
        f"+ SOLD {sold} != {seat_count}"
    )
