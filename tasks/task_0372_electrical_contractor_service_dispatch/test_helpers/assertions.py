"""Entity assertions and domain invariant checkers.

Use the framework's generic validators internally. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp,
)

_JOB_STATES = {"DRAFT", "QUOTED", "SCHEDULED", "IN_PROGRESS", "COMPLETED",
               "INVOICED", "CLOSED", "WARRANTY", "CANCELLED"}
_ESTIMATE_STATES = {"DRAFT", "SENT", "ACCEPTED", "REJECTED", "SUPERSEDED"}
_DISPATCH_STATES = {"ASSIGNED", "EN_ROUTE", "ON_SITE", "CLEARED", "CANCELLED"}
_PERMIT_STATES = {"APPLIED", "ISSUED", "INSPECTION_SCHEDULED", "PASSED", "FAILED"}
_CALLBACK_STATES = {"OPEN", "RESOLVED"}
_MEMBERSHIP_STATES = {"ACTIVE", "CANCELLED"}


def _assert_common(data: dict):
    """Common fields present on every entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["service_zip"], str)
    assert isinstance(data["phone"], str)


def assert_technician(data: dict):
    _assert_common(data)
    assert data["license_class"] in ("JOURNEYMAN", "MASTER")
    assert isinstance(data["service_zone"], str)
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["on_call"], bool)


def assert_membership_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("BASIC", "PREMIER")
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["labor_discount_pct"], (int, float))
    assert isinstance(data["waives_dispatch_fee"], bool)
    assert isinstance(data["priority_dispatch"], bool)


def assert_membership(data: dict):
    _assert_common(data)
    assert data["status"] in _MEMBERSHIP_STATES
    assert is_iso8601_timestamp(data.get("started_at", ""))


def assert_material_sku(data: dict):
    _assert_common(data)
    assert isinstance(data["sku_code"], str) and len(data["sku_code"]) > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["taxable"], bool)


def assert_truck_stock_item(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity_on_hand"], int)
    assert isinstance(data["reorder_threshold"], int)
    assert isinstance(data["low_stock"], bool)
    # Invariant: low_stock == (quantity_on_hand <= reorder_threshold) — PRD §3.2.
    assert data["low_stock"] == (data["quantity_on_hand"] <= data["reorder_threshold"]), \
        "low_stock must equal quantity_on_hand <= reorder_threshold"
    # On-hand balance may never go negative (PRD §3.2).
    assert data["quantity_on_hand"] >= 0, "quantity_on_hand must never be negative"


def assert_service_job(data: dict):
    _assert_common(data)
    assert data["scope"] in ("OUTLET", "PANEL", "EV_CHARGER")
    assert data["job_class"] in ("SERVICE", "INSTALL")
    assert data["priority"] in ("STANDARD", "EMERGENCY")
    assert data["status"] in _JOB_STATES
    assert isinstance(data["requires_permit"], bool)
    assert isinstance(data["total_due_cents"], int)


def assert_estimate(data: dict):
    _assert_common(data)
    assert data["pricing_mode"] in ("FLAT_RATE", "TIME_MATERIALS")
    assert data["status"] in _ESTIMATE_STATES
    assert isinstance(data["quoted_total_cents"], int)


def assert_dispatch(data: dict):
    _assert_common(data)
    assert data["status"] in _DISPATCH_STATES
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert is_iso8601_timestamp(data.get("eta", ""))


def assert_permit(data: dict):
    _assert_common(data)
    assert data["status"] in _PERMIT_STATES
    assert isinstance(data["jurisdiction"], str)
    assert isinstance(data["permit_number"], str)


def assert_material_usage(data: dict):
    _assert_common(data)
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert isinstance(data["line_total_cents"], int)
    assert isinstance(data["voided"], bool)


def assert_invoice(data: dict):
    _assert_common(data)
    for f in ("labor_subtotal_cents", "material_subtotal_cents", "dispatch_fee_cents",
              "emergency_surcharge_cents", "discount_cents", "tax_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"


def assert_callback(data: dict):
    _assert_common(data)
    assert data["status"] in _CALLBACK_STATES
    assert isinstance(data["covered_by_warranty"], bool)


def assert_invoice_total_consistent(inv: dict):
    """Grand-total reconciliation (PRD §3.7 step 7):
    total = (labor - discount) + material + dispatch_fee + emergency + tax.
    """
    expected = (
        inv["labor_subtotal_cents"] - inv["discount_cents"]
        + inv["material_subtotal_cents"]
        + inv["dispatch_fee_cents"]
        + inv["emergency_surcharge_cents"]
        + inv["tax_cents"]
    )
    assert inv["total_cents"] == expected, (
        f"Invoice total {inv['total_cents']} != reconciled {expected}"
    )
