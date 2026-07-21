"""Capsule subscription programme: the cyclic ACTIVE<->PAUSED machine, per-item
capsule retail rounding, the ship-gated-on-active cross-entity rule, the
half-open possession-window overlap, and cancel/reship gates.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    make_shopper_headers,
    new_subscription,
    new_product,
    new_variant,
    new_customer,
    pack_capsule,
    ship_capsule,
    pause_subscription,
    cancel_subscription,
    setup_subscription,
    setup_packed_capsule,
)

AGENT = TEST_USERS["fulfillment_agent_headers"]


def _find_capsule(api, subscription_id, capsule_id):
    resp = api.list_capsules(subscription_id, AGENT, params={"limit": 100, "offset": 0})
    data, _ = validate_paginated(resp)
    for c in data:
        if c["id"] == capsule_id:
            return c
    raise AssertionError(f"capsule {capsule_id} not found under {subscription_id}")


# ---- non_linear_state_machine: subscription_cyclic_active_paused ----

def test_subscription_pause_resume_pause_ends_paused(api):
    """PRD §3.7: "A shopper may pause an `ACTIVE` subscription, moving it to
    `PAUSED` (allowed only from `ACTIVE`, otherwise `ERR_SUBSCRIPTION_NOT_ACTIVE`)."
    PRD §3.7: "She may resume a `PAUSED` subscription, moving it back to `ACTIVE`
    (allowed only from `PAUSED`, otherwise `ERR_SUBSCRIPTION_NOT_PAUSED`),
    re-enabling capsule shipping."

    Design: Difficulty/non_linear_state_machine/subscription_cyclic_active_paused
    """
    setup = setup_subscription(api)
    sub_id, cust_id = setup["subscription"]["id"], setup["customer"]["id"]
    hdr = make_shopper_headers(cust_id)
    validate_success(api.pause_subscription(sub_id, hdr), 200)
    validate_success(api.resume_subscription(sub_id, hdr), 200)
    paused = validate_success(api.pause_subscription(sub_id, hdr), 200)
    assert paused["status"] == "PAUSED"


def test_subscription_resume_returns_to_active(api):
    """PRD §3.7: "She may resume a `PAUSED` subscription, moving it back to
    `ACTIVE` (allowed only from `PAUSED`, otherwise `ERR_SUBSCRIPTION_NOT_PAUSED`),
    re-enabling capsule shipping."
    PRD §3.7: "A shopper may pause an `ACTIVE` subscription, moving it to
    `PAUSED`."

    Design: Difficulty/non_linear_state_machine/subscription_cyclic_active_paused
    """
    setup = setup_subscription(api)
    sub_id, cust_id = setup["subscription"]["id"], setup["customer"]["id"]
    hdr = make_shopper_headers(cust_id)
    validate_success(api.pause_subscription(sub_id, hdr), 200)
    resumed = validate_success(api.resume_subscription(sub_id, hdr), 200)
    assert resumed["status"] == "ACTIVE"


# ---- combinatorial_formula: capsule_retail_round_per_item_mode_b ----

def test_capsule_retail_value_rounds_per_item_then_sums(api):
    """PRD §3.7: "for each variant in `item_variant_ids`, take that variant's
    `buy_price_cents` times a keep percentage of 70 percent (0.70) and round half
    up, then sum those per-item rounded amounts. The rounding is per item before
    summing — the sum is not taken first and rounded once, because the two orders
    of operation can differ by up to one cent per item."

    Design: Difficulty/combinatorial_formula/capsule_retail_round_per_item_mode_b
    """
    cust = new_customer(api)
    sub = new_subscription(api, cust["id"], plan_tier="CAPSULE_BASIC", monthly_fee_cents=3000)
    product = new_product(api, category="CAPSULE", buy_price_cents=2005)
    v1 = new_variant(api, product["id"], size_label="S", trimester_fit=[1])
    v2 = new_variant(api, product["id"], size_label="M", trimester_fit=[2])
    v3 = new_variant(api, product["id"], size_label="L", trimester_fit=[3])
    capsule = pack_capsule(api, sub["id"], [v1["id"], v2["id"], v3["id"]])
    # round(2005*0.70=1403.5)=1404 per item; 3*1404 = 4212 (not round(6015*0.7)=4211).
    assert capsule["retail_value_cents"] == 4212
    assert capsule["status"] == "PACKED"


def test_capsule_retail_value_per_item_two_items(api):
    """PRD §3.7: "take that variant's `buy_price_cents` times a keep percentage of
    70 percent (0.70) and round half up, then sum those per-item rounded
    amounts."

    Design: Difficulty/combinatorial_formula/capsule_retail_round_per_item_mode_b
    """
    cust = new_customer(api)
    sub = new_subscription(api, cust["id"], plan_tier="CAPSULE_BASIC", monthly_fee_cents=3000)
    product = new_product(api, category="CAPSULE", buy_price_cents=1001)
    v1 = new_variant(api, product["id"], size_label="S", trimester_fit=[1])
    v2 = new_variant(api, product["id"], size_label="M", trimester_fit=[2])
    capsule = pack_capsule(api, sub["id"], [v1["id"], v2["id"]])
    # round(1001*0.70=700.7)=701 per item; 2*701 = 1402 (not round(2002*0.7)=1401).
    assert capsule["retail_value_cents"] == 1402


# ---- cross_entity_state_dependency: capsule_ship_requires_subscription_active ----

def test_capsule_ship_blocked_while_subscription_paused(api):
    """PRD §3.7: "only when the parent subscription is `ACTIVE` — a cross-entity
    check that rejects with `ERR_SUBSCRIPTION_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/capsule_ship_requires_subscription_active
    """
    base = setup_packed_capsule(api)
    pause_subscription(api, base["subscription"]["id"], base["customer"]["id"])
    resp = api.ship_capsule(base["capsule"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_ACTIVE.value)
    still = _find_capsule(api, base["subscription"]["id"], base["capsule"]["id"])
    assert still["status"] == "PACKED"


def test_capsule_ship_succeeds_while_subscription_active(api):
    """PRD §3.7: "Shipping a capsule is a fulfillment agent's action that moves it
    from `PACKED` to `SHIPPED`."
    PRD §3.7: "Shipping increments the subscription's `capsules_shipped` by one."

    Design: Difficulty/cross_entity_state_dependency/capsule_ship_requires_subscription_active
    """
    base = setup_packed_capsule(api)
    shipped = validate_success(api.ship_capsule(base["capsule"]["id"], AGENT), 200)
    assert shipped["status"] == "SHIPPED"


# ---- resource_temporal_overlap: capsule_possession_overlap_halfopen ----

def test_capsule_window_overlap_rejected(api):
    """PRD §3.7: "only when the capsule's possession window does not overlap the
    window of any other already-`SHIPPED` capsule of the same subscription; an
    overlap is rejected with `ERR_CAPSULE_WINDOW_OVERLAP`."
    PRD §3.7: "the possession window runs from `ship_date` up to but not including
    `possession_end`."

    Design: Difficulty/resource_temporal_overlap/capsule_possession_overlap_halfopen
    """
    setup = setup_subscription(api, plan_tier="CAPSULE_PLUS", monthly_fee_cents=4000)
    sub_id = setup["subscription"]["id"]
    product = new_product(api, category="CAPSULE", buy_price_cents=5000)
    v1 = new_variant(api, product["id"], size_label="M", trimester_fit=[2])
    cap1 = pack_capsule(api, sub_id, [v1["id"]], ship_date="2026-08-01T00:00:00Z")
    ship_capsule(api, cap1["id"])  # window [08-01, 08-31)
    cap2 = pack_capsule(api, sub_id, [v1["id"]], ship_date="2026-08-15T00:00:00Z")
    resp = api.ship_capsule(cap2["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_CAPSULE_WINDOW_OVERLAP.value)
    still = _find_capsule(api, sub_id, cap2["id"])
    assert still["status"] == "PACKED"


def test_capsule_window_abutting_at_possession_end_ships(api):
    """PRD §3.7: "The `possession_end` is the `ship_date` plus a capsule loan of
    30 days, and the possession window runs from `ship_date` up to but not
    including `possession_end`."
    PRD §3.7: "only when the capsule's possession window does not overlap the
    window of any other already-`SHIPPED` capsule of the same subscription."

    Design: Difficulty/resource_temporal_overlap/capsule_possession_overlap_halfopen
    """
    setup = setup_subscription(api, plan_tier="CAPSULE_PLUS", monthly_fee_cents=4000)
    sub_id = setup["subscription"]["id"]
    product = new_product(api, category="CAPSULE", buy_price_cents=5000)
    v1 = new_variant(api, product["id"], size_label="M", trimester_fit=[2])
    cap1 = pack_capsule(api, sub_id, [v1["id"]], ship_date="2026-08-01T00:00:00Z")
    ship_capsule(api, cap1["id"])  # window [08-01, 08-31)
    # cap2 starts exactly at cap1's possession_end (08-31); half-open windows abut.
    cap2 = pack_capsule(api, sub_id, [v1["id"]], ship_date="2026-08-31T00:00:00Z")
    shipped = validate_success(api.ship_capsule(cap2["id"], AGENT), 200)
    assert shipped["status"] == "SHIPPED"


# ---- Corner: resume_active_subscription_rejected ----

def test_resume_active_subscription_rejected(api):
    """PRD §3.7: "She may resume a `PAUSED` subscription, moving it back to
    `ACTIVE` (allowed only from `PAUSED`, otherwise `ERR_SUBSCRIPTION_NOT_PAUSED`)."

    Design: Corner/state_machines/resume_active_subscription_rejected
    """
    setup = setup_subscription(api)
    resp = api.resume_subscription(setup["subscription"]["id"],
                                   make_shopper_headers(setup["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SUBSCRIPTION_NOT_PAUSED.value)


# ---- Corner: ship_already_shipped_capsule_rejected ----

def test_ship_already_shipped_capsule_rejected(api):
    """PRD §3.7: "Shipping a capsule is a fulfillment agent's action that moves it
    from `PACKED` to `SHIPPED`. It is allowed only when the capsule is `PACKED`
    (otherwise `ERR_CAPSULE_NOT_PACKED`)."

    Design: Corner/state_machines/ship_already_shipped_capsule_rejected
    """
    base = setup_packed_capsule(api)
    ship_capsule(api, base["capsule"]["id"])
    resp = api.ship_capsule(base["capsule"]["id"], AGENT)
    validate_error(resp, ApiErrorId.ERR_CAPSULE_NOT_PACKED.value)


# ---- Corner: subscription_cancel_voids_packed_capsule ----

def test_subscription_cancel_voids_packed_capsule(api):
    """PRD §3.7: "Cancellation cascades: every `Capsule` of the subscription that
    is still `PACKED` is transitioned to `VOIDED`, removing it from the shipping
    queue."

    Design: Corner/state_machines/subscription_cancel_voids_packed_capsule
    """
    base = setup_packed_capsule(api)
    cancelled = cancel_subscription(api, base["subscription"]["id"], base["customer"]["id"])
    assert cancelled["status"] == "CANCELLED"
    capsule = _find_capsule(api, base["subscription"]["id"], base["capsule"]["id"])
    assert capsule["status"] == "VOIDED"
