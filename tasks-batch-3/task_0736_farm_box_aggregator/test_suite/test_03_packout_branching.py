"""Packout: the ALLOCATED -> {PACKED, SHORTED, SUBSTITUTED} branching fork-join and its guards.

Difficulty instance: non_linear_state_machine (OrderLine branching).
Corner instances: over-pack, missing weight, cross-cycle substitution, line ownership,
committed reconciliation, order-posture guard.
"""
from test_helpers import (
    validate_error, ApiErrorId,
    make_admin_headers, make_farm_headers,
    set_clock, new_farm, new_hub, new_customer, new_product, new_weight_product,
    new_cycle, new_offering, open_cycle, new_order, new_line, do_checkout, do_pack,
    cutoff_cycle,
    setup_open_egg_market, setup_allocated_egg_line,
    assert_offering,
)


def _line(api, line_id):
    return api.get_line(line_id, make_admin_headers()).json()["data"]


# ---------------------------------------------------------------------------
# non_linear_state_machine / orderline_branching_pack_short_substitute
# ---------------------------------------------------------------------------
def _two_allocated_egg_lines(api):
    """Two ALLOCATED egg lines (qty 2 each) on offering A, plus a second offering B of the
    same egg product/farm/cycle to serve as a substitute target."""
    set_clock(api)
    farm = new_farm(api, snap_authorized=True)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    egg = new_product(api, farm["id"], name="Eggs", category="DAIRY", pricing_mode="FIXED",
                      unit_price_cents=400, snap_eligible=False)
    cycle = new_cycle(api)
    off_a = new_offering(api, cycle["id"], farm["id"], egg["id"], offered_qty=100)
    off_b = new_offering(api, cycle["id"], farm["id"], egg["id"], offered_qty=100)
    open_cycle(api, cycle["id"])
    order = new_order(api, customer["id"], cycle["id"], hub["id"])
    line_short = new_line(api, customer["id"], order["id"], off_a["id"], 2)
    line_sub = new_line(api, customer["id"], order["id"], off_a["id"], 2)
    do_checkout(api, customer["id"], order["id"])
    cutoff_cycle(api, cycle["id"])
    return {"farm": farm, "cycle": cycle, "order": order,
            "off_a": off_a, "off_b": off_b, "line_short": line_short, "line_sub": line_sub}


def test_pack_fewer_units_routes_to_shorted(api):
    """PRD §3.7: "**Short pack (`ALLOCATED → SHORTED`).** The packer records a `fulfilled_qty`
    that is at least 0 and strictly less than `allocated_qty`."

    Design: Difficulty/non_linear_state_machine/orderline_branching_pack_short_substitute
    """
    world = _two_allocated_egg_lines(api)
    packed = do_pack(api, world["farm"]["id"], world["line_short"]["id"], fulfilled_qty=1)
    assert packed["line_status"] == "SHORTED", "fulfilled 1 < allocated 2 routes to SHORTED"


def test_pack_with_substitute_offering_routes_to_substituted(api):
    """PRD §3.7: "**Substitution (`ALLOCATED → SUBSTITUTED`).** The packer provides a
    `substitute_offering_id` and a `substitute_qty`, replacing the ordered item with another
    offering."
    PRD §3.7: "On success, the line's `substitute_offering_id` is set, `final_line_cents` is
    computed from the substitute offering's resolved price and `substitute_qty` (or actual
    weight for a weight-priced substitute), and `price_delta_cents` is `final_line_cents` minus
    `estimated_line_cents`."

    Design: Difficulty/non_linear_state_machine/orderline_branching_pack_short_substitute
    """
    world = _two_allocated_egg_lines(api)
    packed = do_pack(api, world["farm"]["id"], world["line_sub"]["id"],
                     substitute_offering_id=world["off_b"]["id"], substitute_qty=2)
    assert packed["line_status"] == "SUBSTITUTED"
    assert packed["substitute_offering_id"] == world["off_b"]["id"]


