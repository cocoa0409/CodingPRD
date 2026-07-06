"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, mutation_tracked: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if mutation_tracked:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_package(data: dict):
    # TreatmentPackage is a configuration record: id + created_at only.
    _assert_common(data, mutation_tracked=False)
    assert data["tier"] in ["STANDARD", "PREMIUM", "LIFETIME"]
    assert isinstance(data["base_price_cents"], int)
    assert isinstance(data["deposit_cents"], int)
    assert isinstance(data["enhancement_window_days"], int)
    assert data["refund_mode"] in ["PRO_RATA", "DEPOSIT_FORFEIT"]
    assert isinstance(data["active"], bool)


def assert_suite(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["turnaround_buffer_minutes"], int)
    assert isinstance(data["daily_case_cap"], int)
    assert data["status"] in ["OPEN", "MAINTENANCE"]


def assert_surgeon(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["max_daily_cases"], int)
    assert isinstance(data["accepting"], bool)


def assert_optometrist(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)


def assert_patient(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert data["status"] in ["PROSPECT", "CANDIDATE", "INELIGIBLE", "OPERATED"]


def assert_screening(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("patient_id", ""))
    assert is_valid_uuid(data.get("performed_by_optometrist_id", ""))
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]


def assert_case(data: dict):
    _assert_common(data)
    assert data["clinical_status"] in [
        "PLANNED", "SCHEDULED", "CONSENTED", "OPERATED", "HEALED", "CANCELLED",
    ]
    assert data["financial_status"] in [
        "UNFUNDED", "DEPOSIT_PAID", "PAID_IN_FULL", "REFUNDED",
    ]


def assert_financing(data: dict):
    _assert_common(data)
    assert isinstance(data["amount_settled_cents"], int)
    assert data["status"] in ["OPEN", "SETTLED", "CANCELLED"]


def assert_consent(data: dict):
    _assert_common(data)
    assert data["status"] in ["SIGNED", "REVOKED"]


def assert_enhancement(data: dict):
    _assert_common(data)
    assert data["status"] in ["REQUESTED", "RE_SCREENING", "APPROVED", "DENIED", "FULFILLED"]
    assert isinstance(data["within_window"], bool)


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "RELEASED"]


def assert_refund_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "PAID", "REJECTED"]
