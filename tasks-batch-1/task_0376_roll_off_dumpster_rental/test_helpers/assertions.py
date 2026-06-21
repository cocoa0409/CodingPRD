"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_CONTAINER_STATUSES = ["IN_YARD", "ASSIGNED", "ON_SITE", "AWAITING_DUMP", "OUT_OF_SERVICE"]
_ROUTE_STATUSES = ["PLANNING", "DISPATCHED", "CLOSED"]
_ORDER_LOGISTICS = ["BOOKED", "SCHEDULED", "ON_SITE", "AWAITING_PICKUP", "COMPLETED", "CANCELLED"]
_ORDER_BILLING = ["UNBILLED", "ESTIMATED", "FINALIZED"]
_STOP_TYPES = ["DELIVERY", "SWAP", "PICKUP"]
_STOP_STATUSES = ["UNASSIGNED", "ASSIGNED", "COMPLETED", "CANCELLED"]
_PERMIT_STATUSES = ["REQUESTED", "APPROVED", "DENIED", "EXPIRED"]
_INVOICE_STATUSES = ["ISSUED", "PAID", "VOID"]
_CONTAMINATION_KINDS = ["NONE", "TIRES", "APPLIANCES", "HAZMAT"]
_SIZE_CODES = ["YD10", "YD20", "YD30", "YD40"]


def _assert_full_triple(data: dict):
    """id (UUID) + created_at + updated_at (ISO8601) + version >= 1."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1, "version must be int >= 1"


def assert_container_type(data: dict):
    _assert_full_triple(data)
    assert data["size_code"] in _SIZE_CODES, f"bad size_code {data['size_code']}"
    for f in ("base_rate_cents", "included_days", "overage_day_cents",
              "included_tonnage_lbs", "overage_rate_cents_per_lb"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert isinstance(data["active"], bool), "active must be bool"


def assert_contractor_account(data: dict):
    _assert_full_triple(data)
    assert isinstance(data["business_name"], str) and len(data["business_name"]) > 0
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_cents"], int)
    assert isinstance(data["available_credit_cents"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED"], f"bad status {data['status']}"
    # Ledger invariant: available = limit - outstanding (PRD §3.2).
    assert data["available_credit_cents"] == data["credit_limit_cents"] - data["outstanding_cents"], \
        "available_credit_cents must equal credit_limit_cents - outstanding_cents"


def assert_container(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("container_type_id", "")), "container_type_id must be UUID"
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0
    assert isinstance(data["yard_code"], str) and len(data["yard_code"]) > 0
    assert data["status"] in _CONTAINER_STATUSES, f"bad status {data['status']}"
    assert data["current_order_id"] is None or is_valid_uuid(data["current_order_id"])


def assert_route(data: dict):
    _assert_full_triple(data)
    assert isinstance(data["service_date"], str) and len(data["service_date"]) == 10
    assert isinstance(data["truck_code"], str) and len(data["truck_code"]) > 0
    assert isinstance(data["capacity_stops"], int) and data["capacity_stops"] >= 1
    assert isinstance(data["stop_count"], int) and data["stop_count"] >= 0
    assert data["status"] in _ROUTE_STATUSES, f"bad status {data['status']}"


def assert_rental_order(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be UUID"
    assert is_valid_uuid(data.get("container_type_id", "")), "container_type_id must be UUID"
    assert data["container_id"] is None or is_valid_uuid(data["container_id"])
    assert isinstance(data["site_address"], str) and len(data["site_address"]) > 0
    assert isinstance(data["requested_delivery_date"], str)
    assert isinstance(data["requires_street_permit"], bool)
    assert data["logistics_status"] in _ORDER_LOGISTICS, f"bad logistics_status {data['logistics_status']}"
    assert data["billing_status"] in _ORDER_BILLING, f"bad billing_status {data['billing_status']}"
    for f in ("rental_days", "estimated_total_cents", "final_total_cents"):
        assert isinstance(data[f], int), f"{f} must be int"


def assert_service_stop(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be UUID"
    assert data["route_id"] is None or is_valid_uuid(data["route_id"])
    assert data["stop_type"] in _STOP_TYPES, f"bad stop_type {data['stop_type']}"
    assert data["sequence"] is None or (isinstance(data["sequence"], int) and data["sequence"] >= 1)
    assert isinstance(data["estimated_weight_lbs"], int) and data["estimated_weight_lbs"] >= 0
    assert data["status"] in _STOP_STATUSES, f"bad status {data['status']}"


def assert_street_permit(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be UUID"
    assert isinstance(data["municipality"], str) and len(data["municipality"]) > 0
    assert isinstance(data["permit_fee_cents"], int) and data["permit_fee_cents"] >= 0
    assert isinstance(data["valid_from"], str)
    assert isinstance(data["valid_until"], str)
    assert data["status"] in _PERMIT_STATUSES, f"bad status {data['status']}"


def assert_invoice(data: dict):
    _assert_full_triple(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be UUID"
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be UUID"
    for f in ("base_cents", "overage_day_cents", "tonnage_cents",
              "permit_cents", "contamination_cents", "total_cents"):
        assert isinstance(data[f], int), f"{f} must be int"
    assert data["status"] in _INVOICE_STATUSES, f"bad status {data['status']}"
    # Total is the sum of the five line items (PRD §3.10).
    expected_total = (data["base_cents"] + data["overage_day_cents"] + data["tonnage_cents"]
                      + data["permit_cents"] + data["contamination_cents"])
    assert data["total_cents"] == expected_total, \
        f"total_cents {data['total_cents']} != sum of line items {expected_total}"


def assert_weigh_ticket(data: dict):
    """WeighTicket is append-only: id + created_at only, NO updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "WeighTicket must not carry updated_at"
    assert "version" not in data, "WeighTicket must not carry version"
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be UUID"
    assert is_valid_uuid(data.get("service_stop_id", "")), "service_stop_id must be UUID"
    for f in ("gross_weight_lbs", "tare_weight_lbs", "net_weight_lbs"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be int >= 0"
    assert isinstance(data["contaminated"], bool)
    assert data["contamination_kind"] in _CONTAMINATION_KINDS
    # net = max(0, gross - tare) (PRD §3.9).
    assert data["net_weight_lbs"] == max(0, data["gross_weight_lbs"] - data["tare_weight_lbs"]), \
        "net_weight_lbs must be max(0, gross - tare)"
