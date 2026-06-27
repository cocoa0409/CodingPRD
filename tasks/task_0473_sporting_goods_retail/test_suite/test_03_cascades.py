"""Depth-3 cascades: order fulfillment (commit -> loyalty -> tier) and team-order
approval (spawn -> reserve).

Difficulty queue: transitive_cascade.
"""
import pytest
from test_helpers import (
    api_client,
    get_success_data,
    create_store,
    create_sku,
    create_customer,
    stock_sku,
    setup_ready_order,
    fulfill_order,
    setup_submitted_team_order,
    approve_team_order,
    get_order,
    get_customer,
    get_inventory,
)


# ===========================================================================
# transitive_cascade / fulfill_commit_then_loyalty_then_tier_depth3
# ===========================================================================
def test_fulfill_commits_inventory_and_accrues_loyalty_and_tier(api):
    """PRD §3.3: "On fulfillment the server, for each line, lowers that line's stock
    row `on_hand_qty` and `reserved_qty` by the line's `quantity`, recomputes
    `available_qty`".
    PRD §3.5: "the customer's `loyalty_points` increases by the whole number of
    dollars in the order's final merchandise subtotal".
    PRD §3.5: "otherwise at least 500 points is `SILVER`".

    Fulfilling a single 50000 line drives a depth-3 cascade: on_hand 5->4 and
    reserved ->0; loyalty_points ->500; tier BRONZE->SILVER (recomputed from the
    new points).

    Design: Difficulty/transitive_cascade/fulfill_commit_then_loyalty_then_tier_depth3
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="APPAREL", name="Premium Coat", base_price_cents=50000, size_label="L")
    customer = create_customer(home_state_code="CA")
    inv = stock_sku(store["id"], sku["id"], 5)

    ready, _ = setup_ready_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    fulfill_order(ready["id"])

    inv_after = get_inventory(inv["id"])
    assert inv_after["on_hand_qty"] == 4
    assert inv_after["reserved_qty"] == 0

    cust_after = get_customer(customer["id"])
    assert cust_after["loyalty_points"] == 500
    assert cust_after["loyalty_tier"] == "SILVER"


def test_fulfill_records_loyalty_points_awarded_on_order(api):
    """PRD §3.5: "The amount accrued on that order is also recorded on the order as
    `loyalty_points_awarded`."

    The 500 points accrued from the 50000 final subtotal are also surfaced on the
    fulfilled order's loyalty_points_awarded field.

    Design: Difficulty/transitive_cascade/fulfill_commit_then_loyalty_then_tier_depth3
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="APPAREL", name="Premium Coat", base_price_cents=50000, size_label="L")
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 5)

    ready, _ = setup_ready_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 1}]
    )
    fulfilled = fulfill_order(ready["id"])
    assert fulfilled["final_total_cents"] == 50000
    assert fulfilled["loyalty_points_awarded"] == 500


# ===========================================================================
# transitive_cascade / team_approve_spawn_order_reserve_depth3
# ===========================================================================
def test_team_approve_spawns_reserved_order_and_reserves_inventory(api):
    """PRD §3.10: "Approval spawns a child order: a new order with
    `fulfillment_type` of `BOPIS` is created with one order line per team line (each
    spawned line's `embroidery_text` defaulting to the team order's `team_name` when
    the team line left it null), and each spawned line's stock row is reserved by
    raising `reserved_qty` by the line's `quantity` and recomputing `available_qty`."
    PRD §3.10: "the spawned order is set to `fulfillment_status` `RESERVED` and
    `payment_status` `AUTHORIZED`, the team order's `spawned_order_id` is set to the
    new order's `id`, and the team order's `version` increments by one."

    Approving a 20-unit team order spawns a RESERVED order and pushes the stock
    row to reserved_qty 20 / available_qty 10 (30 on_hand - 20 reserved).

    Design: Difficulty/transitive_cascade/team_approve_spawn_order_reserve_depth3
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="TEAMWEAR", name="Jersey", base_price_cents=3000,
                     size_label="L", embroiderable=True)
    customer = create_customer(home_state_code="CA")
    inv = stock_sku(store["id"], sku["id"], 30)

    submitted, _ = setup_submitted_team_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 20}],
        team_name="Eagles",
    )
    approved = approve_team_order(submitted["id"])
    assert approved["spawned_order_id"] is not None

    spawned = get_order(approved["spawned_order_id"])
    assert spawned["fulfillment_status"] == "RESERVED"

    inv_after = get_inventory(inv["id"])
    assert inv_after["reserved_qty"] == 20
    assert inv_after["available_qty"] == 10


def test_team_approve_spawned_order_payment_authorized(api):
    """PRD §3.10: "the spawned order is set to `fulfillment_status` `RESERVED` and
    `payment_status` `AUTHORIZED`".

    The spawned child order's payment axis is AUTHORIZED, the second arm of the
    spawn cascade.

    Design: Difficulty/transitive_cascade/team_approve_spawn_order_reserve_depth3
    """
    store = create_store(state_code="CA")
    sku = create_sku(sport="TEAMWEAR", name="Jersey", base_price_cents=3000,
                     size_label="L", embroiderable=True)
    customer = create_customer(home_state_code="CA")
    stock_sku(store["id"], sku["id"], 30)

    submitted, _ = setup_submitted_team_order(
        customer["id"], store["id"], [{"sku_id": sku["id"], "quantity": 20}],
        team_name="Eagles",
    )
    approved = approve_team_order(submitted["id"])
    spawned = get_order(approved["spawned_order_id"])
    assert spawned["payment_status"] == "AUTHORIZED"
