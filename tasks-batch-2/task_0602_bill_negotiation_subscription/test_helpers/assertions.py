"""Entity assertions for the bill-negotiation domain."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "member id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["lifetime_gross_savings_cents"], int)
    assert isinstance(data["lifetime_member_savings_cents"], int)
    assert isinstance(data["version"], int)


def assert_savings_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "CLOSED"]
    assert isinstance(data["balance_cents"], int)
    assert data["balance_cents"] >= 0, "balance_cents never negative"


def assert_linked_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["LINKED", "UNLINKED"]
    assert data["account_type"] in ["CHECKING", "CREDIT_CARD"]
    assert isinstance(data["detected_charge_count"], int)
    assert data["detected_charge_count"] >= 0


def assert_recurring_charge(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["DETECTED", "CONFIRMED", "DISMISSED"]
    assert data["cadence"] in ["MONTHLY", "ANNUAL", "WEEKLY"]
    assert data["category"] in ["STREAMING", "TELECOM", "INSURANCE", "UTILITY", "SOFTWARE", "OTHER"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["annualized_cost_cents"], int)


def assert_subscription(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "CANCEL_REQUESTED", "CANCELLED", "CANCEL_FAILED"]
    assert isinstance(data["is_free_trial"], bool)
    assert isinstance(data["reminder_due"], bool)
    assert isinstance(data["version"], int)


def assert_negotiation_case(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "PROPOSED", "COUNTERED", "WON", "LOST", "CANCELLED"]
    assert isinstance(data["baseline_annual_cost_cents"], int)
    assert isinstance(data["round_count"], int)
    assert isinstance(data["gross_annual_savings_cents"], int)
    assert isinstance(data["success_fee_cents"], int)
    assert isinstance(data["member_net_savings_cents"], int)
    assert isinstance(data["version"], int)


def assert_refund_claim(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["FILED", "UNDER_REVIEW", "DISPUTED", "REFUNDED", "DENIED"]
    assert data["claim_type"] in ["PRICE_DROP", "DOUBLE_BILL", "SERVICE_OUTAGE"]
    assert isinstance(data["claimed_refund_cents"], int)
    assert isinstance(data["dispute_round"], int)
    assert isinstance(data["version"], int)


def assert_concierge_agent(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["max_open_cases"], int)
    assert isinstance(data["open_case_count"], int)
    # common_fields: false — no version / updated_at expected
    assert "version" not in data or data.get("version") is None


def assert_ledger_entry(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["source_type"] in ["NEGOTIATION", "REFUND"]
    assert data["transfer_status"] in ["PENDING", "TRANSFERRED", "REVERSED"]
    assert isinstance(data["gross_savings_cents"], int)
    assert isinstance(data["success_fee_cents"], int)
    assert isinstance(data["member_net_cents"], int)
