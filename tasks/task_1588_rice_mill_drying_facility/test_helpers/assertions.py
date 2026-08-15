"""Entity assertions and domain invariant checkers (PRD §2.5, §2.9, §2.10)."""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common_fields(data: dict):
    """All twelve resource types carry id, created_at, updated_at, version (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be an int >= 1, got {data.get('version')!r}"
    )


def assert_season(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SETUP", "INTAKE_OPEN", "INTAKE_CLOSED", "SETTLEMENT_REVIEW", "SETTLED"]
    assert isinstance(data["name"], str)
    assert isinstance(data["spot_daily_cap"], int)


def assert_grower(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["farm_code"], str)
    assert isinstance(data["advance_outstanding_cents"], int)
    assert isinstance(data["cumulative_paid_cents"], int)


def assert_contract(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "PARTIALLY_FULFILLED", "FULFILLED", "CANCELLED", "DEFAULTED"]
    assert data["variety"] in ["LONG_GRAIN", "MEDIUM_GRAIN"]
    assert isinstance(data["delivery_count"], int)
    assert_cost_precision(float(data["fulfilled_cwt"]))


def assert_bin(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["AVAILABLE", "FUMIGATING", "AERATING"]
    assert data.get("variety_lock") in (None, "LONG_GRAIN", "MEDIUM_GRAIN")
    for key in ("capacity_cwt", "stock_cwt", "reserved_cwt", "available_cwt"):
        assert_cost_precision(float(data[key]))


def assert_lot(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["WEIGHED", "GRADED", "BINNED", "SETTLED", "REJECTED"]
    assert data["variety"] in ["LONG_GRAIN", "MEDIUM_GRAIN"]
    assert data["source"] in ["CONTRACT", "SPOT"]
    assert_cost_precision(float(data["net_wet_cwt"]))


def assert_drying_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["PLANNED", "COMPLETED", "CANCELLED"]


def assert_mill_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "IN_PROCESS", "COMPLETED", "VERIFIED", "VOIDED"]


def assert_packaging_run(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "COMPLETED", "CANCELLED"]
    assert data["line_id"] in ["LINE_1", "LINE_2"]


def assert_byproduct_order(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["OPEN", "RESERVED", "SHIPPED", "CANCELLED"]
    assert data["product"] in ["BRAN", "HULL", "BROKEN", "BREWERS"]


def assert_fumigation_event(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "AERATING", "CLEARED"]


def assert_hold(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["ACTIVE", "RELEASED"]
    assert data["target_type"] in ["BIN", "LOT"]


def assert_settlement(data: dict):
    _assert_common_fields(data)
    assert data["status"] in ["DRAFT", "PROVISIONAL_ISSUED", "APPROVED", "DISPUTED", "PAID"]
    assert isinstance(data["lot_ids"], list)


def assert_cwt(actual, expected, label="value"):
    """Compare a 2-decimal cwt quantity pinned by the PRD's half-up rounding rules."""
    assert float(actual) == pytest.approx(expected, abs=1e-6), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_bin_capacity_invariant(bin_data: dict):
    """PRD §2.9: available_cwt is always capacity minus stock minus reservation."""
    capacity = float(bin_data["capacity_cwt"])
    stock = float(bin_data["stock_cwt"])
    reserved = float(bin_data["reserved_cwt"])
    available = float(bin_data["available_cwt"])
    assert available == pytest.approx(capacity - stock - reserved, abs=1e-6), (
        f"bin capacity invariant violated: {available} != {capacity} - {stock} - {reserved}"
    )


def get_inventory_component(row: dict, component: str):
    """Read one ledger component (produced/consumed/reserved/shipped/available)
    from a per-product inventory row (PRD §2.10)."""
    if f"{component}_cwt" in row:
        return row[f"{component}_cwt"]
    return row[component]


def assert_inventory_row(
    row: dict,
    produced=None,
    consumed=None,
    reserved=None,
    shipped=None,
    available=None,
):
    """Pin the season-scoped per-product inventory ledger quantities (PRD §2.10)."""
    for component, expected in (
        ("produced", produced),
        ("consumed", consumed),
        ("reserved", reserved),
        ("shipped", shipped),
        ("available", available),
    ):
        if expected is not None:
            actual = get_inventory_component(row, component)
            assert float(actual) == pytest.approx(expected, abs=1e-6), (
                f"inventory {component}: expected {expected}, got {actual} (row {row})"
            )
