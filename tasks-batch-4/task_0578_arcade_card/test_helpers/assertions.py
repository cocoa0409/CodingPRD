"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_member(data: dict):
    _common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["promo_opt_in"], bool)
    assert isinstance(data["lifetime_spend_cents"], int)
    assert data["membership_tier"] in ("NONE", "SILVER", "GOLD", "PLATINUM")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_game_card(data: dict):
    _common(data)
    assert data["status"] in ("INACTIVE", "ACTIVE", "FROZEN", "CLOSED")
    assert isinstance(data["chip_balance_cents"], int)
    assert isinstance(data["bonus_chip_balance_cents"], int)
    assert isinstance(data["ticket_points_balance"], int)


def assert_attraction(data: dict):
    _common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["chip_cost_cents"], int)
    assert isinstance(data["points_award"], int)
    assert data["status"] in ("OPEN", "MAINTENANCE", "RETIRED")


def assert_prize_item(data: dict):
    _common(data)
    assert isinstance(data["points_price"], int)
    assert isinstance(data["stock_qty"], int)
    assert isinstance(data["reserved_qty"], int)
    assert data["status"] in ("AVAILABLE", "OUT_OF_STOCK", "DISCONTINUED")


def assert_redemption(data: dict):
    _common(data)
    assert is_valid_uuid(data["card_id"])
    assert is_valid_uuid(data["prize_item_id"])
    assert isinstance(data["quantity"], int)
    assert isinstance(data["points_hold"], int)
    assert data["status"] in ("RESERVED", "FULFILLED", "CANCELLED")


def assert_room(data: dict):
    _common(data)
    assert isinstance(data["capacity"], int)
    assert isinstance(data["hourly_rate_cents"], int)
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")


def assert_party_booking(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "CONFIRMED", "CHECKED_IN", "COMPLETED", "CANCELLED")
    assert isinstance(data["guest_count"], int)


def assert_wristband(data: dict):
    _common(data)
    assert data["status"] in ("ISSUED", "ACTIVE", "RETURNED", "VOID")
    assert isinstance(data["band_code"], str) and len(data["band_code"]) > 0


def assert_daily_reconciliation(data: dict):
    _common(data)
    assert isinstance(data["expected_chip_liability_cents"], int)
    assert isinstance(data["expected_prize_units"], int)
    assert data["status"] in ("OPEN", "RECONCILED", "DISCREPANCY")


def assert_card_ledger_entry(data: dict):
    """Append-only record: id + created_at only (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_type"] in (
        "RELOAD", "BONUS_GRANT", "GAMEPLAY_DEBIT", "POINTS_EARN",
        "POINTS_HOLD", "POINTS_SETTLE", "POINTS_REFUND", "BONUS_CLAWBACK",
    )


def assert_game_play(data: dict):
    """Append-only record: id + created_at only (no updated_at / version)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["chip_cost_cents"], int)
    assert isinstance(data["chip_from_bonus_cents"], int)
    assert isinstance(data["chip_from_stored_cents"], int)
    assert isinstance(data["points_awarded"], int)


def assert_card_balances_match_ledger(card: dict, ledger: list):
    """PRD §2.7: a card's balances equal the signed sums of its ledger deltas."""
    assert card["chip_balance_cents"] == sum(e["chip_delta_cents"] for e in ledger)
    assert card["bonus_chip_balance_cents"] == sum(e["bonus_delta_cents"] for e in ledger)
    assert card["ticket_points_balance"] == sum(e["points_delta"] for e in ledger)
