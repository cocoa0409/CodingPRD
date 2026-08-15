"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

_POSTURES = ["NORMAL", "CONSTRAINED", "FROZEN"]
_TIERS = ["PRO", "ELITE", "PREMIER"]
_BRANCH_STATUS = ["OPEN", "CLOSED_SEASON"]
_ACCOUNT_STATUS = ["ACTIVE", "SUSPENDED"]
_ACCOUNT_TYPES = ["DEALER", "SERVICE_CO"]
_PRODUCT_FAMILIES = ["CHEMICAL", "EQUIPMENT", "PARTS"]
_HAZMAT_CLASSES = ["NONE", "OXIDIZER_5_1", "CORROSIVE_8"]
_PROGRAM_STATUS = ["DRAFT", "OPEN", "CLOSED"]
_COMMITMENT_STATUS = ["COMMITTED", "FULFILLED", "DEFAULTED", "SUPERSEDED"]
_CHANNELS = ["WILL_CALL", "ROUTE_DELIVERY"]
_FULFILLMENT = ["DRAFT", "CONFIRMED", "PICKED_LOADED", "COMPLETED", "CANCELLED"]
_PAYMENT = ["UNINVOICED", "INVOICED", "PAID"]
_BACKORDER_STATUS = ["OPEN", "ALLOCATED", "CLOSED", "CANCELLED"]
_CLAIM_STATUS = [
    "SUBMITTED", "UNDER_REVIEW", "MORE_INFO", "APPROVED", "RESOLVED", "CLOSED", "REJECTED",
]
_RMA_REASONS = ["DEFECTIVE", "WRONG_ITEM", "OVERSTOCK", "EXPIRED"]
_RMA_STATUS = ["REQUESTED", "APPROVED", "RECEIVED", "CREDITED", "DENIED"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a bare UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_branch(data: dict):
    _assert_common(data)
    assert isinstance(data["branch_code"], str) and data["branch_code"]
    assert isinstance(data["hazmat_storage_certified"], bool)
    assert isinstance(data["peak_season_start"], str)
    assert isinstance(data["peak_season_end"], str)
    assert isinstance(data["willcall_cutoff_minutes"], int)
    assert isinstance(data["seasonal_pool_units"], int)
    assert data["posture"] in _POSTURES, f"bad posture: {data}"
    assert data["status"] in _BRANCH_STATUS, f"bad branch status: {data}"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert data["account_type"] in _ACCOUNT_TYPES
    assert data["tier"] in _TIERS
    assert isinstance(data["ytd_volume_cents"], int)
    expiry = data.get("hazmat_delivery_license_expiry")
    assert expiry is None or isinstance(expiry, str)
    assert isinstance(data["willcall_authorized"], bool)
    assert isinstance(data["credit_hold"], bool)
    assert data["status"] in _ACCOUNT_STATUS


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["product_family"] in _PRODUCT_FAMILIES
    assert data["hazmat_class"] in _HAZMAT_CLASSES
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["expiry_tracked"], bool)
    assert isinstance(data["low_stock_floor"], int)
    assert isinstance(data["shortage_freeze_threshold"], int)


def assert_stock_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("branch_id", "")), "branch_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["qty_on_hand"], int)
    assert isinstance(data["qty_reserved_willcall"], int)
    assert isinstance(data["qty_reserved_route"], int)
    assert isinstance(data["qty_available"], int)
    assert data["hazmat_storage_class"] in _HAZMAT_CLASSES
    expiry = data.get("expiry_date")
    assert expiry is None or isinstance(expiry, str)
    # three-bucket availability ledger may never go negative (PRD §3.1)
    assert data["qty_available"] == (
        data["qty_on_hand"] - data["qty_reserved_willcall"] - data["qty_reserved_route"]
    ), f"availability ledger broken: {data}"
    assert data["qty_available"] >= 0, f"qty_available may never go negative: {data}"


def assert_seasonal_program(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("branch_id", ""))
    assert isinstance(data["program_name"], str) and data["program_name"]
    for f in ("order_window_start", "order_window_end", "ship_window_start", "ship_window_end"):
        assert isinstance(data[f], str) and data[f], f"{f} must be present"
    assert isinstance(data["early_buy_discount_pct"], (int, float))
    assert isinstance(data["pool_cap_units"], int)
    assert data["status"] in _PROGRAM_STATUS


def assert_seasonal_commitment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("program_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["committed_units"], int)
    assert isinstance(data["consumed_units"], int)
    assert data["status"] in _COMMITMENT_STATUS


def assert_sales_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("branch_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["channel"] in _CHANNELS
    assert data["fulfillment_status"] in _FULFILLMENT
    assert data["payment_status"] in _PAYMENT
    assert isinstance(data["order_subtotal_cents"], int)
    assert isinstance(data["freight_charge_cents"], int)
    assert isinstance(data["invoiced_cents"], int)


def assert_order_line(data: dict):
    # OrderLine carries only id + created_at as common fields (PRD §2.4):
    # updated_at and version are absent.
    assert is_valid_uuid(data.get("id", "")), f"line id must be a UUID: {data}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, f"OrderLine must not carry updated_at: {data}"
    assert "version" not in data, f"OrderLine must not carry version: {data}"
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["extended_price_cents"], int)
    assert isinstance(data["allocated_qty"], int)
    assert isinstance(data["backordered_qty"], int)


def assert_backorder_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("branch_id", ""))
    assert is_valid_uuid(data.get("order_line_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert isinstance(data["qty_open"], int)
    assert isinstance(data["qty_original"], int)
    assert data["priority_rank"] in (1, 2, 3)
    assert data["status"] in _BACKORDER_STATUS


def assert_service_center(data: dict):
    _assert_common(data)
    assert isinstance(data["center_name"], str) and data["center_name"]
    assert isinstance(data["region_code"], str) and data["region_code"]
    assert isinstance(data["authorized_brands"], list)
    assert isinstance(data["labor_rate_cents"], int)
    assert data["status"] in _ACCOUNT_STATUS


def assert_warranty_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["brand"], str) and data["brand"]
    assert isinstance(data["purchase_date"], str)
    assert isinstance(data["failure_description"], str)
    assert isinstance(data["info_cycles"], int)
    assert isinstance(data["provisional_credit_cents"], int)
    assert data["status"] in _CLAIM_STATUS


def assert_return_authorization(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("product_id", ""))
    assert is_valid_uuid(data.get("lot_id", ""))
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["reason"] in _RMA_REASONS
    assert data["status"] in _RMA_STATUS
