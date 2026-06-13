"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_ORDER_STATUSES = ["REQUESTED", "SCHEDULED", "IN_PROGRESS", "REPORT_DRAFT", "DELIVERED", "CANCELLED"]
_REPORT_STATUSES = ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED", "VOIDED"]
_DEFECT_STATUSES = ["LOGGED", "CONFIRMED", "CLEARED", "VOIDED"]
_BANDS = ["PASS", "MINOR", "MAJOR", "CRITICAL"]
_INSPECTION_TYPES = ["BUYER", "SELLER", "FOUR_POINT", "WIND_MIT"]


def _assert_common_full(data: dict):
    """id + created_at + updated_at + version (common_fields:true entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def _assert_common_lean(data: dict):
    """id + created_at only (common_fields:false entities: Client, Agent)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "lean entity must not carry a version field"
    assert "updated_at" not in data, "lean entity must not carry an updated_at field"


def assert_territory(data: dict):
    _assert_common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["zip_codes"], list)
    assert isinstance(data["travel_buffer_minutes"], int)


def assert_fee_schedule(data: dict):
    _assert_common_full(data)
    assert isinstance(data["label"], str)
    assert isinstance(data["base_rate_cents"], int)
    assert data["status"] in ["DRAFT", "PUBLISHED"]


def assert_inspector(data: dict):
    _assert_common_full(data)
    assert isinstance(data["full_name"], str)
    assert is_valid_uuid(data.get("territory_id", "")), "territory_id must be a UUID"
    assert isinstance(data["certifications"], list)
    assert isinstance(data["daily_capacity_minutes"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_client(data: dict):
    _assert_common_lean(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["role_in_deal"] in ["BUYER", "SELLER"]


def assert_agent(data: dict):
    _assert_common_lean(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["brokerage"], str)


def assert_property(data: dict):
    _assert_common_full(data)
    assert isinstance(data["address_line"], str)
    assert isinstance(data["zip_code"], str)
    assert isinstance(data["square_footage"], int) and data["square_footage"] > 0
    assert isinstance(data["year_built"], int)


def assert_inspection_order(data: dict):
    _assert_common_full(data)
    assert data["status"] in _ORDER_STATUSES
    assert data["order_kind"] in ["PRIMARY", "REINSPECTION"]
    assert data["inspection_type"] in _INSPECTION_TYPES
    assert isinstance(data["amount_paid_cents"], int)
    assert isinstance(data["amount_refunded_cents"], int)


def assert_addon(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert data["kind"] in ["RADON", "TERMITE", "SEWER"]
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["added_duration_minutes"], int)
    assert data["status"] in ["ACTIVE", "REMOVED"]


def assert_report(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert isinstance(data["measured_square_footage"], int)
    assert data["status"] in _REPORT_STATUSES


def assert_defect(data: dict):
    _assert_common_full(data)
    assert is_valid_uuid(data.get("report_id", "")), "report_id must be a UUID"
    assert isinstance(data["location"], str)
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert data["status"] in _DEFECT_STATUSES


def assert_delivery(data: dict):
    _assert_common_full(data)
    assert data["recipient_kind"] in ["CLIENT", "AGENT"]
    assert isinstance(data["recipient_email"], str)
    assert data["severity_band_snapshot"] in _BANDS
    assert data["status"] in ["SENT", "CANCELLED"]


def assert_money_conserved(order: dict):
    """On a cancelled order, amount_refunded_cents == amount_paid_cents (PRD §2.9)."""
    assert order["amount_refunded_cents"] == order["amount_paid_cents"], (
        f"net collected must be 0: paid={order['amount_paid_cents']} "
        f"refunded={order['amount_refunded_cents']}"
    )
