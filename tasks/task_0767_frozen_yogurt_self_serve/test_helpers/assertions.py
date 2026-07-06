"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_versioned(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_machine(data: dict):
    _assert_versioned(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["sanitation_status"] in ("READY", "CLEANING", "OUT_OF_SERVICE")
    assert isinstance(data["mix_par_oz"], (int, float))
    assert isinstance(data["current_mix_level_oz"], (int, float))


def assert_flavor(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("LOADED", "SUSPENDED", "ROTATED_OUT")
    assert isinstance(data["price_per_oz_cents"], int)
    assert isinstance(data["cost_per_oz_cents"], int)


def assert_topping(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("AVAILABLE", "ROTATED_OUT")
    assert isinstance(data["on_hand_units"], int)
    assert isinstance(data["surcharge_cents"], int)


def assert_loyalty(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["points_provisional"], int)
    assert isinstance(data["points_lifetime"], int)
    assert isinstance(data["punch_count"], int)


def assert_voucher(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("ISSUED", "REDEEMED", "EXPIRED")
    assert isinstance(data["value_cents"], int)


def assert_ticket(data: dict):
    _assert_versioned(data)
    assert data["payment_status"] in ("OPEN", "CHARGED", "VOIDED")
    assert data["reconciliation_status"] in ("UNRECONCILED", "RECONCILED")


def assert_sale_line(data: dict):
    """SaleLine is append-only: id + created_at only, no updated_at/version."""
    _assert_common(data)
    assert "updated_at" not in data, "SaleLine must not carry updated_at"
    assert "version" not in data, "SaleLine must not carry version"
    assert isinstance(data["net_weight_oz"], (int, float))


def assert_waste_event(data: dict):
    """WasteEvent is immutable: id + created_at only."""
    _assert_common(data)
    assert "updated_at" not in data, "WasteEvent must not carry updated_at"
    assert "version" not in data, "WasteEvent must not carry version"
    assert isinstance(data["cogs_value_cents"], int)
    assert isinstance(data["retail_value_cents"], int)


def assert_sanitation_log(data: dict):
    """SanitationLog is append-only: id + created_at only."""
    _assert_common(data)
    assert "updated_at" not in data, "SanitationLog must not carry updated_at"
    assert "version" not in data, "SanitationLog must not carry version"


def assert_catering_order(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("DRAFT", "QUOTED", "CONFIRMED", "FULFILLED", "CANCELLED")


def assert_reconciliation(data: dict):
    _assert_versioned(data)
    assert data["status"] in ("OPEN", "CLOSED")
