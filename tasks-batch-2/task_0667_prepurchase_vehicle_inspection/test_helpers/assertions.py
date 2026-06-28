"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_lightweight(data: dict):
    """For immutable records: id + created_at only, no updated_at / version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "immutable records must not carry updated_at"
    assert "version" not in data, "immutable records must not carry version"


def assert_account(data: dict):
    _assert_common(data)
    assert data["account_type"] in ["DEALER", "AUCTION", "INDIVIDUAL"]
    assert isinstance(data["legal_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["net_terms_days"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_vehicle(data: dict):
    _assert_lightweight(data)
    assert isinstance(data["vin"], str)
    assert isinstance(data["year"], int)


def assert_fee_schedule(data: dict):
    _assert_common(data)
    assert data["tier_code"] in ["STANDARD", "PREMIUM", "HEAVY_DUTY"]
    assert isinstance(data["base_fee_cents"], int)


def assert_inspector(data: dict):
    _assert_common(data)
    assert isinstance(data["certified_tiers"], list)
    assert data["status"] in ["AVAILABLE", "OFFLINE"]


def assert_order(data: dict):
    _assert_common(data)
    assert data["workflow_status"] in [
        "DRAFT", "DISPATCHED", "IN_PROGRESS", "REPORTED", "DELIVERED", "CANCELLED"
    ]
    assert data["payment_status"] in ["UNPAID", "PAID", "INVOICED", "REFUNDED"]
    assert data["rush_tier"] in ["NONE", "EXPRESS", "SAME_DAY"]
    assert isinstance(data["estimated_fee_cents"], int)


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ["OFFERED", "ACCEPTED", "DECLINED", "RELEASED"]


def assert_report(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "AMENDED"]


def assert_vin_report(data: dict):
    _assert_common(data)
    assert data["status"] == "COMPILED"
    assert data["worst_branding"] in ["NONE", "SALVAGE", "FLOOD", "LEMON", "REBUILT"]


def assert_dispute(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "UNDER_REVIEW", "NEEDS_INFO", "RESOLVED", "REJECTED"]


def assert_refund_conservation(order: dict):
    """Cumulative refunds never exceed the order's finalized fee (PRD §3.8)."""
    assert order["refunded_cents"] >= 0
    assert order["refunded_cents"] <= order["fee_total_cents"], (
        f"refunded_cents {order['refunded_cents']} exceeds fee_total_cents {order['fee_total_cents']}"
    )
