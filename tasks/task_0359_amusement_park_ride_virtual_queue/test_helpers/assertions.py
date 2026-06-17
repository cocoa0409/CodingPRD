"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at its initial value and increments"


def assert_park(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["gate_capacity"], int) and data["gate_capacity"] >= 1
    assert isinstance(data["admitted_count"], int) and data["admitted_count"] >= 0
    assert data["day_phase"] in ("OPEN", "PEAK", "FULL")
    assert isinstance(data["operating_date"], str)


def assert_ride(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["hourly_throughput"], int) and data["hourly_throughput"] >= 1
    assert isinstance(data["min_height_cm"], int) and data["min_height_cm"] >= 0
    assert isinstance(data["wheelchair_transfer_required"], bool)
    assert isinstance(data["single_rider_enabled"], bool)
    assert data["operational_status"] in ("OPEN", "DOWN", "CLOSED")
    assert isinstance(data["booked_slot_count"], int) and data["booked_slot_count"] >= 0
    assert isinstance(data["posted_wait_minutes"], int) and data["posted_wait_minutes"] >= 0


def assert_return_window(data: dict):
    _assert_common(data)
    assert isinstance(data["slot_capacity"], int) and data["slot_capacity"] >= 0
    assert isinstance(data["reserved_count"], int) and data["reserved_count"] >= 0
    assert data["window_status"] in ("OPEN", "EXHAUSTED", "EXPIRED", "SUSPENDED")


def assert_guest(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["height_cm"], int) and data["height_cm"] >= 30
    assert isinstance(data["uses_wheelchair"], bool)
    assert data["party_id"] is None or is_valid_uuid(data["party_id"])


def assert_party(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["leader_guest_id"])
    assert isinstance(data["member_count"], int) and data["member_count"] >= 0
    assert data["party_status"] in ("FORMING", "LOCKED", "DISBANDED")


def assert_party_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["party_id"])
    assert is_valid_uuid(data["guest_id"])
    assert data["membership_status"] in ("LINKED", "REMOVED")


def assert_entitlement_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("MULTI_PASS", "SINGLE_PASS")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["max_concurrent_holds"], int) and data["max_concurrent_holds"] >= 1


def assert_day_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["guest_id"])
    assert data["admission_status"] in ("ISSUED", "ADMITTED", "EXITED")


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["ride_id"])
    assert is_valid_uuid(data["guest_id"])
    assert data["queue_type"] in ("VIRTUAL_QUEUE", "SINGLE_RIDER")
    assert data["reservation_status"] in (
        "HELD", "BOOKED", "REDEEMED", "FORFEITED", "REDISTRIBUTED",
    )


def assert_lightning_lane_purchase(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["guest_id"])
    assert is_valid_uuid(data["ride_id"])
    assert isinstance(data["charged_cents"], int) and data["charged_cents"] >= 0
    assert data["hold_status"] in ("ACTIVE", "CONSUMED", "REFUNDED")
