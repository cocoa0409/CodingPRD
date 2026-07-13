"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the common structural fields and the
entity-specific fields against the PRD's declared shape.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_client(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED"), f"unexpected client status {data['status']!r}"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["outstanding_balance_cents"], int)


def assert_caregiver(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "INACTIVE"), f"unexpected caregiver status {data['status']!r}"
    assert isinstance(data["committed_minutes"], int)
    assert data["committed_minutes"] >= 0


def assert_background_check(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "CLEARED", "FLAGGED", "EXPIRED")


def assert_bond(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "LAPSED")


def assert_schedule(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "PAUSED", "ENDED")
    assert data["task_type"] in ("GROCERY", "RX_PICKUP", "TRANSPORT", "COMPANION")


def assert_visit(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "ESCALATED", "COMPLETED", "CANCELLED")
    assert data["task_type"] in ("GROCERY", "RX_PICKUP", "TRANSPORT", "COMPANION")
    assert isinstance(data["hourly_rate_cents"], int), "visit must snapshot hourly_rate_cents"


def assert_assignment(data: dict):
    _assert_common(data)
    assert data["status"] in ("CONFIRMED", "SUPERSEDED", "CANCELLED")
    assert is_valid_uuid(data.get("visit_id", "")), "assignment.visit_id must be a UUID"
    assert is_valid_uuid(data.get("caregiver_id", "")), "assignment.caregiver_id must be a UUID"


def assert_addon(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "REJECTED")
    assert data["addon_type"] in ("MEAL_PREP", "PET_CARE", "PAPERWORK", "EXTRA_STOP")
    assert isinstance(data["fee_cents"], int)


def assert_invoice(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "FINALIZED", "VOID")
    for f in ("labor_cents", "mileage_cents", "addon_cents", "total_cents"):
        assert isinstance(data[f], int), f"invoice.{f} must be integer cents"
    assert data["total_cents"] == data["labor_cents"] + data["mileage_cents"] + data["addon_cents"], (
        "invoice total must equal the sum of its rounded line items"
    )


def assert_ltc_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "EXHAUSTED")
    assert data["benefit_type"] in ("INDEMNITY", "REIMBURSEMENT")
    assert isinstance(data["reimbursed_to_date_cents"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "NEEDS_INFO", "APPROVED", "DENIED", "WITHDRAWN")
    assert data["benefit_type"] in ("INDEMNITY", "REIMBURSEMENT")
    for f in ("eligible_cents", "reimbursed_cents", "client_responsibility_cents"):
        assert isinstance(data[f], int), f"claim.{f} must be integer cents"


def assert_wellness_check(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "ACKNOWLEDGED", "RESOLVED")
    assert data["severity"] in ("LOW", "MEDIUM", "HIGH")


def assert_visit_log_entry(data: dict):
    """VisitLogEntry is append-only: it carries ONLY id + created_at, with no
    updated_at and no version field."""
    assert is_valid_uuid(data.get("id", "")), "log entry id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_type"] in ("NOTE", "TASK_DONE", "INCIDENT")
    assert "updated_at" not in data, "append-only VisitLogEntry must not carry updated_at"
    assert "version" not in data, "append-only VisitLogEntry must not carry version"
