"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)


def _assert_common_fields(data: dict):
    """id (UUID), created_at/updated_at (ISO 8601), version (int >= 1)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), f"version must be int, got {data.get('version')!r}"
    assert data["version"] >= 1, f"version must be >= 1, got {data['version']}"


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and 1 <= len(data["sku"]) <= 40
    assert isinstance(data["name"], str)
    assert data["container_type"] in ("BOTTLE", "KEG")
    assert data["container_volume_ml"] > 0
    assert data["empty_container_weight_g"] >= 0
    assert data["density_g_per_ml"] > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0
    assert isinstance(data["case_pack"], int) and data["case_pack"] >= 1
    assert data["status"] in ("ACTIVE", "ARCHIVED")
    assert isinstance(data["needs_reorder"], bool)
    assert data["on_hand_units"] >= 0, f"on_hand_units floored at 0, got {data['on_hand_units']}"


def assert_par_setting(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert data["par_level_units"] > 0
    assert data["reorder_point_units"] >= 0
    assert data["reorder_point_units"] <= data["par_level_units"]
    assert data["status"] in ("ACTIVE", "SUPERSEDED")


def assert_recipe(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["recipe_cost_cents"], int) and data["recipe_cost_cents"] >= 0
    assert data["status"] in ("DRAFT", "PUBLISHED", "RETIRED")


def assert_recipe_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["recipe_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["pour_ml"] > 0
    assert isinstance(data["line_cost_cents"], int) and data["line_cost_cents"] >= 0


def assert_menu_item(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["recipe_id"])
    assert isinstance(data["menu_price_cents"], int) and data["menu_price_cents"] > 0
    assert isinstance(data["units_sold"], int) and data["units_sold"] >= 0
    assert data["pour_cost_pct"] >= 0
    assert data["menu_class"] in ("UNCLASSIFIED", "STAR", "PLOWHORSE", "PUZZLE", "DOG")
    assert data["status"] in ("ACTIVE", "DELISTED")


def assert_count_session(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["label"], str)
    assert is_iso8601_timestamp(data["counted_at"])
    assert data["status"] in ("OPEN", "FINALIZED", "VOID")
    assert isinstance(data["total_variance_cost_cents"], int)


def assert_count_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["count_session_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["count_method"] in ("UNITS", "WEIGHT")
    assert isinstance(data["variance_cost_cents"], int)


def assert_purchase_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["vendor_name"], str)
    assert is_iso8601_timestamp(data["expected_at"])
    assert data["status"] in ("DRAFT", "SUBMITTED", "RECEIVED", "CLOSED", "CANCELLED")
    assert isinstance(data["ordered_total_cents"], int) and data["ordered_total_cents"] >= 0


def assert_po_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["purchase_order_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["ordered_qty"], int) and data["ordered_qty"] > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0


def assert_invoice(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["purchase_order_id"])
    assert isinstance(data["vendor_invoice_no"], str)
    assert isinstance(data["freight_cents"], int) and data["freight_cents"] >= 0
    assert data["status"] in ("DRAFT", "POSTED", "VOID")
    for f in ("subtotal_cents", "discount_cents", "tax_cents", "invoice_total_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"


def assert_invoice_line(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["invoice_id"])
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["received_qty"], int) and data["received_qty"] > 0
    assert isinstance(data["unit_cost_cents"], int) and data["unit_cost_cents"] >= 0


def assert_waste_log(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert data["reason"] in ("SPILL", "BREAKAGE", "EXPIRY", "OVERPOUR", "COMP")
    assert data["wasted_units"] > 0
    assert isinstance(data["waste_cost_cents"], int) and data["waste_cost_cents"] >= 0


def assert_keg_tap(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["product_id"])
    assert isinstance(data["draft_line_no"], int) and data["draft_line_no"] >= 1
    assert is_iso8601_timestamp(data["tapped_from"])
    assert is_iso8601_timestamp(data["tapped_until"])
