"""Entity assertions and domain invariants for the Pet Food
Subscription API.

Uses the framework's generic helpers (is_valid_uuid,
is_iso8601_timestamp) under the hood. Each asserter accepts the dict
shape returned by the respective endpoint and verifies all PRD-required
fields.

Per PRD §2.4 common-fields rule:
- Mutable entities (Customer, Pet, Subscription, Warehouse, InventoryLot,
  Order, ShipmentFeedback, RecipeRecommendation, RecipeAdjustment)
  carry id, created_at, updated_at, version.
- Immutable catalog (Recipe) and append-only log (AuditLog) carry ONLY
  id + created_at.
"""
from __future__ import annotations
from typing import Any, Dict

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


# ---------------------------------------------------------------------------
# Common-fields helpers
# ---------------------------------------------------------------------------
def _assert_common_mutable(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'Mutable resources also carry created_at and
    updated_at ... and version, an integer that starts at 1 on creation
    and is incremented by exactly one on every successful mutation.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be a positive int, got "
        f"{data.get('version')!r}"
    )


def _assert_common_appendonly(data: dict, entity_name: str) -> None:
    """PRD §2.4: 'for these two, updated_at and version are absent
    from the JSON payload entirely.'"""
    assert is_valid_uuid(data.get("id", "")), (
        f"{entity_name}.id must be a valid UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601, got "
        f"{data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Address (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_address(addr: Dict[str, Any]) -> None:
    assert isinstance(addr, dict)
    assert isinstance(addr.get("line1"), str) and len(addr["line1"]) > 0
    assert isinstance(addr.get("city"), str) and len(addr["city"]) > 0
    assert isinstance(addr.get("region"), str)
    assert isinstance(addr.get("postal_code"), str)
    assert isinstance(addr.get("country"), str) and len(addr["country"]) == 2
    assert isinstance(addr.get("verified"), bool)


# ---------------------------------------------------------------------------
# Customer (PRD §3.1, §2.10, §2.4)
# ---------------------------------------------------------------------------
def assert_customer(data: dict) -> None:
    _assert_common_mutable(data, "Customer")
    assert isinstance(data.get("email"), str) and "@" in data["email"]
    assert isinstance(data.get("display_name"), str)
    # default_shipping_address is optional on input but the create
    # default supplies one; we assert the structural shape only if
    # present.
    addr = data.get("default_shipping_address")
    if addr is not None:
        assert_address(addr)
    assert isinstance(data.get("total_charged_cents"), int)
    assert data["total_charged_cents"] >= 0
    assert isinstance(data.get("total_refunded_cents"), int)
    assert data["total_refunded_cents"] >= 0


# ---------------------------------------------------------------------------
# Pet (PRD §3.1)
# ---------------------------------------------------------------------------
def assert_pet(data: dict) -> None:
    _assert_common_mutable(data, "Pet")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data.get("name"), str)
    assert data.get("species") in {"DOG", "CAT"}
    assert isinstance(data.get("breed"), str)
    assert isinstance(data.get("birthdate"), str)
    assert isinstance(data.get("weight_kg"), (int, float))
    assert 0 < float(data["weight_kg"]) <= 100
    assert data.get("activity_level") in {"LOW", "MODERATE", "HIGH"}
    assert isinstance(data.get("allergies"), list)
    assert isinstance(data.get("intolerances"), list)
    assert isinstance(data.get("dietary_preferences"), list)
    assert isinstance(data.get("dietary_aversions"), list)
    assert isinstance(data.get("health_conditions"), list)
    assert data.get("life_stage") in {"PUPPY_KITTEN", "ADULT", "SENIOR"}
    assert isinstance(data.get("photo_gallery"), list)
    assert isinstance(data.get("adjustment_history"), list)
    assert data.get("status") in {"ACTIVE", "VET_HOLD", "ARCHIVED"}


