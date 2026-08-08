"""Entity assertions and domain invariant checkers for the Medicaid Billing API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID with no prefix, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_student(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "WITHDRAWN")
    assert isinstance(data["interim_paid_cents"], int)
    assert isinstance(data["verified_service_units"], int)


def assert_provider(data: dict):
    _assert_common(data)
    assert data["employment_status"] == "ACTIVE"


def assert_credential(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "ACTIVE", "SUSPENDED", "EXPIRED")


def assert_authorization(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "DISCONTINUED", "EXPIRED")


def assert_consent(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "GRANTED", "REVOKED")


def assert_service_log(data: dict):
    _assert_common(data)
    assert data["status"] in ("LOGGED", "DOCUMENTED", "VERIFIED", "CLAIMED", "PAID", "DENIED", "VOID")
    assert isinstance(data["delivered_units"], int)
    assert isinstance(data["charge_cents"], int)


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "PAID", "DENIED", "VOID")
    assert isinstance(data["total_charge_cents"], int)
    assert isinstance(data["attached_log_count"], int)


def assert_quarter(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")


def assert_moment(data: dict):
    _assert_common(data)
    assert data["status"] in ("GENERATED", "RESPONDED", "CODED")


def assert_settlement(data: dict):
    _assert_common(data)
    assert data["status"] in ("CALCULATED", "CERTIFIED", "SETTLED")
