"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_election(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["jurisdiction"], str)
    assert data["status"] in ("PLANNING", "VOTING_OPEN", "VOTING_CLOSED")
    assert isinstance(data["initial_ballot_stock"], int)
    assert isinstance(data["unallocated_ballot_stock"], int)
    assert data["unallocated_ballot_stock"] >= 0, "unallocated_ballot_stock must be >= 0"


def assert_polling_place(data: dict):
    _assert_common(data)
    assert data["readiness_posture"] in ("SETUP", "OPEN", "SUSPENDED", "CLOSED", "RECONCILED")
    assert data["reconciliation_status"] in ("UNRECONCILED", "BALANCED", "MISMATCH")
    assert isinstance(data["slots_filled"], int)
    assert isinstance(data["slots_open"], int)
    # Staffing-slot invariant (PRD Section 2.10).
    assert data["slots_filled"] + data["slots_open"] == data["staffing_capacity"], (
        "slots_filled + slots_open must equal staffing_capacity"
    )


def assert_equipment(data: dict):
    _assert_common(data)
    assert data["equipment_type"] in ("SCANNER", "BMD", "EPOLLBOOK", "PRINTER")
    assert data["status"] in ("IN_WAREHOUSE", "OPERATIONAL", "OUT_OF_SERVICE")


def assert_poll_worker(data: dict):
    _assert_common(data)
    assert data["training_status"] in ("PENDING", "CERTIFIED")
    assert isinstance(data["accrued_payroll_cents"], int)


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("PROPOSED", "ACTIVE", "WITHDRAWN")
    assert isinstance(data["is_lead"], bool)


def assert_shift(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "CHECKED_IN", "CHECKED_OUT")
    assert isinstance(data["is_lead"], bool)


def assert_supply_kit(data: dict):
    _assert_common(data)
    assert data["custody_state"] in (
        "PREPARED", "ISSUED", "IN_TRANSIT", "AT_PLACE",
        "RETURN_PENDING", "RECONCILED", "COMPROMISED",
    )
    assert isinstance(data["ballot_count"], int)


def assert_provisional_ballot(data: dict):
    _assert_common(data)
    assert data["status"] in ("CAST", "ACCEPTED", "REJECTED")


def assert_incident(data: dict):
    _assert_common(data)
    assert data["category"] in ("EQUIPMENT", "STAFFING", "SECURITY", "ACCESSIBILITY", "OTHER")
    assert data["severity"] in ("LOW", "CRITICAL")
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED", "RESOLVED")


def assert_custody_event(data: dict):
    """Append-only audit record — carries only id + created_at (PRD Section 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "custody event id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["event_type"] in (
        "ISSUE", "DISPATCH", "RECEIVE", "RETURN", "RECONCILE", "SEAL_BREAK", "VOID_ISSUE",
    )
