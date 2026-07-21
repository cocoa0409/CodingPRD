"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["club_tier"] in ["NONE", "SILVER", "GOLD"]
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["wallet_credit_cents"] >= 0, "wallet is a floor-zero resource"
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_species(data: dict):
    _assert_common(data)
    assert isinstance(data["common_name"], str)
    assert isinstance(data["scientific_name"], str)
    assert data["cites_appendix"] in ["I", "II", "III", "NONE"]
    assert isinstance(data["permit_required"], bool)
    assert data["status"] in ["ACTIVE", "RESTRICTED"]
    assert isinstance(data["listed_bird_count"], int)
    assert data["listed_bird_count"] >= 0


def assert_permit(data: dict):
    _assert_common(data)
    assert isinstance(data["species_id"], str)
    assert isinstance(data["permit_number"], str)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REVOKED", "EXPIRED"]


def assert_bird(data: dict):
    _assert_common(data)
    assert isinstance(data["species_id"], str)
    assert isinstance(data["band_code"], str)
    assert data["status"] in [
        "INTAKE", "IN_QUARANTINE", "CLEARED", "LISTED", "SOLD", "REJECTED", "SUSPENDED"
    ]


def assert_quarantine_record(data: dict):
    _assert_common(data)
    assert isinstance(data["bird_id"], str)
    assert isinstance(data["failed_test_count"], int)
    assert isinstance(data["retest_count"], int)
    assert data["status"] in ["OPEN", "UNDER_TEST", "CLEARED", "FAILED"]


def assert_cage(data: dict):
    _assert_common(data)
    assert data["cage_class"] in ["HOUSING", "BOARDING"]
    assert isinstance(data["capacity"], int)
    assert isinstance(data["current_occupancy"], int)
    assert data["current_occupancy"] >= 0
    assert data["status"] in ["AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE"]


def assert_reservation(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["cage_id"], str)
    assert data["status"] in ["RESERVED", "CHECKED_IN", "CHECKED_OUT", "CANCELLED"]


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data["service_types"], list)
    assert data["status"] in ["OPEN", "CLOSED"]


def assert_appointment(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["grooming_station_id"], str)
    assert data["service_type"] in ["WING_TRIM", "NAIL_TRIM"]
    assert data["status"] in ["BOOKED", "COMPLETED", "CANCELLED", "NO_SHOW"]


def assert_subscription(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert data["tier"] in ["STANDARD", "PREMIUM"]
    assert isinstance(data["bird_count"], int)
    assert isinstance(data["monthly_charge_cents"], int)
    assert data["status"] in ["ACTIVE", "PAUSED", "CANCELLED"]


def assert_inventory_item(data: dict):
    _assert_common(data)
    assert data["feed_kind"] in ["DRY", "FRESH"]
    assert isinstance(data["quantity_on_hand"], int)
    assert isinstance(data["quantity_allocated"], int)
    assert data["quantity_on_hand"] >= 0, "quantity_on_hand may never go negative"
    assert data["quantity_allocated"] >= 0, "quantity_allocated may never go negative"


def assert_special_order(data: dict):
    _assert_common(data)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["invoice_total_cents"], int)
    assert data["payment_status"] in ["UNPAID", "PAID", "REFUNDED"]
    assert data["build_status"] in ["QUEUED", "IN_BUILD", "BUILT", "DELIVERED", "CANCELLED"]


def assert_inventory_conserved(data: dict, expected_total: int):
    """PRD Section 2.9: quantity_on_hand + quantity_allocated is constant across
    every allocate/release pair (consume/deliver excepted)."""
    total = data["quantity_on_hand"] + data["quantity_allocated"]
    assert total == expected_total, (
        f"inventory conservation broken: on_hand {data['quantity_on_hand']} + "
        f"allocated {data['quantity_allocated']} = {total}, expected {expected_total}"
    )
