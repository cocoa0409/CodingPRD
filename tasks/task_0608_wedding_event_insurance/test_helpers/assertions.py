"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_policy(data: dict):
    assert is_valid_uuid(data.get("id", "")), "policy id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert data["policy_form"] in ("SINGLE_EVENT", "ANNUAL")
    assert data["lifecycle_status"] in (
        "QUOTED", "BOUND", "IN_FORCE", "EXPIRED", "CANCELLED", "CLAIMED_OUT",
    )
    assert data["billing_status"] in ("UNPAID", "PAID", "REFUNDED", "EARNED")
    for f in (
        "base_premium_cents", "rider_premium_cents", "total_premium_cents",
        "premium_earned_cents", "refund_due_cents",
    ):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert isinstance(data.get("version"), int)


def assert_coverage(data: dict):
    assert is_valid_uuid(data.get("id", "")), "coverage id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["status"] in ("SELECTED", "ACTIVE", "EXHAUSTED", "VOIDED")
    assert isinstance(data["rated_premium_cents"], int)
    assert isinstance(data["consumed_limit_cents"], int)
    assert data["consumed_limit_cents"] >= 0


def assert_rider(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("SELECTED", "ACTIVE", "VOIDED")
    assert isinstance(data["rider_premium_cents"], int)


def assert_claim(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("SUBMITTED", "INFO_REQUESTED", "APPROVED", "DENIED", "PAID")
    assert isinstance(data["approved_amount_cents"], int)
    assert isinstance(data["revision_count"], int)


def assert_certificate(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["status"] in ("REQUESTED", "ISSUED", "REVOKED")


def assert_ledger_entry(data: dict):
    """Append-only ledger row: id + created_at only (no version / updated_at)."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["entry_kind"] in (
        "PREMIUM_CHARGE", "ENDORSEMENT_CHARGE", "REFUND", "INDEMNITY_PAYOUT",
    )
    assert isinstance(data["amount_cents"], int)


def ledger_net_cents(entries: list) -> int:
    """Sum of signed amount_cents across all ledger rows (carrier net balance)."""
    return sum(e["amount_cents"] for e in entries)


def ledger_sum_by_kind(entries: list, kind: str) -> int:
    return sum(e["amount_cents"] for e in entries if e["entry_kind"] == kind)
