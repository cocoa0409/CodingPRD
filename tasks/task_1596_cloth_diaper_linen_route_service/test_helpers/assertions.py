"""Entity assertions and domain invariant checkers.

Each assert_* helper validates the common system-managed fields (PRD 2.4) plus
the entity's declared enum memberships and identifier types. The invariant
checkers encode the two conservation ledgers of PRD 2.7 and 2.8.
"""
from typing import Any, Dict

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: Dict[str, Any], entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a server-minted UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"


def assert_plan(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SubscriptionPlan")
    assert isinstance(data["tier_code"], str) and data["tier_code"]
    assert isinstance(data["weekly_quota"], int) and data["weekly_quota"] > 0
    assert isinstance(data["weekly_fee_cents"], int)
    assert isinstance(data["overage_rate_cents"], int)
    assert isinstance(data["overage_cap_items"], int)
    assert isinstance(data["deposit_cents"], int)
    assert isinstance(data["service_bags_per_week"], int)
    assert data["weight_policy"] in ("COUNT_BASIS", "WEIGHT_BASIS")
    assert isinstance(data["kit_reserve_pct"], int)


def assert_zone(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "ServiceZone")
    assert isinstance(data["zone_code"], str) and data["zone_code"]
    assert isinstance(data["service_weekdays"], list)
    assert data["service_days_per_week"] == len(data["service_weekdays"])
    assert isinstance(data["stop_cutoff_hours"], int)
    assert isinstance(data["active"], bool)


def assert_customer(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Customer")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["email"], str) and data["email"]
    assert data["status"] in ("ONBOARDING", "ACTIVE", "SUSPENDED", "CLOSED")
    for field in (
        "deposit_charged_cents",
        "deposit_held_cents",
        "deposit_applied_cents",
        "deposit_refunded_cents",
    ):
        assert isinstance(data[field], int), f"Customer.{field} must be an integer"


def assert_subscription(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Subscription")
    assert data["service_status"] in (
        "PENDING_START",
        "ACTIVE",
        "PAUSED",
        "SUSPENDED",
        "TERMINATED",
    )
    assert data["billing_status"] in ("CURRENT", "PAST_DUE")
    assert isinstance(data["missed_stop_count"], int)
    assert isinstance(data["window_start_minutes"], int)
    assert isinstance(data["window_end_minutes"], int)


def assert_pause(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "ServicePause")
    assert data["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED", "CANCELLED")
    assert isinstance(data["estimated_credit_cents"], int)


def assert_kit(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "StarterKit")
    assert data["status"] in ("RESERVED", "ISSUED", "RETURNED", "SETTLED")
    assert data["size_code"] in ("NEWBORN", "SMALL", "MEDIUM", "LARGE", "XL")
    assert isinstance(data["item_count"], int)
    assert isinstance(data["items_returned_count"], int)


def assert_pool(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "InventoryPool")
    assert data["size_code"] in ("NEWBORN", "SMALL", "MEDIUM", "LARGE", "XL")
    for field in (
        "on_hand_units",
        "reserved_units",
        "in_transit_units",
        "checked_out_units",
        "in_wash_units",
        "quarantined_units",
        "lost_units",
        "retired_units",
        "total_acquired_units",
    ):
        assert isinstance(data[field], int), f"InventoryPool.{field} must be an integer"


def assert_swap(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "InventorySwap")
    assert data["status"] in (
        "REQUESTED",
        "APPROVED",
        "STAGED",
        "COMPLETED",
        "DENIED",
        "CANCELLED",
    )
    assert isinstance(data["quantity"], int)
    assert isinstance(data["returned_old_count"], int)
    assert isinstance(data["shortage_count"], int)


def assert_route(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Route")
    assert data["status"] in (
        "PLANNED",
        "SEQUENCED",
        "LOCKED",
        "IN_PROGRESS",
        "COMPLETED",
        "CANCELLED",
    )
    assert isinstance(data["planned_stop_count"], int)
    assert isinstance(data["completed_stop_count"], int)
    assert isinstance(data["total_clean_items_delivered"], int)
    assert isinstance(data["total_soiled_bags_collected"], int)


def assert_stop(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "RouteStop")
    assert data["status"] in (
        "PLANNED",
        "COMPLETED",
        "MISSED",
        "SKIPPED",
        "FORFEITED",
        "RESCHEDULED",
    )
    assert data["stop_seq"] is None or isinstance(data["stop_seq"], int)
    assert isinstance(data["clean_items_delivered"], int)
    assert isinstance(data["soiled_bags_collected"], int)
    assert isinstance(data["is_makeup"], bool)


def assert_intake(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "SoiledIntake")
    assert data["status"] in ("RECONCILED", "DISPUTED", "RESOLVED")
    assert data["soil_level"] in ("LIGHT", "NORMAL", "HEAVY")
    assert isinstance(data["scale_weight_g"], int) and data["scale_weight_g"] > 0
    assert isinstance(data["expected_weight_g"], int)
    assert isinstance(data["verified_count"], int)


def assert_formula(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "WashFormula")
    assert isinstance(data["formula_code"], str) and data["formula_code"]
    assert isinstance(data["max_rewash_count"], int)


def assert_batch(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "WashBatch")
    assert data["status"] in (
        "RECEIVING",
        "LOADED",
        "WASHING",
        "VALIDATING",
        "RELEASED",
        "QUARANTINED",
    )
    assert data["soil_level"] in ("LIGHT", "NORMAL", "HEAVY")
    assert data["water_hardness"] in ("SOFT", "MEDIUM", "HARD")
    assert isinstance(data["total_load_g"], int)
    assert isinstance(data["rewash_count"], int)


def assert_case(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "LostItemCase")
    assert data["case_type"] in ("LOST", "DAMAGED")
    assert data["status"] in ("OPEN", "CHARGED", "DISPUTED", "SETTLED", "WAIVED")
    assert isinstance(data["item_count"], int) and data["item_count"] >= 1


def assert_invoice(data: Dict[str, Any]) -> None:
    _assert_common_fields(data, "Invoice")
    assert data["status"] in ("DRAFT", "ISSUED", "PAID", "PAST_DUE", "VOID", "WRITTEN_OFF")
    for field in ("base_fee_cents", "overage_cents", "pause_credit_cents", "total_cents"):
        assert isinstance(data[field], int), f"Invoice.{field} must be an integer"


def assert_pool_conservation(pool: Dict[str, Any]) -> None:
    """PRD 2.7: the eight buckets sum exactly to total_acquired_units, and
    available_units is on-hand minus reserved."""
    bucket_sum = (
        pool["on_hand_units"]
        + pool["reserved_units"]
        + pool["in_transit_units"]
        + pool["checked_out_units"]
        + pool["in_wash_units"]
        + pool["quarantined_units"]
        + pool["lost_units"]
        + pool["retired_units"]
    )
    assert bucket_sum == pool["total_acquired_units"], (
        f"pool conservation broken: buckets sum to {bucket_sum}, "
        f"total_acquired_units is {pool['total_acquired_units']}"
    )
    assert pool["available_units"] == pool["on_hand_units"] - pool["reserved_units"], (
        f"available_units {pool['available_units']} != on_hand "
        f"{pool['on_hand_units']} - reserved {pool['reserved_units']}"
    )


def assert_deposit_ledger_conserved(customer: Dict[str, Any]) -> None:
    """PRD 2.8: at all times, the charged amount equals the sum of held,
    applied, and refunded; held may never go negative."""
    total = (
        customer["deposit_held_cents"]
        + customer["deposit_applied_cents"]
        + customer["deposit_refunded_cents"]
    )
    assert customer["deposit_charged_cents"] == total, (
        f"deposit ledger broken: charged {customer['deposit_charged_cents']} != "
        f"held+applied+refunded {total}"
    )
    assert customer["deposit_held_cents"] >= 0, "deposit_held_cents may never go negative"
