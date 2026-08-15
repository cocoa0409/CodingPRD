"""Entity assertions and domain invariant checkers.

Field-level shape checks only; behavioral rules are asserted in the tests.
Nullable event timestamps (PRD section 2.4) are checked for ISO 8601 shape
only when non-null.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, label: str):
    assert is_valid_uuid(data.get("id", "")), f"{label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int), f"{label}.version must be int"


def _assert_nullable_ts(data: dict, field: str, label: str):
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{label}.{field} must be null or ISO 8601, got {value!r}"
    )


def assert_product(data: dict):
    _assert_common(data, "Product")
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["product_kind"] in ["MODULE", "INVERTER", "RACKING", "BOS"]
    assert isinstance(data["manufacturer_name"], str)
    for f in ("wattage_w", "ac_output_w", "dc_input_max_w",
              "technology_generation", "list_price_cents"):
        assert isinstance(data[f], int), f"Product.{f} must be int"
    assert data["status"] in ["ACTIVE", "DISCONTINUED", "OBSOLETE"]


def assert_compatibility_rule(data: dict):
    _assert_common(data, "CompatibilityRule")
    assert is_valid_uuid(data["module_product_id"])
    assert is_valid_uuid(data["inverter_product_id"])
    assert isinstance(data["max_modules_per_inverter"], int)
    assert isinstance(data["min_modules_per_inverter"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    _assert_nullable_ts(data, "effective_to", "CompatibilityRule")
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_tariff_rate(data: dict):
    _assert_common(data, "TariffRate")
    assert isinstance(data["hts_code"], str) and data["hts_code"]
    assert isinstance(data["duty_rate_bp"], int)
    assert is_iso8601_timestamp(data["effective_from"])
    _assert_nullable_ts(data, "effective_to", "TariffRate")
    assert data["status"] in ["ACTIVE", "SUPERSEDED"]


def assert_installer(data: dict):
    _assert_common(data, "Installer")
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["license_number"], str)
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["progress_payment_pct_bp"], int)
    assert isinstance(data["payment_terms_days"], int)
    assert isinstance(data["credit_exposure_cents"], int)
    assert isinstance(data["credit_hold"], bool)
    assert data["status"] in ["ONBOARDING", "ACTIVE", "SUSPENDED", "TERMINATED"]


def assert_inventory_lot(data: dict):
    _assert_common(data, "InventoryLot")
    assert is_valid_uuid(data["product_id"])
    for f in ("qty_on_hand", "qty_allocated", "qty_available", "qty_quarantined"):
        assert isinstance(data[f], int), f"InventoryLot.{f} must be int"
    assert isinstance(data["unit_cost_cents_provisional"], int)
    assert data["unit_cost_cents_final"] is None or isinstance(
        data["unit_cost_cents_final"], int
    )
    _assert_nullable_ts(data, "received_at", "InventoryLot")
    _assert_nullable_ts(data, "stranded_at", "InventoryLot")
    assert data["status"] in [
        "IN_TRANSIT", "ON_HAND", "DEPLETED", "STRANDED", "WRITTEN_OFF",
    ]


def assert_container(data: dict):
    _assert_common(data, "Container")
    assert isinstance(data["container_number"], str) and data["container_number"]
    assert isinstance(data["bol_number"], str)
    assert isinstance(data["origin_port"], str)
    assert is_iso8601_timestamp(data["eta_utc"])
    _assert_nullable_ts(data, "actual_arrival_utc", "Container")
    assert isinstance(data["freight_cost_cents"], int)
    assert isinstance(data["insurance_cost_cents"], int)
    assert data["status"] in [
        "BOOKED", "IN_TRANSIT", "ARRIVED", "RECEIVED", "CLOSED", "CANCELLED",
    ]


def assert_container_line(data: dict):
    _assert_common(data, "ContainerLine")
    assert is_valid_uuid(data["container_id"])
    assert is_valid_uuid(data["inventory_lot_id"])
    assert is_valid_uuid(data["product_id"])
    for f in ("qty_booked", "qty_received", "qty_damaged",
              "declared_unit_value_cents"):
        assert isinstance(data[f], int), f"ContainerLine.{f} must be int"


def assert_project(data: dict):
    _assert_common(data, "Project")
    assert is_valid_uuid(data["installer_id"])
    assert isinstance(data["project_name"], str) and data["project_name"]
    assert isinstance(data["site_postal_code"], str)
    assert is_valid_uuid(data["module_product_id"])
    assert is_valid_uuid(data["inverter_product_id"])
    assert isinstance(data["module_qty"], int)
    assert isinstance(data["inverter_qty"], int)
    assert data["compatibility_rule_id"] is None or is_valid_uuid(
        data["compatibility_rule_id"]
    )
    _assert_nullable_ts(data, "design_locked_at", "Project")
    assert data["system_size_kw_dc"] is None or isinstance(
        data["system_size_kw_dc"], (int, float)
    )
    for f in ("allocated_value_cents", "invoiced_value_cents",
              "paid_value_cents"):
        assert isinstance(data[f], int), f"Project.{f} must be int"
    assert data["payment_status"] in [
        "UNBILLED", "PROGRESS_BILLED", "PTO_BILLED", "PAID_IN_FULL",
        "WRITTEN_OFF",
    ]
    assert data["fulfillment_status"] in [
        "DESIGN", "ALLOCATED", "PARTIALLY_SHIPPED", "SHIPPED", "COMPLETE",
        "CANCELLED",
    ]


def assert_allocation(data: dict):
    _assert_common(data, "Allocation")
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["inventory_lot_id"])
    assert isinstance(data["qty_allocated"], int)
    assert isinstance(data["unit_cost_cents_at_allocation"], int)
    assert is_iso8601_timestamp(data["allocated_at"])
    _assert_nullable_ts(data, "released_at", "Allocation")
    _assert_nullable_ts(data, "shipped_at", "Allocation")
    assert data["status"] in ["OPEN", "SHIPPED", "RELEASED", "CANCELLED"]


def assert_invoice(data: dict):
    _assert_common(data, "Invoice")
    assert is_valid_uuid(data["project_id"])
    assert is_valid_uuid(data["installer_id"])
    assert data["invoice_kind"] in ["PROGRESS", "PTO", "CREDIT_MEMO", "WRITE_OFF"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["balance_due_cents"], int)
    assert is_iso8601_timestamp(data["invoice_date"])
    assert is_iso8601_timestamp(data["due_date"])
    assert data["status"] in [
        "OPEN", "PARTIALLY_PAID", "PAID", "VOID", "PAST_DUE",
    ]


def assert_payment(data: dict):
    _assert_common(data, "Payment")
    assert is_valid_uuid(data["invoice_id"])
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data["posted_at"])
    _assert_nullable_ts(data, "reversed_at", "Payment")
    assert data["status"] in ["POSTED", "REVERSED"]


def assert_rma_claim(data: dict):
    _assert_common(data, "RmaClaim")
    assert is_valid_uuid(data["installer_id"])
    assert is_valid_uuid(data["product_id"])
    assert is_valid_uuid(data["allocation_id"])
    assert isinstance(data["qty_claimed"], int)
    assert data["manufacturer_rma_number"] is None or isinstance(
        data["manufacturer_rma_number"], str
    )
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "CREDIT_ISSUED", "CLOSED",
    ]


def assert_permit_package(data: dict):
    _assert_common(data, "PermitPackage")
    assert is_valid_uuid(data["project_id"])
    assert isinstance(data["ahj_code"], str)
    assert isinstance(data["required_documents"], list)
    assert isinstance(data["submitted_documents"], list)
    _assert_nullable_ts(data, "submitted_at", "PermitPackage")
    _assert_nullable_ts(data, "approved_at", "PermitPackage")
    assert data["status"] in [
        "ASSEMBLING", "SUBMITTED", "APPROVED", "REJECTED", "WITHDRAWN",
    ]


def assert_damage_claim(data: dict):
    _assert_common(data, "DamageClaim")
    assert is_valid_uuid(data["container_id"])
    assert is_valid_uuid(data["container_line_id"])
    assert isinstance(data["qty_damaged"], int)
    _assert_nullable_ts(data, "filed_at", "DamageClaim")
    _assert_nullable_ts(data, "settled_at", "DamageClaim")
    assert data["status"] in ["DRAFT", "FILED", "SETTLED", "DENIED"]


def assert_lot_invariants(data: dict):
    """qty_available == on_hand - allocated - quarantined, never negative
    (PRD section 3.3)."""
    assert_inventory_lot(data)
    expected = (
        data["qty_on_hand"] - data["qty_allocated"] - data["qty_quarantined"]
    )
    assert data["qty_available"] == expected, (
        f"qty_available {data['qty_available']} != "
        f"{data['qty_on_hand']} - {data['qty_allocated']} - "
        f"{data['qty_quarantined']}"
    )
    assert data["qty_available"] >= 0, "qty_available is never negative"
