"""Entity assertions and domain invariant checkers.

Field names are PRD-exact. Append-only ledger entries are validated WITHOUT
updated_at/version (PRD 2.4: a LoyaltyLedgerEntry carries only id and created_at).
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_member(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert data["tier"] in ("BRONZE", "SILVER", "GOLD")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["point_balance"], int) and data["point_balance"] >= 0
    assert isinstance(data["lifetime_points_earned"], int) and data["lifetime_points_earned"] >= 0
    assert isinstance(data.get("version"), int)


def assert_paint_bar_item(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["category"] in ("GLAZE", "UNDERGLAZE", "TOOL", "TOGO_KIT")
    assert data["status"] in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["on_hand_qty"], int) and data["on_hand_qty"] >= 0
    assert isinstance(data["low_stock"], bool)


def assert_visit(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("OPEN", "SETTLED", "VOIDED")
    assert data["visit_type"] in ("WALK_IN", "PARTY")
    assert isinstance(data["party_size"], int) and data["party_size"] >= 1
    for f in ("studio_fee_cents", "bisque_subtotal_cents", "supplies_subtotal_cents",
              "provisional_total_cents", "settled_total_cents", "points_earned"):
        assert isinstance(data[f], int) and data[f] >= 0, f"{f} must be a non-negative int"


def assert_piece(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("PAINTED", "LOADED", "FIRING", "READY", "PICKED_UP", "VOIDED")
    assert data["firing_temp"] in ("CONE_06", "CONE_6")
    assert isinstance(data["bisque_price_cents"], int) and data["bisque_price_cents"] >= 1


def assert_batch(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("LOADING", "FIRING", "COMPLETED", "CANCELLED")
    assert data["firing_temp"] in ("CONE_06", "CONE_6")
    assert isinstance(data["capacity_slots"], int) and data["capacity_slots"] >= 1
    assert isinstance(data["occupied_slots"], int) and 0 <= data["occupied_slots"] <= data["capacity_slots"]


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("DEPOSIT_PENDING", "CONFIRMED", "EXPIRED", "CANCELLED")
    assert data["package_tier"] in ("BASIC", "DELUXE")
    for f in ("package_total_cents", "deposit_due_cents", "deposit_paid_cents"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_series(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("OPEN", "FULL", "STARTED", "CANCELLED")
    assert isinstance(data["seat_capacity"], int) and data["seat_capacity"] >= 1
    assert isinstance(data["enrolled_count"], int) and data["enrolled_count"] >= 0


def assert_enrollment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["status"] in ("ENROLLED", "ATTENDED", "WITHDRAWN", "REFUNDED")
    assert isinstance(data["amount_paid_cents"], int) and data["amount_paid_cents"] >= 0
    assert isinstance(data["points_earned"], int) and data["points_earned"] >= 0


def assert_ledger_entry(data: dict):
    """Append-only event: id + created_at only; no updated_at, no version."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["entry_type"] in ("EARN", "REDEEM", "REVERSAL")
    assert data["source_ref_type"] in ("VISIT", "ENROLLMENT", "BOOKING")
    assert isinstance(data["points_delta"], int)
    assert "version" not in data, "append-only ledger entry must NOT carry a version field"
    assert "updated_at" not in data, "append-only ledger entry must NOT carry an updated_at field"
