"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints (the server is restarted before every test, so the DB always starts
empty). Fixtures use get_success_data() so a setup failure surfaces as a clear
"Setup failed" rather than a confusing assertion error downstream.

Identity threading: the Customer role is entity_backed, so any ownership-gated
call uses make_customer_headers(customer["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories as F

INVMGR = TEST_USERS["inventory_manager_headers"]
KEEPER = TEST_USERS["livestock_keeper_headers"]
VET = TEST_USERS["clinic_vet_headers"]
CLERK = TEST_USERS["store_clerk_headers"]

DEFAULT_CLOCK = "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Clock control
# ---------------------------------------------------------------------------
def set_clock(to_iso8601, headers=KEEPER):
    """Set the logical server clock (§2.11)."""
    return get_success_data(api_client.set_clock(to_iso8601, headers))


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def make_store(state_code="CA", loyalty_point_value_cents=None, name="Test Store"):
    payload = F.create_store_payload(name=name, state_code=state_code)
    if loyalty_point_value_cents is not None:
        payload["loyalty_point_value_cents"] = loyalty_point_value_cents
    return get_success_data(api_client.create_store(payload, INVMGR))


def make_product(unit_price_cents=1000, category="FOOD", is_prescription_diet=None,
                 loyalty_points_per_unit=None, sku=None, name="Test Product"):
    payload = F.create_product_payload(
        unit_price_cents=unit_price_cents, category=category, name=name
    )
    if sku is not None:
        payload["sku"] = sku
    if is_prescription_diet is not None:
        payload["is_prescription_diet"] = is_prescription_diet
    if loyalty_points_per_unit is not None:
        payload["loyalty_points_per_unit"] = loyalty_points_per_unit
    return get_success_data(api_client.create_product(payload, INVMGR))


def make_customer(home_store_id, email=None, full_name="Test Customer"):
    payload = F.create_customer_payload(home_store_id, full_name=full_name)
    if email is not None:
        payload["email"] = email
    return get_success_data(api_client.create_customer(payload, CLERK))


def make_lot(store_id, product_id, quantity_on_hand=50, lot_code="L1",
             received_at="2026-01-02T00:00:00Z",
             expiry_date="2026-12-01T00:00:00Z"):
    payload = F.create_inventory_lot_payload(
        store_id, product_id, lot_code=lot_code,
        quantity_on_hand=quantity_on_hand,
        received_at=received_at, expiry_date=expiry_date,
    )
    return get_success_data(api_client.create_inventory_lot(payload, INVMGR))


def make_batch(store_id, head_count=10, unit_price_cents=500, species="betta",
               animal_class="FISH", intake_at="2026-01-01T00:00:00Z",
               quarantine_days=5):
    payload = F.create_livestock_batch_payload(
        store_id, head_count=head_count, unit_price_cents=unit_price_cents,
        species=species, animal_class=animal_class,
        intake_at=intake_at, quarantine_days=quarantine_days,
    )
    return get_success_data(api_client.create_livestock_batch(payload, KEEPER))


# ---------------------------------------------------------------------------
# Tier 1 / 3: Livestock state progression
# ---------------------------------------------------------------------------
def make_healthy_on_floor_batch(store_id, head_count=10, unit_price_cents=500,
                                species="betta", animal_class="FISH",
                                clock="2026-01-10T00:00:00Z"):
    """Intake → advance clock past quarantine → clear-quarantine (HEALTHY) →
    list-on-floor (ON_FLOOR). Returns the batch dict in HEALTHY/ON_FLOOR."""
    batch = make_batch(
        store_id, head_count=head_count, unit_price_cents=unit_price_cents,
        species=species, animal_class=animal_class,
    )
    if clock is not None:
        set_clock(clock)
    api_client.clear_quarantine(batch["id"], KEEPER)
    res = api_client.list_on_floor(batch["id"], KEEPER)
    return get_success_data(res)


def raise_customer_to_tier(store_id, customer_id, target_tier,
                           clock="2026-01-10T00:00:00Z"):
    """Push a customer's lifetime spend to reach target_tier (SILVER or GOLD)
    by selling one or more full healthy on-floor batches (BRONZE 0% discount,
    so net == head * unit_price). Returns the refreshed customer dict.

    SILVER needs >= 5,000,000 cents; GOLD needs >= 20,000,000 cents.
    """
    if target_tier == "SILVER":
        # One sale of head=100 @ 50500 = 5,050,000 net (BRONZE 0%).
        batch = make_healthy_on_floor_batch(
            store_id, head_count=100, unit_price_cents=50500,
            species="koi", clock=clock,
        )
        api_client.create_livestock_sale(
            F.create_livestock_sale_payload(batch["id"], customer_id), CLERK
        )
    elif target_tier == "GOLD":
        # Two big sales of head=200 @ 100000 = 20,000,000 each → well past GOLD.
        batch = make_healthy_on_floor_batch(
            store_id, head_count=200, unit_price_cents=100000,
            species="arowana", clock=clock,
        )
        api_client.create_livestock_sale(
            F.create_livestock_sale_payload(batch["id"], customer_id), CLERK
        )
    else:
        raise ValueError(f"Unsupported target_tier {target_tier!r}")
    return get_success_data(api_client.get_customer(customer_id, CLERK))


# ---------------------------------------------------------------------------
# Tier 4: Subscriptions due now with stocked inventory
# ---------------------------------------------------------------------------
def setup_subscription_due(store_id, product_id, customer_id, quantity_per_cycle=1,
                           cycle_days=30, discount_pct=None,
                           next_ship_at="2026-01-10T00:00:00Z",
                           created_by=CLERK, customer_for_owner=None):
    """Create an ACTIVE subscription. Returns the subscription dict.

    created_by defaults to StoreClerk; pass customer_for_owner=customer_id to
    create it as the owning Customer (entity_backed identity threading)."""
    payload = F.create_subscription_payload(
        customer_id, product_id, store_id,
        quantity_per_cycle=quantity_per_cycle, cycle_days=cycle_days,
        next_ship_at=next_ship_at,
    )
    if discount_pct is not None:
        payload["discount_pct"] = discount_pct
    headers = created_by
    if customer_for_owner is not None:
        headers = make_customer_headers(customer_for_owner)
    return get_success_data(api_client.create_subscription(payload, headers))


def setup_stocked_subscription(quantity_per_cycle=1, lot_qty=50, unit_price_cents=1000,
                               discount_pct=None,
                               next_ship_at="2026-01-10T00:00:00Z",
                               run_clock="2026-02-02T00:00:00Z"):
    """Store + Product (CLEAR) + stocked AVAILABLE lot + Customer + ACTIVE
    subscription due now, clock advanced past next_ship_at.

    Returns dict with keys: store, product, lot, customer, subscription.
    """
    store = make_store()
    product = make_product(unit_price_cents=unit_price_cents)
    lot = make_lot(store["id"], product["id"], quantity_on_hand=lot_qty)
    customer = make_customer(store["id"])
    if run_clock is not None:
        set_clock(run_clock)
    subscription = setup_subscription_due(
        store["id"], product["id"], customer["id"],
        quantity_per_cycle=quantity_per_cycle, discount_pct=discount_pct,
        next_ship_at=next_ship_at,
    )
    return {
        "store": store, "product": product, "lot": lot,
        "customer": customer, "subscription": subscription,
    }


# ---------------------------------------------------------------------------
# Tier 3: Special orders
# ---------------------------------------------------------------------------
def make_special_order(store_id, product_id, customer_id, quantity=3,
                       deposit_pct=None, created_by=CLERK):
    payload = F.create_special_order_payload(
        customer_id, product_id, store_id, quantity=quantity
    )
    if deposit_pct is not None:
        payload["deposit_pct"] = deposit_pct
    return get_success_data(api_client.create_special_order(payload, created_by))


def setup_allocated_special_order(quantity=3, lot_qty=50, unit_price_cents=1000,
                                  deposit_pct=None):
    """Store + Product + stocked lot + Customer + ALLOCATED special order.

    Returns dict: store, product, lot, customer, order.
    """
    store = make_store()
    product = make_product(unit_price_cents=unit_price_cents)
    lot = make_lot(store["id"], product["id"], quantity_on_hand=lot_qty)
    customer = make_customer(store["id"])
    order = make_special_order(
        store["id"], product["id"], customer["id"],
        quantity=quantity, deposit_pct=deposit_pct,
    )
    order = get_success_data(api_client.allocate_special_order(order["id"], INVMGR))
    return {
        "store": store, "product": product, "lot": lot,
        "customer": customer, "order": order,
    }


# ---------------------------------------------------------------------------
# Tier 3: Clinic appointments — completed VET_EXAM gateway
# ---------------------------------------------------------------------------
def make_completed_vet_exam(store_id, customer_id, fee_cents=8000,
                            start_at="2026-01-05T09:00:00Z",
                            end_at="2026-01-05T10:00:00Z",
                            check_in_clock="2026-01-05T09:30:00Z"):
    """Book a VET_EXAM → advance clock → check-in → complete. Returns the
    COMPLETED appointment dict."""
    appt = get_success_data(api_client.create_clinic_appointment(
        F.create_clinic_appointment_payload(
            store_id, customer_id, service_type="VET_EXAM",
            start_at=start_at, end_at=end_at, fee_cents=fee_cents,
        ), VET,
    ))
    if check_in_clock is not None:
        set_clock(check_in_clock)
    api_client.check_in_appointment(appt["id"], VET)
    return get_success_data(api_client.complete_appointment(appt["id"], VET))


# ---------------------------------------------------------------------------
# Tier 3: Adoption events + placements
# ---------------------------------------------------------------------------
def make_open_event(store_id, capacity=10):
    """Schedule + open an adoption event. Returns the OPEN event dict."""
    event = get_success_data(api_client.create_adoption_event(
        F.create_adoption_event_payload(store_id, capacity=capacity), CLERK
    ))
    return get_success_data(api_client.open_adoption_event(event["id"], CLERK))


def setup_event_with_placement(head_count=4, capacity=10, animal_class="SMALL_ANIMAL",
                               species="rabbit"):
    """Store + healthy ON_FLOOR batch + OPEN event + one full-head PLACED
    placement (batch now RESERVED).

    Returns dict: store, batch, event, placement.
    """
    store = make_store()
    batch = make_healthy_on_floor_batch(
        store["id"], head_count=head_count, unit_price_cents=3000,
        species=species, animal_class=animal_class,
    )
    event = make_open_event(store["id"], capacity=capacity)
    placement = get_success_data(api_client.create_adoption_placement(
        F.create_adoption_placement_payload(event["id"], batch["id"], head_count),
        KEEPER,
    ))
    return {"store": store, "batch": batch, "event": event, "placement": placement}


# ---------------------------------------------------------------------------
# Tier 2: Recall scenarios
# ---------------------------------------------------------------------------
def setup_recall_scenario(lot_qty=50, with_subscription=True,
                          sub_next_ship_at="2026-02-01T00:00:00Z"):
    """Store + Product + AVAILABLE lot (+ optional ACTIVE subscription). No
    recall issued yet. Returns dict: store, product, lot, customer, subscription.
    """
    store = make_store()
    product = make_product(unit_price_cents=1000)
    lot = make_lot(store["id"], product["id"], quantity_on_hand=lot_qty)
    customer = make_customer(store["id"])
    subscription = None
    if with_subscription:
        subscription = setup_subscription_due(
            store["id"], product["id"], customer["id"],
            quantity_per_cycle=1, next_ship_at=sub_next_ship_at,
            customer_for_owner=customer["id"],
        )
    return {
        "store": store, "product": product, "lot": lot,
        "customer": customer, "subscription": subscription,
    }


def issue_recall(product_id, severity="MANDATORY", lot_code=None,
                 scope_state_code=None):
    """Issue an OPEN recall. Returns the recall dict."""
    payload = F.create_recall_payload(product_id, severity=severity)
    if lot_code is not None:
        payload["lot_code"] = lot_code
    if scope_state_code is not None:
        payload["scope_state_code"] = scope_state_code
    return get_success_data(api_client.create_recall(payload, INVMGR))
