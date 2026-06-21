"""Entity assertions and domain invariant checkers.

Each assert_{entity}() verifies the system-managed fields and value domains the
PRD guarantees on a returned resource. Field names are PRD-exact.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_versioned_common(data: dict):
    """id + created_at + updated_at + version for mutable, versioned resources (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_vehicle(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("AVAILABLE", "ON_DEAL", "SOLD", "RECON"), data.get("status")
    assert data["condition"] in ("NEW", "USED"), data.get("condition")
    assert isinstance(data["vin"], str)
    assert isinstance(data["list_price_cents"], int)


def assert_floor_plan_line(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("ACTIVE", "PAID_OFF", "SUPERSEDED", "REINSTATED"), data.get("status")
    assert isinstance(data["principal_cents"], int)
    assert isinstance(data["principal_outstanding_cents"], int)
    assert isinstance(data["curtailments_applied"], int)


def assert_customer(data: dict):
    _assert_versioned_common(data)
    assert data["credit_tier"] in ("TIER_A", "TIER_B", "TIER_C", "TIER_D")
    assert isinstance(data["drivers_license_valid"], bool)


def assert_trade_in(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("APPRAISED", "ACCEPTED", "RELEASED"), data.get("status")
    assert isinstance(data["gross_equity_cents"], int)


def assert_deal(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in (
        "DRAFT", "DESKING", "SUBMITTED_TO_LENDER", "APPROVED",
        "CONTRACTED", "FUNDED", "UNWOUND", "DEAD",
    ), data.get("status")
    assert data["deal_type"] in ("FINANCE", "CASH")
    for f in (
        "rebate_cents", "trade_allowance_cents", "trade_equity_cents",
        "total_tax_cents", "fi_products_total_cents", "amount_financed_cents",
        "front_gross_cents", "back_gross_cents",
    ):
        assert isinstance(data.get(f), int), f"{f} must be an integer, got {data.get(f)!r}"


def assert_lender_program(data: dict):
    _assert_versioned_common(data)
    assert data["tier"] in ("TIER_A", "TIER_B", "TIER_C", "TIER_D")
    assert isinstance(data["active"], bool)


def assert_finance_product(data: dict):
    _assert_versioned_common(data)
    assert isinstance(data["taxable"], bool)
    assert isinstance(data["max_retail_cents"], int)


def assert_deal_product(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("ACTIVE", "VOID"), data.get("status")
    assert isinstance(data["product_cost_cents"], int)


def assert_finance_contract(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("ACTIVE", "SUPERSEDED", "CANCELLED"), data.get("status")
    assert isinstance(data["sell_rate_bps"], int)
    assert isinstance(data["monthly_payment_cents"], int)
    assert isinstance(data["finance_reserve_cents"], int)


def assert_oem_incentive(data: dict):
    _assert_versioned_common(data)
    assert data["eligible_condition"] in ("NEW", "USED", "ANY")
    assert isinstance(data["active"], bool)


def assert_test_drive(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "CANCELLED"), data.get("status")


def assert_repair_order(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("OPEN", "CLOSED", "CANCELLED"), data.get("status")
    assert data["bay"] in ("BAY_1", "BAY_2", "BAY_3")
    assert isinstance(data["total_cents"], int)


def assert_title_registration(data: dict):
    _assert_versioned_common(data)
    assert data["status"] in ("PENDING", "SUBMITTED", "ACCEPTED", "REJECTED"), data.get("status")
    assert isinstance(data["resubmit_count"], int)


def assert_deal_jacket_document(data: dict):
    """Append-only, immutable: carries ONLY id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "immutable deal-jacket document must NOT carry version"
    assert "updated_at" not in data, "immutable deal-jacket document must NOT carry updated_at"
