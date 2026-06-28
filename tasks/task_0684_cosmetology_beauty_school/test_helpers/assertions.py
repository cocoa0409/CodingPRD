"""Entity assertions and domain invariant checkers.

Built on the framework's generic validators (is_valid_uuid,
is_iso8601_timestamp). Field names are exactly as the PRD defines them.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common fields carried by every entity in this domain (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["total_clock_hours"], int)
    assert isinstance(data["tuition_cents"], int)
    assert isinstance(data["kit_fee_cents"], int)
    assert isinstance(data["lab_fee_cents"], int)
    assert isinstance(data["clinic_phase_start_hour"], int)
    assert isinstance(data["credit_hours"], int)
    assert isinstance(data["admin_fee_cap_cents"], int)


def assert_student(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["status"] in ("PROSPECT", "ENROLLED", "ARCHIVED")


def assert_instructor(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["license_number"], str)
    assert isinstance(data["active"], bool)


def assert_station(data: dict):
    _assert_common(data)
    assert isinstance(data["label"], str)
    assert data["station_type"] in ("HAIR", "NAIL", "SKIN", "MAKEUP")
    assert data["status"] in ("AVAILABLE", "OCCUPIED", "OUT_OF_SERVICE")


def assert_enrollment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["student_id"])
    assert is_valid_uuid(data["program_id"])
    assert data["status"] in (
        "ACTIVE", "SAP_WARNING", "EXAM_PENDING", "GRADUATED", "WITHDRAWN",
    )
    assert isinstance(data["scheduled_hours_to_date"], int)
    assert isinstance(data["total_charges_cents"], int)
    assert isinstance(data["total_credits_cents"], int)
    assert isinstance(data["ledger_balance_cents"], int)
    assert data["placement_status"] in (
        "UNREPORTED", "PLACED", "UNPLACED", "EXCLUDED",
    )


def assert_attendance_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["instructor_id"])
    assert data["record_type"] in ("REGULAR", "MAKEUP")
    assert data["status"] in ("PENDING", "APPROVED", "VOIDED")


def assert_clinic_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["instructor_id"])
    assert data["status"] in ("OPEN", "SIGNED_OFF", "PAID", "VOIDED")


def assert_station_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["station_id"])
    assert is_valid_uuid(data["enrollment_id"])
    assert is_valid_uuid(data["instructor_id"])
    assert data["status"] in ("RESERVED", "RELEASED")


def assert_disbursement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["payment_period"] in (1, 2)
    assert data["status"] in ("SCHEDULED", "POSTED", "RETURNED")


def assert_exam_application(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["exam_type"] in ("WRITTEN", "PRACTICAL")
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "RETURNED_FOR_REVISION",
        "APPROVED", "SCHEDULED", "PASSED", "FAILED",
    )


def assert_withdrawal(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["enrollment_id"])
    assert data["withdrawal_type"] in ("OFFICIAL", "UNOFFICIAL")
    assert data["status"] in ("CALCULATED", "FINALIZED")


# --------------------------------------------------------------------------
# Domain invariant checkers
# --------------------------------------------------------------------------
def assert_ledger_consistent(enrollment: dict):
    """PRD §3.5: ledger_balance_cents == total_charges_cents - total_credits_cents,
    all exact integer cents."""
    assert isinstance(enrollment["total_charges_cents"], int)
    assert isinstance(enrollment["total_credits_cents"], int)
    assert isinstance(enrollment["ledger_balance_cents"], int)
    assert (
        enrollment["ledger_balance_cents"]
        == enrollment["total_charges_cents"] - enrollment["total_credits_cents"]
    ), "ledger_balance_cents must equal charges minus credits"
