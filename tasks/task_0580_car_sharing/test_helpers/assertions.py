"""Entity assertions and domain invariant checkers (Car Sharing PRD §2.4, §2.8).

These validate structural shape and cross-field invariants that hold after any
operation. They deliberately avoid asserting absolute version numbers, whose
initial value the PRD does not pin (§2.4 says version "starts at its initial
value"); version is only ever checked via relative increments in the tests.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_host(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    for f in ("pending_balance_cents", "available_balance_cents", "reserved_payout_cents",
              "lifetime_earnings_cents", "lifetime_paid_cents"):
        assert isinstance(data[f], int), f"{f} must be int cents"
    assert_host_ledger_invariants(data)


def assert_host_ledger_invariants(data: dict):
    """PRD §2.8 conservation rule on the host ledger."""
    assert data["available_balance_cents"] >= 0, "available_balance never negative"
    assert data["reserved_payout_cents"] >= 0, "reserved_payout never negative"
    assert (
        data["lifetime_earnings_cents"]
        == data["available_balance_cents"] + data["reserved_payout_cents"] + data["lifetime_paid_cents"]
    ), "lifetime_earnings == available + reserved + lifetime_paid"


def assert_guest(data: dict):
    _common(data)
    assert data["verification_status"] in (
        "UNVERIFIED", "PENDING_REVIEW", "VERIFIED", "REJECTED",
    )
    assert 0 <= data["driver_risk_score"] <= 100, "driver_risk_score in 0..100"


def assert_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "plan id must be UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "plan created_at must be ISO 8601"
    assert data["tier"] in ("BASIC", "STANDARD", "PREMIUM")


def assert_vehicle(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "LISTED", "SNOOZED", "UNLISTED")
    assert data["booked_night_count"] >= 0
    assert data["completed_trip_count"] >= 0


def assert_trip(data: dict):
    _common(data)
    assert data["status"] in (
        "REQUESTED", "CONFIRMED", "CHECKED_IN", "CHECKED_OUT",
        "COMPLETED", "CANCELLED", "DECLINED",
    )
    assert data["nights"] == _days_between(data["start_date"], data["end_date"])


def assert_claim(data: dict):
    _common(data)
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "NEEDS_INFO", "APPROVED", "DENIED", "SETTLED",
    )
    assert data["claimant"] in ("HOST", "GUEST")


def assert_extension(data: dict):
    _common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "DENIED")


def assert_payout(data: dict):
    _common(data)
    assert data["status"] in ("REQUESTED", "PAID", "FAILED")


def assert_availability_block(data: dict):
    _common(data)
    assert data["status"] in ("ACTIVE", "RELEASED", "CONSUMED")
    assert data["block_type"] in ("BOOKED", "HOST_BLOCKED", "MAINTENANCE")


def assert_inspection(data: dict):
    _common(data)
    assert data["phase"] in ("CHECK_IN", "CHECK_OUT")


def _days_between(start: str, end: str) -> int:
    from datetime import date
    y1, m1, d1 = (int(x) for x in start.split("-"))
    y2, m2, d2 = (int(x) for x in end.split("-"))
    return (date(y2, m2, d2) - date(y1, m1, d1)).days
