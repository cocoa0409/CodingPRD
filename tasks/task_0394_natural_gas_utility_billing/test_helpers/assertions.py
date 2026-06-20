"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_rate_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["customer_class"] in ("RESIDENTIAL", "COMMERCIAL")
    assert isinstance(data["fixed_customer_charge_cents"], int) and data["fixed_customer_charge_cents"] >= 0
    assert isinstance(data["distribution_rate_cents_per_therm"], int) and data["distribution_rate_cents_per_therm"] >= 0
    assert 0.9 <= data["btu_factor"] <= 1.2
    assert isinstance(data["minimum_bill_cents"], int) and data["minimum_bill_cents"] >= 0
    assert isinstance(data["active"], bool)
    assert isinstance(data["version"], int)


def assert_pga_schedule(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["customer_class"] in ("RESIDENTIAL", "COMMERCIAL")
    assert isinstance(data["commodity_rate_cents_per_therm"], int) and data["commodity_rate_cents_per_therm"] >= 0
    assert isinstance(data["supplier_refund_cents_per_therm"], int) and data["supplier_refund_cents_per_therm"] >= 0


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0
    assert data["customer_class"] in ("RESIDENTIAL", "COMMERCIAL")
    assert data["service_status"] in ("ACTIVE", "SHUTOFF_PENDING", "DISCONNECTED", "FINALED")
    assert data["low_income_status"] in ("NONE", "ENROLLED")
    assert data["low_income_tier"] in ("NONE", "TIER_1", "TIER_2")
    assert isinstance(data["budget_enrolled"], bool)
    assert isinstance(data["version"], int)


def assert_meter(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["serial_no"], str) and len(data["serial_no"]) > 0
    assert data["uom"] in ("CCF", "THERM")
    assert data["status"] in ("PENDING_SET", "SET", "LOCKED", "REMOVED")
    assert data["install_index"] >= 0


def assert_meter_read(data: dict):
    """MeterRead is append-only (common_fields:false): id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["read_type"] in ("ACTUAL", "ESTIMATED")
    assert data["status"] in ("POSTED", "VOID")


def assert_no_version_fields(data: dict):
    """For append-only records (MeterRead, Payment, Clock): must carry no version/updated_at."""
    assert "version" not in data, "append-only record must not carry a version field"
    assert "updated_at" not in data, "append-only record must not carry an updated_at field"


def assert_bill(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "VOID", "CORRECTED")
    assert isinstance(data["amount_due_cents"], int)
    assert isinstance(data["budget_billed_cents"], int)


def assert_budget_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("ACTIVE", "TRUED_UP", "CANCELLED")
    assert isinstance(data["monthly_installment_cents"], int)


def assert_payment(data: dict):
    """Payment is append-only (common_fields:false): id + created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ("POSTED", "REVERSED")
    assert isinstance(data["on_time"], bool)


def assert_service_order(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["order_type"] in ("METER_SET", "SHUTOFF", "RECONNECT")
    assert data["status"] in ("SCHEDULED", "DISPATCHED", "COMPLETED", "CANCELLED")


def assert_ticket(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["kind"] in ("ODOR", "LEAK", "CARBON_MONOXIDE")
    assert data["severity"] in ("GRADE_1", "GRADE_2", "GRADE_3")
    assert data["status"] in ("OPEN", "DISPATCHED", "MADE_SAFE", "RESOLVED", "CANCELLED")
    assert isinstance(data["gas_locked"], bool)


def assert_deposit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["reason"] in ("NEW_SERVICE", "RECONNECT", "DELINQUENCY")
    assert data["status"] in ("REQUIRED", "HELD", "WAIVED", "REFUNDED", "APPLIED")


def assert_low_income_credit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["tier"] in ("NONE", "TIER_1", "TIER_2")
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "EXPIRED")
