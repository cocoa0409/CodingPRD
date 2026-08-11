"""Entity assertions and domain invariant checkers (PRD §2.4, §3.x)."""
from datetime import datetime, timezone

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp, tolerating optional fractional digits."""
    assert isinstance(ts, str), f"expected timestamp string, got {ts!r}"
    text = ts.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def assert_ts_equal(actual: str, expected_iso: str, label: str = "timestamp"):
    """Assert two ISO 8601 timestamps denote the same instant, regardless of
    fractional-digit formatting."""
    assert parse_iso(actual) == parse_iso(expected_iso), (
        f"{label}: expected instant {expected_iso}, got {actual}"
    )


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"


def assert_program(data: dict):
    _assert_common(data)
    assert data["posture"] in ["ENROLLMENT_OPEN", "ENROLLMENT_PAUSED", "PROGRAM_SUSPENDED", "CLOSED"]
    assert isinstance(data["total_budget_cents"], int)
    assert isinstance(data["encumbered_cents"], int)
    assert isinstance(data["settled_cents"], int)
    assert isinstance(data["unencumbered_cents"], int)


def assert_caregiver(data: dict):
    _assert_common(data)
    assert data["status"] in ["ENROLLED", "ACTIVE", "SUSPENDED",
                              "REDETERMINATION_PENDING", "DISENROLLED"]
    assert isinstance(data["email"], str) and len(data["email"]) > 0


def assert_application(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED",
                              "APPEALED", "DENIED_FINAL", "WITHDRAWN"]
    assert isinstance(data["revision_count"], int)


def assert_allocation(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "FROZEN", "CLOSED"]
    for bucket in ("granted_hours", "available_hours", "reserved_hours",
                   "consumed_hours", "expired_hours", "revoked_hours"):
        assert isinstance(data[bucket], (int, float)), f"{bucket} must be numeric"
        assert data[bucket] >= 0, f"{bucket} must be non-negative"


def assert_voucher(data: dict):
    _assert_common(data)
    assert data["status"] in ["ISSUED", "COMMITTED", "REDEEMED", "SETTLED", "EXPIRED", "REVOKED"]
    for bucket in ("authorized_hours", "committed_hours", "consumed_hours",
                   "released_hours", "forfeited_hours"):
        assert isinstance(data[bucket], (int, float)), f"{bucket} must be numeric"


def assert_provider(data: dict):
    _assert_common(data)
    assert data["credential_status"] in ["APPLIED", "ACTIVE", "SUSPENDED", "LAPSED", "TERMINATED"]
    assert data["credential_level"] in ["STANDARD", "ENHANCED"]


def assert_window(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "FULLY_BOOKED", "CLOSED", "WITHDRAWN"]
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1


def assert_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING_CONFIRMATION", "CONFIRMED", "IN_SERVICE",
                              "COMPLETED", "CANCELLED", "NO_SHOW"]
    assert isinstance(data["committed_minutes"], int)


def assert_visit_record(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "SUBMITTED", "VERIFIED", "REJECTED"]


def assert_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "PAID", "DENIED",
                              "APPEALED", "DENIED_FINAL"]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["provisional_amount_cents"], int)


def assert_ledger_entry(data: dict):
    """Append-only ledger row: id + created_at only, NO updated_at / version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ledger entries must not expose updated_at"
    assert "version" not in data, "ledger entries must not expose version"
    assert data["entry_type"] in ["ENCUMBER", "RELEASE", "SETTLE", "ADJUSTMENT"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_emergency_request(data: dict):
    _assert_common(data)
    assert data["status"] in ["OPEN", "TRIAGED", "DISPATCHED", "FULFILLED", "EXPIRED", "CANCELLED"]


def assert_survey(data: dict):
    _assert_common(data)
    assert isinstance(data["rating"], int) and 1 <= data["rating"] <= 5


def assert_snapshot(data: dict):
    _assert_common(data)
    assert data["status"] in ["GENERATED", "FINALIZED", "SUBMITTED_TO_FUNDER",
                              "UNDER_AMENDMENT", "RESUBMITTED"]


def assert_hours(actual, expected, label="hours"):
    """Hour quantities are stored/compared at two decimal places (PRD §2.6)."""
    assert actual == pytest.approx(expected, abs=1e-9), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_allocation_hours_identity(allocation: dict):
    """Bucket conservation: granted == available + reserved + consumed + expired + revoked."""
    total = (allocation["available_hours"] + allocation["reserved_hours"]
             + allocation["consumed_hours"] + allocation["expired_hours"]
             + allocation["revoked_hours"])
    assert allocation["granted_hours"] == pytest.approx(total, abs=1e-9), (
        f"allocation bucket identity violated: granted={allocation['granted_hours']} "
        f"but buckets sum to {total}"
    )


def assert_program_budget_identity(program: dict):
    """Budget conservation: total == unencumbered + encumbered + settled (PRD §2.6)."""
    total = program["unencumbered_cents"] + program["encumbered_cents"] + program["settled_cents"]
    assert program["total_budget_cents"] == total, (
        f"program budget identity violated: total={program['total_budget_cents']} "
        f"but unencumbered+encumbered+settled={total}"
    )
