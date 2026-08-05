"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_APP_STATUSES = [
    "DRAFT", "SUBMITTED", "UNDER_REVIEW", "REVISIONS_REQUESTED", "APPROVED",
    "PERMIT_ISSUED", "EVENT_COMPLETE", "CLOSED", "DENIED", "REVOKED",
]


def assert_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "application id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in _APP_STATUSES, f"unexpected status {data.get('status')}"
    assert data["deposit_status"] in ["NONE", "HELD", "REFUNDED", "FORFEITED"]
    assert isinstance(data["balance_due_cents"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["pending_review_count"], int)
    assert isinstance(data["approved_review_count"], int)
    assert isinstance(data["rejected_review_count"], int)
    assert isinstance(data["total_review_count"], int)


def assert_venue(data: dict):
    assert is_valid_uuid(data.get("id", "")), "venue id must be a valid UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["occupancy_limit"], int)


def assert_server(data: dict):
    assert is_valid_uuid(data.get("id", "")), "server id must be a valid UUID"
    assert data["status"] in ["PENDING", "VERIFIED"]
    assert data["training_provider"] in ["TIPS", "SERVSAFE_ALCOHOL", "STATE_APPROVED"]


def assert_insurance_policy(data: dict):
    assert is_valid_uuid(data.get("id", "")), "policy id must be a valid UUID"
    assert data["status"] in ["SUBMITTED", "ACCEPTED"]
    assert isinstance(data["coverage_cents"], int)


def assert_security_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "plan id must be a valid UUID"
    assert data["status"] in ["SUBMITTED", "APPROVED"]
    assert isinstance(data["required_guard_count"], int)


def assert_agency_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "review id must be a valid UUID"
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED", "APPROVED_WITH_CONDITIONS"]


def assert_inspection(data: dict):
    assert is_valid_uuid(data.get("id", "")), "inspection id must be a valid UUID"
    assert data["result"] in ["SCHEDULED", "PASSED", "FAILED"]


def assert_violation(data: dict):
    assert is_valid_uuid(data.get("id", "")), "violation id must be a valid UUID"
    assert data["status"] in ["ISSUED", "CONTESTED", "UPHELD", "DISMISSED"]
    assert data["severity"] in ["MINOR", "MAJOR", "CRITICAL"]


def assert_report(data: dict):
    assert is_valid_uuid(data.get("id", "")), "report id must be a valid UUID"
    assert data["status"] in ["FILED", "ACCEPTED"]


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: only id + created_at are guaranteed common fields."""
    assert is_valid_uuid(data.get("id", "")), "ledger entry id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only LedgerEntry must not carry updated_at"
    assert "version" not in data, "append-only LedgerEntry must not carry version"


def find_ledger_entry(entries: list, entry_type: str, amount_cents=None):
    """Return the first ledger entry matching entry_type (and amount_cents if given)."""
    for e in entries:
        if e.get("entry_type") == entry_type and (amount_cents is None or e.get("amount_cents") == amount_cents):
            return e
    return None
