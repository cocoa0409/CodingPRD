"""Entity assertions and domain invariant checkers (PRD §2.4, §2.8, §2.9)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_fridge(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["location_label"], str)
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 1
    assert data["safety_posture"] in ("OPERATIONAL", "RESTRICTED", "QUARANTINED")
    assert isinstance(data["stock_slots_used"], int)
    assert isinstance(data["free_slots"], int)
    assert_fridge_invariants(data)


def assert_fridge_invariants(data: dict):
    """Ledger invariants that hold after any operation (PRD §2.8, §2.9)."""
    assert data["stock_slots_used"] + data["free_slots"] == data["capacity_slots"], (
        "slot conservation: stock_slots_used + free_slots must equal capacity_slots"
    )
    assert data["stock_slots_used"] >= 0 and data["free_slots"] >= 0
    assert (
        data["budget_granted_cents"]
        == data["budget_available_cents"] + data["budget_committed_cents"]
    ), "budget identity: granted == available + committed"


def assert_steward(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["email"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["missed_count"], int)


def assert_donor(data: dict):
    _assert_common(data)
    assert data["donor_type"] in ("RESTAURANT", "GROCER", "INDIVIDUAL")


def assert_grant(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CANCELLED")
    assert isinstance(data["amount_cents"], int)


def assert_shift(data: dict):
    _assert_common(data)
    assert data["kind"] in ("COVERAGE", "CLEANING")
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED")
    assert isinstance(data["reimbursement_amount_cents"], int)


def assert_offer(data: dict):
    _assert_common(data)
    assert data["status"] in ("OFFERED", "ACCEPTED", "CONVERTED", "EXPIRED")


def assert_batch(data: dict):
    _assert_common(data)
    assert data["food_category"] in (
        "PRODUCE", "BAKERY", "DAIRY", "PREPARED", "PACKAGED",
    )
    assert data["storage_type"] in ("COLD_CHAIN", "AMBIENT")
    assert data["status"] in (
        "STOCKED", "HELD", "RECALLED", "EXPIRED", "DISCARDED", "CLAIMED_OUT",
    )
    assert isinstance(data["slot_footprint"], int) and data["slot_footprint"] >= 1


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "VOIDED", "EXPIRED")


def assert_need(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "SUSPENDED", "EXPIRED")
