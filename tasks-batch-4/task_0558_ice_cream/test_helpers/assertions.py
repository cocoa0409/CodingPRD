"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a non-prefixed UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_flavor(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["stock_status"] in ("IN_STOCK", "BELOW_PAR", "OUT_OF_STOCK")
    assert isinstance(data["total_available_ml"], int)
    assert data["total_available_ml"] >= 0
    assert isinstance(data["par_level_ml"], int)


def assert_size_option(data: dict):
    _assert_common(data)
    assert isinstance(data["scoop_count"], int) and data["scoop_count"] >= 1
    assert isinstance(data["base_price_cents"], int)


def assert_topping(data: dict):
    _assert_common(data)
    assert isinstance(data["price_cents"], int)


def assert_batch(data: dict):
    _assert_common(data)
    assert data["status"] in ("PREP", "AVAILABLE", "DEPLETED", "DISCARDED")
    for field in ("initial_volume_ml", "remaining_volume_ml", "reserved_volume_ml",
                  "committed_volume_ml", "wasted_volume_ml"):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_waste_event(data: dict):
    # WasteEvent is an append-only log: only id + created_at (no updated_at, no version).
    assert is_valid_uuid(data.get("id", "")), "id must be a non-prefixed UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["waste_type"] in ("MELT", "SPILLAGE", "TRIM_SHRINK", "EXPIRED_DISCARD")


def assert_loyalty_account(data: dict):
    _assert_common(data)
    for field in ("punches", "free_scoop_credits", "lifetime_scoops"):
        assert isinstance(data[field], int)


def assert_drawer(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert data["reconciliation_status"] in ("PENDING", "BALANCED", "OVER", "SHORT")


def assert_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "PAID", "VOID", "REFUNDED")
    for field in ("subtotal_cents", "tax_cents", "total_cents"):
        assert isinstance(data[field], int)


def assert_order_line(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "REMOVED", "COMMITTED")
    assert isinstance(data["scoops"], int)
    assert isinstance(data["line_price_cents"], int)
    assert isinstance(data["allergen_label"], list)


def assert_pre_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUOTED", "CONFIRMED", "IN_PRODUCTION", "FULFILLED", "CANCELLED")


def assert_catering_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("BOOKED", "SETTLED", "CANCELLED")
    assert isinstance(data["estimate_cents"], int)


def assert_batch_volume_conserved(batch: dict):
    """PRD 2.7 invariant: remaining = initial - committed - wasted."""
    assert batch["remaining_volume_ml"] == (
        batch["initial_volume_ml"] - batch["committed_volume_ml"] - batch["wasted_volume_ml"]
    ), (
        "batch volume invariant violated: "
        f"remaining={batch['remaining_volume_ml']} initial={batch['initial_volume_ml']} "
        f"committed={batch['committed_volume_ml']} wasted={batch['wasted_volume_ml']}"
    )
