"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields (PRD §2.4): id, created_at, updated_at, version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1 and increments"


def assert_pool_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["currency"], str) and data["currency"]
    assert data["status"] in ("ACTIVE", "RETIRED")
    assert isinstance(data["equity_warn_threshold"], int)
    assert isinstance(data["voucher_expiry_days"], int)
    assert isinstance(data["audit_min_interval_days"], int)


def assert_asset_type(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str)
    assert isinstance(data["base_daily_rate_cents"], int) and data["base_daily_rate_cents"] >= 0
    assert isinstance(data["replacement_cost_cents"], int) and data["replacement_cost_cents"] >= 0
    assert isinstance(data["useful_life_days"], int) and data["useful_life_days"] >= 1
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["role_type"] in ("MANUFACTURER", "DISTRIBUTOR", "RETAILER")
    assert isinstance(data["credit_limit_cents"], int) and data["credit_limit_cents"] >= 0
    assert isinstance(data["outstanding_charge_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")


def assert_location(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be UUID"
    assert isinstance(data["name"], str)
    assert isinstance(data["physical_balance"], int)
    assert isinstance(data["equity_balance"], int)
    assert data["equity_status"] in ("BALANCED", "SHORT", "SURPLUS")
    assert data["status"] in ("OPEN", "CLOSED")


def assert_asset(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("asset_type_id", "")), "asset_type_id must be UUID"
    assert isinstance(data["serial"], str) and data["serial"]
    assert data["condition"] in (
        "AVAILABLE", "ON_HIRE", "IN_TRANSIT", "DAMAGED", "IN_REPAIR", "LOST"
    )
    # current_location_id is null while IN_TRANSIT or LOST (PRD §3.2).
    if data["condition"] in ("IN_TRANSIT", "LOST"):
        assert data["current_location_id"] is None, \
            "current_location_id must be null while IN_TRANSIT or LOST"


def assert_transfer_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("from_location_id", "")), "from_location_id UUID"
    assert is_valid_uuid(data.get("to_location_id", "")), "to_location_id UUID"
    assert data["kind"] in ("ISSUANCE", "RETURN", "TRANSFER")
    assert isinstance(data["asset_ids"], list)
    assert data["quantity"] == len(data["asset_ids"]), "quantity == len(asset_ids)"
    assert data["status"] in ("DRAFT", "DISPATCHED", "RECEIVED", "CANCELLED")


def assert_hire(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id UUID"
    assert is_valid_uuid(data.get("location_id", "")), "location_id UUID"
    assert is_valid_uuid(data.get("asset_type_id", "")), "asset_type_id UUID"
    assert isinstance(data["asset_ids"], list)
    assert isinstance(data["accrued_charge_cents"], int)
    assert data["lifecycle_status"] in ("OPEN", "CLOSED", "VOIDED")
    assert data["settlement_status"] in ("UNBILLED", "INVOICED", "SETTLED")


def assert_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id UUID"
    assert isinstance(data["counted_physical"], int) and data["counted_physical"] >= 0
    assert data["loss_basis"] in ("REPLACEMENT", "NET_BOOK")
    assert isinstance(data["declared_loss_qty"], int)
    assert isinstance(data["declared_loss_cents"], int)
    assert data["status"] in ("DRAFT", "FINALIZED", "VOIDED")


def assert_voucher(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("from_location_id", "")), "from_location_id UUID"
    assert is_valid_uuid(data.get("to_account_id", "")), "to_account_id UUID"
    assert is_valid_uuid(data.get("asset_type_id", "")), "asset_type_id UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ("OUTSTANDING", "REDEEMED", "EXPIRED", "CANCELLED")


def assert_collection_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id UUID"
    assert isinstance(data["asset_ids"], list)
    assert data["status"] in ("REQUESTED", "COLLECTED", "CLOSED", "CANCELLED")


def assert_repair_job(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("collection_request_id", "")), "collection_request_id UUID"
    assert isinstance(data["asset_ids"], list)
    assert isinstance(data["repair_cost_cents"], int) and data["repair_cost_cents"] >= 0
    assert data["status"] in ("OPEN", "COMPLETED", "SCRAPPED")


def assert_invoice(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id UUID"
    assert isinstance(data["subtotal_cents"], int)
    assert isinstance(data["credit_cents"], int)
    assert isinstance(data["total_cents"], int)
    assert isinstance(data["paid_cents"], int)
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID")


def assert_invoice_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("invoice_id", "")), "invoice_id UUID"
    assert data["kind"] in ("HIRE", "LOSS", "REPAIR", "CREDIT")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0


def assert_demand_forecast(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id UUID"
    assert is_valid_uuid(data.get("asset_type_id", "")), "asset_type_id UUID"
    assert isinstance(data["horizon_days"], int) and data["horizon_days"] >= 1
    assert isinstance(data["projected_demand"], int)
    assert isinstance(data["recommended_reposition"], int)
    assert data["status"] == "COMPUTED"
