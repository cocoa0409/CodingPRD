"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """Common properties every resource carries (PRD §2.5)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive integer"


def assert_employee(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["employee_ref"], str) and data["employee_ref"]
    assert data["department"] in ["TRADING", "OPERATIONS", "COMPLIANCE", "EXECUTIVE"]
    assert data["employment_status"] in ["ACTIVE", "ON_LEAVE", "TERMINATED"]
    assert data["attestation_status"] in ["CURRENT", "DUE", "LAPSED"]
    assert isinstance(data["open_case_count"], int) and data["open_case_count"] >= 0
    assert isinstance(data["training_overdue_count"], int) and data["training_overdue_count"] >= 0


def assert_venue(data: dict):
    _assert_common(data)
    assert isinstance(data["venue_code"], str) and data["venue_code"]
    assert data["venue_type"] in ["EXCHANGE", "ATS", "MARKET_MAKER"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_arrangement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("venue_id", ""))
    assert data["status"] in ["NEGOTIATION", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["pfof_tiers"], list) and len(data["pfof_tiers"]) >= 1
    assert data["pfof_tiers"][0]["min_monthly_shares"] == 0


def assert_order(data: dict):
    _assert_common(data)
    assert data["side"] in ["BUY", "SELL"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["order_type"] in ["MARKET", "LIMIT", "MARKET_ON_CLOSE"]
    assert data["status"] in ["RECEIVED", "ROUTED", "EXECUTED", "CANCELLED"]
    assert data["arrival_nbbo_ask_cents"] > data["arrival_nbbo_bid_cents"]


def assert_snapshot(data: dict):
    _assert_common(data)
    assert data["order_type"] in ["MARKET", "LIMIT", "MARKET_ON_CLOSE"]
    assert data["variant"] in ["FAR_TOUCH", "MIDPOINT"]
    assert data["status"] in ["PROVISIONAL", "LOCKED"]
    assert isinstance(data["order_count"], int) and data["order_count"] >= 0
    assert isinstance(data["total_quantity"], int) and data["total_quantity"] >= 0
    assert isinstance(data["total_improvement_cents"], (int, float))
    assert isinstance(data["avg_improvement_cents_per_share"], (int, float))


def assert_disclosure(data: dict):
    _assert_common(data)
    assert data["pricing_variant"] in ["MARGINAL", "RETROACTIVE"]
    assert data["status"] in ["DRAFT", "PENDING_APPROVAL", "PUBLISHED", "SUPERSEDED"]
    assert isinstance(data["revision_number"], int) and data["revision_number"] >= 1
    assert isinstance(data["venue_lines"], list)
    assert isinstance(data["total_pfof_cents"], int)


def assert_review(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "IN_COMMITTEE", "APPROVED", "PUBLISHED"]
    assert isinstance(data["snapshot_ids"], list)
    assert isinstance(data["venue_decisions"], list)
    assert isinstance(data["voter_user_ids"], list)
    assert isinstance(data["created_by_user_id"], str)


def assert_alert(data: dict):
    _assert_common(data)
    assert data["alert_type"] in ["FRONT_RUNNING", "MARKING_THE_CLOSE"]
    assert data["status"] in ["NEW", "ACKNOWLEDGED", "ESCALATED", "CLOSED_FALSE_POSITIVE"]
    assert isinstance(data["score"], int)
    assert isinstance(data["score_inputs"], dict)


def assert_case(data: dict):
    _assert_common(data)
    assert data["opened_from"] in ["ALERT", "COMM_REVIEW"]
    assert data["review_status"] in ["OPEN", "UNDER_INVESTIGATION", "DISPOSITIONED", "REOPENED"]
    assert data["filing_status"] in ["NOT_REQUIRED", "DRAFT", "SUBMITTED", "ACKNOWLEDGED"]
    assert isinstance(data["linked_alert_ids"], list)
    assert isinstance(data["late_fee_cents"], int) and data["late_fee_cents"] >= 0


def assert_personal_trade(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert data["side"] in ["BUY", "SELL"]
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in [
        "PRECLEARANCE_REQUESTED", "APPROVED", "DENIED",
        "EXECUTION_REPORTED", "RECONCILED", "EXPIRED",
    ]


def assert_restricted_entry(data: dict):
    _assert_common(data)
    assert data["restriction_kind"] in ["ALL", "EMPLOYEE_ONLY", "CLIENT_ONLY"]
    assert data["status"] in ["SCHEDULED", "ACTIVE", "EXPIRED"]


def assert_comm_item(data: dict):
    _assert_common(data)
    assert data["channel"] in ["EMAIL", "CHAT"]
    assert data["status"] in ["QUEUED", "IN_REVIEW", "CLEARED", "ESCALATED"]
    assert isinstance(data["score"], int)
    assert isinstance(data["matched_terms"], list)


def assert_lexicon_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["terms"], list)
    assert data["status"] in ["DRAFT", "ACTIVE", "RETIRED"]


def assert_compliance_policy(data: dict):
    _assert_common(data)
    assert isinstance(data["policy_code"], str) and data["policy_code"]
    assert data["status"] in ["DRAFT", "EFFECTIVE", "SUPERSEDED"]


def assert_training_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("employee_id", ""))
    assert is_valid_uuid(data.get("policy_id", ""))
    assert data["status"] in ["ASSIGNED", "OVERDUE", "COMPLETED", "CANCELLED"]
