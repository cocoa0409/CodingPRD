"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_species(data: dict):
    _assert_common(data)
    assert isinstance(data["common_name"], str) and data["common_name"]
    assert isinstance(data["scientific_name"], str) and data["scientific_name"]
    assert isinstance(data["is_regulated"], bool)
    assert data["permit_class"] in ["NONE", "CLASS_I", "CLASS_II", "CLASS_III"]
    assert data["min_quarantine_days"] >= 0
    assert data["warranty_days"] >= 0
    assert data["care_feeder_type"] in ["CRICKET", "DUBIA", "MOUSE_PINKY", "MOUSE_ADULT", "RAT"]


def assert_animal(data: dict):
    _assert_common(data)
    assert data["status"] in ["INTAKE", "QUARANTINE", "AVAILABLE", "RESERVED", "SOLD", "DECEASED"]
    assert data["health_status"] in ["HEALTHY", "DECEASED"]
    assert data["sex"] in ["MALE", "FEMALE", "UNKNOWN"]
    assert data["acquisition_cost_cents"] >= 0
    assert data["list_price_cents"] >= 0


def assert_quarantine_record(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "CLEARED", "FAILED"]
    assert isinstance(data["health_checks"], list)
    assert data["passed_checks_count"] >= 0


def assert_customer(data: dict):
    _assert_common(data)
    assert data["loyalty_tier"] in ["STANDARD", "SILVER", "GOLD"]
    assert data["wallet_credit_cents"] >= 0


def assert_permit(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING_VERIFICATION", "VERIFIED", "REVOKED"]
    assert data["permit_class"] in ["CLASS_I", "CLASS_II", "CLASS_III"]


def assert_sale(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "CONFIRMED", "FULFILLED", "REFUNDED", "VOIDED", "CLOSED"]


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED", "RESOLVED"]
    assert data["claim_type"] in ["DOA", "EARLY_DEATH"]


def assert_feeder_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ["AVAILABLE", "DEPLETED", "RECALLED"]
    assert data["quantity_on_hand"] >= 0


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "PAUSED", "HELD", "CANCELLED"]


def assert_shipment(data: dict):
    _assert_common(data)
    assert data["status"] in ["SHIPPED", "REVERSED"]
    assert isinstance(data["allocations"], list)


def assert_habitat_build(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "QUOTED", "DEPOSIT_PAID", "IN_PROGRESS", "CHANGE_REQUESTED", "DELIVERED", "CANCELLED"
    ]


def assert_expo(data: dict):
    _assert_common(data)
    assert data["status"] in ["SCHEDULED", "OPEN", "CLOSED", "CANCELLED"]


def assert_expo_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ASSIGNED", "ENDED", "CANCELLED"]


def assert_recall(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "CLOSED"]
