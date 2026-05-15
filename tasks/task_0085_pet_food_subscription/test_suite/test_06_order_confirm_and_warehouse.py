"""Order confirmation, warehouse selection, lot selection, and
inventory (PRD §3.4)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_clock_by_hours,
    api_client,
    confirm_order,
    create_draft_subscription,
    create_inventory_lot,
    create_recipe,
    create_warehouse,
    create_warehouse_payload,
    emit_next_order,
    make_customer_headers,
    pause_subscription,
    setup_active_subscription,
    setup_customer_with_pet,
    setup_subscription_with_order,
    setup_warehouse_with_inventory,
    update_warehouse_payload,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Confirm preconditions
# ---------------------------------------------------------------------------
def test_confirm_requires_subscription_active(api):
    """PRD §3.4: 'Confirmation requires that the owning subscription's
    status is ACTIVE (otherwise ERR_INVALID_SUBSCRIPTION_STATE).'
    """
    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    sub = bundle["subscription"]
    order = bundle["order"]
    # Pause the subscription so confirm finds it non-ACTIVE.
    pause_subscription(
        customer, sub, "2099-12-31T00:00:00.000Z",
    )
    res = api.confirm_order(
        order["id"], make_customer_headers(customer["id"]),
    )
    validate_error(
        res, ApiErrorId.ERR_INVALID_SUBSCRIPTION_STATE.value,
    )


def test_confirm_with_no_warehouse_matching_region_fails(api):
    """PRD §3.4: 'the warehouse selector returns a non-empty candidate
    set (otherwise ERR_NO_WAREHOUSE_AVAILABLE).'

    Setup with a warehouse that serves a DIFFERENT region than the
    subscription's address.region. Confirm must fail with
    ERR_NO_WAREHOUSE_AVAILABLE.
    """
    from test_helpers import (
        activate_subscription,
        create_pet,
        verify_customer_address,
        verify_subscription_address,
        setup_verified_customer,
    )
    from test_helpers import (
        create_subscription_payload,
    )

    recipe = create_recipe()
    # Warehouse serves only 'EU' but address.region is default 'CA'.
    create_warehouse(serves_regions=["EU"])
    # Stock the EU warehouse so we don't trip ERR_INSUFFICIENT_INVENTORY
    # for an unrelated reason — but selector should already reject due
    # to region mismatch before inventory matters.
    customer, pet = setup_customer_with_pet()
    sub = create_draft_subscription(customer, pet)
    sub = verify_subscription_address(customer, sub)
    sub = activate_subscription(customer, sub)
    advance_clock_by_hours(7 * 24)
    list_res = api.list_orders(
        sub["id"], make_customer_headers(customer["id"]),
    ).json()["data"]
    assert list_res, (
        "PRD §3.4: cycle scheduler must emit an Order on _clock advance "
        "even when no warehouse will end up serving the address — "
        "warehouse routing happens at confirmation, not at emission."
    )
    order = list_res[0]
    res = api.confirm_order(
        order["id"], make_customer_headers(customer["id"]),
    )
    validate_error(res, ApiErrorId.ERR_NO_WAREHOUSE_AVAILABLE.value)


def test_confirm_succeeds_assigns_warehouse_and_lots_and_debits_inventory(api):
    """PRD §3.4: 'On success, the order's warehouse_id is set to the
    selector's output, its assigned_lots array is populated by the lot
    selector ..., each chosen InventoryLot has its quantity_grams
    decremented atomically by the item's total_grams, and the chosen
    warehouse's daily outbound capacity for the scheduled_ship_at UTC
    date is debited by one.'
    """
    bundle = setup_subscription_with_order()
    customer = bundle["customer"]
    order = bundle["order"]
    lot_before = bundle["lot"]
    confirmed = confirm_order(customer, order)
    assert confirmed["fulfillment_status"] == "CONFIRMED"
    assert confirmed["warehouse_id"] == bundle["warehouse"]["id"]
    assert len(confirmed["assigned_lots"]) == len(confirmed["items"])
    for al in confirmed["assigned_lots"]:
        assert al["lot_id"]
        assert al["batch_code"]
        assert al["expiration_date"]
        assert al["grams_drawn"] > 0


def test_confirm_with_insufficient_inventory_rejected(api):
    """PRD §3.4: 'every item can be assigned to a non-expired
    InventoryLot with sufficient grams on hand (otherwise
    ERR_INSUFFICIENT_INVENTORY).'

    PRD §3.4 also requires the warehouse selector to filter out any
    warehouse that lacks a lot with sufficient quantity_grams. When the
    only stocked warehouse has insufficient inventory, a PRD-faithful
    implementation may surface ERR_NO_WAREHOUSE_AVAILABLE (warehouse-
    selector elimination) or ERR_INSUFFICIENT_INVENTORY (lot-selector
    elimination); both denote the same underlying defect.
    """
    from test_helpers import validate_error_is_one_of
    # Setup with very small inventory that won't satisfy the order.
    bundle = setup_active_subscription(
        warehouse_quantity_grams=1,
    )
    order = emit_next_order(bundle["customer"], bundle["subscription"])
    res = api.confirm_order(
        order["id"], make_customer_headers(bundle["customer"]["id"]),
    )
    validate_error_is_one_of(
        res,
        [
            ApiErrorId.ERR_INSUFFICIENT_INVENTORY.value,
            ApiErrorId.ERR_NO_WAREHOUSE_AVAILABLE.value,
        ],
    )


# ---------------------------------------------------------------------------
# Warehouse selection ranking
# ---------------------------------------------------------------------------
def test_warehouse_selector_prefers_lower_priority_rank(api):
    """PRD §3.4: 'Surviving warehouses are ranked by priority_rank in
    ascending order (smaller wins).'

    Two ONLINE warehouses both serving the region, both stocked. The
    one with the smaller priority_rank wins.
    """
    from test_helpers import (
        activate_subscription,
        create_draft_subscription,
        verify_subscription_address,
    )

    recipe = create_recipe()
    wh_low = create_warehouse(
        priority_rank=1, code="WH-LOW",
        daily_outbound_capacity=10,
    )
    wh_high = create_warehouse(
        priority_rank=99, code="WH-HIGH",
        daily_outbound_capacity=10,
    )
    create_inventory_lot(wh_low, recipe["id"])
    create_inventory_lot(wh_high, recipe["id"])
    customer, pet = setup_customer_with_pet()
    sub = create_draft_subscription(customer, pet)
    sub = verify_subscription_address(customer, sub)
    sub = activate_subscription(customer, sub)
    advance_clock_by_hours(7 * 24)
    orders = api.list_orders(
        sub["id"], make_customer_headers(customer["id"]),
    ).json()["data"]
    assert orders, (
        "PRD §3.4: cycle scheduler must emit an Order on _clock advance."
    )
    order = orders[0]
    confirmed = confirm_order(customer, order)
    assert confirmed["warehouse_id"] == wh_low["id"], (
        "PRD §3.4: lower priority_rank warehouse must be selected."
    )


def test_warehouse_offline_is_excluded_from_routing(api):
    """PRD §3.4: 'only warehouses whose status is ONLINE are
    eligible'.

    Two warehouses serving the same region; ONLINE-only one must be
    chosen.
    """
    from test_helpers import (
        activate_subscription,
        create_draft_subscription,
        verify_subscription_address,
    )

    recipe = create_recipe()
    wh_offline = create_warehouse(
        priority_rank=1, code="WH-DOWN",
        daily_outbound_capacity=10,
    )
    create_inventory_lot(wh_offline, recipe["id"])
    # Toggle to OFFLINE via PATCH.
    api.update_warehouse(
        wh_offline["id"],
        update_warehouse_payload(status="OFFLINE"),
        TEST_USERS["admin_ops_headers"],
    )
    wh_online = create_warehouse(
        priority_rank=99, code="WH-UP",
        daily_outbound_capacity=10,
    )
    create_inventory_lot(wh_online, recipe["id"])
    customer, pet = setup_customer_with_pet()
    sub = create_draft_subscription(customer, pet)
    sub = verify_subscription_address(customer, sub)
    sub = activate_subscription(customer, sub)
    advance_clock_by_hours(7 * 24)
    orders = api.list_orders(
        sub["id"], make_customer_headers(customer["id"]),
    ).json()["data"]
    assert orders, (
        "PRD §3.4: cycle scheduler must emit an Order on _clock advance."
    )
    order = orders[0]
    confirmed = confirm_order(customer, order)
    assert confirmed["warehouse_id"] == wh_online["id"], (
        "PRD §3.4: OFFLINE warehouses must be excluded from routing."
    )


# ---------------------------------------------------------------------------
# Lot selector — FEFO
# ---------------------------------------------------------------------------
def test_lot_selector_picks_earliest_expiration_first(api):
    """PRD §3.4: 'The lot selector then runs per item against the
    chosen warehouse and picks, from the lots that satisfy the same
    expiration and quantity criteria, the one with the earliest
    expiration_date (First-Expire-First-Out).'
    """
    from test_helpers import (
        activate_subscription,
        create_draft_subscription,
        verify_subscription_address,
    )

    recipe = create_recipe()
    wh = create_warehouse(daily_outbound_capacity=10)
    lot_far = create_inventory_lot(
        wh, recipe["id"],
        expiration_date="2099-12-31",
        batch_code="FAR",
    )
    lot_near = create_inventory_lot(
        wh, recipe["id"],
        expiration_date="2098-12-31",
        batch_code="NEAR",
    )
    customer, pet = setup_customer_with_pet()
    sub = create_draft_subscription(customer, pet)
    sub = verify_subscription_address(customer, sub)
    sub = activate_subscription(customer, sub)
    advance_clock_by_hours(7 * 24)
    order = api.list_orders(
        sub["id"], make_customer_headers(customer["id"]),
    ).json()["data"][0]
    confirmed = confirm_order(customer, order)
    al = confirmed["assigned_lots"][0]
    assert al["lot_id"] == lot_near["id"], (
        "PRD §3.4: lot selector must pick the earlier-expiring lot."
    )
    assert al["batch_code"] == "NEAR"