# ---------------------------------------------------------------------------
# Subscription (PRD §3.2)
# ---------------------------------------------------------------------------
def assert_subscription(data: dict) -> None:
    _assert_common_mutable(data, "Subscription")
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data.get("pet_ids"), list)
    assert len(data["pet_ids"]) >= 1
    assert data.get("frequency") in {"WEEKLY", "BIWEEKLY", "MONTHLY"}
    assert isinstance(data.get("cycle_days"), int)
    assert data["cycle_days"] in (7, 14, 30)
    assert_address(data.get("shipping_address", {}))
    assert isinstance(data.get("is_trial"), bool)
    assert data.get("status") in {
        "DRAFT", "ACTIVE", "PAUSED", "CANCELLED", "REACTIVATING",
    }
    assert isinstance(data.get("retention_offer_applied"), bool)
    assert isinstance(data.get("scheduled_order_count"), int)
    assert isinstance(data.get("skipped_count"), int)
    assert isinstance(data.get("total_cycles_elapsed"), int)
    assert isinstance(data.get("modification_deadline_hours"), int)


def assert_cycle_invariant(sub: dict) -> None:
    """PRD §2.10: 'For every Subscription, the equality
    scheduled_order_count + skipped_count == total_cycles_elapsed must
    be true at all times.'"""
    s = sub.get("scheduled_order_count", 0)
    k = sub.get("skipped_count", 0)
    t = sub.get("total_cycles_elapsed", 0)
    assert s + k == t, (
        f"Cycle invariant violated: scheduled_order_count({s}) + "
        f"skipped_count({k}) != total_cycles_elapsed({t})"
    )


# ---------------------------------------------------------------------------
# Recipe (PRD §3.3, §2.4 immutable catalog)
# ---------------------------------------------------------------------------
def assert_recipe(data: dict) -> None:
    _assert_common_appendonly(data, "Recipe")
    # PRD §2.4: Recipe carries only id + created_at; updated_at and
    # version MUST be absent.
    assert "updated_at" not in data, (
        "PRD §2.4: Recipe is immutable catalog; updated_at must be "
        "absent from the JSON payload entirely."
    )
    assert "version" not in data, (
        "PRD §2.4: Recipe is immutable catalog; version must be absent "
        "from the JSON payload entirely."
    )
    assert isinstance(data.get("code"), str)
    assert data.get("target_species") in {"DOG", "CAT"}
    assert data.get("target_life_stage") in {
        "PUPPY_KITTEN", "ADULT", "SENIOR", "ALL",
    }
    assert isinstance(data.get("protein_sources"), list)
    assert isinstance(data.get("grain_sources"), list)
    assert isinstance(data.get("supplement_sources"), list)
    assert isinstance(data.get("kcal_per_gram"), (int, float))
    assert 0 < float(data["kcal_per_gram"]) <= 10
    assert isinstance(data.get("unit_price_cents_per_100g"), int)
    assert data["unit_price_cents_per_100g"] >= 1
    assert isinstance(data.get("vet_prescribed"), bool)
    assert isinstance(data.get("prescribed_for"), list)
    assert isinstance(data.get("monotony_class"), str)
    assert isinstance(data.get("trial_eligible"), bool)


# ---------------------------------------------------------------------------
# RecipeRecommendation (PRD §3.3)
# ---------------------------------------------------------------------------
def assert_recipe_recommendation(data: dict) -> None:
    _assert_common_mutable(data, "RecipeRecommendation")
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("pet_id", ""))
    assert isinstance(data.get("cycle_index"), int)
    assert data["cycle_index"] >= 1
    assert is_valid_uuid(data.get("recipe_id", ""))
    assert isinstance(data.get("match_score"), (int, float))
    assert 0 <= float(data["match_score"]) <= 100
    assert isinstance(data.get("explanation"), list)
    assert data.get("status") in {"PENDING", "FROZEN", "SUPERSEDED"}


