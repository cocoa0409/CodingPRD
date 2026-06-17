"""Entity assertions and domain invariant checkers.

Uses the framework's generic validators internally. Field names are exact PRD
names. Append-only entities are NOT asserted to carry updated_at/version.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


_CATEGORIES = ["KAYAK", "SKI", "SUP", "SNOWBOARD"]


def _assert_common_mutable(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        f"version must be int >= 1, got {data.get('version')!r}"


def _assert_common_append_only(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_gear_type(data: dict):
    _assert_common_mutable(data)
    assert data["category"] in _CATEGORIES, f"unexpected category {data['category']!r}"
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["size_label"], str)
    assert isinstance(data["requires_lesson_for_beginner"], bool)
    assert isinstance(data["active"], bool)


def assert_rate_card(data: dict):
    _assert_common_mutable(data)
    for field in ("hourly_cents", "daily_cents", "seasonal_flat_cents", "deposit_cents",
                  "damage_waiver_cents_per_day", "late_fee_cents_per_hour", "loss_fee_cents",
                  "grace_minutes"):
        assert isinstance(data[field], int) and data[field] >= 0, \
            f"{field} must be non-negative int, got {data.get(field)!r}"
    assert isinstance(data["active"], bool)


def assert_season_window(data: dict):
    _assert_common_append_only(data)
    assert data["category"] in _CATEGORIES
    assert isinstance(data["demand_multiplier_bp"], int) and data["demand_multiplier_bp"] >= 1
    assert is_iso8601_timestamp(data["starts_on"])
    assert is_iso8601_timestamp(data["ends_on"])
    # Append-only: must NOT carry updated_at / version.
    assert "version" not in data, "SeasonWindow is append-only; must not carry version"


def assert_customer(data: dict):
    _assert_common_mutable(data)
    assert isinstance(data["full_name"], str) and len(data["full_name"]) > 0
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["skill_level"] in ["BEGINNER", "INTERMEDIATE", "EXPERT"]
    assert data["standing"] in ["GOOD", "WATCH", "SUSPENDED"]
    assert isinstance(data["strike_points"], int) and data["strike_points"] >= 0, \
        "strike_points never negative"
    assert isinstance(data["open_loss_balance_cents"], int) and data["open_loss_balance_cents"] >= 0


def assert_addon(data: dict):
    _assert_common_mutable(data)
    assert data["kind"] in ["LESSON", "PACKAGE"]
    assert data["category"] in _CATEGORIES
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["capacity_per_slot"], int) and data["capacity_per_slot"] >= 1
    assert isinstance(data["active"], bool)


def assert_gear_unit(data: dict):
    _assert_common_mutable(data)
    assert data["condition"] in ["GOOD", "WORN", "DAMAGED", "LOST"]
    assert data["availability"] in [
        "AVAILABLE", "RESERVED", "CHECKED_OUT", "INSPECTING", "MAINTENANCE", "RETIRED"
    ]
    assert isinstance(data["asset_tag"], str) and len(data["asset_tag"]) > 0


def assert_reservation(data: dict):
    _assert_common_mutable(data)
    assert data["lifecycle_status"] in [
        "QUOTED", "CONFIRMED", "PICKED_UP", "RETURNED", "CLOSED", "CANCELLED"
    ]
    assert data["payment_status"] in ["UNPAID", "DEPOSIT_HELD", "SETTLED", "REFUNDED"]
    assert isinstance(data["quoted_total_cents"], int) and data["quoted_total_cents"] >= 0
    assert isinstance(data["damage_waiver_opted"], bool)


def assert_damage_assessment(data: dict):
    _assert_common_mutable(data)
    assert data["outcome"] in ["NONE", "DAMAGE", "LOSS"]
    assert isinstance(data["charge_cents"], int) and data["charge_cents"] >= 0
    assert isinstance(data["waiver_applied"], bool)
    assert data["status"] in ["ASSESSED", "SETTLED", "DISPUTED"]


def assert_ledger_entry(data: dict):
    _assert_common_append_only(data)
    assert data["entry_type"] in [
        "DEPOSIT_HOLD", "DEPOSIT_REFUND", "RENTAL_CHARGE", "LATE_FEE", "DAMAGE_FEE", "LOSS_FEE"
    ]
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["settled"], bool)
    assert "version" not in data, "LedgerEntry is append-only; must not carry version"


def assert_ledger_nets_zero(entries: list):
    """Compensating invariant: sum of signed amount_cents over a reservation's
    ledger returns to 0 after a deposit hold + refund pair."""
    total = sum(e["amount_cents"] for e in entries)
    assert total == 0, f"ledger should net to 0, got {total}"
