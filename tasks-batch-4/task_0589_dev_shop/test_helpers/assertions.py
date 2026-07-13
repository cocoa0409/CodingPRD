"""Entity assertions and domain invariant checkers (PRD 2.4, 2.9)."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Every resource carries id / created_at / updated_at / version (PRD 2.4)."""
    assert is_valid_uuid(
        data.get("id", "")
    ), f"id must be a server-minted UUID with no type prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"created_at must be ISO 8601 UTC, got {data.get('created_at')!r}"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"updated_at must be ISO 8601 UTC, got {data.get('updated_at')!r}"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, f"version starts at 1, got {data['version']}"


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp into a naive-UTC datetime for comparison
    against a known logical-clock instant (PRD 2.4)."""
    assert value is not None, "expected a stamped timestamp, got null"
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def assert_instant_equals(value: str, expected_iso: str):
    """The stamped instant must equal the logical clock's value at the moment of
    the write (PRD 2.4), regardless of the textual ISO 8601 rendering."""
    assert parse_instant(value) == parse_instant(
        expected_iso
    ), f"expected instant {expected_iso}, got {value}"


def assert_client(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["billing_email"], str) and len(data["billing_email"]) > 0
    assert (
        isinstance(data["country_code"], str)
        and len(data["country_code"]) == 2
        and data["country_code"].isupper()
    ), "country_code is exactly two uppercase letters"


def assert_engagement(data: dict):
    _assert_common(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["source_channel"] in ["REFERRAL", "INBOUND", "OUTBOUND", "PARTNER"]
    assert data["status"] in [
        "LEAD",
        "QUALIFIED",
        "DISQUALIFIED",
        "SOW_ISSUED",
        "ACTIVE",
        "CLOSED",
    ]
    assert data["billing_status"] in ["UNBILLED", "PARTIALLY_BILLED", "FULLY_BILLED"]
    assert data["budget_posture"] in ["HEALTHY", "AT_RISK", "OVERBURNED"]
    assert data["approved_hours"] >= 0
    assert data["burned_cost"] >= 0
    assert data["burn_ratio"] >= 0
    assert data["invoiced_amount"] >= 0


def assert_milestone(data: dict):
    _assert_common(data)
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["amount"] > 0, "milestone amount is strictly greater than zero"
    assert data["status"] in ["PLANNED", "COMPLETED", "BILLED"]


def assert_sprint(data: dict):
    _assert_common(data)
    assert isinstance(data["engagement_id"], str)
    assert data["status"] in ["PLANNED", "ACTIVE", "CLOSED"]
    assert isinstance(data["spend_frozen"], bool)
    assert data["committed_hours"] >= 0
    assert data["start_date"] < data["end_date"]


def assert_ticket(data: dict):
    _assert_common(data)
    assert isinstance(data["sprint_id"], str)
    assert isinstance(data["title"], str) and len(data["title"]) > 0
    assert data["estimated_hours"] > 0, "estimated_hours is strictly greater than zero"
    assert isinstance(data["assignee_user_id"], str)
    assert data["status"] in [
        "TODO",
        "IN_PROGRESS",
        "IN_QA",
        "REWORK",
        "DONE",
        "CANCELLED",
    ]
    assert data["actual_hours"] >= 0
    assert data["variance_ratio"] >= 0
    assert isinstance(data["rework_rounds"], int) and data["rework_rounds"] >= 0


def assert_time_entry(data: dict):
    _assert_common(data)
    assert isinstance(data["ticket_id"], str)
    assert isinstance(data["employee_user_id"], str)
    assert 0 < data["hours"] <= 12, "hours are strictly above 0 and no greater than 12"
    assert isinstance(data["billable"], bool)
    assert data["status"] in ["SUBMITTED", "APPROVED", "REJECTED", "REVERSED"]


def assert_change_request(data: dict):
    _assert_common(data)
    assert isinstance(data["engagement_id"], str)
    assert data["delta_hours"] > 0, "delta_hours is strictly greater than zero"
    assert isinstance(data["rush"], bool)
    assert data["quoted_amount"] >= 0
    assert data["status"] in [
        "DRAFT",
        "SUBMITTED",
        "REVISION_REQUESTED",
        "APPROVED",
        "REJECTED",
    ]
    assert isinstance(data["revision_rounds"], int) and 0 <= data["revision_rounds"] <= 2


def assert_release(data: dict):
    _assert_common(data)
    assert isinstance(data["engagement_id"], str)
    assert isinstance(data["milestone_id"], str)
    assert data["status"] in ["BUILDING", "QA_PASSED", "REWORK", "ACCEPTED", "DEPLOYED"]
    assert isinstance(data["defect_count"], int) and data["defect_count"] >= 0
    assert isinstance(data["qa_rounds"], int) and data["qa_rounds"] >= 0


def assert_invoice(data: dict):
    _assert_common(data)
    assert isinstance(data["engagement_id"], str)
    assert data["kind"] in ["MILESTONE", "TIME_AND_MATERIALS", "RETAINER"]
    assert data["status"] in ["DRAFT", "ISSUED", "PAID", "VOID"]
    assert isinstance(data["lines"], list)
    for line in data["lines"]:
        assert "label" in line and "amount" in line, "each line carries a label and an amount"
    assert data["tax"] >= 0, "tax is never negative"


def assert_retainer(data: dict):
    _assert_common(data)
    assert isinstance(data["client_id"], str)
    assert isinstance(data["engagement_id"], str)
    assert data["monthly_fee"] > 0
    assert data["included_hours"] >= 0
    assert data["sla_tier"] in ["GOLD", "SILVER", "BRONZE"]
    assert data["start_date"] <= data["end_date"]


def assert_support_incident(data: dict):
    _assert_common(data)
    assert isinstance(data["retainer_id"], str)
    assert data["severity"] in ["SEV1", "SEV2", "SEV3"]
    assert data["status"] in ["OPEN", "RESPONDED", "RESOLVED"]
    assert is_iso8601_timestamp(data.get("opened_at", "")), "opened_at is stamped at creation"
    assert isinstance(data["sla_response_breached"], bool)
    assert isinstance(data["sla_resolution_breached"], bool)
    assert data["sla_credit_amount"] >= 0


# --- Domain invariants (PRD 2.9) -------------------------------------------


def assert_lines_sum_to_subtotal(invoice: dict):
    """The subtotal is the plain arithmetic sum of the already-rounded line
    amounts, with no further rounding applied (PRD 2.8, 3.8)."""
    line_sum = round(sum(line["amount"] for line in invoice["lines"]), 2)
    assert abs(invoice["subtotal"] - line_sum) < 1e-9, (
        f"subtotal {invoice['subtotal']} must equal the plain sum of the rounded "
        f"line amounts {line_sum}"
    )


def assert_total_is_subtotal_plus_tax(invoice: dict):
    """total is subtotal plus tax, with no further rounding (PRD 3.8)."""
    assert abs(invoice["total"] - (invoice["subtotal"] + invoice["tax"])) < 0.005, (
        f"total {invoice['total']} must equal subtotal {invoice['subtotal']} + "
        f"tax {invoice['tax']}"
    )


def assert_billing_status_matches_ledger(engagement: dict):
    """billing_status is a pure function of invoiced_amount against
    contract_value (PRD 2.9)."""
    invoiced = engagement["invoiced_amount"]
    contract = engagement["contract_value"]
    if invoiced == 0:
        expected = "UNBILLED"
    elif contract is not None and invoiced >= contract:
        expected = "FULLY_BILLED"
    else:
        expected = "PARTIALLY_BILLED"
    assert engagement["billing_status"] == expected, (
        f"billing_status {engagement['billing_status']} disagrees with the money "
        f"ledger (invoiced_amount {invoiced} against contract_value {contract}); "
        f"expected {expected}"
    )


def assert_posture_matches_ratio(engagement: dict):
    """budget_posture is a threshold read on the 4-decimal burn_ratio, and both
    boundaries are inclusive (PRD 3.5)."""
    ratio = engagement["burn_ratio"]
    if ratio >= 1.0:
        expected = "OVERBURNED"
    elif ratio >= 0.9:
        expected = "AT_RISK"
    else:
        expected = "HEALTHY"
    assert engagement["budget_posture"] == expected, (
        f"budget_posture {engagement['budget_posture']} disagrees with burn_ratio "
        f"{ratio}; expected {expected}"
    )
