"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_trade_account(data: dict):
    _assert_common(data)
    assert isinstance(data["business_name"], str) and data["business_name"]
    assert data["tier"] in ("STANDARD", "SILVER", "GOLD")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["available_credit_cents"], int)


def assert_fixture_model(data: dict):
    _assert_common(data)
    assert data["category"] in ("CEILING_FAN", "CHANDELIER", "PENDANT", "SCONCE", "RECESSED")
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["base_wattage"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert data["fulfillment_status"] in ("DRAFT", "QUOTED", "CONFIRMED", "COMPLETED", "CANCELLED")
    assert data["payment_status"] in ("UNPAID", "DEPOSIT_PAID", "SETTLED", "REFUNDED")
    assert isinstance(data["customer_name"], str) and data["customer_name"]


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert data["line_status"] in ("ACTIVE", "RETURNED", "CANCELLED")


def assert_special_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "CONFIRMED", "READY", "CANCELLED")


def assert_design_consult(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "IN_REVIEW", "REVISION", "APPROVED")
    assert isinstance(data["revision_count"], int) and data["revision_count"] >= 0


def assert_installer(data: dict):
    _assert_common(data)
    assert isinstance(data["active_referral_count"], int)


def assert_delivery_job(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "DELIVERED", "VOIDED")


def assert_install_referral(data: dict):
    _assert_common(data)
    assert data["status"] in ("REFERRED", "SCHEDULED", "COMPLETED", "WITHDRAWN")


def assert_return_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "REFUNDED", "DENIED")
    assert data["reason"] in ("DAMAGE", "DEFECTIVE", "CHANGED_MIND", "WARRANTY")


def assert_rebate_program(data: dict):
    _assert_common(data)
    assert isinstance(data["budget_remaining_cents"], int)


def assert_rebate_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "VOID", "DENIED")
