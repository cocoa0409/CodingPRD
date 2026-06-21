"""Entity assertions and structural checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


def _assert_common(data: dict) -> None:
    """id + created_at present and well-formed (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601: {data.get('created_at')!r}"
    )


def assert_participant(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "TERMINATED"), data
    assert isinstance(data["is_five_percent_owner"], bool), data


def assert_plan(data: dict) -> None:
    _assert_common(data)
    assert isinstance(data["company_name"], str) and data["company_name"], data


def assert_offering(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in (
        "OPEN", "ENROLLMENT_CLOSED", "ACTIVE", "CLOSED", "CANCELLED"
    ), data


def assert_purchase_period(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in (
        "PENDING", "OPEN", "CERTIFIED", "PURCHASED", "CANCELLED"
    ), data


def assert_enrollment(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("ENROLLED", "SUSPENDED", "WITHDRAWN", "COMPLETED"), data


def assert_contribution(data: dict) -> None:
    """Contribution is common_fields:false — carries only id + created_at (PRD §2.4)."""
    _assert_common(data)
    assert data["status"] in ("POSTED", "CONSUMED", "REFUNDED"), data


def assert_purchase(data: dict) -> None:
    _assert_common(data)
    assert data["status"] == "SETTLED", data


def assert_share_lot(data: dict) -> None:
    _assert_common(data)
    assert data["status"] in ("OPEN", "FULLY_DISPOSED"), data


def assert_disposition(data: dict) -> None:
    _assert_common(data)
    assert data["disposition_type"] in ("QUALIFYING", "DISQUALIFYING"), data


def assert_form_3922(data: dict) -> None:
    _assert_common(data)


def assert_accrual_ledger(data: dict) -> None:
    _assert_common(data)
