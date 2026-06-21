"""Entity assertions and domain invariant checkers (PRD §3, §2.4)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_ASSET_CLASSES = ["US_EQUITY", "INTL_EQUITY", "BOND", "REIT", "COMMODITY"]


def assert_common_fields(data: dict):
    """id + created_at + updated_at + version for common_fields entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version >= 1"


def assert_security(data: dict):
    assert_common_fields(data)
    assert isinstance(data["ticker"], str) and data["ticker"] == data["ticker"].upper()
    assert data["asset_class"] in _ASSET_CLASSES
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 1
    assert isinstance(data["is_active"], bool)


def assert_model_portfolio(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert 0 <= data["min_risk_score"] <= 100
    assert 0 <= data["max_risk_score"] <= 100
    assert data["max_risk_score"] >= data["min_risk_score"]
    assert isinstance(data["targets"], list)
    assert sum(t["target_pct"] for t in data["targets"]) == 100, "targets sum to 100 (PRD §3.1)"
    assert data["drift_threshold_pct"] >= 1
    assert data["lot_selection"] in ("FIFO", "HIFO")
    assert isinstance(data["is_active"], bool)


def assert_account(data: dict):
    assert_common_fields(data)
    assert isinstance(data["client_email"], str) and len(data["client_email"]) > 0
    assert data["status"] in (
        "PENDING_PROFILE",
        "ACTIVE",
        "REBALANCE_DUE",
        "FROZEN",
        "CLOSED",
    )
    assert isinstance(data["cash_balance_cents"], int)
    assert isinstance(data["total_value_cents"], int)
    assert isinstance(data["max_drift_pct"], int)
    assert isinstance(data["realized_gain_cents_ytd"], int)
    assert isinstance(data["wash_sale_disallowed_cents_ytd"], int)


def assert_questionnaire(data: dict):
    """RiskQuestionnaire is common_fields=false: id + created_at only, no version/updated_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "questionnaire has no version field (PRD §2.4)"
    assert "updated_at" not in data, "questionnaire has no updated_at field (PRD §2.4)"
    assert data["status"] in ("SCORED", "ACCEPTED", "SUPERSEDED")
    assert 0 <= data["risk_score"] <= 100


def assert_tax_lot(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert data["quantity"] > 0
    assert isinstance(data["cost_basis_cents"], int) and data["cost_basis_cents"] >= 1
    assert is_iso8601_timestamp(data.get("acquired_at", "")), "acquired_at must be ISO 8601"


def assert_harvest_event(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PROPOSED", "EXECUTED", "REJECTED", "REVERSED")


def assert_rebalance_event(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("PLANNED", "EXECUTED", "CANCELLED")


def assert_tax_form(data: dict):
    assert_common_fields(data)
    assert data["status"] in ("DRAFT", "FINALIZED")
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0


def assert_account_value_conserved(data: dict, expected_total_value_cents: int):
    """Account total_value_cents == cash + invested and equals expected (PRD §2.8, §3.7)."""
    assert (
        data["total_value_cents"]
        == data["cash_balance_cents"] + data["invested_value_cents"]
    ), "total_value_cents == cash_balance_cents + invested_value_cents (PRD §2.8)"
    assert data["total_value_cents"] == expected_total_value_cents, (
        f"total_value_cents conserved: expected {expected_total_value_cents}, "
        f"got {data['total_value_cents']}"
    )
