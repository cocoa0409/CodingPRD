"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_timestamp_format,
)

REQUEST_STATUSES = [
    "DRAFT", "MATCHING", "OFFERED", "CONFIRMED", "IN_PROGRESS",
    "COMPLETED", "CANCELLED", "UNFILLED", "CLOSED",
]
ASSIGNMENT_STATUSES = [
    "OFFERED", "ACCEPTED", "CONFIRMED", "EN_ROUTE", "ON_SITE",
    "COMPLETED", "DECLINED", "EXPIRED", "CANCELLED", "NO_SHOW",
]
INTERPRETER_STATUSES = ["PENDING_ONBOARD", "ACTIVE", "SUSPENDED"]
LINE_ITEM_KINDS = [
    "LABOR", "TRAVEL_TIME", "MILEAGE", "PLATFORM_FEE",
    "CANCELLATION_FEE", "ADJUSTMENT",
]


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional digits)."""
    assert isinstance(value, str), f"Expected timestamp string, got {type(value)}"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_instant_equal(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 timestamps denote the same instant, regardless of
    fractional-digit rendering (PRD §2.5 renders three fractional digits)."""
    assert_timestamp_format(actual)
    actual_dt = parse_instant(actual)
    expected_dt = parse_instant(expected_iso)
    assert actual_dt == expected_dt, (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_org(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["org_type"] in ["MEDICAL", "LEGAL", "EDUCATION", "GENERAL"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)
    assert data["outstanding_balance_cents"] >= 0


def assert_rate_card(data: dict):
    assert_common_fields(data)
    assert data["modality"] in ["ASL_ONSITE", "CART_ONSITE", "VRI"]
    assert data["ada_context"] in ["MEDICAL", "LEGAL", "EDUCATION", "GENERAL"]
    assert data["credential_level"] in ["SCREENED", "CERTIFIED", "SPECIALIST"]
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["minimum_billable_minutes"], int)
    assert data["status"] in ["ACTIVE", "RETIRED"]


def assert_interpreter(data: dict):
    assert_common_fields(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["modalities_offered"], list) and len(data["modalities_offered"]) > 0
    for m in data["modalities_offered"]:
        assert m in ["ASL_ONSITE", "CART_ONSITE", "VRI"]
    assert data["status"] in INTERPRETER_STATUSES
    assert isinstance(data["active_strike_count"], int) and data["active_strike_count"] >= 0
    assert isinstance(data["quality_score"], int)
    assert isinstance(data["quality_score_provisional"], int)
    assert 0 <= data["quality_score"] <= 100
    assert 0 <= data["quality_score_provisional"] <= 100


def assert_certification(data: dict):
    assert_common_fields(data)
    assert data["credential"] in [
        "RID_NIC", "RID_CI_CT", "STATE_QA", "CART_CRR", "NAD_V", "LEGAL_SCL",
    ]
    assert data["level"] in ["SCREENED", "CERTIFIED", "SPECIALIST"]
    assert isinstance(data["verified"], bool)


def assert_availability_window(data: dict):
    assert_common_fields(data)
    assert is_iso8601_timestamp(data["start_at"])
    assert is_iso8601_timestamp(data["end_at"])
    assert isinstance(data["modalities"], list) and len(data["modalities"]) > 0


def assert_request(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("org_id", "")), "org_id must be a UUID"
    assert isinstance(data["consumer_name"], str) and len(data["consumer_name"]) > 0
    assert data["modality"] in ["ASL_ONSITE", "CART_ONSITE", "VRI"]
    assert data["ada_context"] in ["MEDICAL", "LEGAL", "EDUCATION", "GENERAL"]
    assert data["status"] in REQUEST_STATUSES
    assert data["required_credential_level"] in ["SCREENED", "CERTIFIED", "SPECIALIST"]
    assert isinstance(data["offer_attempt_count"], int) and data["offer_attempt_count"] >= 0


def assert_assignment(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("request_id", "")), "request_id must be a UUID"
    assert is_valid_uuid(data.get("interpreter_id", "")), "interpreter_id must be a UUID"
    assert data["status"] in ASSIGNMENT_STATUSES
    assert isinstance(data["estimated_cost_cents"], int)
    assert isinstance(data["pinned_hourly_rate_cents"], int)
    assert isinstance(data["pinned_minimum_billable_minutes"], int)
    assert is_iso8601_timestamp(data.get("offered_at", "")), "offered_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("response_deadline", "")), (
        "response_deadline must be ISO 8601"
    )


