"""Validation precedence: when two checks both fail, the lower-numbered check wins.

The PRD fixes the evaluation order in §2.10 ("the server evaluates them in a fixed priority
order and returns the error for the first failing check"), so both outcomes are uniquely derivable.

Difficulty instance: priority_pair_validation_conflict.
"""
from test_helpers import (
    validate_error, validate_paginated, ApiErrorId,
    make_admin_headers, make_farm_headers, make_customer_headers,
    set_clock, new_farm, new_hub, new_customer, new_product, new_cycle, new_offering,
    open_cycle, new_order, new_line, do_checkout, cutoff_cycle,
)


def _offering(api, offering_id):
    return api.get_offering(offering_id, make_admin_headers()).json()["data"]


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / addline_cycle_not_open_beats_availability
# ---------------------------------------------------------------------------
def _addline_conflict_world(api):
    """OPEN cycle, egg offering offered_qty 5. order1 reserves 3 (checked-out qty3 line) leaving
    remaining 2; order2 left in CART; the cycle is then cut off (order2 stays CART)."""
    set_clock(api)
    farm = new_farm(api, snap_authorized=True)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    egg = new_product(api, farm["id"], name="Eggs", category="DAIRY", pricing_mode="FIXED",
                      unit_price_cents=400, snap_eligible=False)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], egg["id"], offered_qty=5)
    open_cycle(api, cycle["id"])

    order1 = new_order(api, customer["id"], cycle["id"], hub["id"])
    new_line(api, customer["id"], order1["id"], offering["id"], 3)
    do_checkout(api, customer["id"], order1["id"])

    order2 = new_order(api, customer["id"], cycle["id"], hub["id"])
    cutoff_cycle(api, cycle["id"])
    return {"customer": customer, "offering": offering, "order2": order2}


def test_addline_cutoff_beats_availability_returns_cycle_not_open(api):
    """PRD §2.10: "When several checks could fail on a single request, the server evaluates them
    in a fixed priority order and returns the error for the first failing check."
    PRD §2.10: "**Cycle-open posture** — creating an order, adding a line, or checking out
    requires the market cycle to be `OPEN`, else `ERR_CYCLE_NOT_OPEN`."
    PRD §2.10: "**Availability and concurrency** — `ERR_INSUFFICIENT_AVAILABILITY` (requested
    units exceed remaining) and `ERR_STALE_FARM_VERSION` (settlement OCC mismatch)."

    Design: Difficulty/priority_pair_validation_conflict/addline_cycle_not_open_beats_availability
    """
    world = _addline_conflict_world(api)
    # requested_qty 3 > remaining 2 (availability, pri 14) AND cycle is CUTOFF (pri 8)
    resp = api.add_line(world["order2"]["id"], {"offering_id": world["offering"]["id"], "requested_qty": 3},
                        make_customer_headers(world["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CYCLE_NOT_OPEN.value, 409)


def test_addline_rejection_does_not_reserve_offering_units(api):
    """PRD §2.10: "**Cycle-open posture** — creating an order, adding a line, or checking out
    requires the market cycle to be `OPEN`, else `ERR_CYCLE_NOT_OPEN`."

    Design: Difficulty/priority_pair_validation_conflict/addline_cycle_not_open_beats_availability
    """
    world = _addline_conflict_world(api)
    api.add_line(world["order2"]["id"], {"offering_id": world["offering"]["id"], "requested_qty": 3},
                 make_customer_headers(world["customer"]["id"]))
    # The rejected add writes nothing: offering still shows reserved 3 / remaining 2.
    offering = _offering(api, world["offering"]["id"])
    assert offering["reserved_qty"] == 3
    assert offering["remaining_qty"] == 2


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / offering_product_mismatch_beats_snap_auth
# ---------------------------------------------------------------------------
def _mismatch_world(api):
    """Farm F1 (snap_authorized) owns a snap_eligible product; Farm F2 (not snap_authorized)
    exists; a cycle exists. F2 offering F1's product violates ownership AND SNAP authorization."""
    set_clock(api)
    f1 = new_farm(api, name="F1", snap_authorized=True)
    f2 = new_farm(api, name="F2", snap_authorized=False)
    kale = new_product(api, f1["id"], name="Kale", category="PRODUCE", pricing_mode="FIXED",
                       unit_price_cents=300, snap_eligible=True)
    cycle = new_cycle(api)
    return {"f2": f2, "kale": kale, "cycle": cycle}


def test_offering_farm_mismatch_beats_snap_authorization(api):
    """PRD §2.10: "When several checks could fail on a single request, the server evaluates them
    in a fixed priority order and returns the error for the first failing check."
    PRD §2.10: "**Business-referential** — `ERR_PRODUCT_FARM_MISMATCH` (offering a product the
    acting farm does not own), `ERR_OFFERING_CYCLE_MISMATCH` (substituting across cycles), and
    `ERR_NOT_LINE_OWNER` (packing a line whose farm the actor does not own)."
    PRD §2.10: "**SNAP authorization** — a SNAP-eligible product may only be created or offered
    under a SNAP-authorized farm, else `ERR_FARM_NOT_SNAP_AUTHORIZED`."

    Design: Difficulty/priority_pair_validation_conflict/offering_product_mismatch_beats_snap_auth
    """
    world = _mismatch_world(api)
    resp = api.create_offering(world["cycle"]["id"], {"product_id": world["kale"]["id"], "offered_qty": 10},
                               make_farm_headers(world["f2"]["id"]))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_FARM_MISMATCH.value, 409)


def test_rejected_offering_is_not_created(api):
    """PRD §3.3: "The product being offered must belong to the acting farm: if the product's
    `farm_id` is not the acting farm, the request is rejected with `ERR_PRODUCT_FARM_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/offering_product_mismatch_beats_snap_auth
    """
    world = _mismatch_world(api)
    api.create_offering(world["cycle"]["id"], {"product_id": world["kale"]["id"], "offered_qty": 10},
                        make_farm_headers(world["f2"]["id"]))
    resp = api.list_offerings(make_admin_headers(), params={"product_id": world["kale"]["id"]})
    data, _meta = validate_paginated(resp)
    assert data == [], "the rejected offering must not have been persisted"
