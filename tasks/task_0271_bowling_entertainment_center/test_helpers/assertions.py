"""Entity assertions and domain invariant checkers.

Uses the framework's generic format validators internally. All monetary fields
are integer cents (PRD §2.8).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_full(data: dict):
    """id + created_at + updated_at + version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def _assert_common_lean(data: dict):
    """id + created_at only — leaner entities (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_rate_card(data: dict):
    _assert_common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["per_game_cents"], int) and data["per_game_cents"] >= 0
    assert isinstance(data["per_hour_cents"], int) and data["per_hour_cents"] >= 0


def assert_lane(data: dict):
    _assert_common_full(data)
    assert isinstance(data["number"], int) and data["number"] >= 1
    assert isinstance(data["max_bowlers"], int) and data["max_bowlers"] >= 1
    assert data["status"] in ("IN_SERVICE", "OUT_OF_SERVICE")


def assert_bay(data: dict):
    _assert_common_full(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["capacity"], int) and data["capacity"] >= 1
    assert isinstance(data["cleanup_buffer_minutes"], int) and data["cleanup_buffer_minutes"] >= 0
    assert data["status"] in ("IN_SERVICE", "OUT_OF_SERVICE")


def assert_customer(data: dict):
    _assert_common_full(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["deposit_balance_cents"], int)
    assert isinstance(data["wallet_credit_cents"], int)
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_rental_item(data: dict):
    _assert_common_full(data)
    assert data["kind"] in ("SHOES", "BALL", "BUMPER")
    assert isinstance(data["total_count"], int) and data["total_count"] >= 0
    assert isinstance(data["out_on_rent_count"], int) and data["out_on_rent_count"] >= 0
    assert isinstance(data["available_count"], int) and data["available_count"] >= 0
    assert_rental_inventory_conserved(data)


def assert_reservation(data: dict):
    _assert_common_full(data)
    assert data["resource_kind"] in ("LANE", "BAY")
    assert data["pricing_mode"] in ("PER_GAME", "PER_HOUR")
    assert data["status"] in (
        "DRAFT", "HELD", "CONFIRMED", "CHECKED_IN", "COMPLETED",
        "CANCELLED", "EXPIRED", "NO_SHOW", "WAITLISTED",
    )
    assert isinstance(data["bowler_count"], int) and data["bowler_count"] >= 1


def assert_food_order_line(data: dict):
    # Leaner entity: id + created_at only, no updated_at/version (PRD §2.4).
    _assert_common_lean(data)
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0


def assert_rental_line(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("OPEN", "RETURNED")
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0


def assert_league(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("DRAFT", "ACTIVE", "CLOSED")


def assert_league_night(data: dict):
    _assert_common_full(data)
    assert data["status"] in ("SCHEDULED", "PLAYED", "FORFEITED", "RAINED_OUT")


# --- Domain invariants ----------------------------------------------------
def assert_rental_inventory_conserved(item: dict):
    """PRD §3.1: total_count always equals available_count + out_on_rent_count."""
    assert item["total_count"] == item["available_count"] + item["out_on_rent_count"], (
        f"rental inventory not conserved: total={item['total_count']} "
        f"avail={item['available_count']} out={item['out_on_rent_count']}"
    )
    assert item["available_count"] >= 0, "available_count must never go negative"


def assert_deposit_ledger_conserved(customer: dict, original_deposit_cents: int):
    """PRD §3.6: a full-refund cancel moves the held deposit to wallet credit, so
    deposit_balance_cents + wallet_credit_cents == the original held deposit."""
    assert customer["deposit_balance_cents"] + customer["wallet_credit_cents"] == original_deposit_cents, (
        f"deposit ledger not conserved: balance={customer['deposit_balance_cents']} "
        f"wallet={customer['wallet_credit_cents']} original={original_deposit_cents}"
    )
