"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["mrn"], str) and data["mrn"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["date_of_birth"], str) and data["date_of_birth"]


def assert_program(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "ON_HOLD", "DISCHARGED", "WITHDRAWN")
    assert data["program_type"] in ("CARDIAC", "PULMONARY")
    assert data["risk_stratification"] in ("LOW", "MODERATE", "HIGH")
    assert isinstance(data["authorized_session_cap"], int)
    for counter in (
        "sessions_used",
        "sessions_scheduled",
        "sessions_remaining_authorized",
        "consecutive_missed_count",
        "total_billed_cents",
        "total_reimbursed_cents",
        "total_patient_responsibility_cents",
        "outstanding_balance_cents",
    ):
        assert isinstance(data[counter], int), f"{counter} must be an integer"


def assert_program_money_identity(data: dict):
    """Over non-VOID claims: total_billed == total_reimbursed + total_patient_responsibility (PRD §2.9)."""
    assert data["total_billed_cents"] == (
        data["total_reimbursed_cents"] + data["total_patient_responsibility_cents"]
    ), "money identity total_billed == total_reimbursed + total_patient_responsibility must hold"


def assert_program_capacity_identity(data: dict):
    """authorized_session_cap == sessions_used + sessions_remaining_authorized (PRD §2.8)."""
    assert data["authorized_session_cap"] == (
        data["sessions_used"] + data["sessions_remaining_authorized"]
    ), "capacity identity cap == sessions_used + sessions_remaining_authorized must hold"


def assert_session(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "MISSED", "CANCELLED", "VOIDED")
    assert data["session_type"] in ("MONITORED_EXERCISE", "EDUCATION", "ASSESSMENT")


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "PAID", "DENIED", "VOID")
    assert isinstance(data["billed_amount_cents"], int)


def assert_outcome(data: dict):
    _assert_common(data)
    assert data["timing"] in ("BASELINE", "DISCHARGE")
    assert data["status"] in ("DRAFT", "FINALIZED")


def assert_maintenance_program(data: dict):
    _assert_common(data)
    assert data["tier"] in ("STANDARD", "INTENSIVE")
    assert data["status"] in ("ACTIVE", "CANCELLED")
