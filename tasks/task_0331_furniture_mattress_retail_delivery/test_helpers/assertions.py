"""Entity assertions and domain invariant checkers.

Validate response structure against the PRD contract using the framework's
generic format checkers. Money fields are integer cents.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    """id + created_at + updated_at + version (common_fields entities)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_customer(data: dict):
    _common(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert 300 <= data["credit_score"] <= 850
    assert isinstance(data["monthly_income_cents"], int) and data["monthly_income_cents"] >= 0
    assert isinstance(data["existing_monthly_obligations_cents"], int)
    assert isinstance(data["open_financing_count"], int) and data["open_financing_count"] >= 0


def assert_product(data: dict):
    _common(data)
    assert data["category"] in ["SOFA", "SECTIONAL", "MATTRESS", "BED_FRAME", "TABLE"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["available_fabrics"], list)
    assert isinstance(data["available_sizes"], list)


def assert_order(data: dict):
    _common(data)
    assert data["payment_status"] in ["UNPAID", "FINANCED", "PAID_IN_FULL"]
    assert data["fulfillment_status"] in [
        "DRAFT", "CONFIRMED", "SCHEDULED", "DELIVERED", "CLOSED", "CANCELLED",
    ]
    assert data["delivery_tier"] in ["THRESHOLD", "WHITE_GLOVE"]
    for fld in ("merchandise_subtotal_cents", "service_total_cents",
                "order_total_cents", "amount_refunded_cents"):
        assert isinstance(data[fld], int), f"{fld} must be integer cents"
    assert data["amount_refunded_cents"] >= 0


def assert_order_line(data: dict):
    _common(data)
    assert data["status"] in ["ACTIVE", "CANCELLED", "RETURNED"]
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    for fld in ("unit_config_price_cents", "line_total_cents", "addon_fee_cents"):
        assert isinstance(data[fld], int), f"{fld} must be integer cents"


def assert_financing_plan(data: dict):
    _common(data)
    assert data["plan_type"] in ["INSTALLMENT", "LEASE_TO_OWN"]
    assert data["status"] in [
        "PENDING_APPROVAL", "CURRENT", "PAST_DUE", "PAID_OFF", "DECLINED", "DEFAULTED",
    ]
    assert isinstance(data["term_months"], int)
    for fld in ("monthly_payment_cents", "total_of_payments_cents",
                "paid_to_date_cents", "payoff_balance_cents"):
        assert isinstance(data[fld], int), f"{fld} must be integer cents"
    assert data["payoff_balance_cents"] >= 0, "payoff_balance_cents is floored at 0"
    assert isinstance(data["payments_made_count"], int)


def assert_payment(data: dict):
    """Payment is immutable: id + created_at only — NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Payment must not carry updated_at (immutable)"
    assert "version" not in data, "Payment must not carry version (immutable)"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["applied_period_index"], int) and data["applied_period_index"] >= 1


def assert_delivery_route(data: dict):
    _common(data)
    assert data["status"] in ["OPEN", "LOCKED", "COMPLETED"]
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] > 0
    assert isinstance(data["committed_units"], int) and data["committed_units"] >= 0


def assert_delivery_stop(data: dict):
    _common(data)
    assert data["status"] in ["BOOKED", "DISPATCHED", "COMPLETED", "CANCELLED"]
    assert data["service_tier"] in ["THRESHOLD", "WHITE_GLOVE"]
    assert isinstance(data["unit_load"], int) and data["unit_load"] >= 0


def assert_protection_plan(data: dict):
    _common(data)
    assert data["tier"] in ["BASIC", "PREMIUM"]
    assert data["status"] in ["ACTIVE", "VOIDED"]
    assert isinstance(data["premium_cents"], int) and data["premium_cents"] >= 0


def assert_return_request(data: dict):
    _common(data)
    assert data["reason"] in ["DAMAGED", "DEFECTIVE", "CHANGED_MIND"]
    assert data["status"] in ["REQUESTED", "APPROVED", "REFUNDED", "REJECTED"]
    for fld in ("restocking_fee_cents", "refund_amount_cents"):
        assert isinstance(data[fld], int), f"{fld} must be integer cents"
