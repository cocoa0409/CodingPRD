"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators (UUID / ISO-8601). Append-only records
(ComplianceAction, Certificate) are checked WITHOUT updated_at / version, which they
correctly do not carry.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be an int >= 1"


def _assert_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"


def assert_participant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["risk_level"] in ("LOW", "MEDIUM", "HIGH")


def assert_site(data: dict):
    _assert_common(data)
    assert data["agency_type"] in ("NONPROFIT", "GOVERNMENT", "FAITH_BASED", "OTHER")
    assert data["status"] in ("PROSPECTIVE", "ACCEPTING", "PAUSED")
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 1


def assert_insurance_policy(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "VERIFIED", "REJECTED")


def assert_supervisor(data: dict):
    _assert_common(data)
    assert isinstance(data["max_concurrent_participants"], int)


def assert_referral(data: dict):
    _assert_common(data)
    assert data["offense_class"] in ("INFRACTION", "MISDEMEANOR", "FELONY")
    assert data["indigency_status"] in ("NONE", "PARTIAL", "FULL")
    assert data["status"] in (
        "ACTIVE", "NON_COMPLIANT", "COMPLETED", "CONVERTED", "TERMINATED")
    assert_referral_partition(data)


def assert_referral_partition(data: dict):
    """The conserved hours partition (PRD §2.7):
    hours_ordered == hours_completed + hours_converted + hours_outstanding,
    with each term >= 0 and outstanding floored at 0."""
    completed = data["hours_completed"]
    converted = data["hours_converted"]
    outstanding = data["hours_outstanding"]
    ordered = data["hours_ordered"]
    assert completed >= 0, "hours_completed must be >= 0"
    assert converted >= 0, "hours_converted must be >= 0"
    assert outstanding >= 0, "hours_outstanding must be floored at 0"
    assert abs(ordered - (completed + converted + outstanding)) < 1e-9, (
        f"partition broken: {ordered} != {completed}+{converted}+{outstanding}")


def assert_placement(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PROPOSED", "ACTIVE", "SUSPENDED", "COMPLETED", "TERMINATED")
    assert isinstance(data["waiver_signed"], bool)


def assert_work_session(data: dict):
    _assert_common(data)
    assert data["attendance_status"] in (
        "SCHEDULED", "CHECKED_IN", "COMPLETED", "CANCELLED", "VOIDED")
    assert data["verification_status"] in (
        "PENDING", "VERIFIED", "DISPUTED", "REJECTED")


def assert_fee_conversion(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "REQUESTED", "APPROVED", "DENIED", "PAID", "REVERSED")
    assert data["indigency_status_snapshot"] in ("NONE", "PARTIAL", "FULL")


def assert_compliance_action(data: dict):
    _assert_append_only(data)
    assert data["action_type"] in ("WARNING", "REPORT_BACK")


def assert_certificate(data: dict):
    _assert_append_only(data)
    assert isinstance(data["certificate_number"], str) and data["certificate_number"]
