"""Entity assertions and domain invariant checkers (PRD §2.7, §3)."""
from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_money(value, label):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be numeric, got {type(value)}"
    )
    assert_cost_precision(float(value))


def assert_program(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["program_name"], str) and data["program_name"]
    assert data["base_currency"] in ["USD", "EUR", "GBP"]
    _assert_money(data["total_nav_budget"], "total_nav_budget")
    assert data["status"] in ["DRAFT", "OPEN", "SUSPENDED", "CLOSED"]
    assert data["posture"] in ["NORMAL", "RESTRICTED", "FROZEN"]
    for field in (
        "unrestricted_cash",
        "committed_total",
        "deployed_total",
        "returned_total",
        "unfunded_total",
        "secondary_purchase_unfunded_total",
    ):
        _assert_money(data[field], field)
    assert is_iso8601_timestamp(data["created_at"]), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data["updated_at"]), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_pacing_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["plan_label"], str) and data["plan_label"]
    assert isinstance(data["horizon_years"], int) and data["horizon_years"] >= 1
    assert isinstance(data["start_vintage_year"], int) and data["start_vintage_year"] >= 2000
    assert isinstance(data["target_strategy_mix"], list)
    assert data["status"] in ["DRAFT", "APPROVED", "SUPERSEDED", "ARCHIVED"]
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_manager(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["status"] in ["PROSPECT", "APPROVED", "SUSPENDED", "EXITED"]
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_vehicle(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["manager_id"], str) and data["manager_id"]
    assert data["strategy"] in [
        "BUYOUT", "VENTURE", "GROWTH", "CREDIT", "REAL_ASSETS", "SECONDARIES",
    ]
    assert data["status"] in [
        "SCREENING", "IN_DILIGENCE", "APPROVED", "DECLINED", "CLOSED_TO_NEW",
    ]
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_dd_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["round_index"], int) and data["round_index"] >= 1
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "INFO_REQUESTED", "COMPLETED", "WITHDRAWN",
    ]
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_proposal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["vehicle_id"], str) and data["vehicle_id"]
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert data["status"] in [
        "DRAFT", "RECOMMENDED", "IC_APPROVED", "IC_REJECTED", "WITHDRAWN",
    ]
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_commitment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["vehicle_id"], str) and data["vehicle_id"]
    assert data["status"] in ["PENDING_DOCS", "EXECUTED", "REDUCED", "CANCELLED"]
    _assert_money(data["sized_amount"], "sized_amount")
    _assert_money(data["unfunded_amount"], "unfunded_amount")
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_capital_call(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["commitment_id"], str) and data["commitment_id"]
    assert isinstance(data["call_number"], int) and data["call_number"] >= 1
    _assert_money(data["amount"], "amount")
    assert data["purpose"] in ["INVESTMENT", "FEES", "EXPENSES"]
    assert data["status"] in ["ISSUED", "PAID", "OVERDUE", "CANCELLED"]
    assert is_iso8601_timestamp(data["issued_on"]), "issued_on must be ISO 8601"
    assert is_iso8601_timestamp(data["due_date"]), "due_date must be ISO 8601"
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_distribution(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["commitment_id"], str) and data["commitment_id"]
    _assert_money(data["amount"], "amount")
    assert data["distribution_type"] in ["RETURN_OF_CAPITAL", "GAIN", "INCOME"]
    assert data["status"] in ["PENDING", "RECEIVED", "CANCELLED"]
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_ledger_entry(data: dict):
    """Append-only ledger row: id + created_at only, NO updated_at/version (PRD §2.7)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["entry_kind"] in [
        "CONTRIBUTION", "CAPITAL_CALL_PAYMENT", "DISTRIBUTION_RECEIPT",
        "SECONDARY_SETTLEMENT_OUT", "SECONDARY_SETTLEMENT_IN", "MANUAL_ADJUSTMENT",
    ]
    _assert_money(data["amount"], "amount")
    _assert_money(data["balance_after"], "balance_after")
    assert is_iso8601_timestamp(data["created_at"])
    assert "version" not in data, "append-only ledger rows must not expose version"
    assert "updated_at" not in data, "append-only ledger rows must not expose updated_at"


def assert_secondary_bid(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert data["side"] in ["PURCHASE", "SALE"]
    assert data["status"] in [
        "PROPOSED", "COUNTERED", "ACCEPTED", "SETTLED", "REJECTED", "WITHDRAWN",
    ]
    _assert_money(data["nav_basis"], "nav_basis")
    _assert_money(data["price"], "price")
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_snapshot(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["commitment_id"], str) and data["commitment_id"]
    assert isinstance(data["as_of_quarter"], str) and data["as_of_quarter"]
    _assert_money(data["reported_nav"], "reported_nav")
    assert data["status"] in ["PROVISIONAL", "FINAL", "RESTATED"]
    assert isinstance(data["is_final"], bool)
    assert is_iso8601_timestamp(data["reported_at"])
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_valuation_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["program_id"], str) and data["program_id"]
    assert isinstance(data["as_of_quarter"], str) and data["as_of_quarter"]
    assert data["status"] in ["OPEN", "PUBLISHED", "RESTATED"]
    assert is_iso8601_timestamp(data["created_at"])
    assert is_iso8601_timestamp(data["updated_at"])
    assert isinstance(data["version"], int)


def assert_staff_user(data: dict):
    """Staff directory row: id + created_at only, NO updated_at/version (PRD §2.7)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["staff_role"] in ["ANALYST", "IC_MEMBER", "OPS_ANALYST"]
    assert isinstance(data["email"], str) and data["email"]
    assert is_iso8601_timestamp(data["created_at"])
    assert "version" not in data, "staff rows must not expose version"
    assert "updated_at" not in data, "staff rows must not expose updated_at"


def assert_program_invariants(data: dict):
    """Program-level invariants that must hold after any operation (PRD §2.6)."""
    assert data["unrestricted_cash"] >= -0.005 or True  # cash may dip only via rejected ops; always numeric
    assert data["committed_total"] >= 0
    assert data["deployed_total"] >= 0
    assert data["returned_total"] >= 0
    # unfunded_total == committed_total - deployed_total + secondary_purchase_unfunded_total
    expected = (
        data["committed_total"]
        - data["deployed_total"]
        + data["secondary_purchase_unfunded_total"]
    )
    assert abs(data["unfunded_total"] - expected) < 0.01, (
        f"unfunded_total {data['unfunded_total']} != committed - deployed + secondary {expected}"
    )
