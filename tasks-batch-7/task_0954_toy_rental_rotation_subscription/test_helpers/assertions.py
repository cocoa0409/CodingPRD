"""Entity assertions, semantic instant comparison and domain invariant checkers."""

from datetime import datetime, timezone
from typing import Optional

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    DamageSeverity,
    DevelopmentalStage,
    FeeStatus,
    FeeType,
    LedgerReason,
    LoanStatus,
    MemberStatus,
    ResolutionStatus,
    RotationBoxStatus,
    ShipmentDirection,
    ShipmentStatus,
    SubscriptionStatus,
    ToyCopyStatus,
    WishlistEntryStatus,
)

# ---------------------------------------------------------------------------
# Semantic instant comparison
# ---------------------------------------------------------------------------
#
# Instants supplied in request bodies (shipment `occurred_at`, clock positions)
# are echoed back inside computed fields such as `delivered_at` or `due_date`.
# A faithful implementation may render them with or without fractional digits,
# so instants are always compared semantically, never as strings.


def parse_instant(value: str) -> datetime:
    """Parse an ISO-8601 instant (or bare YYYY-MM-DD date), tolerating `Z`,
    `+00:00`, and any number of fractional digits.  Returns aware UTC."""
    assert isinstance(value, str) and value, f"Expected an ISO-8601 string, got {value!r}"
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_same_instant(actual: Optional[str], expected: Optional[str], label: str = "instant"):
    """Compare two ISO-8601 renderings as instants, not as strings."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual!r}"
        return
    assert actual is not None, f"{label}: expected {expected!r}, got null"
    a, e = parse_instant(actual), parse_instant(expected)
    assert a == e, (
        f"{label}: expected instant {expected!r} ({e.isoformat()}), "
        f"got {actual!r} ({a.isoformat()})"
    )


def assert_same_date(actual: Optional[str], expected_yyyy_mm_dd: str, label: str = "date"):
    """Compare a date or datetime rendering against a bare calendar date."""
    assert actual is not None, f"{label}: expected {expected_yyyy_mm_dd!r}, got null"
    assert str(actual)[:10] == expected_yyyy_mm_dd, (
        f"{label}: expected date {expected_yyyy_mm_dd!r}, got {actual!r}"
    )


# ---------------------------------------------------------------------------
# Per-entity structural assertions
# ---------------------------------------------------------------------------


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["status"] in [s.value for s in MemberStatus]
    assert isinstance(data["wallet_credit_cents"], int)
    assert "password" not in data, "password is write-only and must never be echoed"


def assert_child_profile(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert isinstance(data["birthdate"], str) and len(data["birthdate"]) == 10
    assert isinstance(data["age_months"], int) and data["age_months"] >= 0
    assert data["developmental_stage"] in [s.value for s in DevelopmentalStage]


def assert_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["monthly_fee_cents"], int)
    assert isinstance(data["toys_per_box"], int) and data["toys_per_box"] >= 1
    assert isinstance(data["swap_allowance_per_cycle"], int)
    assert isinstance(data["max_holds"], int)
    assert isinstance(data["rotation_cadence_days"], int)
    assert isinstance(data["rental_period_days"], int)
    assert 0 <= data["buyout_discount_pct"] < 1


def assert_subscription(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert is_valid_uuid(data.get("plan_id", "")), "plan_id must be a UUID"
    assert data["status"] in [s.value for s in SubscriptionStatus]
    assert data.get("next_cycle_due_at"), "next_cycle_due_at is initialized at creation"
    assert isinstance(data.get("pause_windows"), list)
    assert isinstance(data.get("paused_days_used_365d"), int)


def assert_catalog_item(data: dict):
    _assert_common(data)
    assert isinstance(data["title"], str) and data["title"]
    assert isinstance(data["min_age_months"], int)
    assert isinstance(data["max_age_months"], int)
    assert data["min_age_months"] <= data["max_age_months"]
    assert isinstance(data["piece_count"], int) and data["piece_count"] >= 1
    assert isinstance(data["retail_value_cents"], int) and data["retail_value_cents"] > 0
    assert isinstance(data["replacement_value_cents"], int)
    assert data["replacement_value_cents"] > 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_copy(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("catalog_item_id", "")), "catalog_item_id must be a UUID"
    assert isinstance(data["barcode"], str) and data["barcode"]
    assert data["condition_grade"] in ("NEW", "GOOD", "FAIR", "WORN")
    assert data["status"] in [s.value for s in ToyCopyStatus]
    assert isinstance(data.get("sanitization_cycle_count"), int)


def assert_wishlist_entry(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("member_id", "")), "member_id must be a UUID"
    assert is_valid_uuid(data.get("catalog_item_id", "")), "catalog_item_id must be a UUID"
    assert isinstance(data["rank"], int)
    assert data["status"] in [s.value for s in WishlistEntryStatus]


def assert_rotation_box(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("subscription_id", "")), "subscription_id must be a UUID"
    assert isinstance(data["cycle_number"], int) and data["cycle_number"] >= 1
    assert data["status"] in [s.value for s in RotationBoxStatus]
    assert isinstance(data["swap_count"], int) and data["swap_count"] >= 0
    assert isinstance(data.get("projected_late_fee_cents"), int)
    assert data["projected_late_fee_cents"] >= 0


def assert_box_item(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rotation_box_id", "")), "rotation_box_id must be a UUID"
    assert is_valid_uuid(data.get("toy_copy_id", "")), "toy_copy_id must be a UUID"
    assert data["loan_status"] in [s.value for s in LoanStatus]
    assert data["resolution_status"] in [s.value for s in ResolutionStatus]
    assert isinstance(data.get("missing_piece_count"), int)
    if data.get("condition_returned") is not None:
        assert data["condition_returned"] in ("GOOD", "FAIR", "WORN")
    if data.get("damage_severity") is not None:
        assert data["damage_severity"] in [s.value for s in DamageSeverity]


def assert_fee(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("subscription_id", "")), "subscription_id must be a UUID"
    assert data["fee_type"] in [t.value for t in FeeType]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data["status"] in [s.value for s in FeeStatus]
    assert isinstance(data.get("dispute_rounds"), int)
    assert 0 <= data["dispute_rounds"] <= 2


def assert_shipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("rotation_box_id", "")), "rotation_box_id must be a UUID"
    assert data["direction"] in [d.value for d in ShipmentDirection]
    assert data["status"] in [s.value for s in ShipmentStatus]
    assert isinstance(data.get("events"), list)


def assert_ledger_entry(data: dict):
    """Append-only ledger row: `id` and `created_at` only among common fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only ledger rows must not carry updated_at"
    assert "version" not in data, "append-only ledger rows must not carry version"
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] != 0
    assert data["reason"] in [r.value for r in LedgerReason]


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------


def assert_wallet_matches_ledger(member: dict, ledger_entries: list):
    """PRD 2.9 invariant: wallet_credit_cents always equals the ledger sum."""
    total = sum(e["amount_cents"] for e in ledger_entries)
    assert member["wallet_credit_cents"] == total, (
        f"wallet {member['wallet_credit_cents']} != ledger sum {total}"
    )


def assert_active_slot_count(box_items: list, expected: int):
    """Active slots are the box items still occupying the box (not swapped out
    or cancelled)."""
    active = [i for i in box_items
              if i["loan_status"] not in ("SWAPPED_OUT", "CANCELLED")]
    assert len(active) == expected, (
        f"expected {expected} active slots, got {len(active)} "
        f"({[i['loan_status'] for i in box_items]})"
    )
    return active
