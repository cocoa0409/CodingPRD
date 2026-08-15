"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_identity(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a prefix-less UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    )


def _assert_mutable(data: dict):
    """Resources that mutate carry updated_at + integer version (PRD §2.4)."""
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_account(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert isinstance(data["account_code"], str) and data["account_code"]
    assert isinstance(data["display_name"], str)
    assert data["account_type"] in ("DISCRETIONARY", "PROPRIETARY", "ERROR")
    assert isinstance(data["custodian_name"], str)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_security(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert isinstance(data["ticker"], str) and data["ticker"]
    assert data["asset_class"] in ("EQUITY", "FIXED_INCOME")
    assert isinstance(data["currency"], str)
    assert isinstance(data["lot_size"], int) and data["lot_size"] >= 1
    assert isinstance(data["reference_price_cents"], int) and data["reference_price_cents"] > 0
    assert data["status"] in ("ACTIVE", "HALTED")


def assert_broker(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert isinstance(data["broker_code"], str) and data["broker_code"]
    assert isinstance(data["display_name"], str)
    assert data["commission_rate_bp"] > 0
    assert isinstance(data["supported_asset_classes"], list) and len(data["supported_asset_classes"]) > 0
    for ac in data["supported_asset_classes"]:
        assert ac in ("EQUITY", "FIXED_INCOME")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_commission_budget(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a UUID"
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["budget_amount_cents"], int) and data["budget_amount_cents"] > 0
    assert isinstance(data["accrued_commission_cents"], int) and data["accrued_commission_cents"] >= 0
    assert data["status"] in ("OPEN", "EXHAUSTED")


def assert_restriction(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert data.get("account_id") is None or is_valid_uuid(data["account_id"])
    assert data.get("security_id") is None or is_valid_uuid(data["security_id"])
    assert data["rule_type"] in ("PROHIBITED", "MAX_POSITION_UNITS")
    assert data["side"] in ("BUY", "SELL", "BOTH")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "RETIRED")
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["effective_to"], str)


def assert_order(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("security_id", ""))
    assert data["side"] in ("BUY", "SELL")
    assert isinstance(data["order_qty"], int) and data["order_qty"] > 0
    assert data["order_type"] in ("MARKET", "LIMIT")
    assert data.get("block_id") is None or is_valid_uuid(data["block_id"])
    assert data["status"] in (
        "PENDING_COMPLIANCE", "COMPLIANCE_REJECTED", "APPROVED", "BLOCKED",
        "ALLOCATED", "UNDER_CORRECTION", "SETTLED", "CANCELLED",
    )
    assert isinstance(data["allocated_qty"], int) and data["allocated_qty"] >= 0
    assert data.get("avg_executed_price_cents") is None or isinstance(data["avg_executed_price_cents"], int)
    assert data.get("compliance_note") is None or isinstance(data["compliance_note"], str)


def assert_block_order(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data.get("security_id", ""))
    assert data["side"] in ("BUY", "SELL")
    assert data.get("broker_id") is None or is_valid_uuid(data["broker_id"])
    assert isinstance(data["total_qty"], int) and data["total_qty"] >= 0
    assert isinstance(data["filled_qty"], int) and data["filled_qty"] >= 0
    assert data.get("avg_fill_price_cents") is None or isinstance(data["avg_fill_price_cents"], int)
    assert isinstance(data["allocated_through_seq"], int) and data["allocated_through_seq"] >= 0
    assert data["status"] in ("OPEN", "WORKING", "PARTIALLY_FILLED", "FILLED", "CANCELLED")
    assert data["allocation_status"] in ("UNALLOCATED", "PARTIAL", "FULL")


def assert_fill(data: dict):
    """Append-only kind (PRD §2.4): id + created_at only, never updated_at/version."""
    _assert_identity(data)
    assert "updated_at" not in data, "Fill must not carry updated_at"
    assert "version" not in data, "Fill must not carry version"
    assert is_valid_uuid(data.get("block_id", ""))
    assert isinstance(data["fill_qty"], int) and data["fill_qty"] > 0
    assert isinstance(data["fill_price_cents"], int) and data["fill_price_cents"] > 0
    assert isinstance(data["fill_seq"], int) and data["fill_seq"] >= 1
    assert isinstance(data["gross_amount_cents"], int)


def assert_allocation_plan(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data.get("block_id", ""))
    assert data["method"] in ("PRO_RATA", "EQUAL_SPLIT")
    assert data["status"] in ("DRAFT", "PROPOSED", "APPROVED", "POSTED", "SUPERSEDED")
    assert isinstance(data["covered_from_seq"], int)
    assert data.get("covered_to_seq") is None or isinstance(data["covered_to_seq"], int)
    assert data.get("batch_qty") is None or isinstance(data["batch_qty"], int)
    assert data.get("batch_avg_price_cents") is None or isinstance(data["batch_avg_price_cents"], int)
    assert data.get("max_deviation_bp") is None or isinstance(data["max_deviation_bp"], int)
    assert isinstance(data["created_by_user_id"], str)


def assert_allocation(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data.get("plan_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("order_id", ""))
    assert isinstance(data["alloc_qty"], int)
    assert isinstance(data["alloc_price_cents"], int)
    assert data["status"] in ("PROPOSED", "POSTED", "SETTLED", "ERROR_FLAGGED", "REVERSED")
    assert data.get("corrects_allocation_id") is None or is_valid_uuid(data["corrects_allocation_id"])


def assert_trade_error(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data.get("allocation_id", ""))
    assert data["error_type"] in ("WRONG_ACCOUNT", "WRONG_QTY", "WRONG_PRICE")
    assert data["status"] in ("OPEN", "RESOLVED", "DISMISSED")
    assert isinstance(data["flagged_by_user_id"], str)


def assert_settlement_instruction(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data.get("allocation_id", ""))
    assert isinstance(data["custodian_name"], str)
    assert isinstance(data["trade_date"], str)
    assert isinstance(data["settle_date"], str)
    assert data["instruction_status"] in ("PENDING", "INSTRUCTED", "SETTLED", "FAILED", "CANCELLED")
    assert data.get("fail_reason") is None or data["fail_reason"] in (
        "BROKER_NON_DELIVERY", "CUSTODIAN_MISMATCH", "INSUFFICIENT_POSITION", "OTHER",
    )
    assert isinstance(data["fail_count"], int) and data["fail_count"] >= 0


def assert_position(data: dict):
    _assert_identity(data)
    _assert_mutable(data)
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("security_id", ""))
    assert isinstance(data["net_qty"], int)


def assert_audit_event(data: dict):
    """Append-only kind (PRD §2.4): id + created_at only, never updated_at/version."""
    _assert_identity(data)
    assert "updated_at" not in data, "AuditEvent must not carry updated_at"
    assert "version" not in data, "AuditEvent must not carry version"
    assert isinstance(data["entity_type"], str) and data["entity_type"]
    assert isinstance(data["entity_id"], str) and data["entity_id"]
    assert isinstance(data["action"], str) and data["action"]
    assert isinstance(data["actor_role"], str) and data["actor_role"]
    assert isinstance(data["actor_user_id"], str) and data["actor_user_id"]
