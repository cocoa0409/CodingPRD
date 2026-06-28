"""Entity assertions and domain invariant checkers.

Assertion helpers validate the shape of each entity using the framework's generic
validators, and domain invariant checkers enforce conserved-quantity rules from the PRD.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_subscription_plan(data: dict):
    _assert_common(data)
    assert data["tier"] in ("ESSENTIAL", "PLUS", "PREMIUM")
    assert isinstance(data["monthly_fee_cents"], int) and data["monthly_fee_cents"] >= 1
    assert isinstance(data["included_miles_per_cycle"], int) and data["included_miles_per_cycle"] >= 0
    assert isinstance(data["free_buffer_miles"], int) and data["free_buffer_miles"] >= 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_fleet(data: dict):
    _assert_common(data)
    assert isinstance(data["total_vehicles"], int) and data["total_vehicles"] >= 0
    assert isinstance(data["in_use_count"], int) and data["in_use_count"] >= 0
    assert isinstance(data["utilization_pct"], (int, float))


def assert_vehicle(data: dict):
    _assert_common(data)
    assert data["status"] in ("AVAILABLE", "RESERVED", "ASSIGNED", "IN_INSPECTION", "MAINTENANCE")
    assert isinstance(data["odometer_miles"], int) and data["odometer_miles"] >= 0


def assert_applicant(data: dict):
    _assert_common(data)
    assert 300 <= data["credit_score"] <= 850
    assert data["history_flag"] in ("CLEAN", "MINOR", "SEVERE")


def assert_subscription(data: dict):
    _assert_common(data)
    assert data["lifecycle_status"] in (
        "DRAFT", "PENDING_DELIVERY", "ACTIVE", "RETURN_PENDING", "CLOSED")
    assert data["billing_status"] in ("CURRENT", "PAST_DUE")
    assert isinstance(data["deposit_held_cents"], int)
    assert isinstance(data["swaps_used"], int)
    assert isinstance(data["lifetime_billed_cents"], int)


def assert_billing_cycle(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "CLOSED")
    assert isinstance(data["cycle_index"], int) and data["cycle_index"] >= 1
    assert isinstance(data["overage_cents"], int)


def assert_invoice(data: dict):
    # Invoice is immutable: id + created_at only, NO updated_at / version.
    assert is_valid_uuid(data.get("id", "")), "invoice id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert data["source_kind"] in ("CYCLE", "SWAP", "EARLY_CANCEL", "RETURN_SETTLEMENT")
    assert isinstance(data["amount_cents"], int)


def assert_invoice_immutable_shape(data: dict):
    """Invoice carries no version field and no updated_at (PRD §2.4)."""
    assert "version" not in data, "Invoice must not carry a version field"
    assert "updated_at" not in data, "Invoice must not carry an updated_at field"


def assert_swap_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "APPROVED", "COMPLETED", "REJECTED")
    assert isinstance(data["swap_fee_applied_cents"], int)
    assert isinstance(data["net_adjustment_cents"], int)


def assert_return_inspection(data: dict):
    _assert_common(data)
    assert data["status"] in ("OPEN", "ASSESSED", "SETTLED")
    assert isinstance(data["total_damage_cents"], int)


def assert_courier(data: dict):
    _assert_common(data)
    assert isinstance(data["buffer_minutes"], int) and data["buffer_minutes"] >= 0


def assert_delivery_slot(data: dict):
    _assert_common(data)
    assert data["kind"] in ("DELIVERY", "RETURN")
    assert data["status"] in ("SCHEDULED", "FULFILLED", "CANCELLED")


def assert_deposit_conserved(inspection: dict, deposit_held_cents: int):
    """PRD §3.11: applied + refunded must equal the held deposit, exactly (no drift)."""
    applied = inspection["deposit_applied_cents"]
    refunded = inspection["deposit_refunded_cents"]
    assert applied + refunded == deposit_held_cents, (
        f"deposit conservation violated: applied {applied} + refunded {refunded} "
        f"!= held {deposit_held_cents}"
    )
