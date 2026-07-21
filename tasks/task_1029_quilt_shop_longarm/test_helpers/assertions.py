"""Entity assertions and domain invariant checkers (PRD §2, §3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid, is_iso8601_timestamp, assert_cost_precision,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be int >= 1"


def assert_member(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["points_balance"], int), "points_balance must be an integer"
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")


def assert_fabric_bolt(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and len(data["sku"]) > 0
    assert data["status"] in ("IN_STOCK", "LOW_STOCK", "DEPLETED", "DISCONTINUED")
    assert isinstance(data["yards_remaining"], (int, float))


def assert_fabric_cut(data: dict):
    _assert_common(data)
    assert data["status"] in ("CUT", "VOIDED")
    assert is_valid_uuid(data["bolt_id"])
    assert isinstance(data["yards_requested"], (int, float))
    assert isinstance(data["line_price"], (int, float))
    assert_cost_precision(data["line_price"])


def assert_kit(data: dict):
    _assert_common(data)
    assert data["kit_type"] in ("KIT", "BOM", "BLOCK_OF_MONTH")
    assert data["status"] in ("AVAILABLE", "UNAVAILABLE")
    assert isinstance(data["materials_cost"], (int, float))
    assert isinstance(data["kit_price"], (int, float))
    assert_cost_precision(data["materials_cost"])
    assert_cost_precision(data["kit_price"])


def assert_longarm_machine(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "MAINTENANCE")


def assert_longarm_job(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUEUED", "IN_PROGRESS", "COMPLETED")
    assert data["pattern_tier"] in ("EDGE_TO_EDGE", "CUSTOM", "HEIRLOOM")
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["estimated_price"], (int, float))
    assert_cost_precision(data["estimated_price"])
    if data.get("final_price") is not None:
        assert_cost_precision(data["final_price"])


def assert_class_event(data: dict):
    _assert_common(data)
    assert data["event_type"] in ("CLASS", "RETREAT")
    assert data["status"] in ("OPEN", "FULL", "CANCELLED")
    assert isinstance(data["seats_taken"], int)
    assert isinstance(data["capacity"], int)


def assert_enrollment(data: dict):
    _assert_common(data)
    assert data["status"] in ("CONFIRMED", "CANCELLED")
    assert is_valid_uuid(data["class_event_id"])
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["points_earned"], int)


def assert_special_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("QUOTED", "FULFILLED")
    assert is_valid_uuid(data["member_id"])
    assert isinstance(data["quantity"], int)
    assert isinstance(data["quoted_price"], (int, float))
    assert_cost_precision(data["quoted_price"])
    if data.get("final_total") is not None:
        assert_cost_precision(data["final_total"])


def assert_loyalty_transaction(data: dict):
    """Append-only ledger row (PRD §2.4): id + created_at only, no updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["points"], int), "points must be a signed integer"
    assert data["reason"] in (
        "ENROLLMENT_CONFIRM", "ENROLLMENT_CANCEL_REVERSAL",
        "SPECIAL_ORDER_FULFILL", "LONGARM_COMPLETE",
    )
