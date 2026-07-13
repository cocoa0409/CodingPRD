"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with or without fractional seconds / 'Z')."""
    v = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def assert_same_instant(actual: str, expected_iso: str):
    """Compare two ISO 8601 UTC timestamps by instant, tolerating fractional-second
    formatting differences ('...00:00:00Z' vs '...00:00:00.000Z')."""
    assert is_iso8601_timestamp(actual), f"not an ISO 8601 timestamp: {actual!r}"
    assert _parse_instant(actual) == _parse_instant(expected_iso), (
        f"Expected instant {expected_iso}, got {actual}"
    )


def assert_vessel(data: dict):
    assert is_valid_uuid(data.get("id", "")), "vessel id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["registration_status"] in {"DRAFT", "REGISTERED", "RETIRED"}
    assert data["service_status"] in {
        "NOT_IN_SERVICE", "IN_SERVICE", "RESTRICTED", "SUSPENDED", "OUT_OF_SERVICE",
    }
    assert data["vessel_class"] in {"POWER_BOILER", "HEATING_BOILER", "PRESSURE_VESSEL"}
    assert isinstance(data["open_deficiency_count"], int)
    assert isinstance(data["open_critical_deficiency_count"], int)


def assert_inspection(data: dict):
    assert is_valid_uuid(data.get("id", "")), "inspection id must be valid UUID"
    assert data["status"] in {
        "SCHEDULED", "PASSED", "PASSED_WITH_DEFICIENCIES", "FAILED", "CANCELLED",
    }
    assert isinstance(data["is_special"], bool)


def assert_deficiency(data: dict):
    assert is_valid_uuid(data.get("id", "")), "deficiency id must be valid UUID"
    assert data["status"] in {"OPEN", "UNDER_REPAIR", "REINSPECTION", "CLEARED", "WITHDRAWN"}
    assert data["severity"] in {"CRITICAL", "NON_CRITICAL"}


def assert_certificate(data: dict):
    assert is_valid_uuid(data.get("id", "")), "certificate id must be valid UUID"
    assert data["status"] in {"ACTIVE", "EXPIRED", "SUPERSEDED", "REVOKED"}
    assert is_iso8601_timestamp(data.get("valid_from", "")), "valid_from must be ISO 8601"
    assert is_iso8601_timestamp(data.get("valid_until", "")), "valid_until must be ISO 8601"


def assert_fee_invoice(data: dict):
    assert is_valid_uuid(data.get("id", "")), "fee invoice id must be valid UUID"
    assert data["status"] in {"UNPAID", "PAID", "REFUNDED", "VOID"}
    assert isinstance(data["amount_cents"], int)


def assert_jurisdiction_ledger_nonnegative(data: dict):
    """The conserved money quantity is a plain integer cents value."""
    assert isinstance(data["collected_fees_cents"], int)
