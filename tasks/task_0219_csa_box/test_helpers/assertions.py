"""Entity assertions and domain invariant checkers (CSA Box API)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    """Shared id/created_at/updated_at/version checks for full-field entities."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_season(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["week_count"], int) and 1 <= data["week_count"] <= 52
    assert data["status"] in ("DRAFT", "OPEN", "CLOSED")
    assert isinstance(data["total_share_capacity"], int) and data["total_share_capacity"] >= 0
    assert isinstance(data["confirmed_share_count"], int) and data["confirmed_share_count"] >= 0


def assert_pickup_site(data: dict):
    _assert_common(data)
    assert data["kind"] in ("PICKUP", "HOME_DELIVERY")
    assert isinstance(data["weekly_capacity"], int) and data["weekly_capacity"] >= 0
    assert isinstance(data["active_subscription_count"], int) and data["active_subscription_count"] >= 0


def assert_share_type(data: dict):
    _assert_common(data)
    assert data["size"] in ("SMALL", "MEDIUM", "LARGE")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert isinstance(data["items_per_box"], int) and data["items_per_box"] >= 1


def assert_add_on(data: dict):
    _assert_common(data)
    assert data["kind"] in ("EGGS", "FLOWERS")
    assert isinstance(data["weekly_price_cents"], int) and data["weekly_price_cents"] > 0
    assert isinstance(data["weekly_supply_cap"], int) and data["weekly_supply_cap"] >= 0
    assert isinstance(data["committed_count"], int) and data["committed_count"] >= 0


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["sliding_scale_tier"] in ("SOLIDARITY", "BASELINE", "SUSTAINER")
    assert isinstance(data["wallet_credit_cents"], int)


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["billing_status"] in ("PENDING_PAYMENT", "CONFIRMED", "ACTIVE", "CANCELLED")
    assert data["fulfillment_status"] in ("NOT_STARTED", "IN_SEASON", "COMPLETED")
    assert isinstance(data["season_price_cents"], int) and data["season_price_cents"] >= 0
    assert isinstance(data["outstanding_balance_cents"], int) and data["outstanding_balance_cents"] >= 0
    assert isinstance(data["working_share_opt_in"], bool)


def assert_subscription_add_on(data: dict):
    _assert_common(data)
    assert data["status"] in ("ATTACHED", "DETACHED")


def assert_weekly_box(data: dict):
    _assert_common(data)
    assert isinstance(data["week_index"], int) and data["week_index"] >= 1
    assert data["status"] in ("SCHEDULED", "HELD", "PACKED", "DELIVERED", "SKIPPED")
    assert isinstance(data["item_count"], int) and data["item_count"] >= 0


def assert_vacation_hold(data: dict):
    _assert_common(data)
    assert data["mode"] in ("REFUND", "SWAP")
    assert data["status"] in ("ACTIVE", "RELEASED", "CONSUMED")


def assert_waitlist_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ("WAITING", "OFFERED", "CONVERTED", "DECLINED", "EXPIRED")


def assert_work_share_shift(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "COMPLETED", "NO_SHOW")
    assert isinstance(data["credit_earned_cents"], int) and data["credit_earned_cents"] >= 0


def assert_ledger_entry(data: dict):
    """LedgerEntry is append-only: id + created_at only, NO updated_at, NO version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_type"] in (
        "CHARGE_SEASON", "CHARGE_ADDON", "CHARGE_SURCHARGE",
        "CREDIT_WORKSHARE", "CREDIT_HOLD_REFUND", "PAYMENT",
    )
    assert isinstance(data["amount_cents"], int)


def assert_ledger_entry_is_append_only(data: dict):
    """A LedgerEntry response carries no version and no updated_at field."""
    assert "version" not in data, "LedgerEntry must not expose a version field"
    assert "updated_at" not in data, "LedgerEntry must not expose an updated_at field"
