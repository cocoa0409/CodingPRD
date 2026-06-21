"""Entity assertions and domain invariant checkers.

Per-entity assert_{entity}(data) verifies the shape and field types the PRD
promises. Domain invariant checkers verify conserved quantities (trust funds,
gain partition) that must hold after any operation.
"""
import pytest
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def assert_exchanger(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["taxpayer_id"], str) and len(data["taxpayer_id"]) > 0
    assert isinstance(data["email"], str)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["version"] >= 1


def assert_exchange(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["exchanger_id"], str)
    assert data["exchange_type"] in ["FORWARD", "REVERSE", "IMPROVEMENT"]
    assert data["status"] in ["DRAFT", "ACTIVE", "COMPLETED", "FAILED", "TERMINATED"]
    if data.get("compliance_posture") is not None:
        assert data["compliance_posture"] in [
            "OPEN", "IDENTIFIED", "AT_RISK", "COMPLETED", "FAILED",
        ]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["version"] >= 1


def assert_relinquished_property(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["exchange_id"], str)
    assert isinstance(data["address"], str)
    assert data["fair_market_value"] > 0
    assert data["selling_expenses"] >= 0
    assert data["mortgage_payoff"] >= 0
    assert data["adjusted_basis"] >= 0
    assert data["net_proceeds"] >= 0
    assert_cost_precision(data["net_proceeds"])
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["version"] >= 1


def assert_qualified_trust(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["exchange_id"], str)
    assert data["deposited_amount"] >= 0
    assert_cost_precision(data["deposited_amount"])
    assert_cost_precision(data["available_balance"])
    assert isinstance(data["is_locked"], bool)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["version"] >= 1


def assert_identification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["exchange_id"], str)
    assert data["method"] in ["THREE_PROPERTY", "TWO_HUNDRED_PCT"]
    assert data["status"] in ["DRAFT", "FINALIZED", "REVOKED"]
    assert data["aggregate_identified_fmv"] >= 0
    assert_cost_precision(data["aggregate_identified_fmv"])
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["version"] >= 1


def assert_identified_property(data: dict):
    """IdentifiedProperty is append-only: id + created_at only, no version field."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["identification_id"], str)
    assert isinstance(data["description"], str)
    assert data["estimated_fmv"] > 0
    assert data["status"] in ["CANDIDATE", "ACQUIRED", "WITHDRAWN"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_replacement_property(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["exchange_id"], str)
    assert isinstance(data["identified_property_id"], str)
    assert data["purchase_price"] > 0
    assert data["replacement_debt"] >= 0
    assert data["improvement_value"] >= 0
    assert_cost_precision(data["cash_applied"])
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["version"] >= 1


def assert_disbursement(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["exchange_id"], str)
    assert data["purpose"] in ["QI_FEE", "ACQUISITION", "IMPROVEMENT_DRAW", "BOOT_RETURN"]
    assert data["priority"] in [1, 2, 3, 4]
    assert data["amount"] > 0
    assert data["settlement_status"] in ["REQUESTED", "SETTLED", "VOIDED"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["version"] >= 1


# ── Domain invariant checkers ────────────────────────────────────────

def assert_trust_conserved(trust: dict, settled_total: float):
    """deposited_amount == available_balance + sum(SETTLED disbursement amounts).

    settled_total is the caller-known sum of SETTLED disbursement amounts.
    """
    assert trust["available_balance"] == pytest.approx(
        trust["deposited_amount"] - settled_total, abs=0.01
    ), (
        f"trust not conserved: deposited {trust['deposited_amount']} != "
        f"available {trust['available_balance']} + settled {settled_total}"
    )


def assert_gain_partition(exchange: dict):
    """realized_gain == recognized_gain + deferred_gain (exact partition)."""
    assert exchange["recognized_gain"] is not None and exchange["deferred_gain"] is not None
    assert exchange["realized_gain"] == pytest.approx(
        exchange["recognized_gain"] + exchange["deferred_gain"], abs=0.01
    ), (
        f"gain not partitioned: realized {exchange['realized_gain']} != "
        f"recognized {exchange['recognized_gain']} + deferred {exchange['deferred_gain']}"
    )
