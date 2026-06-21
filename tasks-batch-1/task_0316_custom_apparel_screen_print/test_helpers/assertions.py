"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common versioned-resource fields (PRD §2.4): id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_shop(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["spoilage_pct"], (int, float))
    assert isinstance(data["rush_threshold_days"], int)
    assert isinstance(data["rush_surcharge_pct"], (int, float))


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["email"], str)
    assert isinstance(data["outstanding_deposit_cents"], int)
    assert isinstance(data["archived"], bool)


def assert_decoration_method(data: dict):
    _assert_common(data)
    assert data["method_type"] in ("SCREEN_PRINT", "EMBROIDERY")
    assert data["resource_kind"] in ("PRESS", "EMBROIDERY_STATION")


def assert_garment_style(data: dict):
    _assert_common(data)
    assert isinstance(data["sku_code"], str) and len(data["sku_code"]) > 0
    assert isinstance(data["blank_cost_cents"], int)
    assert isinstance(data["available_colors"], list)
    assert isinstance(data["available_sizes"], list)


def assert_blank_sku(data: dict):
    _assert_common(data)
    assert isinstance(data["total_stock_qty"], int)
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["reserved_qty"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in (
        "DRAFT", "CONFIRMED", "IN_PRODUCTION", "FULFILLED", "CANCELLED"
    )
    assert data["billing_status"] in ("UNBILLED", "INVOICED", "PAID")


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["line_qty"], int)
    assert isinstance(data["size_run"], dict)


def assert_art_proof(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "CHANGES_REQUESTED", "APPROVED", "VOID"
    )
    assert isinstance(data["revision_round"], int)


def assert_blank_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "CONSUMED", "RELEASED")
    assert isinstance(data["ordered_qty"], int)
    assert isinstance(data["reserved_qty"], int)


def assert_quote(data: dict):
    _assert_common(data)
    assert data["variant"] == "ESTIMATE"
    assert isinstance(data["blank_subtotal_cents"], int)
    assert isinstance(data["setup_subtotal_cents"], int)
    assert isinstance(data["decoration_subtotal_cents"], int)
    assert isinstance(data["rush_surcharge_cents"], int)
    assert isinstance(data["grand_total_cents"], int)


def assert_production_run(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "RUNNING", "COMPLETED", "ABORTED")


def assert_blank_conservation_invariant(sku: dict):
    """PRD §2.8: on_hand_qty + reserved_qty == total_stock_qty for every BlankSku
    (the ACTIVE-reservation form, where reserved_qty on the SKU sums its ACTIVE holds)."""
    assert sku["on_hand_qty"] + sku["reserved_qty"] == sku["total_stock_qty"], (
        f"Conservation invariant broken: on_hand {sku['on_hand_qty']} + "
        f"reserved {sku['reserved_qty']} != total {sku['total_stock_qty']}"
    )
