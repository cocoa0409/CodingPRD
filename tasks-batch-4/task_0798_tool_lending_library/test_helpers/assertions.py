"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def parse_iso(ts: str) -> datetime:
    """Parse an ISO 8601 UTC timestamp (with optional trailing Z and fractional
    seconds) to an aware UTC datetime for instant comparison."""
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def assert_same_instant(actual: str, expected: str, label: str = "instant"):
    """Compare two ISO 8601 timestamps as instants (tolerant of fractional-second
    formatting, since responses carry three fractional digits per PRD §2.4)."""
    assert parse_iso(actual) == parse_iso(expected), (
        f"{label}: expected {expected}, got {actual}"
    )


def _assert_common(data: dict):
    """id/created_at/updated_at/version carried by every entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version begins at 1 on creation"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["tier"] in ("BASIC", "PLUS")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    for c in ("outstanding_balance_cents", "total_assessed_cents",
              "total_paid_cents", "total_waived_cents",
              "max_active_loans", "max_active_holds"):
        assert isinstance(data[c], int), f"{c} must be an integer"


def assert_volunteer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["role_level"] in ("VOLUNTEER", "COORDINATOR")
    assert isinstance(data["active"], bool)


def assert_item(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ("TOOL", "OUTDOOR", "KITCHEN")
    for c in ("replacement_value_cents", "loan_period_days", "daily_late_fee_cents",
              "max_renewals", "serviceable_copies_count", "available_copies_count",
              "reserved_count", "on_loan_count", "maintenance_count", "waitlist_length"):
        assert isinstance(data[c], int), f"{c} must be an integer"
    assert_item_partition(data)


def assert_item_partition(data: dict):
    """Copy-partition conservation invariant (PRD §2.6): available + reserved +
    on_loan + maintenance == serviceable_copies_count."""
    partition = (data["available_copies_count"] + data["reserved_count"]
                 + data["on_loan_count"] + data["maintenance_count"])
    assert partition == data["serviceable_copies_count"], (
        f"copy partition {partition} must equal serviceable_copies_count "
        f"{data['serviceable_copies_count']}"
    )


def assert_item_copy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("item_id", "")), "item_id must be a UUID"
    assert data["availability_status"] in ("AVAILABLE", "RESERVED", "ON_LOAN")
    assert data["condition_status"] in ("GOOD", "NEEDS_MAINTENANCE",
                                        "UNDER_MAINTENANCE", "RETIRED")
    assert data["origin"] in ("PURCHASE", "DONATION")


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert is_valid_uuid(data.get("item_id", "")), "item_id must be a UUID"
    assert data["status"] in ("PENDING", "FULFILLED", "CANCELLED", "EXPIRED")
    assert data["source"] in ("MEMBER", "WAITLIST_PROMOTION")


def assert_loan(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert is_valid_uuid(data.get("copy_id", "")), "copy_id must be a UUID"
    assert data["status"] in ("ACTIVE", "OVERDUE", "RETURNED", "LOST")
    assert isinstance(data["renewals_used"], int)


def assert_hold(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert is_valid_uuid(data.get("item_id", "")), "item_id must be a UUID"
    assert data["status"] in ("PENDING", "PROMOTED", "FULFILLED", "EXPIRED")


def assert_fee(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert data["fee_type"] in ("LATE", "DAMAGE", "REPLACEMENT")
    assert data["status"] in ("ACCRUING", "PENDING", "PAID", "WAIVED")
    assert isinstance(data["amount_cents"], int)


def assert_donation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("item_id", "")), "item_id must be a UUID"
    assert data["status"] in ("OFFERED", "ACCEPTED", "REJECTED")
    assert data["proposed_condition"] in ("GOOD", "FAIR")


def assert_maintenance_ticket(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("copy_id", "")), "copy_id must be a UUID"
    assert data["reason"] in ("DAMAGE", "ROUTINE", "INSPECTION")
    assert data["source"] in ("MANUAL", "DAMAGE_INTAKE")
    assert data["status"] in ("OPEN", "IN_PROGRESS", "RESOLVED")


def assert_member_ledger_conserved(data: dict, outstanding_pending_cents: int):
    """Ledger conservation (PRD §2.7): total_assessed_cents == outstanding PENDING
    fees + total_paid_cents + total_waived_cents. The caller supplies the sum of the
    member's still-outstanding finalized (PENDING) fee amounts."""
    lhs = data["total_assessed_cents"]
    rhs = outstanding_pending_cents + data["total_paid_cents"] + data["total_waived_cents"]
    assert lhs == rhs, (
        f"ledger not conserved: total_assessed_cents {lhs} != "
        f"PENDING {outstanding_pending_cents} + paid {data['total_paid_cents']} "
        f"+ waived {data['total_waived_cents']} = {rhs}"
    )
