"""Entity assertions and domain invariant checkers (PRD §2.5, §3)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with optional fractional digits / Z)."""
    assert isinstance(value, str) and value, f"expected ISO timestamp string, got {value!r}"
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str, label: str = "timestamp"):
    """Two ISO 8601 strings denote the same instant (second-precision comparisons, PRD §2.4)."""
    assert parse_instant(actual) == parse_instant(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be an integer >= 1"
    )


def assert_covered_person(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["designation"] in [
        "SECTION_16_OFFICER", "DIRECTOR", "EMPLOYEE", "CONSULTANT",
    ]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["policy_ack_current"], bool)
    assert isinstance(data["training_current"], bool)
    assert isinstance(data["compliance_hold"], bool)


def assert_deal(data: dict):
    _assert_common(data)
    assert data["deal_type"] in [
        "MERGER", "ACQUISITION", "DIVESTITURE", "FINANCING", "RESTRUCTURING",
    ]
    assert data["status"] in ["INTAKE", "ACTIVE", "CLOSED", "ABANDONED"]
    assert isinstance(data["security_ticker"], str) and data["security_ticker"]


def assert_restricted_list_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["security_ticker"], str) and data["security_ticker"]
    assert data["source"] in ["DEAL_INTAKE", "MANUAL"]
    assert data["status"] in ["ACTIVE", "REMOVED"]


def assert_blackout_window(data: dict):
    _assert_common(data)
    assert data["kind"] in ["QUARTERLY", "EVENT_DRIVEN"]
    assert data["status"] in ["SCHEDULED", "ACTIVE", "LIFTED", "CANCELLED", "MERGED"]
    assert is_iso8601_timestamp(data.get("start_at", ""))
    assert is_iso8601_timestamp(data.get("end_at", ""))


def assert_preclearance_request(data: dict):
    _assert_common(data)
    assert data["trade_side"] in ["BUY", "SELL"]
    assert data["status"] in [
        "SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED",
        "WITHDRAWN", "EXPIRED", "VOIDED", "CLOSED",
    ]
    assert data["quantity"] > 0


def assert_exception_request(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "APPROVED", "DENIED", "WITHDRAWN", "EXPIRED"]
    assert isinstance(data["votes_for"], int)
    assert isinstance(data["votes_against"], int)
    assert isinstance(data["voter_ids"], list)


def assert_tenb5_plan(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "APPROVED", "RETURNED",
        "ACTIVE", "SUSPENDED", "TERMINATED", "CANCELLED",
    ]
    assert data["total_quantity"] > 0


def assert_trade_confirmation(data: dict):
    _assert_common(data)
    assert data["trade_side"] in ["BUY", "SELL"]
    assert data["status"] in [
        "RECEIVED", "MATCHED_PRECLEARANCE", "MATCHED_PLAN", "FLAGGED", "CLEARED",
    ]
    assert data["quantity"] > 0
    assert data["price"] > 0


def assert_violation_case(data: dict):
    _assert_common(data)
    assert data["violation_type"] in [
        "BLACKOUT_TRADE", "NO_PRECLEARANCE", "RESTRICTED_LIST", "PLAN_VIOLATION", "OTHER",
    ]
    assert data["source"] in ["AUTO_FLAG", "MANUAL"]
    assert data["status"] in [
        "OPENED", "UNDER_INVESTIGATION", "ESCALATED", "SUBSTANTIATED",
        "UNFOUNDED", "SANCTION_RECORDED", "CLOSED",
    ]


def assert_attestation(data: dict):
    _assert_common(data)
    assert data["kind"] in ["POLICY_ACK", "ANNUAL_TRAINING"]
    assert data["status"] in ["ASSIGNED", "COMPLETED", "OVERDUE"]
    assert isinstance(data["period_year"], int)


def assert_quantity_conservation(request: dict):
    """Share balance invariant on a preclearance request:
    quantity == matched_quantity + remaining_quantity (PRD §3.4/§3.7)."""
    matched = request["matched_quantity"]
    remaining = request["remaining_quantity"]
    assert abs((matched + remaining) - request["quantity"]) < 1e-6, (
        f"quantity conservation broken: {request['quantity']} != "
        f"{matched} (matched) + {remaining} (remaining)"
    )
