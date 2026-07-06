"""Subscription lifecycle plus offering listing / pagination.

Difficulty instance: non_linear_state_machine (subscription ACTIVE<->PAUSED cycle).
Corner instances: subscription initial state, pause-idempotency, filtered listing, bad pagination.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    make_admin_headers, make_customer_headers,
    set_clock, new_farm, new_hub, new_customer, new_product, new_cycle, new_offering,
    new_subscription,
    assert_subscription,
)


def _subscription(api, sub_id, customer_id):
    return api.get_subscription(sub_id, make_customer_headers(customer_id)).json()["data"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / subscription_active_paused_active_cycle
# ---------------------------------------------------------------------------
def _active_subscription(api):
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    sub = new_subscription(api, customer["id"], hub["id"], box_size="MEDIUM", cadence="WEEKLY", price_cap_cents=3000)
    return {"customer": customer, "sub": sub}


def test_subscription_pause_moves_active_to_paused(api):
    """PRD §3.4: "A subscription's `status` starts `ACTIVE` and moves cyclically: pausing
    advances `ACTIVE → PAUSED`, resuming advances `PAUSED → ACTIVE`, and cancelling advances
    either `ACTIVE → CANCELLED` or `PAUSED → CANCELLED`, which is terminal."

    Design: Difficulty/non_linear_state_machine/subscription_active_paused_active_cycle
    """
    world = _active_subscription(api)
    resp = api.pause_subscription(world["sub"]["id"], make_customer_headers(world["customer"]["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "PAUSED"


def test_subscription_resume_loops_back_to_active(api):
    """PRD §3.4: "A subscription's `status` starts `ACTIVE` and moves cyclically: pausing
    advances `ACTIVE → PAUSED`, resuming advances `PAUSED → ACTIVE`, and cancelling advances
    either `ACTIVE → CANCELLED` or `PAUSED → CANCELLED`, which is terminal."

    Design: Difficulty/non_linear_state_machine/subscription_active_paused_active_cycle
    """
    world = _active_subscription(api)
    api.pause_subscription(world["sub"]["id"], make_customer_headers(world["customer"]["id"]))
    resp = api.resume_subscription(world["sub"]["id"], make_customer_headers(world["customer"]["id"]))
    data = validate_success(resp, 200)
    assert data["status"] == "ACTIVE", "ACTIVE -> PAUSED -> ACTIVE returns to the start state"


# ---------------------------------------------------------------------------
# Corner: state_machines / subscription_initial_state_active
# ---------------------------------------------------------------------------
def test_new_subscription_starts_active(api):
    """PRD §3.4: "A subscription's `status` starts `ACTIVE` and moves cyclically: pausing
    advances `ACTIVE → PAUSED`, resuming advances `PAUSED → ACTIVE`, and cancelling advances
    either `ACTIVE → CANCELLED` or `PAUSED → CANCELLED`, which is terminal."

    Design: Corner/state_machines/subscription_initial_state_active
    """
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    sub = new_subscription(api, customer["id"], hub["id"], box_size="SMALL", cadence="WEEKLY", price_cap_cents=1500)
    assert_subscription(sub)
    assert sub["status"] == "ACTIVE"


# ---------------------------------------------------------------------------
# Corner: state_machines / pause_already_paused_subscription_rejected
# ---------------------------------------------------------------------------
def test_pause_already_paused_subscription_rejected(api):
    """PRD §3.4: "Each transition requires the acting customer to own the subscription and the
    subscription to hold the expected predecessor state, else `ERR_INVALID_STATE`."

    Design: Corner/state_machines/pause_already_paused_subscription_rejected
    """
    world = _active_subscription(api)
    api.pause_subscription(world["sub"]["id"], make_customer_headers(world["customer"]["id"]))
    resp = api.pause_subscription(world["sub"]["id"], make_customer_headers(world["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, 409)
    assert _subscription(api, world["sub"]["id"], world["customer"]["id"])["status"] == "PAUSED"


# ---------------------------------------------------------------------------
# Corner: endpoints / list_offerings_by_market_cycle_reverse_reachability
# ---------------------------------------------------------------------------
def test_list_offerings_filtered_by_market_cycle(api):
    """PRD §2.8: "Offerings can be filtered by `product_id`, `market_cycle_id`, or `farm_id`."
    PRD §2.3: "Every list response includes `limit`, `offset`, `total_count`, and `has_more` in
    the `meta` object of the envelope."

    Design: Corner/endpoints/list_offerings_by_market_cycle_reverse_reachability
    """
    farm = new_farm(api)
    product = new_product(api, farm["id"])
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], product["id"], offered_qty=100)

    resp = api.list_offerings(make_admin_headers(), params={"market_cycle_id": cycle["id"]})
    data, meta = validate_paginated(resp)  # asserts total_count + has_more present in meta
    assert any(o["id"] == offering["id"] for o in data), "the cycle's offering must be reachable via the filter"


# ---------------------------------------------------------------------------
# Corner: endpoints / list_offerings_bad_limit_rejected
# ---------------------------------------------------------------------------
def test_list_offerings_bad_limit_rejected(api):
    """PRD §2.3: "A request whose `limit` falls outside the inclusive range of 1 through 100, or
    whose `offset` is negative, is rejected with `ERR_INVALID_PAGINATION`."

    Design: Corner/endpoints/list_offerings_bad_limit_rejected
    """
    set_clock(api)
    resp = api.list_offerings(make_admin_headers(), params={"limit": 0})
    validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value, 422)
