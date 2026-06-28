"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def _assert_append_only_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "append-only entity must not carry version"
    assert "updated_at" not in data, "append-only entity must not carry updated_at"


def assert_location(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["state_code"], str)
    assert isinstance(data["open_minute_of_day"], int)
    assert isinstance(data["close_minute_of_day"], int)
    assert isinstance(data["deposit_required_cents"], int)
    assert isinstance(data["no_show_fee_cents"], int)


def assert_service_type(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["duration_minutes"], int) and data["duration_minutes"] > 0
    assert isinstance(data["buffer_minutes"], int)
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["credit_cost"], int)
    assert isinstance(data["intro_eligible"], bool)
    assert isinstance(data["active"], bool)


def assert_product(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["stock_qty"], int) and data["stock_qty"] >= 0


def assert_room(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["label"], str)
    assert isinstance(data["active"], bool)


def assert_technician(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["location_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["certified_service_ids"], list)
    assert isinstance(data["active"], bool)


def assert_member(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["home_location_id"])
    assert isinstance(data["full_name"], str)
    assert isinstance(data["email"], str)
    assert isinstance(data["intro_used"], bool)
    assert isinstance(data["no_show_strike_count"], int) and data["no_show_strike_count"] >= 0
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_membership(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["tier"] in ("BASIC", "PLUS", "UNLIMITED")
    assert data["status"] in ("PENDING", "ACTIVE", "FROZEN", "PAST_DUE", "CANCELLED")
    assert isinstance(data["credit_balance"], int) and data["credit_balance"] >= 0
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 0


def assert_reservation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["booking_status"] in ("BOOKED", "CHECKED_IN", "COMPLETED", "CANCELLED", "NO_SHOW")
    assert data["settlement_status"] in (
        "UNSETTLED", "DEPOSIT_HELD", "CREDIT_HELD", "PAID", "REFUNDED", "FORFEITED")
    assert data["payment_method"] in ("CREDIT", "DEPOSIT", "INTRO_FREE", "WALK_IN")
    assert isinstance(data["credits_held"], int) and data["credits_held"] >= 0
    assert isinstance(data["deposit_held_cents"], int) and data["deposit_held_cents"] >= 0
    assert isinstance(data["charged_amount_cents"], int) and data["charged_amount_cents"] >= 0


def assert_retail_sale(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["member_id"])
    assert is_valid_uuid(data["reservation_id"])
    assert is_valid_uuid(data["product_id"])
    assert data["status"] in ("PENDING", "CONFIRMED", "VOIDED")
    assert isinstance(data["gross_cents"], int) and data["gross_cents"] >= 0
    assert isinstance(data["discount_cents"], int) and data["discount_cents"] >= 0
    assert isinstance(data["net_cents"], int) and data["net_cents"] >= 0


def assert_credit_ledger_entry(data: dict):
    _assert_append_only_common(data)
    assert is_valid_uuid(data["membership_id"])
    assert data["entry_type"] in (
        "GRANT", "DEBIT", "REFUND", "ROLLOVER_FORFEIT", "FREEZE_PARK", "UNFREEZE_RESTORE")
    assert isinstance(data["delta_credits"], int)
    assert data["source_kind"] in ("MEMBERSHIP", "RESERVATION")


def assert_no_show_strike(data: dict):
    _assert_append_only_common(data)
    assert is_valid_uuid(data["member_id"])
    assert data["strike_kind"] in ("NO_SHOW", "LATE_CANCEL")
    assert data["status"] in ("ACTIVE", "EXPIRED", "WAIVED")
    assert isinstance(data["fee_charged_cents"], int) and data["fee_charged_cents"] >= 0
