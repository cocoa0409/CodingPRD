"""Entity assertions for the Greenhouse Nursery Grower API.

Each assert_{entity}() validates the structural invariants that hold on every
serialized instance of that entity. Value-specific assertions live in the tests.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

from .types import (
    VarietyStatus, ZoneStatus, ZoneFillState, BatchStatus, BrokerStatus,
    AvailabilityStatus, OrderStatus, OrderLineStatus, ShipmentStatus, PhytoStatus,
    PROPAGATION_FORMS, CLIMATE_CLASSES,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def _assert_mutable_common(data: dict):
    _assert_common(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an int"
    assert data["version"] >= 0, "version must be non-negative"


def assert_variety(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in [s.value for s in VarietyStatus]
    assert data["propagation_form"] in PROPAGATION_FORMS
    assert isinstance(data["cultivar_code"], str) and len(data["cultivar_code"]) > 0
    assert isinstance(data["grow_cycle_days"], int)
    assert isinstance(data["container_footprint_units"], int)
    assert isinstance(data["requires_phyto"], bool)


def assert_zone(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in [s.value for s in ZoneStatus]
    assert data["fill_state"] in [s.value for s in ZoneFillState]
    for f in ("capacity_units", "occupied_units", "reserved_units", "free_units"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["free_units"] == data["capacity_units"] - data["occupied_units"] - data["reserved_units"], \
        "free_units must equal capacity - occupied - reserved"


def assert_batch(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in [s.value for s in BatchStatus]
    assert isinstance(data["lot_code"], str) and len(data["lot_code"]) > 0
    for f in ("sourced_count", "started_count", "cull_count", "live_count",
              "shipped_count", "saleable_count"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_input_log(data: dict):
    # Append-only: id + created_at only; NO updated_at, NO version.
    _assert_common(data)
    assert "version" not in data, "InputLog must NOT carry a version field"
    assert "updated_at" not in data, "InputLog must NOT carry an updated_at field"
    assert data["event_type"] in ["CLIMATE", "IRRIGATION", "FERTILIZER", "SCOUTING", "GRADE"]


def assert_broker(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in [s.value for s in BrokerStatus]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["open_balance_cents"], int)


def assert_availability_entry(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in [s.value for s in AvailabilityStatus]
    for f in ("unit_price_cents", "published_quantity", "committed_quantity", "available_quantity"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["available_quantity"] == data["published_quantity"] - data["committed_quantity"], \
        "available_quantity must equal published - committed"


def assert_order(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in [s.value for s in OrderStatus]
    for f in ("order_subtotal_cents", "freight_cents", "order_total_cents"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_order_line(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in [s.value for s in OrderLineStatus]
    assert isinstance(data["quantity"], int)


def assert_shipment(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in [s.value for s in ShipmentStatus]


def assert_phyto_certificate(data: dict):
    _assert_mutable_common(data)
    assert data["status"] in [s.value for s in PhytoStatus]
