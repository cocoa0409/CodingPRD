"""Registry lifecycle: creation, activation, completion aggregation, the 0.80
completion boundary, the cyclic unlock/revert, and the gift completion cascade.

Difficulty (queue A) and corner (queue B) instances both appear here.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    make_customer_headers,
    new_store,
    new_customer,
    new_sku,
    new_registry,
    activate_registry,
    add_item,
    read_registry_version,
    gift,
    setup_active_registry_with_item,
)


def test_registry_created_is_draft_initial_state(api):
    """PRD §3.2: "A `Customer` opens a registry, which begins life in `DRAFT`."
    PRD §3.2: "when `desired_value_cents` is zero, `completion_pct` is defined
    to be zero."

    Design: Corner/state_machines/registry_created_is_draft_initial_state
    """
    customer = new_customer(api)
    resp = api.create_registry(
        {"registrant_customer_id": customer["id"], "title": "Baby R",
         "event_date": "2026-09-01T00:00:00Z"},
        make_customer_headers(customer["id"]),
    )
    data = validate_success(resp, 201)
    assert data["status"] == "DRAFT"
    assert data["completion_pct"] == pytest.approx(0, abs=1e-4)


def test_activate_already_active_registry_returns_invalid_state(api):
    """PRD §3.2: "Only the registrant may activate, and the registry must
    currently be in `DRAFT`; an activation attempt on any non-`DRAFT` registry
    is rejected with `ERR_INVALID_REGISTRY_STATE`."

    Design: Corner/state_machines/activate_already_active_registry_returns_invalid_state
    """
    customer = new_customer(api)
    registry = new_registry(api, customer["id"])
    activate_registry(api, registry["id"], customer["id"])
    resp = api.activate_registry(registry["id"], make_customer_headers(customer["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_REGISTRY_STATE.value)


def test_registry_desired_value_aggregates_items(api):
    """PRD §3.2: "The `desired_value_cents` is the sum, across the registry's
    items, of each item's `desired_qty` multiplied by its SKU's
    `base_price_cents`."
    PRD §3.2: "when `desired_value_cents` is zero, `completion_pct` is defined
    to be zero." — with items, fulfilled_value starts at zero.

    Design: Corner/calculations/registry_desired_value_aggregates_items
    """
    store = new_store(api)
    customer = new_customer(api)
    sku = new_sku(api, store["id"], base_price_cents=10000, initial_on_hand_qty=100)
    registry = new_registry(api, customer["id"])
    activate_registry(api, registry["id"], customer["id"])
    add_item(api, registry["id"], customer["id"], sku["id"], 5)
    reg = get_success_data(api.get_registry(registry["id"], make_customer_headers(customer["id"])))
    assert reg["desired_value_cents"] == 50000
    assert reg["fulfilled_value_cents"] == 0
    assert reg["completion_pct"] == pytest.approx(0, abs=1e-4)


def test_completion_pct_exactly_080_unlocks_inclusive(api):
    """PRD §3.2: "a `BABY_REGISTRY` is considered unlocked once its
    `completion_pct` reaches at least 0.80 (the boundary is inclusive — exactly
    0.80 unlocks)."
    PRD §3.2: "When a recompute finds an `ACTIVE` `BABY_REGISTRY` at or above
    0.80, the registry transitions `ACTIVE → COMPLETION_UNLOCKED`; as that
    transition fires, the registrant's `loyalty_points` are increased by a
    one-time bonus of 250 points, the registrant's loyalty tier is re-evaluated
    against the new points-bearing lifetime spend, and the registry's
    `updated_at` is refreshed."

    Design: Difficulty/boundary_precision_check/completion_pct_exactly_080_unlocks_inclusive
    """
    ctx = setup_active_registry_with_item(api, base_price_cents=10000, desired_qty=5)
    cust = ctx["customer"]["id"]
    gift(api, ctx["registry"]["id"], cust, ctx["item"]["id"], 4, ctx["version"])
    reg = get_success_data(api.get_registry(ctx["registry"]["id"], make_customer_headers(cust)))
    assert reg["completion_pct"] == pytest.approx(0.8, abs=1e-4)
    assert reg["status"] == "COMPLETION_UNLOCKED"


def test_completion_pct_below_080_stays_active(api):
    """PRD §3.2: "a `BABY_REGISTRY` is considered unlocked once its
    `completion_pct` reaches at least 0.80 (the boundary is inclusive — exactly
    0.80 unlocks)." — below the threshold the registry does not unlock.

    Design: Difficulty/boundary_precision_check/completion_pct_exactly_080_unlocks_inclusive
    """
    ctx = setup_active_registry_with_item(api, base_price_cents=10000, desired_qty=5)
    cust = ctx["customer"]["id"]
    gift(api, ctx["registry"]["id"], cust, ctx["item"]["id"], 3, ctx["version"])
    reg = get_success_data(api.get_registry(ctx["registry"]["id"], make_customer_headers(cust)))
    assert reg["completion_pct"] == pytest.approx(0.6, abs=1e-4)
    assert reg["status"] == "ACTIVE"


def test_registry_cycles_unlocked_back_to_active_on_item_add(api):
    """PRD §3.2: "Conversely, if a later item addition dilutes the registry so
    that `completion_pct` falls below 0.80, the registry reverts
    `COMPLETION_UNLOCKED → ACTIVE` and its `updated_at` is refreshed — but the
    250-point bonus already granted is **not** clawed back."

    Design: Difficulty/non_linear_state_machine/registry_cycles_unlocked_back_to_active_on_item_add
    """
    store = new_store(api)
    customer = new_customer(api)
    sku_a = new_sku(api, store["id"], base_price_cents=10000, initial_on_hand_qty=100)
    sku_b = new_sku(api, store["id"], base_price_cents=10000, initial_on_hand_qty=100)
    cust = customer["id"]
    registry = new_registry(api, cust)
    activate_registry(api, registry["id"], cust)
    item_a = add_item(api, registry["id"], cust, sku_a["id"], 5)
    rv1 = read_registry_version(api, registry["id"], cust)
    gift(api, registry["id"], cust, item_a["id"], 4, rv1)  # -> completion 0.80, UNLOCKED
    add_item(api, registry["id"], cust, sku_b["id"], 3)  # desired 80000, fulfilled 40000 -> 0.5
    reg = get_success_data(api.get_registry(registry["id"], make_customer_headers(cust)))
    assert reg["desired_value_cents"] == 80000
    assert reg["fulfilled_value_cents"] == 40000
    assert reg["completion_pct"] == pytest.approx(0.5, abs=1e-4)
    assert reg["status"] == "ACTIVE"


def test_registry_revert_does_not_claw_back_bonus(api):
    """PRD §3.2: "the registry reverts `COMPLETION_UNLOCKED → ACTIVE` and its
    `updated_at` is refreshed — but the 250-point bonus already granted is
    **not** clawed back."

    Design: Difficulty/non_linear_state_machine/registry_cycles_unlocked_back_to_active_on_item_add
    """
    store = new_store(api)
    customer = new_customer(api)
    sku_a = new_sku(api, store["id"], base_price_cents=10000, initial_on_hand_qty=100)
    sku_b = new_sku(api, store["id"], base_price_cents=10000, initial_on_hand_qty=100)
    cust = customer["id"]
    registry = new_registry(api, cust)
    activate_registry(api, registry["id"], cust)
    item_a = add_item(api, registry["id"], cust, sku_a["id"], 5)
    rv1 = read_registry_version(api, registry["id"], cust)
    gift(api, registry["id"], cust, item_a["id"], 4, rv1)  # unlock -> +250 bonus
    add_item(api, registry["id"], cust, sku_b["id"], 3)  # revert to ACTIVE
    cust_data = get_success_data(api.get_customer(cust, make_customer_headers(cust)))
    assert cust_data["loyalty_points"] == 250


def test_gift_cascade_registryitem_registry_customer_bonus(api):
    """PRD §3.2: "the target item's `fulfilled_qty` rises by the gifted `qty`
    (first hop), the registry's `fulfilled_value_cents` and `completion_pct` are
    recomputed (second hop), and if that recompute carries `completion_pct` to
    at least 0.80 the registry unlocks with the 250-point bonus and tier
    re-evaluation described above (third hop)."

    Design: Difficulty/transitive_cascade/gift_cascade_registryitem_registry_customer_bonus
    """
    ctx = setup_active_registry_with_item(api, base_price_cents=10000, desired_qty=5)
    cust = ctx["customer"]["id"]
    gift(api, ctx["registry"]["id"], cust, ctx["item"]["id"], 4, ctx["version"])
    item = get_success_data(api.get_registry_item(ctx["item"]["id"], make_customer_headers(cust)))
    reg = get_success_data(api.get_registry(ctx["registry"]["id"], make_customer_headers(cust)))
    cust_data = get_success_data(api.get_customer(cust, make_customer_headers(cust)))
    assert item["fulfilled_qty"] == 4
    assert reg["completion_pct"] == pytest.approx(0.8, abs=1e-4)
    assert reg["status"] == "COMPLETION_UNLOCKED"
    assert cust_data["loyalty_points"] == 250


def test_gift_cascade_records_amount_and_fulfilled_value(api):
    """PRD §3.2: "When the purchase succeeds, the server records the acting
    customer as `gifter_customer_id` (taken from `X-User-ID`), sets the gift's
    `amount_cents` to the gifted `qty` multiplied by the SKU's `base_price_cents`,
    and then cascades: the target item's `fulfilled_qty` rises by the gifted
    `qty` (first hop), the registry's `fulfilled_value_cents` and `completion_pct`
    are recomputed (second hop), and if that recompute carries `completion_pct`
    to at least 0.80 the registry unlocks with the 250-point bonus and tier
    re-evaluation described above (third hop)."
    PRD §3.2: "The `fulfilled_value_cents` is the sum, across those same items,
    of the lesser of the item's `fulfilled_qty` and its `desired_qty` multiplied
    by the SKU's `base_price_cents` — an over-gifted item is never credited
    beyond what was desired."

    Design: Difficulty/transitive_cascade/gift_cascade_registryitem_registry_customer_bonus
    """
    ctx = setup_active_registry_with_item(api, base_price_cents=10000, desired_qty=5)
    cust = ctx["customer"]["id"]
    g = gift(api, ctx["registry"]["id"], cust, ctx["item"]["id"], 4, ctx["version"])
    reg = get_success_data(api.get_registry(ctx["registry"]["id"], make_customer_headers(cust)))
    assert g["amount_cents"] == 40000
    assert reg["fulfilled_value_cents"] == 40000