def assert_encounter(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a UUID"
    assert data["modality_delivered"] in ["ASL_ONSITE", "CART_ONSITE", "VRI"]
    assert is_iso8601_timestamp(data.get("actual_start", "")), "actual_start must be ISO 8601"
    assert isinstance(data["verified"], bool)


def assert_invoice(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("org_id", "")), "org_id must be a UUID"
    assert is_valid_uuid(data.get("assignment_id", "")), "assignment_id must be a UUID"
    assert data["issue_status"] in ["DRAFT", "ISSUED", "VOID"]
    assert data["dispute_status"] in ["NONE", "OPEN", "RESOLVED_UPHELD", "RESOLVED_OVERTURNED"]
    assert data["payment_status"] in ["UNPAID", "PARTIALLY_PAID", "PAID"]
    assert isinstance(data["line_items"], list)
    for line in data["line_items"]:
        assert line["kind"] in LINE_ITEM_KINDS, f"unexpected line kind {line.get('kind')}"
        assert isinstance(line["amount_cents"], int), "line amount_cents must be integer cents"
        assert "quantity" in line and "unit_rate_cents" in line


def assert_invoice_invariants(data: dict):
    """PRD §3.7 invariant: amount_due = max(0, subtotal - credits - payments)."""
    expected = max(
        0,
        data["subtotal_cents"]
        - data["credits_applied_cents"]
        - data["payments_applied_cents"],
    )
    assert data["amount_due_cents"] == expected, (
        f"amount_due_cents invariant broken: {data['amount_due_cents']} != "
        f"max(0, {data['subtotal_cents']} - {data['credits_applied_cents']} - "
        f"{data['payments_applied_cents']})"
    )
    assert data["subtotal_cents"] == sum(
        line["amount_cents"] for line in data["line_items"]
    ), "subtotal_cents must equal the sum of per-line rounded amount_cents"


def assert_complaint(data: dict):
    assert_common_fields(data)
    assert data["category"] in ["QUALITY", "LATENESS", "PROFESSIONALISM", "BILLING", "ACCESS"]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]
    assert data["status"] in ["FILED", "UNDER_REVIEW", "SUBSTANTIATED", "DISMISSED"]
    assert isinstance(data["reopen_count"], int) and data["reopen_count"] >= 0


def assert_credit_memo(data: dict):
    assert_common_fields(data)
    assert is_valid_uuid(data.get("org_id", "")), "org_id must be a UUID"
    assert data["status"] in ["OPEN", "EXHAUSTED", "VOID"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert isinstance(data["remaining_cents"], int) and data["remaining_cents"] >= 0
    assert isinstance(data["applications"], list)
    for app in data["applications"]:
        assert is_valid_uuid(app.get("invoice_id", "")), "application invoice_id must be a UUID"
        assert isinstance(app["amount_cents"], int) and app["amount_cents"] > 0


def assert_strike_record(data: dict):
    """StrikeRecord is append-only: id + created_at common fields only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ["ACTIVE", "RESCINDED"]
    assert "version" not in data, "StrikeRecord must not carry version"
    assert "updated_at" not in data, "StrikeRecord must not carry updated_at"


def assert_report(data: dict):
    assert_common_fields(data)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    for field in (
        "total_requests", "filled_count", "unfilled_count", "cancelled_count",
        "no_show_count", "total_billed_cents", "complaint_count", "substantiated_count",
    ):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be >= 0"
    assert isinstance(data["fulfillment_rate"], (int, float))
    assert isinstance(data["avg_response_minutes"], (int, float))
    mix = data["ada_context_mix"]
    for ctx in ("MEDICAL", "LEGAL", "EDUCATION", "GENERAL"):
        assert isinstance(mix.get(ctx), int), f"ada_context_mix must carry {ctx}"


def find_line(invoice: dict, kind: str) -> dict:
    """Return the single line item of the given kind from an invoice."""
    matches = [line for line in invoice["line_items"] if line["kind"] == kind]
    assert len(matches) == 1, (
        f"Expected exactly one {kind} line, found {len(matches)} "
        f"in {invoice['line_items']}"
    )
    return matches[0]
