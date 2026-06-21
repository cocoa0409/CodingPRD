"""Entity assertions and domain invariant checkers for the Banquet Event Order API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_event(data: dict):
    """Validate an Event response structure against the PRD contract (§2.4, §3.2)."""
    assert is_valid_uuid(data.get("id", "")), "event id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["status"] in [
        "INQUIRY", "TENTATIVE", "DEFINITE", "CONFIRMED", "COMPLETED", "CANCELLED"
    ], f"unexpected event status {data.get('status')}"
    assert isinstance(data["account_name"], str) and len(data["account_name"]) > 0
    assert isinstance(data["expected_attendance"], int)
    # Computed money fields are integer cents per PRD §2.6.
    assert isinstance(data["estimated_total_cents"], int)
    assert isinstance(data["paid_to_date_cents"], int)
    assert isinstance(data["balance_due_cents"], int)


def assert_function_room(data: dict):
    assert is_valid_uuid(data.get("id", "")), "function room id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["max_capacity"], int) and data["max_capacity"] >= 1
    assert isinstance(data["hourly_rental_cents"], int) and data["hourly_rental_cents"] >= 0
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_hotel_room_block(data: dict):
    assert is_valid_uuid(data.get("id", "")), "block id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["total_rooms"], int) and data["total_rooms"] >= 1
    assert isinstance(data["rooms_committed"], int) and data["rooms_committed"] >= 0
    assert isinstance(data["rooms_available"], int) and data["rooms_available"] >= 0
    assert_block_inventory_conserved(data)


def assert_block_inventory_conserved(data: dict):
    """PRD §3.1 / §3.6: rooms_available == total_rooms - rooms_committed, never negative."""
    assert data["rooms_available"] >= 0, "rooms_available must never be negative"
    assert data["rooms_committed"] + data["rooms_available"] == data["total_rooms"], (
        f"committed {data['rooms_committed']} + available {data['rooms_available']} "
        f"must equal total {data['total_rooms']}"
    )


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "booking id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["hold_status"] in ["HOLD", "DEFINITE", "RELEASED"]
    assert isinstance(data["rental_charge_cents"], int) and data["rental_charge_cents"] >= 0


def assert_menu_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "menu line id must be a valid UUID"
    assert data["pricing_mode"] in ["PER_PERSON", "CONSUMPTION"]
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["extended_cents"], int) and data["extended_cents"] >= 0


def assert_service_line(data: dict):
    assert is_valid_uuid(data.get("id", "")), "service line id must be a valid UUID"
    assert data["category"] in ["AV", "LABOR", "RENTAL_ITEM"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["extended_cents"], int) and data["extended_cents"] >= 0


def assert_room_block_link(data: dict):
    assert is_valid_uuid(data.get("id", "")), "link id must be a valid UUID"
    assert data["link_status"] in ["RESERVED", "PICKED_UP", "RELEASED"]
    assert isinstance(data["rooms_reserved"], int) and data["rooms_reserved"] >= 1


def assert_payment_schedule_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "schedule item id must be a valid UUID"
    assert isinstance(data["sequence_no"], int) and data["sequence_no"] >= 1
    assert isinstance(data["amount_due_cents"], int) and data["amount_due_cents"] >= 1
    assert isinstance(data["allocated_cents"], int) and data["allocated_cents"] >= 0
    assert isinstance(data["settled"], bool)


def assert_payment(data: dict):
    """Payment is append-only (PRD §2.4): only id + created_at, no version / updated_at."""
    assert is_valid_uuid(data.get("id", "")), "payment id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["APPLIED", "VOIDED"]
    assert "version" not in data, "Payment must NOT expose a version field (append-only)"
    assert "updated_at" not in data, "Payment must NOT expose an updated_at field (append-only)"
