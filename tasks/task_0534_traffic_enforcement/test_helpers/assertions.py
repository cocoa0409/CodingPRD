"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Field names are PRD-exact.
Append-only artifacts (CalibrationRecord, NoticeRecord) carry only id + created_at.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

CITATION_STATES = [
    "PENDING_REVIEW", "REJECTED", "CITED", "CONTESTED", "HEARING_SCHEDULED",
    "ADJUDICATED_UPHELD", "ADJUDICATED_DISMISSED", "PAID", "DELINQUENT", "VOID",
]


def _assert_common(data: dict):
    """Common server-managed fields on full resources (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def _assert_audit_common(data: dict):
    """Append-only audit artifacts carry only id + created_at (PRD 2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_program(data: dict):
    _assert_common(data)
    assert isinstance(data["jurisdiction_name"], str) and len(data["jurisdiction_name"]) > 0
    assert isinstance(data["base_red_light_fine_cents"], int)
    assert isinstance(data["base_speed_fine_cents"], int)
    assert isinstance(data["admin_fee_cents"], int)
    assert isinstance(data["late_fee_cents"], int)


def assert_camera(data: dict):
    _assert_common(data)
    assert data["camera_type"] in ("RED_LIGHT", "SPEED")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "DECOMMISSIONED")


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["plate_number"], str) and len(data["plate_number"]) > 0
    assert isinstance(data["full_name"], str)


def assert_citation(data: dict):
    _assert_common(data)
    assert data["status"] in CITATION_STATES, f"unexpected citation status {data['status']}"
    assert isinstance(data["captured_plate_number"], str)


def assert_contest(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "SCHEDULED", "UPHELD", "DISMISSED", "WITHDRAWN")


def assert_hearing(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "RULED", "ADJOURNED")


def assert_payment(data: dict):
    _assert_common(data)
    assert data["status"] in ("INITIATED", "CLEARED", "FAILED", "REVERSED")


def assert_vendor_contract(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert data["accrued_vendor_share_cents"] >= 0, "accrued share never below 0 (PRD 3.7)"


def assert_calibration_record(data: dict):
    _assert_audit_common(data)


def assert_notice_record(data: dict):
    _assert_audit_common(data)
    assert data["notice_type"] in ("INITIAL", "DELINQUENT")
