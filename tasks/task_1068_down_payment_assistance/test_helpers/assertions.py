"""Entity assertions and domain invariant checkers.

These validate that a returned resource carries the PRD-declared field shape.
They intentionally avoid asserting the value of optional/computed fields that
the PRD leaves null until a later lifecycle event.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict, has_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if has_version:
        assert "updated_at" in data, "mutable entity must carry updated_at"
        assert isinstance(data.get("version"), int), "version must be an integer"


def assert_program(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["ami_limit_pct"], int)
    assert isinstance(data["max_assistance_cents"], int)
    assert data["recapture_model"] in ("SHARED_APPRECIATION", "DECLINING_BALANCE")


def assert_income_limit(data: dict):
    # IncomeLimit is immutable: id + created_at only, no version/updated_at.
    _assert_common(data, has_version=False)
    assert isinstance(data["household_size"], int)
    assert isinstance(data["ami_100_income_cents"], int)


def assert_applicant(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert isinstance(data["household_size"], int)


def assert_property(data: dict):
    _assert_common(data)
    assert isinstance(data["purchase_price_cents"], int)
    assert data["unit_type"] in ("SINGLE_FAMILY", "CONDO", "TOWNHOME")


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "NEEDS_INFO",
        "ELIGIBLE", "INELIGIBLE", "WITHDRAWN",
    )


def assert_education_session(data: dict):
    _assert_common(data)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["enrolled_count"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "ATTENDED", "NO_SHOW", "CANCELLED")


def assert_certificate(data: dict):
    _assert_common(data)
    assert data["status"] in ("VALID", "EXPIRED")
    assert is_iso8601_timestamp(data["issued_at"])
    assert is_iso8601_timestamp(data["expires_at"])


def assert_award(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "PENDING_EDUCATION", "APPROVED", "FUNDED", "SERVICING",
        "REPAID", "RECAPTURED", "CANCELLED",
    )
    assert data["recapture_model"] in ("SHARED_APPRECIATION", "DECLINING_BALANCE")
    assert isinstance(data["assistance_amount_cents"], int)


def assert_funding_source(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "FULLY_COMMITTED")
    assert isinstance(data["available_cents"], int)
    assert isinstance(data["reserved_cents"], int)
    assert isinstance(data["disbursed_cents"], int)


def assert_funding_source_ledger_invariant(data: dict):
    """PRD Section 2.10: available + reserved + disbursed == total_appropriation."""
    total = data["available_cents"] + data["reserved_cents"] + data["disbursed_cents"]
    assert total == data["total_appropriation_cents"], (
        f"ledger invariant broken: {data['available_cents']} + {data['reserved_cents']} "
        f"+ {data['disbursed_cents']} != {data['total_appropriation_cents']}"
    )


def assert_funding_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ("RESERVED", "DISBURSED", "RELEASED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["lien_position"], int)


def assert_closing(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "DOCS_PENDING", "COMPLETED", "CANCELLED")


def assert_servicing_account(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in ("ACTIVE", "IN_SALE", "CLOSED")
    assert data["payment_status"] in ("CURRENT", "DELINQUENT")


def assert_sale_event(data: dict):
    _assert_common(data)
    assert isinstance(data["sale_price_cents"], int)
    assert isinstance(data["appreciation_cents"], int)