# ---------------------------------------------------------------------------
# Warehouse + InventoryLot (PRD §3.6)
# ---------------------------------------------------------------------------
def assert_warehouse(data: dict) -> None:
    _assert_common_mutable(data, "Warehouse")
    assert isinstance(data.get("code"), str)
    assert isinstance(data.get("serves_regions"), list)
    assert isinstance(data.get("priority_rank"), int)
    assert 1 <= data["priority_rank"] <= 100
    assert isinstance(data.get("daily_outbound_capacity"), int)
    assert data["daily_outbound_capacity"] >= 1
    assert data.get("status") in {"ONLINE", "OFFLINE"}


def assert_inventory_lot(data: dict) -> None:
    _assert_common_mutable(data, "InventoryLot")
    assert is_valid_uuid(data.get("warehouse_id", ""))
    assert is_valid_uuid(data.get("recipe_id", ""))
    assert isinstance(data.get("batch_code"), str)
    assert isinstance(data.get("expiration_date"), str)
    assert isinstance(data.get("quantity_grams"), int)
    assert data["quantity_grams"] >= 0


# ---------------------------------------------------------------------------
# Order (PRD §3.4)
# ---------------------------------------------------------------------------
def assert_order(data: dict) -> None:
    _assert_common_mutable(data, "Order")
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data.get("cycle_index"), int)
    assert data["cycle_index"] >= 1
    assert isinstance(data.get("scheduled_ship_at"), str)
    assert isinstance(data.get("items"), list)
    for item in data["items"]:
        assert is_valid_uuid(item.get("pet_id", ""))
        assert is_valid_uuid(item.get("recipe_id", ""))
        assert isinstance(item.get("portion_grams_per_day"), int)
        assert item["portion_grams_per_day"] >= 1
        assert isinstance(item.get("total_grams"), int)
        assert isinstance(item.get("unit_price_cents"), int)
        assert isinstance(item.get("line_total_cents"), int)
        assert item["line_total_cents"] >= 0
    assert isinstance(data.get("subtotal_cents"), int)
    assert isinstance(data.get("shipping_fee_cents"), int)
    assert isinstance(data.get("total_cents"), int)
    assert data["total_cents"] == (
        data["subtotal_cents"] + data["shipping_fee_cents"]
    ), (
        "PRD §3.4: total_cents must equal subtotal + shipping fee"
    )
    assert data.get("payment_status") in {
        "PENDING", "PAID", "REFUNDED", "FAILED",
    }
    assert data.get("fulfillment_status") in {
        "SCHEDULED", "CONFIRMED", "SKIPPED", "SHIPPED",
        "DELIVERED", "CANCELLED",
    }
    assert isinstance(data.get("is_trial_pack"), bool)


def assert_order_subtotal_per_line_round_then_sum(order: dict) -> None:
    """PRD §3.4: 'this is sum-after-round, not round-after-sum, and
    reversing the two operations is a defect.' Verifies that the
    reported subtotal_cents equals the sum of items[].line_total_cents.

    NOTE: For trial-pack orders, PRD §3.4 says the subtotal is
    multiplied by 0.5 and re-rounded; in that case subtotal != raw sum.
    So we only check for non-trial orders.
    """
    if order.get("is_trial_pack"):
        return
    raw_sum = sum(item["line_total_cents"] for item in order["items"])
    assert order["subtotal_cents"] == raw_sum, (
        f"PRD §3.4 per-line-round-then-sum violated: "
        f"subtotal_cents={order['subtotal_cents']} but "
        f"sum(items.line_total_cents)={raw_sum}"
    )


# ---------------------------------------------------------------------------
# ShipmentFeedback (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_shipment_feedback(data: dict) -> None:
    _assert_common_mutable(data, "ShipmentFeedback")
    assert is_valid_uuid(data.get("order_id", ""))
    assert is_valid_uuid(data.get("pet_id", ""))
    assert isinstance(data.get("palatability"), int)
    assert 1 <= data["palatability"] <= 5
    assert isinstance(data.get("stool_quality"), int)
    assert 1 <= data["stool_quality"] <= 5
    assert isinstance(data.get("coat_condition"), int)
    assert 1 <= data["coat_condition"] <= 5
    assert isinstance(data.get("weight_change_grams"), int)
    assert isinstance(data.get("adverse_flag"), bool)
    # PRD §3.5: 'adverse_flag is true when palatability is at most 2
    # or stool_quality is at most 2; otherwise it is false.'
    expected = (
        data["palatability"] <= 2 or data["stool_quality"] <= 2
    )
    assert data["adverse_flag"] is expected, (
        f"PRD §3.5: adverse_flag should be {expected} when "
        f"palatability={data['palatability']} stool_quality="
        f"{data['stool_quality']}; got {data['adverse_flag']}."
    )


