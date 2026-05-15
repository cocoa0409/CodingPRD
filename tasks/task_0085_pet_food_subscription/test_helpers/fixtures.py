"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce
clear 'Setup failed' errors instead of confusing assertion mismatches.

Identity threading (PRD §2.1): every Customer-acting call uses
make_customer_headers(customer['id']) — never the shared
TEST_USERS['customer_headers'] fallback, which is reserved for tests
that do not exercise ownership.

The logical clock (PRD §2.8) starts at zero in a fresh implementation
and advances only via /_clock/advance. Fixtures that depend on a
specific clock instant call advance_clock to reach that state.
"""
from __future__ import annotations
import datetime as dt
import uuid
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CYCLE_DAYS_BY_FREQUENCY,
    DEFAULT_MODIFICATION_DEADLINE_HOURS,
    SECONDS_PER_DAY,
    SECONDS_PER_HOUR,
    SHIP_LEAD_TIME_HOURS,
    TEST_DEFAULTS,
)
from .factories import (
    add_pet_photo_payload,
    cancel_subscription_payload,
    clock_advance_payload,
    create_customer_payload,
    create_inventory_lot_payload,
    create_pet_payload,
    create_recipe_payload,
    create_subscription_payload,
    create_warehouse_payload,
    logistics_event_payload,
    make_address,
    pause_subscription_payload,
    payment_event_payload,
    submit_feedback_payload,
    update_pet_payload,
    update_subscription_payload,
    vet_event_payload,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
)


# ===========================================================================
# Tier 0: Time helpers
# ===========================================================================
def advance_clock_by_hours(hours: int) -> Dict[str, Any]:
    """PRD §3.7: relative by_hours advance."""
    res = api_client.advance_clock(
        clock_advance_payload(by_hours=hours),
        TEST_USERS["admin_ops_headers"],
    )
    return get_success_data(res)


def advance_clock_to(to_iso: str) -> Dict[str, Any]:
    """PRD §3.7: absolute clock advance to a specific instant."""
    res = api_client.advance_clock(
        clock_advance_payload(to=to_iso),
        TEST_USERS["admin_ops_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 1: Single-entity creation
# ===========================================================================
def create_customer(**overrides: Any) -> Dict[str, Any]:
    """Create a Customer with default verifiable address. Returns the
    Customer dict (with `verified=false` on the address until
    /shipping-address/verify runs)."""
    res = api_client.create_customer(
        create_customer_payload(**overrides),
        TEST_USERS["customer_headers"],  # creation precedes ownership
    )
    return get_success_data(res)


def verify_customer_address(customer: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.1 customer-level verify capability. Uses owner-bound
    headers (Customer is entity_backed)."""
    res = api_client.verify_customer_address(
        customer["id"],
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def create_pet(customer: Dict[str, Any],
               **overrides: Any) -> Dict[str, Any]:
    """Create a Pet under the customer. Uses owner-bound Customer
    headers."""
    res = api_client.create_pet(
        customer["id"],
        create_pet_payload(**overrides),
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def create_recipe(**overrides: Any) -> Dict[str, Any]:
    """AdminOps create a Recipe in the catalog (PRD §3.3)."""
    res = api_client.create_recipe(
        create_recipe_payload(**overrides),
        TEST_USERS["admin_ops_headers"],
    )
    return get_success_data(res)


def create_warehouse(**overrides: Any) -> Dict[str, Any]:
    """AdminOps create a Warehouse (PRD §3.6)."""
    res = api_client.create_warehouse(
        create_warehouse_payload(**overrides),
        TEST_USERS["admin_ops_headers"],
    )
    return get_success_data(res)


def create_inventory_lot(warehouse: Dict[str, Any], recipe_id: str,
                         **overrides: Any) -> Dict[str, Any]:
    """AdminOps stock an InventoryLot in a warehouse (PRD §3.6)."""
    res = api_client.create_inventory_lot(
        warehouse["id"],
        create_inventory_lot_payload(recipe_id, **overrides),
        TEST_USERS["admin_ops_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2: Compound setups
# ===========================================================================
def setup_verified_customer(**customer_overrides: Any) -> Dict[str, Any]:
    """Create a Customer and verify their default shipping address.
    Returns the Customer record (with default_shipping_address.verified
    == True)."""
    customer = create_customer(**customer_overrides)
    customer = verify_customer_address(customer)
    return customer


def setup_customer_with_pet(
    *,
    customer_overrides: Optional[Dict[str, Any]] = None,
    pet_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Verified Customer + one ACTIVE Pet. Returns (customer, pet)."""
    customer = setup_verified_customer(**(customer_overrides or {}))
    pet = create_pet(customer, **(pet_overrides or {}))
    return customer, pet


def setup_basic_recipe(**overrides: Any) -> Dict[str, Any]:
    """One ADULT/DOG recipe in the catalog with default
    monotony_class A. For multi-recipe setups, override
    monotony_class/code as needed."""
    return create_recipe(**overrides)


def setup_warehouse_with_inventory(
    recipe_id: str, *,
    quantity_grams: int = TEST_DEFAULTS["BATCH_QUANTITY_GRAMS"],
    expiration_date: str = "2099-12-31",
    daily_outbound_capacity: int = TEST_DEFAULTS["DAILY_CAPACITY"],
    serves_regions: Optional[List[str]] = None,
    priority_rank: int = TEST_DEFAULTS["PRIORITY_RANK"],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """One ONLINE warehouse stocked with one InventoryLot for recipe.
    Returns (warehouse, lot)."""
    wh = create_warehouse(
        daily_outbound_capacity=daily_outbound_capacity,
        serves_regions=serves_regions or [TEST_DEFAULTS["REGION"]],
        priority_rank=priority_rank,
    )
    lot = create_inventory_lot(
        wh, recipe_id,
        quantity_grams=quantity_grams,
        expiration_date=expiration_date,
    )
    return wh, lot


def create_draft_subscription(customer: Dict[str, Any],
                              pet: Dict[str, Any],
                              **overrides: Any) -> Dict[str, Any]:
    """Create a DRAFT Subscription for one pet. Address.verified is
    False until verify_subscription_address runs (PRD §3.2)."""
    res = api_client.create_subscription(
        customer["id"],
        create_subscription_payload([pet["id"]], **overrides),
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def verify_subscription_address(customer: Dict[str, Any],
                                sub: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.verify_subscription_address(
        sub["id"], make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def activate_subscription(customer: Dict[str, Any],
                          sub: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.activate_subscription(
        sub["id"], make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


# ===========================================================================
# Tier 3: Active subscription with infrastructure for order generation
# ===========================================================================
def setup_active_subscription(
    *,
    pet_overrides: Optional[Dict[str, Any]] = None,
    customer_overrides: Optional[Dict[str, Any]] = None,
    subscription_overrides: Optional[Dict[str, Any]] = None,
    recipe_overrides: Optional[Dict[str, Any]] = None,
    seed_recipe: bool = True,
    seed_warehouse: bool = True,
    serves_regions: Optional[List[str]] = None,
    warehouse_daily_capacity: int = TEST_DEFAULTS["DAILY_CAPACITY"],
    warehouse_quantity_grams: int = TEST_DEFAULTS["BATCH_QUANTITY_GRAMS"],
) -> Dict[str, Any]:
    """End-to-end setup that yields an ACTIVE Subscription, ready for
    the cycle scheduler to emit Orders on the next /_clock/advance.

    Returns a dict with keys:
        customer, pet, subscription, recipe (or None),
        warehouse (or None), lot (or None)

    PRD §3.2: 'A DRAFT subscription moves to ACTIVE when the customer
    invokes activation, provided that the subscription's
    shipping_address has been verified ... and that every pet in
    pet_ids is in ACTIVE status.'
    """
    customer, pet = setup_customer_with_pet(
        customer_overrides=customer_overrides,
        pet_overrides=pet_overrides,
    )
    recipe = None
    if seed_recipe:
        # Derive target_species and target_life_stage from the pet so
        # the seeded recipe always passes PRD §3.3 eligibility for this
        # pet — unless the test explicitly overrides them.
        derived: Dict[str, Any] = {}
        if "target_species" not in (recipe_overrides or {}):
            derived["target_species"] = pet["species"]
        if "target_life_stage" not in (recipe_overrides or {}):
            derived["target_life_stage"] = pet["life_stage"]
        merged = {**derived, **(recipe_overrides or {})}
        recipe = setup_basic_recipe(**merged)

    warehouse = None
    lot = None
    if seed_warehouse and recipe is not None:
        warehouse, lot = setup_warehouse_with_inventory(
            recipe["id"],
            quantity_grams=warehouse_quantity_grams,
            daily_outbound_capacity=warehouse_daily_capacity,
            serves_regions=serves_regions,
        )

    sub = create_draft_subscription(
        customer, pet, **(subscription_overrides or {}),
    )
    sub = verify_subscription_address(customer, sub)
    sub = activate_subscription(customer, sub)
    return {
        "customer": customer,
        "pet": pet,
        "subscription": sub,
        "recipe": recipe,
        "warehouse": warehouse,
        "lot": lot,
    }


def emit_next_order(customer: Dict[str, Any],
                    sub: Dict[str, Any],
                    *, cycle_days: int = 7) -> Dict[str, Any]:
    """Advance the logical clock by `cycle_days` days so the cycle
    scheduler emits one new Order for this subscription. Returns the
    most recent (highest cycle_index) Order belonging to `sub`.

    PRD §3.4: 'For every subscription whose status is ACTIVE and whose
    next_cycle_at is at or before the new clock value, the scheduler
    emits one new Order per advance.'
    """
    advance_clock_by_hours(cycle_days * 24)
    list_res = api_client.list_orders(
        sub["id"], make_customer_headers(customer["id"]),
        params={"limit": 100, "offset": 0},
    )
    data = list_res.json()["data"]
    if not isinstance(data, list):
        raise AssertionError(
            f"Setup failed: list_orders returned non-array data: {data!r}"
        )
    if not data:
        raise AssertionError(
            "Setup failed: cycle scheduler did not emit an Order after "
            f"advancing clock by {cycle_days} days."
        )
    # Return the order with the largest cycle_index.
    return max(data, key=lambda o: o.get("cycle_index", 0))


def setup_subscription_with_order(
    *,
    pet_overrides: Optional[Dict[str, Any]] = None,
    subscription_overrides: Optional[Dict[str, Any]] = None,
    recipe_overrides: Optional[Dict[str, Any]] = None,
    cycle_days: int = 7,
) -> Dict[str, Any]:
    """ACTIVE Subscription + first Order emitted by the cycle scheduler.
    Returns the same dict shape as setup_active_subscription plus
    'order'."""
    bundle = setup_active_subscription(
        pet_overrides=pet_overrides,
        subscription_overrides=subscription_overrides,
        recipe_overrides=recipe_overrides,
    )
    order = emit_next_order(
        bundle["customer"], bundle["subscription"],
        cycle_days=cycle_days,
    )
    bundle["order"] = order
    return bundle


# ===========================================================================
# Tier 4: Drive an order through its lifecycle
# ===========================================================================
def confirm_order(customer: Dict[str, Any],
                  order: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.confirm_order(
        order["id"], make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def capture_payment(order: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.post_payment_event(
        order["id"],
        payment_event_payload("PAYMENT_CAPTURED"),
        TEST_USERS["payment_adapter_headers"],
    )
    return get_success_data(res)


def dispatch_shipment(order: Dict[str, Any],
                      tracking_number: Optional[str] = None) -> Dict[str, Any]:
    res = api_client.post_logistics_event(
        order["id"],
        logistics_event_payload(
            "SHIPMENT_DISPATCHED",
            tracking_number=tracking_number or f"TRK-{uuid.uuid4().hex[:10]}",
        ),
        TEST_USERS["logistics_adapter_headers"],
    )
    return get_success_data(res)


def deliver_order(order: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.post_logistics_event(
        order["id"],
        logistics_event_payload("DELIVERY_CONFIRMED"),
        TEST_USERS["logistics_adapter_headers"],
    )
    return get_success_data(res)


def refund_order(order: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.post_payment_event(
        order["id"],
        payment_event_payload("PAYMENT_REFUNDED"),
        TEST_USERS["payment_adapter_headers"],
    )
    return get_success_data(res)


def drive_order_to_delivered(customer: Dict[str, Any],
                             order: Dict[str, Any]) -> Dict[str, Any]:
    """Walks an Order: SCHEDULED → CONFIRMED → (PAID) → SHIPPED →
    DELIVERED. Returns the final delivered Order dict.

    PRD §3.4: 'A SHIPMENT_DISPATCHED event moves fulfillment_status
    from CONFIRMED to SHIPPED, provided that payment_status is PAID';
    'A DELIVERY_CONFIRMED event moves fulfillment_status from SHIPPED
    to DELIVERED.'
    """
    confirmed = confirm_order(customer, order)
    capture_payment(confirmed)
    dispatch_shipment(confirmed)
    delivered = deliver_order(confirmed)
    return delivered


# ===========================================================================
# Tier 4 specialized: difficulty-design fixtures
# ===========================================================================
def setup_two_recipes_grain_free_dog_adult(
    *, kcal_per_gram: float = TEST_DEFAULTS["KCAL_PER_GRAM"],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Two ADULT/DOG recipes with distinct monotony_classes. Used by
    tests that need rotation-eligible alternatives in the catalog."""
    r_a = create_recipe(
        code=f"R-A-{uuid.uuid4().hex[:6].upper()}",
        protein_sources=["SALMON"],
        grain_sources=[],
        supplement_sources=["OMEGA3"],
        kcal_per_gram=kcal_per_gram,
        monotony_class=TEST_DEFAULTS["MONOTONY_CLASS_A"],
    )
    r_b = create_recipe(
        code=f"R-B-{uuid.uuid4().hex[:6].upper()}",
        protein_sources=["TURKEY"],
        grain_sources=[],
        supplement_sources=["GLUCOSAMINE"],
        kcal_per_gram=kcal_per_gram,
        monotony_class=TEST_DEFAULTS["MONOTONY_CLASS_B"],
    )
    return r_a, r_b


def setup_active_subscription_with_two_recipes(
    *,
    pet_overrides: Optional[Dict[str, Any]] = None,
    subscription_overrides: Optional[Dict[str, Any]] = None,
    kcal_per_gram: float = TEST_DEFAULTS["KCAL_PER_GRAM"],
) -> Dict[str, Any]:
    """ACTIVE Subscription + two distinct ADULT/DOG recipes (different
    monotony_classes) + warehouse with inventory of both recipes.
    Useful when the test must exercise rotation or recipe swap."""
    r_a, r_b = setup_two_recipes_grain_free_dog_adult(
        kcal_per_gram=kcal_per_gram,
    )
    customer, pet = setup_customer_with_pet(
        customer_overrides=None,
        pet_overrides=pet_overrides,
    )
    wh = create_warehouse()
    lot_a = create_inventory_lot(wh, r_a["id"])
    lot_b = create_inventory_lot(wh, r_b["id"])
    sub = create_draft_subscription(
        customer, pet, **(subscription_overrides or {}),
    )
    sub = verify_subscription_address(customer, sub)
    sub = activate_subscription(customer, sub)
    return {
        "customer": customer,
        "pet": pet,
        "subscription": sub,
        "recipe_a": r_a,
        "recipe_b": r_b,
        "warehouse": wh,
        "lot_a": lot_a,
        "lot_b": lot_b,
    }


def setup_delivered_order(
    *,
    pet_overrides: Optional[Dict[str, Any]] = None,
    subscription_overrides: Optional[Dict[str, Any]] = None,
    recipe_overrides: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """ACTIVE Subscription + first Order driven all the way to
    DELIVERED. Returns bundle with 'order' set to the DELIVERED Order.
    Useful for feedback-loop tests."""
    bundle = setup_subscription_with_order(
        pet_overrides=pet_overrides,
        subscription_overrides=subscription_overrides,
        recipe_overrides=recipe_overrides,
    )
    delivered = drive_order_to_delivered(
        bundle["customer"], bundle["order"],
    )
    bundle["order"] = delivered
    return bundle


def submit_feedback(customer: Dict[str, Any],
                    order: Dict[str, Any],
                    pet: Dict[str, Any],
                    **overrides: Any) -> Dict[str, Any]:
    """Submit a ShipmentFeedback under the customer (PRD §3.5)."""
    res = api_client.submit_feedback(
        order["id"],
        submit_feedback_payload(pet["id"], **overrides),
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def list_recipe_adjustments(customer: Dict[str, Any],
                            pet: Dict[str, Any],
                            **params: Any) -> List[Dict[str, Any]]:
    res = api_client.list_recipe_adjustments(
        pet["id"], make_customer_headers(customer["id"]),
        params=params or None,
    )
    payload = res.json()
    return payload.get("data") or []


def get_recipe_recommendations(customer: Dict[str, Any],
                               pet: Dict[str, Any]
                               ) -> List[Dict[str, Any]]:
    res = api_client.list_recipe_recommendations(
        pet["id"], make_customer_headers(customer["id"]),
    )
    payload = res.json()
    return payload.get("data") or []


def trigger_decrease_portion_adjustment(
    bundle: Dict[str, Any],
) -> Dict[str, Any]:
    """Drive feedback aggregation so suggestion_engine emits a
    DECREASE_PORTION adjustment.

    PRD §3.5 branch 3: 'if total_weight_change_grams is strictly
    greater than 500 grams, emit a RecipeAdjustment whose
    suggestion_type is DECREASE_PORTION and whose portion_delta_pct is
    -10.'

    Requires bundle already contains a DELIVERED order. Submits 2
    feedbacks with weight_change_grams=+600 each so total > 500
    (and adverse_count=0 so vet-escalate branch does not fire).
    """
    customer = bundle["customer"]
    pet = bundle["pet"]
    order = bundle["order"]
    submit_feedback(
        customer, order, pet,
        palatability=5, stool_quality=5, coat_condition=5,
        weight_change_grams=600,
    )
    submit_feedback(
        customer, order, pet,
        palatability=5, stool_quality=5, coat_condition=5,
        weight_change_grams=600,
    )
    adjustments = list_recipe_adjustments(customer, pet)
    suggested = [
        a for a in adjustments
        if a.get("status") == "SUGGESTED"
        and a.get("suggestion_type") == "DECREASE_PORTION"
    ]
    if not suggested:
        raise AssertionError(
            "Setup failed: expected a SUGGESTED DECREASE_PORTION "
            f"adjustment after 2 feedbacks; got {adjustments!r}"
        )
    return suggested[0]


def apply_recipe_adjustment(customer: Dict[str, Any],
                            pet: Dict[str, Any],
                            adjustment: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.apply_recipe_adjustment(
        pet["id"], adjustment["id"],
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def dismiss_recipe_adjustment(customer: Dict[str, Any],
                              pet: Dict[str, Any],
                              adjustment: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.dismiss_recipe_adjustment(
        pet["id"], adjustment["id"],
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def escalate_recipe_adjustment(customer: Dict[str, Any],
                               pet: Dict[str, Any],
                               adjustment: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.escalate_recipe_adjustment(
        pet["id"], adjustment["id"],
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


# ===========================================================================
# Tier 5: Cancellation / pause helpers
# ===========================================================================
def cancel_force(customer: Dict[str, Any], sub: Dict[str, Any],
                 cancel_reason: str = "OTHER") -> Dict[str, Any]:
    """PRD §3.2 force cancellation: bypass the PRICE retention
    deflection by passing force=true."""
    res = api_client.cancel_subscription(
        sub["id"],
        cancel_subscription_payload(cancel_reason, force=True),
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def pause_subscription(customer: Dict[str, Any], sub: Dict[str, Any],
                       pause_until_iso: str) -> Dict[str, Any]:
    res = api_client.pause_subscription(
        sub["id"],
        pause_subscription_payload(pause_until_iso),
        make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def resume_subscription(customer: Dict[str, Any],
                        sub: Dict[str, Any]) -> Dict[str, Any]:
    res = api_client.resume_subscription(
        sub["id"], make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


# ===========================================================================
# Tier 6: Refresh helpers
# ===========================================================================
def reload_subscription(customer: Dict[str, Any],
                        sub_id: str) -> Dict[str, Any]:
    res = api_client.get_subscription(
        sub_id, make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def reload_order(customer: Dict[str, Any],
                 order_id: str) -> Dict[str, Any]:
    res = api_client.get_order(
        order_id, make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def reload_pet(customer: Dict[str, Any],
               pet_id: str) -> Dict[str, Any]:
    res = api_client.get_pet(
        customer["id"], pet_id, make_customer_headers(customer["id"]),
    )
    return get_success_data(res)


def reload_customer(customer_id: str) -> Dict[str, Any]:
    res = api_client.get_customer(
        customer_id, make_customer_headers(customer_id),
    )
    return get_success_data(res)


__all__ = [
    # time
    "advance_clock_by_hours",
    "advance_clock_to",
    # creates
    "create_customer",
    "verify_customer_address",
    "create_pet",
    "create_recipe",
    "create_warehouse",
    "create_inventory_lot",
    # compound setups
    "setup_verified_customer",
    "setup_customer_with_pet",
    "setup_basic_recipe",
    "setup_warehouse_with_inventory",
    "create_draft_subscription",
    "verify_subscription_address",
    "activate_subscription",
    "setup_active_subscription",
    "setup_active_subscription_with_two_recipes",
    "emit_next_order",
    "setup_subscription_with_order",
    "setup_delivered_order",
    "setup_two_recipes_grain_free_dog_adult",
    # order lifecycle
    "confirm_order",
    "capture_payment",
    "dispatch_shipment",
    "deliver_order",
    "refund_order",
    "drive_order_to_delivered",
    # adjustment helpers
    "submit_feedback",
    "list_recipe_adjustments",
    "get_recipe_recommendations",
    "trigger_decrease_portion_adjustment",
    "apply_recipe_adjustment",
    "dismiss_recipe_adjustment",
    "escalate_recipe_adjustment",
    # subscription state shortcuts
    "cancel_force",
    "pause_subscription",
    "resume_subscription",
    # reload
    "reload_subscription",
    "reload_order",
    "reload_pet",
    "reload_customer",
]
