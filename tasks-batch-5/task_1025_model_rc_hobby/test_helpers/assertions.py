"""Entity assertions and domain invariant checkers.

These check structural shape only; specific computed values (totals, points,
allocation units) are asserted directly in the test bodies with the literal
values the design index pins.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and len(data["email"]) > 0
    assert isinstance(data["full_name"], str)
    assert isinstance(data["lifetime_spend_cents"], int)
    assert isinstance(data["loyalty_points_balance"], int)
    assert data["loyalty_tier"] in ("BRONZE", "SILVER", "GOLD")
    assert isinstance(data["hazmat_safety_ack"], bool)


def assert_product(data: dict):
    _assert_common(data)
    assert data["product_type"] in ("KIT", "RC_VEHICLE", "PART", "BATTERY")
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["stock_on_hand"], int)
    assert isinstance(data["is_hazmat"], bool)


def assert_campaign(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "OPEN", "ALLOCATING", "CANCELLED")
    assert isinstance(data["total_allocation_units"], int)
    assert isinstance(data["allocated_units"], int)
    assert isinstance(data["remaining_units"], int)
    assert data["remaining_units"] >= 0, "remaining_units is never negative"


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("HELD", "ALLOCATED", "WAITLISTED", "CONVERTED", "CANCELLED", "EXPIRED")
    assert isinstance(data["requested_units"], int)
    assert isinstance(data["allocated_units"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PLACED")
    assert data["payment_status"] in ("UNPAID", "PAID", "REFUNDED")
    assert data["fulfillment_status"] in ("PENDING", "FULFILLED", "CANCELLED")
    assert data["source"] in ("STANDARD", "PRE_ORDER")


def assert_service_job(data: dict):
    _assert_common(data)
    assert data["status"] in (
        "RECEIVED", "DIAGNOSING", "AWAITING_PARTS", "IN_PROGRESS",
        "QC", "READY", "COMPLETED", "CANCELLED",
    )
    assert data["job_type"] in ("BUILD", "REPAIR")
    assert isinstance(data["rework_count"], int)


def assert_race_event(data: dict):
    _assert_common(data)
    assert data["status"] in ("SCHEDULED", "OPEN", "RUNNING", "FINISHED", "CANCELLED")
    assert isinstance(data["entry_count"], int)


def assert_race_entry(data: dict):
    _assert_common(data)
    assert data["status"] in ("REGISTERED", "CHECKED_IN", "RACED", "DISQUALIFIED", "WITHDRAWN")
    assert data["race_class"] in ("STOCK", "MODIFIED", "PRO")


def assert_allocation_conserved(campaign: dict):
    """Conserved-quantity invariant (PRD 3.3): remaining == total - allocated."""
    assert campaign["remaining_units"] == campaign["total_allocation_units"] - campaign["allocated_units"], (
        f"remaining_units {campaign['remaining_units']} must equal "
        f"total {campaign['total_allocation_units']} - allocated {campaign['allocated_units']}"
    )
