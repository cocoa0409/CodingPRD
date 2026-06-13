"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict):
    """id + created_at + updated_at + version, present on every resource."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1"


def assert_patron(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert data["residency"] in ("RESIDENT", "NON_RESIDENT")
    assert isinstance(data["residency_verified"], bool)
    assert data["standing"] in ("GOOD", "PROBATION", "BARRED")
    assert isinstance(data["no_show_strikes"], int)
    assert isinstance(data["wallet_credit_cents"], int)


def assert_facility(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str)
    assert data["facility_type"] in ("FIELD", "COURT", "POOL", "PAVILION")
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["hourly_rate_cents"], int)
    assert isinstance(data["granted_permit_count"], int)
    assert data["granted_permit_count"] >= 0


def assert_insurance_certificate(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("patron_id", "")), "patron_id must be a valid UUID"
    assert isinstance(data["coverage_amount_cents"], int)
    assert data["status"] in ("ACTIVE", "EXPIRED", "REVOKED")


def assert_league(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a valid UUID"
    assert is_valid_uuid(data.get("patron_id", "")), "patron_id must be a valid UUID"
    assert data["status"] in ("PENDING", "PARTIALLY_GRANTED", "GRANTED", "CANCELLED")
    assert isinstance(data["granted_occurrence_count"], int)
    assert isinstance(data["conflicted_occurrence_count"], int)


def assert_permit(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a valid UUID"
    assert is_valid_uuid(data.get("patron_id", "")), "patron_id must be a valid UUID"
    assert data["status"] in (
        "APPLIED", "GRANTED", "WAITLISTED", "DENIED",
        "CANCELLED", "COMPLETED", "NO_SHOW",
    )
    assert data["pricing_residency"] in ("RESIDENT", "NON_RESIDENT")
    assert isinstance(data["quoted_fee_cents"], int)
    assert isinstance(data["is_prime_requested"], bool)


def assert_payment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("permit_id", "")), "permit_id must be a valid UUID"
    assert isinstance(data["fee_component_cents"], int)
    assert isinstance(data["deposit_component_cents"], int)
    assert data["status"] in ("AUTHORIZED", "CAPTURED", "VOIDED")


def assert_refund(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("permit_id", "")), "permit_id must be a valid UUID"
    assert data["refund_destination"] in ("ORIGINAL", "CREDIT")
    assert isinstance(data["fee_refund_cents"], int)
    assert isinstance(data["deposit_refund_cents"], int)
    assert isinstance(data["total_refund_cents"], int)
    assert data["total_refund_cents"] == data["fee_refund_cents"] + data["deposit_refund_cents"], (
        "total_refund_cents must equal fee_refund_cents + deposit_refund_cents"
    )


def assert_lottery_round(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a valid UUID"
    assert data["status"] in ("OPEN", "DRAWN", "CANCELLED")
    assert isinstance(data["entry_count"], int)
    assert data["entry_count"] >= 0


def assert_lottery_entry(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("lottery_round_id", "")), "lottery_round_id must be a valid UUID"
    assert is_valid_uuid(data.get("patron_id", "")), "patron_id must be a valid UUID"
    assert data["status"] in ("ENTERED", "WON", "LOST", "WITHDRAWN")
    assert isinstance(data["priority_weight"], int)
