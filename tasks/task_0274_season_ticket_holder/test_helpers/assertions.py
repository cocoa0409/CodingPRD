"""Entity assertions and domain invariant checkers.

Each assert_{entity}() validates the common system fields (PRD §2.4) plus the
entity's declared fields, using the framework's generic UUID/timestamp checks.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Common system-managed fields carried by every entity (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be int"
    assert data["version"] >= 1, "version starts at 1 and only increments"


def assert_section(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["tier"] in ("PREMIUM", "STANDARD", "VALUE"), f"bad tier {data['tier']!r}"
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert isinstance(data["total_seats"], int) and data["total_seats"] >= 0
    assert isinstance(data["available_seats"], int) and data["available_seats"] >= 0
    assert data["available_seats"] <= data["total_seats"], "available <= total seats"


def assert_seat(data: dict):
    _assert_common(data)
    assert isinstance(data["section_id"], str)
    assert isinstance(data["row_label"], str)
    assert isinstance(data["seat_number"], int) and data["seat_number"] >= 1
    assert is_iso8601_timestamp(data["season_start_date"])
    assert is_iso8601_timestamp(data["season_end_date"])
    assert data["status"] in ("AVAILABLE", "SOLD"), f"bad seat status {data['status']!r}"


def assert_account(data: dict):
    _assert_common(data)
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["consecutive_seasons"], int) and data["consecutive_seasons"] >= 0
    assert isinstance(data["priority_points"], int)
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD"), f"bad tier {data['loyalty_tier']!r}"
    assert data["status"] in ("ACTIVE", "SUSPENDED"), f"bad account status {data['status']!r}"
    assert_loyalty_tier_consistent(data)


def assert_loyalty_tier_consistent(data: dict):
    """loyalty_tier is derived purely from priority_points (PRD §3.2)."""
    pts = data["priority_points"]
    tier = data["loyalty_tier"]
    if pts < 500:
        expected = "BRONZE"
    elif pts < 1000:
        expected = "SILVER"
    else:
        expected = "GOLD"
    assert tier == expected, f"priority_points={pts} should be {expected}, got {tier}"


def assert_season_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert data["plan_type"] in ("FULL", "PARTIAL"), f"bad plan_type {data['plan_type']!r}"
    assert isinstance(data["game_count"], int) and data["game_count"] >= 1
    assert isinstance(data["price_multiplier_bps"], int)
    assert 0 <= data["price_multiplier_bps"] <= 10000
    assert isinstance(data["includes_playoffs"], bool)


def assert_subscription(data: dict):
    _assert_common(data)
    assert isinstance(data["account_id"], str)
    assert isinstance(data["season_plan_id"], str)
    assert data["status"] in (
        "PENDING", "ACTIVE", "RELOCATING", "RENEWAL_OFFERED", "SUSPENDED", "CANCELLED"
    ), f"bad subscription status {data['status']!r}"
    assert isinstance(data["locked_price_cents"], int) and data["locked_price_cents"] >= 0
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 0
    assert isinstance(data["renewal_cycle"], int) and data["renewal_cycle"] >= 0


def assert_seat_assignment(data: dict):
    _assert_common(data)
    assert isinstance(data["subscription_id"], str)
    assert isinstance(data["seat_id"], str)
    assert isinstance(data["assigned_price_cents"], int) and data["assigned_price_cents"] >= 0
    assert data["status"] in ("ASSIGNED", "RELEASED", "REASSIGNED"), f"bad status {data['status']!r}"


def assert_payment_plan(data: dict):
    _assert_common(data)
    assert isinstance(data["subscription_id"], str)
    assert isinstance(data["total_cents"], int) and data["total_cents"] >= 0
    assert isinstance(data["installment_count"], int) and 2 <= data["installment_count"] <= 12
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert data["status"] in ("ACTIVE", "PAID_IN_FULL", "DEFAULTED", "CANCELLED"), \
        f"bad plan status {data['status']!r}"


def assert_installment(data: dict):
    _assert_common(data)
    assert isinstance(data["payment_plan_id"], str)
    assert isinstance(data["sequence"], int) and data["sequence"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert data["status"] in ("SCHEDULED", "PAID", "VOID"), f"bad installment status {data['status']!r}"


def assert_ticket_transfer(data: dict):
    _assert_common(data)
    assert isinstance(data["seat_assignment_id"], str)
    assert data["transfer_type"] in ("FORWARD", "RESALE"), f"bad transfer_type {data['transfer_type']!r}"
    assert isinstance(data["payout_cents"], int) and data["payout_cents"] >= 0
    assert data["status"] in ("PENDING", "FORWARDED", "LISTED", "SOLD", "CANCELLED"), \
        f"bad transfer status {data['status']!r}"


def assert_parking_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str)
    assert isinstance(data["capacity"], int) and data["capacity"] >= 0
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["active_pass_count"], int) and data["active_pass_count"] >= 0
    assert data["active_pass_count"] <= data["capacity"], "active passes never exceed capacity"


def assert_parking_addon(data: dict):
    _assert_common(data)
    assert isinstance(data["subscription_id"], str)
    assert isinstance(data["parking_zone_id"], str)
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert data["status"] in ("ACTIVE", "RELEASED"), f"bad addon status {data['status']!r}"


__all__ = [
    "assert_section",
    "assert_seat",
    "assert_account",
    "assert_loyalty_tier_consistent",
    "assert_season_plan",
    "assert_subscription",
    "assert_seat_assignment",
    "assert_payment_plan",
    "assert_installment",
    "assert_ticket_transfer",
    "assert_parking_zone",
    "assert_parking_addon",
]
