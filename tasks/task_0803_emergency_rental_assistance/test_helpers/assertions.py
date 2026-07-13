"""Entity assertions and domain invariant checkers for the ERAP API."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" in data, "entity must carry a version"


def assert_program(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "EXHAUSTED"), f"bad program status {data.get('status')!r}"
    assert isinstance(data["funding_pool_total_cents"], int)
    assert isinstance(data["funding_pool_remaining_cents"], int)


def assert_tenant(data: dict):
    _assert_common(data)
    assert isinstance(data["household_size"], int) and data["household_size"] >= 1
    assert isinstance(data["months_used"], int)


def assert_landlord(data: dict):
    _assert_common(data)
    assert data["w9_status"] in ("MISSING", "SUBMITTED", "VERIFIED", "REJECTED")


def assert_unit(data: dict):
    _assert_common(data)
    assert isinstance(data["monthly_rent_cents"], int) and data["monthly_rent_cents"] > 0


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "DRAFT", "SUBMITTED", "UNDER_REVIEW", "INFO_REQUESTED",
        "APPROVED", "DISBURSED", "DENIED", "CLOSED",
    ), f"bad application status {data.get('status')!r}"


def assert_income_source(data: dict):
    _assert_common(data)
    assert data["source_type"] in (
        "WAGES", "SELF_EMPLOYMENT", "UNEMPLOYMENT", "SSI", "TANF", "CHILD_SUPPORT",
    )
    assert isinstance(data["countable"], bool)


def assert_disbursement(data: dict):
    _assert_common(data)
    assert data["status"] in ("PENDING", "SENT", "CLEARED", "FAILED", "RECAPTURED")


def assert_recapture_case(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "SUBSTANTIATED", "RECOVERED", "DISMISSED")


def assert_funding_pool_invariant(program: dict, reserved_cents: int):
    """funding_pool_remaining == funding_pool_total - SUM(reserving disbursements) (PRD §2.7)."""
    expected = program["funding_pool_total_cents"] - reserved_cents
    assert program["funding_pool_remaining_cents"] == expected, (
        f"remaining {program['funding_pool_remaining_cents']} != "
        f"total {program['funding_pool_total_cents']} - reserved {reserved_cents}"
    )
