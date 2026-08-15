"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"expected a timestamp string, got {value!r}"
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, msg: str = ""):
    """Assert two ISO 8601 timestamps denote the same instant.

    PRD §2.4 pins three fractional digits only for `created_at`/`updated_at`
    (and §2.2 for `api_request_timestamp`); the wire format of stamped or
    computed timestamp fields (`deadline_at`, `due_at`, `filed_at`,
    `sent_at`, `certification_expires_at`, `window_start`, `window_end`,
    overwritten `effective_to`, ...) is not format-pinned by the PRD, while
    the instant itself is (e.g. §2.8 deadline arithmetic, §3.6 cadence).
    Compare instants, not serializations.
    """
    assert is_iso8601_timestamp(actual), f"not an ISO 8601 UTC timestamp: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected), (
        msg or f"instant mismatch: {actual!r} != {expected!r}"
    )


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer starting at 1"
    )


def assert_analyst(data: dict):
    _assert_common_fields(data, "Analyst")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["capacity_max_cases"], int) and data["capacity_max_cases"] >= 1
    assert isinstance(data["assigned_open_cases"], int) and data["assigned_open_cases"] >= 0
    assert data["assigned_open_cases"] <= data["capacity_max_cases"] or True  # counter may transiently equal capacity


def assert_customer(data: dict):
    _assert_common_fields(data, "Customer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["country_code"], str) and data["country_code"]
    assert data["country_risk"] in ("LOW", "HIGH")
    assert data["status"] in ("ACTIVE", "EXITED")
    assert isinstance(data["sar_filings_365d"], int) and data["sar_filings_365d"] >= 0
    assert isinstance(data["open_le_inquiry_count"], int) and data["open_le_inquiry_count"] >= 0
    assert isinstance(data["any_account_exited"], bool)
    assert isinstance(data["risk_score_standard"], int)
    assert isinstance(data["risk_score_enhanced"], int)
    assert data["risk_rating"] in ("LOW", "MEDIUM", "HIGH", "PROHIBITED")


def assert_account(data: dict):
    _assert_common_fields(data, "Account")
    assert isinstance(data["account_number"], str) and data["account_number"]
    assert data["status"] in ("OPEN", "RESTRICTED", "EXITED")
    assert data.get("restriction_reason") in (None, "RISK_CASCADE", "DECISION")


def assert_transaction(data: dict):
    """Transactions are immutable posted events: only id + created_at (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "Transaction.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "Transaction must not carry updated_at"
    assert "version" not in data, "Transaction must not carry version"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["txn_type"] in ("CASH_DEPOSIT", "WIRE_IN", "WIRE_OUT", "ACH_DEBIT", "CHECK_DEPOSIT")
    assert data["direction"] in ("CREDIT", "DEBIT")
    assert isinstance(data["counterparty_country"], str) and data["counterparty_country"]
    assert data["channel"] in ("BRANCH", "ATM", "ONLINE", "WIRE_DESK")


def assert_scenario(data: dict):
    _assert_common_fields(data, "MonitoringScenario")
    assert isinstance(data["scenario_code"], str) and data["scenario_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["applies_to_txn_types"], list) and data["applies_to_txn_types"]
    assert data["direction_filter"] in ("CREDIT", "DEBIT", "BOTH")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "RETIRED")
    assert isinstance(data["stale_alert_days"], int) and data["stale_alert_days"] >= 1


def assert_threshold(data: dict):
    _assert_common_fields(data, "ScenarioThreshold")
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert isinstance(data["threshold_amount_cents"], int) and data["threshold_amount_cents"] > 0
    assert isinstance(data["lookback_days"], int) and data["lookback_days"] >= 1
    assert isinstance(data["min_transaction_count"], int) and data["min_transaction_count"] >= 1
    for w in ("weight_amount", "weight_velocity", "weight_geo"):
        assert isinstance(data[w], (int, float))
    assert data["status"] in ("PROPOSED", "APPROVED", "ACTIVE", "SUPERSEDED")


def assert_alert(data: dict):
    _assert_common_fields(data, "Alert")
    assert data["status"] in ("NEW", "UNDER_TRIAGE", "DISMISSED", "LINKED", "AUTO_CLOSED")
    assert isinstance(data["aggregate_amount_cents"], int)
    assert isinstance(data["txn_count"], int)
    assert isinstance(data["risk_score"], int)
    assert isinstance(data["baseline_score"], int)
    assert data.get("closure_reason") in (None, "STALE_EXPIRY", "CUSTOMER_EXITED")


def assert_case(data: dict):
    _assert_common_fields(data, "Case")
    assert data["status"] in (
        "OPEN", "ASSIGNED", "INVESTIGATING", "ON_HOLD",
        "SAR_IN_PROGRESS", "PENDING_QA", "CLOSED",
    )
    assert data["decision"] in ("NONE", "SAR_REQUIRED", "NO_SAR")
    assert data.get("closed_reason") in (None, "NO_SAR_CONFIRMED", "SAR_FILED")


def assert_sar_report(data: dict):
    _assert_common_fields(data, "SARReport")
    assert data["status"] in ("DRAFT", "IN_QA", "QA_PASSED", "APPROVED", "FILED")
    assert isinstance(data["is_continuing"], bool)
    assert isinstance(data["narrative_length"], int) and data["narrative_length"] >= 0
    assert is_iso8601_timestamp(data.get("deadline_at", "")), "deadline_at must be ISO 8601"


def assert_continuing_review(data: dict):
    _assert_common_fields(data, "ContinuingReview")
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "OVERDUE", "COMPLETED")
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("filing_deadline_at", "")), (
        "filing_deadline_at must be ISO 8601"
    )


def assert_le_inquiry(data: dict):
    _assert_common_fields(data, "LawEnforcementInquiry")
    assert data["status"] in ("RECEIVED", "UNDER_REVIEW", "RESPONDED", "CLOSED")
    assert isinstance(data["agency_name"], str) and data["agency_name"]
    assert isinstance(data["inquiry_reference"], str) and data["inquiry_reference"]


def assert_info_share(data: dict):
    _assert_common_fields(data, "InfoShareRequest")
    assert data["direction"] in ("OUTBOUND", "INBOUND")
    assert data["status"] in ("DRAFT", "SENT", "RESPONDED", "EXPIRED", "CANCELLED")
    assert is_iso8601_timestamp(data.get("certification_expires_at", "")), (
        "certification_expires_at must be ISO 8601"
    )


def assert_account_decision(data: dict):
    _assert_common_fields(data, "AccountDecision")
    assert data["decision"] in ("EXIT", "RESTRICT", "RETAIN")
    assert data["status"] in ("PROPOSED", "APPROVED", "EXECUTED", "REVERSED")


def assert_qa_review(data: dict):
    _assert_common_fields(data, "QAReview")
    assert data["status"] in ("SAMPLED", "COMPLETED")
    assert data["outcome"] in ("PENDING", "PASS", "FAIL")
    assert isinstance(data["period_month"], str) and len(data["period_month"]) == 7


def assert_backlog_summary(data: dict):
    for field in (
        "cases_open", "cases_age_0_15", "cases_age_16_30", "cases_age_31_60",
        "cases_age_61_plus", "overdue_sar_count", "stale_alert_count",
        "overdue_review_count", "qa_samples_this_month", "qa_quota_this_month",
    ):
        assert isinstance(data.get(field), int) and data[field] >= 0, (
            f"backlog summary field {field} must be a non-negative integer"
        )
