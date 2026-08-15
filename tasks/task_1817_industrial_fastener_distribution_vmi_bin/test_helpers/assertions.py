"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Standard system-managed fields carried by every primary resource."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a prefix-free UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_site(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["ship_to_code"], str) and data["ship_to_code"]
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["credit_limit_cents"], int)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["delivery_mode"] in ("DOCK_TO_STOCK", "LINE_SIDE")


def assert_part(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["description"], str)
    assert data["status"] in ("ACTIVE", "OBSOLETE")
    assert isinstance(data["is_critical"], bool)
    assert isinstance(data["unit_price_cents"], int)
    assert data["unit_price_cents"] >= 1
    assert isinstance(data["total_stock_qty"], int)
    assert data["total_stock_qty"] >= 0
    assert isinstance(data["reserved_qty"], int)
    assert isinstance(data["available_qty"], int)


def assert_part_conservation(data: dict):
    """PRD §2.9: reserved_qty + available_qty always equals total_stock_qty."""
    assert data["reserved_qty"] + data["available_qty"] == data["total_stock_qty"], (
        f"conservation broken: reserved {data['reserved_qty']} + available "
        f"{data['available_qty']} != total {data['total_stock_qty']}"
    )


def assert_cross_reference(data: dict):
    """Cross-references carry id and created_at only — no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), (
        f"id must be a prefix-free UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, "cross-reference must not carry updated_at"
    assert "version" not in data, "cross-reference must not carry version"
    assert isinstance(data["from_part_id"], str)
    assert isinstance(data["to_part_id"], str)
    assert isinstance(data["priority_rank"], int) and data["priority_rank"] >= 1
    assert isinstance(data["is_active"], bool)


def assert_bin_agreement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["bin_location"], str)
    assert data["pricing_mode"] in ("UNIT_PRICE", "COST_PER_BIN")
    assert isinstance(data["flat_bin_price_cents"], int)
    assert data["flat_bin_price_cents"] >= 0
    assert isinstance(data["min_qty"], int) and data["min_qty"] >= 0
    assert isinstance(data["max_qty"], int) and data["max_qty"] >= 1
    assert data["min_qty"] < data["max_qty"]
    assert isinstance(data["on_hand_qty"], int)
    assert isinstance(data["open_order_qty"], int)
    assert data["status"] in ("ACTIVE", "AT_CAPACITY", "RETIRED")
    assert data["compliance_flag"] in ("CLEAR", "BLOCKED")


def assert_route(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert is_iso8601_timestamp(data["route_date"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "CLOSED", "CANCELLED")


def assert_route_stop(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["route_id"], str)
    assert isinstance(data["bin_agreement_id"], str)
    assert data["status"] in ("PENDING", "SUBMITTED")
    # counted_qty is recorded at submit time; generated_order_id is null unless
    # the count triggered an order.
    if data.get("counted_qty") is not None:
        assert isinstance(data["counted_qty"], int) and data["counted_qty"] >= 0
    assert "generated_order_id" in data
    if data["generated_order_id"] is not None:
        assert is_valid_uuid(data["generated_order_id"])


def assert_replenishment_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["bin_agreement_id"], str)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["ordered_qty"], int) and data["ordered_qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert data["unit_price_cents"] >= 0
    assert isinstance(data["total_price_cents"], int)
    assert data["total_price_cents"] >= 0
    assert data["status"] in (
        "DRAFT", "CONFIRMED", "ON_HOLD", "IN_TRANSIT",
        "DELIVERED", "DISPUTED", "CANCELLED",
    )
    # delivery_mode is pinned from the site at confirmation; before that it may
    # be absent or null, so only type-check when present.
    if data.get("delivery_mode") is not None:
        assert data["delivery_mode"] in ("DOCK_TO_STOCK", "LINE_SIDE")


def assert_lot_certificate(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["lot_number"], str) and data["lot_number"]
    assert is_iso8601_timestamp(data["cert_expires_at"])
    assert data["status"] in ("VALID", "EXPIRED")


def assert_kit_job(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["site_id"], str)
    assert isinstance(data["kit_name"], str)
    assert isinstance(data["component_part_ids"], list)
    assert 1 <= len(data["component_part_ids"]) <= 20
    assert isinstance(data["qty_per_part"], int) and data["qty_per_part"] >= 1
    assert isinstance(data["kit_count"], int) and data["kit_count"] >= 1
    assert is_iso8601_timestamp(data["station_window_start"])
    assert is_iso8601_timestamp(data["station_window_end"])
    assert data["status"] in (
        "DRAFT", "PICKING", "ON_HOLD", "PACKED", "COMPLETED", "SCRAPPED",
    )
    # packaging_cost_cents is computed at PACKED time; before that it is unset.
    if data.get("packaging_cost_cents") is not None:
        assert isinstance(data["packaging_cost_cents"], int)
        assert data["packaging_cost_cents"] >= 0