# ---------------------------------------------------------------------------
# Corner: validations / over_pack_more_than_allocated_rejected
# ---------------------------------------------------------------------------
def test_over_pack_more_than_allocated_rejected(api):
    """PRD §3.7: "A `fulfilled_qty` greater than `allocated_qty` is rejected with `ERR_OVER_PACK`."

    Design: Corner/validations/over_pack_more_than_allocated_rejected
    """
    world = setup_allocated_egg_line(api, requested_qty=2)
    resp = api.pack_line(world["line"]["id"], {"fulfilled_qty": 3}, make_farm_headers(world["farm"]["id"]))
    validate_error(resp, ApiErrorId.ERR_OVER_PACK.value, 409)
    assert _line(api, world["line"]["id"])["line_status"] == "ALLOCATED", "rejected pack leaves the line ALLOCATED"


# ---------------------------------------------------------------------------
# Corner: validations / pack_weight_line_missing_weight_invalid
# ---------------------------------------------------------------------------
def test_pack_weight_line_missing_weight_invalid(api):
    """PRD §3.7: "For a weight-priced line, `actual_weight_kg` must be present and greater than
    zero, else `ERR_INVALID_WEIGHT`."

    Design: Corner/validations/pack_weight_line_missing_weight_invalid
    """
    set_clock(api)
    farm = new_farm(api, snap_authorized=True)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    tomato = new_weight_product(api, farm["id"], name="Heirloom Tomatoes", category="PRODUCE",
                                price_per_kg_cents=800, estimated_weight_kg=0.5, snap_eligible=True)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], tomato["id"], offered_qty=100)
    open_cycle(api, cycle["id"])
    order = new_order(api, customer["id"], cycle["id"], hub["id"])
    line = new_line(api, customer["id"], order["id"], offering["id"], 3)
    do_checkout(api, customer["id"], order["id"])
    cutoff_cycle(api, cycle["id"])

    resp = api.pack_line(line["id"], {"fulfilled_qty": 3}, make_farm_headers(farm["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_WEIGHT.value, 422)


# ---------------------------------------------------------------------------
# Corner: validations / substitute_cross_cycle_offering_mismatch_rejected
# ---------------------------------------------------------------------------
def test_substitute_cross_cycle_offering_mismatch_rejected(api):
    """PRD §3.7: "the substitute offering must belong to the same `market_cycle_id` as the
    original line's offering (`ERR_OFFERING_CYCLE_MISMATCH`)".

    Design: Corner/validations/substitute_cross_cycle_offering_mismatch_rejected
    """
    set_clock(api)
    farm = new_farm(api, snap_authorized=True)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    egg = new_product(api, farm["id"], name="Eggs", category="DAIRY", pricing_mode="FIXED",
                      unit_price_cents=400, snap_eligible=False)
    cycle1 = new_cycle(api, cycle_code="C1", region_code="R1")
    cycle2 = new_cycle(api, cycle_code="C2", region_code="R2",
                       order_open_at="2026-07-02T00:00:00Z", order_cutoff_at="2026-07-05T00:00:00Z",
                       fulfillment_date="2026-07-06T00:00:00Z")
    off1 = new_offering(api, cycle1["id"], farm["id"], egg["id"], offered_qty=100)
    off2 = new_offering(api, cycle2["id"], farm["id"], egg["id"], offered_qty=100)
    open_cycle(api, cycle1["id"])
    order = new_order(api, customer["id"], cycle1["id"], hub["id"])
    line = new_line(api, customer["id"], order["id"], off1["id"], 1)
    do_checkout(api, customer["id"], order["id"])
    cutoff_cycle(api, cycle1["id"])

    resp = api.pack_line(line["id"], {"substitute_offering_id": off2["id"], "substitute_qty": 1},
                         make_farm_headers(farm["id"]))
    validate_error(resp, ApiErrorId.ERR_OFFERING_CYCLE_MISMATCH.value, 409)
    assert _line(api, line["id"])["line_status"] == "ALLOCATED", "rejected substitution leaves the line ALLOCATED"


# ---------------------------------------------------------------------------
# Corner: validations / farm_b_cannot_pack_farm_a_line_rejected
# ---------------------------------------------------------------------------
def test_farm_b_cannot_pack_farm_a_line_rejected(api):
    """PRD §3.7: "Every pack requires the parent order to be `ALLOCATED` — checked first, so a
    pack attempted while the order is still `PLACED` yields `ERR_ORDER_NOT_ALLOCATED` — and
    requires the acting farm to own the line's offering's product (`ERR_NOT_LINE_OWNER`)."

    Design: Corner/validations/farm_b_cannot_pack_farm_a_line_rejected
    """
    set_clock(api)
    farm_a = new_farm(api, name="Farm A", snap_authorized=True)
    farm_b = new_farm(api, name="Farm B", snap_authorized=True)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    egg = new_product(api, farm_a["id"], name="Eggs", category="DAIRY", pricing_mode="FIXED",
                      unit_price_cents=400, snap_eligible=False)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm_a["id"], egg["id"], offered_qty=100)
    open_cycle(api, cycle["id"])
    order = new_order(api, customer["id"], cycle["id"], hub["id"])
    line = new_line(api, customer["id"], order["id"], offering["id"], 1)
    do_checkout(api, customer["id"], order["id"])
    cutoff_cycle(api, cycle["id"])

    resp = api.pack_line(line["id"], {"fulfilled_qty": 1}, make_farm_headers(farm_b["id"]))
    validate_error(resp, ApiErrorId.ERR_NOT_LINE_OWNER.value, 403)
    assert _line(api, line["id"])["line_status"] == "ALLOCATED"


# ---------------------------------------------------------------------------
# Corner: cross_cutting / offering_committed_reconciled_after_pack
# ---------------------------------------------------------------------------
def test_offering_committed_reconciled_after_pack(api):
    """PRD §3.7: "The final price is computed by the final pricing rule below, `price_delta_cents`
    is set to `final_line_cents` minus `estimated_line_cents`, the offering's `reserved_qty`
    decreases by the line's `requested_qty` while its `committed_qty` increases by `fulfilled_qty`."

    Design: Corner/cross_cutting_complexity_layers/offering_committed_reconciled_after_pack
    """
    world = setup_allocated_egg_line(api, requested_qty=2, offered_qty=100)
    do_pack(api, world["farm"]["id"], world["line"]["id"], fulfilled_qty=2)
    offering = api.get_offering(world["offering"]["id"], make_admin_headers()).json()["data"]
    assert_offering(offering)
    assert offering["reserved_qty"] == 0
    assert offering["committed_qty"] == 2
    assert offering["remaining_qty"] == 98


# ---------------------------------------------------------------------------
# Corner: state_machines / pack_before_cutoff_order_not_allocated
# ---------------------------------------------------------------------------
def test_pack_before_cutoff_yields_order_not_allocated(api):
    """PRD §2.10: "when packing a line, the parent order must be in `ALLOCATED`, checked
    *before* the line's own state; a line whose parent order is not `ALLOCATED` yields
    `ERR_ORDER_NOT_ALLOCATED`."

    Design: Corner/state_machines/pack_before_cutoff_order_not_allocated
    """
    world = setup_open_egg_market(api)
    order = new_order(api, world["customer"]["id"], world["cycle"]["id"], world["hub"]["id"])
    line = new_line(api, world["customer"]["id"], order["id"], world["offering"]["id"], 1)
    do_checkout(api, world["customer"]["id"], order["id"])  # order PLACED, cycle NOT cut off

    resp = api.pack_line(line["id"], {"fulfilled_qty": 1}, make_farm_headers(world["farm"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_ALLOCATED.value, 409)
    assert _line(api, line["id"])["line_status"] == "REQUESTED", "line stays REQUESTED (never allocated)"