# ---------------------------------------------------------------------------
# RecipeAdjustment (PRD §3.5)
# ---------------------------------------------------------------------------
def assert_recipe_adjustment(data: dict) -> None:
    _assert_common_mutable(data, "RecipeAdjustment")
    assert is_valid_uuid(data.get("pet_id", ""))
    assert is_valid_uuid(data.get("subscription_id", ""))
    assert isinstance(data.get("based_on_feedback_ids"), list)
    assert data.get("suggestion_type") in {
        "ROTATE_PROTEIN", "INCREASE_PORTION", "DECREASE_PORTION",
        "SWAP_RECIPE_FAMILY", "VET_ESCALATE",
    }
    assert data.get("status") in {
        "SUGGESTED", "APPLIED", "DISMISSED",
        "VET_PENDING", "VET_APPROVED", "VET_REJECTED",
    }
    assert isinstance(data.get("rationale"), list)


# ---------------------------------------------------------------------------
# AuditLog (PRD §2.9, §2.4 append-only)
# ---------------------------------------------------------------------------
def assert_audit_log_entry(data: dict) -> None:
    _assert_common_appendonly(data, "AuditLog")
    # PRD §2.4: AuditLog is append-only; updated_at and version MUST be
    # absent.
    assert "updated_at" not in data, (
        "PRD §2.4: AuditLog is append-only; updated_at must be absent."
    )
    assert "version" not in data, (
        "PRD §2.4: AuditLog is append-only; version must be absent."
    )
    assert isinstance(data.get("actor_role"), str)
    assert isinstance(data.get("actor_id"), str)
    assert isinstance(data.get("entity_type"), str)
    assert isinstance(data.get("entity_id"), str)
    assert data.get("event_type") in {
        "PLAN_MODIFIED", "SKIPPED", "PAUSED", "RESUMED",
        "CANCELLED", "REACTIVATED",
        "ADJUSTMENT_APPLIED", "ADJUSTMENT_DISMISSED", "VET_ESCALATED",
    }
    assert isinstance(data.get("ts"), str)


# ---------------------------------------------------------------------------
# Money invariant (PRD §2.10)
# ---------------------------------------------------------------------------
def assert_money_invariant(customer: dict, paid_orders_total: int,
                           refunded_orders_total: int) -> None:
    """PRD §2.10: 'For every Customer, the sum of total_cents across
    the customer's orders whose payment_status is PAID must equal
    total_charged_cents, and the sum of total_cents across the
    customer's orders whose payment_status is REFUNDED must equal
    total_refunded_cents.'"""
    assert customer["total_charged_cents"] == paid_orders_total, (
        f"PRD §2.10 money invariant: total_charged_cents="
        f"{customer['total_charged_cents']} != sum(PAID orders)="
        f"{paid_orders_total}"
    )
    assert customer["total_refunded_cents"] == refunded_orders_total, (
        f"PRD §2.10 money invariant: total_refunded_cents="
        f"{customer['total_refunded_cents']} != sum(REFUNDED orders)="
        f"{refunded_orders_total}"
    )


__all__ = [
    "assert_address",
    "assert_customer",
    "assert_pet",
    "assert_subscription",
    "assert_cycle_invariant",
    "assert_recipe",
    "assert_recipe_recommendation",
    "assert_warehouse",
    "assert_inventory_lot",
    "assert_order",
    "assert_order_subtotal_per_line_round_then_sum",
    "assert_shipment_feedback",
    "assert_recipe_adjustment",
    "assert_audit_log_entry",
    "assert_money_invariant",
]
