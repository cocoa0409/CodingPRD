"""Release allocation and shipping: stock sufficiency boundaries, LOCKED vs
CURRENT pricing variants, cancellation conservation, and the ship-triggered
replenishment cascade."""
from test_helpers import (
    PLANT,
    ApiErrorId,
    allocate_release,
    assert_program_stock_invariant,
    create_approved_spec,
    create_active_program,
    create_locked_die_program,
    create_release,
    get_program,
    patch_material,
    replenish_and_complete,
    setup_stocked_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def _setup_two_pricing_programs():
    """Approved spec + LOCKED DIE program; two ACTIVE inventory programs on
    the same spec (LOCKED and CURRENT pricing), each stocked to 1000 units
    while the material costs 250 cents/bf; then the material is repriced to
    300."""
    customer, material, spec = create_approved_spec()
    program, _tooling = create_locked_die_program(spec["id"])

    prog_a = create_active_program(
        customer["id"], spec["id"], pricing_mode="LOCKED",
        max_stock_qty=1000, reorder_point_qty=200, min_release_qty=50,
    )
    prog_b = create_active_program(
        customer["id"], spec["id"], pricing_mode="CURRENT",
        max_stock_qty=1000, reorder_point_qty=200, min_release_qty=50,
    )

    replenish_and_complete(prog_a["id"], 1000, "DIE-1",
                           "2026-08-04T08:00:00Z", "2026-08-04T09:00:00Z")
    replenish_and_complete(prog_b["id"], 1000, "DIE-1",
                           "2026-08-04T09:00:00Z", "2026-08-04T10:00:00Z")

    patch_material(material["id"], cost_per_board_ft_cents=300)
    return customer, material, spec, prog_a, prog_b


def test_locked_pricing_uses_cost_pinned_at_activation(api):
    """PRD §3.6: "When `pricing_mode` is `LOCKED`, activation pins
    `locked_material_cost_bf_cents` to the material's
    `cost_per_board_ft_cents` at that moment; later material price edits
    never move the pin." PRD §3.6: "a `LOCKED` program prices from the pinned
    `locked_material_cost_bf_cents`, so a later material cost change does not
    move the release price, while a `CURRENT` program re-reads the material's
    `cost_per_board_ft_cents` at allocation time, so an identical release
    prices differently after a material cost change."

    Design: Difficulty/dual_variant_calc/release_order_locked_vs_current_pricing
    """
    customer, _m, _s, prog_a, _prog_b = _setup_two_pricing_programs()

    prog_a_now = get_program(prog_a["id"])
    assert prog_a_now["locked_material_cost_bf_cents"] == 250, (
        "the pin was taken at activation and the later PATCH did not move it"
    )

    rel = create_release(prog_a["id"], 100, customer["id"])
    allocated = allocate_release(rel["id"])
    # LOCKED at 250: 2 sheets * 72 bf * 250 / 100 = 360/part material; +25
    # cutting; 385 * 1.15 = 442.75 -> 443.
    assert allocated["unit_price_cents"] == 443
    assert allocated["total_price_cents"] == 44300


def test_current_pricing_reprices_at_allocate(api):
    """PRD §3.6: "a `LOCKED` program prices from the pinned
    `locked_material_cost_bf_cents`, so a later material cost change does not
    move the release price, while a `CURRENT` program re-reads the material's
    `cost_per_board_ft_cents` at allocation time, so an identical release
    prices differently after a material cost change." PRD §3.6: "The raw unit
    amount — material plus cutting, scaled by the same tier multipliers as
    §3.5 — is rounded per the pinned order with no setup fee:
    `unit_price_cents` is the raw unit rounded half-up to whole cents, and
    `total_price_cents` is the rounded unit times `qty`."

    Design: Difficulty/dual_variant_calc/release_order_locked_vs_current_pricing
    """
    customer, _m, _s, prog_a, prog_b = _setup_two_pricing_programs()

    rel_b = create_release(prog_b["id"], 100, customer["id"])
    allocated_b = allocate_release(rel_b["id"])
    # CURRENT at 300: 2 sheets * 72 bf * 300 / 100 = 432/part; +25 cutting;
    # 457 * 1.15 = 525.55 -> 526.
    assert allocated_b["unit_price_cents"] == 526
    assert allocated_b["total_price_cents"] == 52600

    rel_a = create_release(prog_a["id"], 100, customer["id"])
    allocated_a = allocate_release(rel_a["id"])
    assert allocated_a["unit_price_cents"] == 443
    assert allocated_a["unit_price_cents"] != allocated_b["unit_price_cents"], (
        "identical releases price differently across the two pricing modes"
    )


def test_allocate_exact_available_succeeds(api):
    """PRD §3.6: "The release `qty` may not exceed the unreserved stock — the
    program's `on_hand_qty` minus its `reserved_qty` — though exact equality
    is permitted; a shortfall is rejected with `ERR_INSUFFICIENT_STOCK`
    (HTTP 409)." PRD §3.6: "The program's `reserved_qty` increases by the
    release `qty`."

    Design: Difficulty/boundary_precision_check/allocate_exact_available_then_zero_available
    """
    ctx = setup_stocked_program()  # on_hand 1000, reserved 0
    customer, program = ctx["customer"], ctx["program"]

    rel = create_release(program["id"], 1000, customer["id"])
    allocated = allocate_release(rel["id"])
    assert allocated["status"] == "ALLOCATED", "exact equality is permitted"

    program_now = get_program(program["id"])
    assert program_now["reserved_qty"] == 1000
    assert program_now["on_hand_qty"] == 1000, "reservation is not a shipment"


def test_allocate_beyond_zero_available_rejected(api):
    """PRD §3.6: "The release `qty` may not exceed the unreserved stock — the
    program's `on_hand_qty` minus its `reserved_qty` — though exact equality
    is permitted; a shortfall is rejected with `ERR_INSUFFICIENT_STOCK`
    (HTTP 409)."

    Design: Difficulty/boundary_precision_check/allocate_exact_available_then_zero_available
    """
    ctx = setup_stocked_program()
    customer, program = ctx["customer"], ctx["program"]

    rel1 = create_release(program["id"], 1000, customer["id"],
                          requested_ship_date="2026-08-10T00:00:00Z")
    allocate_release(rel1["id"])  # consumes the entire pool

    rel2 = create_release(program["id"], 50, customer["id"],
                          requested_ship_date="2026-08-11T00:00:00Z")
    resp = api.allocate_release(rel2["id"], PLANT)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK)


def test_allocate_then_cancel_restores_reserved_qty(api):
    """PRD §3.6: "Allocation, by a `PlantManager`, moves a release from
    `PENDING` to `ALLOCATED`." PRD §3.6: "The program's `reserved_qty`
    increases by the release `qty`." PRD §3.6: "Cancellation — by the owning
    `Customer`, by a `PlantManager`, or by the system when the program is
    suspended — moves a release from `PENDING` or `ALLOCATED` to `CANCELLED`,
    and cancelling an `ALLOCATED` release returns its reservation to the
    program."

    Design: Difficulty/compensating_invariant/allocate_cancel_conserves_program_stock
    """
    ctx = setup_stocked_program()
    customer, program = ctx["customer"], ctx["program"]
    rel = create_release(program["id"], 100, customer["id"])

    allocate_release(rel["id"])
    assert get_program(program["id"])["reserved_qty"] == 100

    cancelled = validate_success(api.cancel_release(rel["id"], PLANT))
    assert cancelled["status"] == "CANCELLED"
    assert get_program(program["id"])["reserved_qty"] == 0, (
        "the forward allocation and the compensating cancellation net to zero"
    )


def test_allocate_cancel_pair_conserves_stock_totals(api):
    """PRD §3.5: "Completing a `REPLENISHMENT` order credits its inventory
    program — the program's `produced_qty` and `on_hand_qty` each increase by
    the order `qty`." PRD §3.6: "The program's `on_hand_qty` and
    `reserved_qty` each decrease by the release `qty`, and `shipped_qty`
    increases by it."

    Design: Difficulty/compensating_invariant/allocate_cancel_conserves_program_stock
    """
    ctx = setup_stocked_program()
    customer, program = ctx["customer"], ctx["program"]
    before = get_program(program["id"])
    assert before["produced_qty"] == 1000
    assert_program_stock_invariant(before)

    rel = create_release(program["id"], 100, customer["id"])
    allocate_release(rel["id"])
    validate_success(api.cancel_release(rel["id"], PLANT))

    after = get_program(program["id"])
    assert after["produced_qty"] == 1000
    assert after["on_hand_qty"] == 1000
    assert after["shipped_qty"] == 0
    assert_program_stock_invariant(after)


def _setup_ship_ready_release(qty=850):
    """Stocked program (1000 on hand, reorder 200) with one ALLOCATED
    release of `qty`."""
    ctx = setup_stocked_program()
    customer, program = ctx["customer"], ctx["program"]
    rel = create_release(program["id"], qty, customer["id"])
    allocate_release(rel["id"])
    return ctx, rel


def test_ship_mutates_program_stock_counters(api):
    """PRD §3.6: "Shipping, by a `PlantManager`, moves an `ALLOCATED` release
    to `SHIPPED`; the program must be `ACTIVE`, or the ship is rejected with
    `ERR_PROGRAM_NOT_ACTIVE`. The program's `on_hand_qty` and `reserved_qty`
    each decrease by the release `qty`, and `shipped_qty` increases by it."

    Design: Difficulty/transitive_cascade/release_ship_triggers_replenishment_below_reorder
    """
    ctx, rel = _setup_ship_ready_release()
    program = ctx["program"]

    shipped = validate_success(api.ship_release(rel["id"], PLANT))
    assert shipped["status"] == "SHIPPED"

    program_after = get_program(program["id"])
    assert program_after["on_hand_qty"] == 150  # 1000 - 850
    assert program_after["reserved_qty"] == 0
    assert program_after["shipped_qty"] == 850
    assert_program_stock_invariant(program_after)


def test_ship_below_reorder_point_spawns_replenishment_order(api):
    """PRD §3.6: "If the post-ship `on_hand_qty` has fallen strictly below
    the program's `reorder_point_qty` — landing exactly on the reorder point
    triggers nothing — the system computes the pipeline quantity as the sum
    of `qty` across the production orders carrying this program's
    `inventory_program_id` whose `fab_status` is `QUOTED`, `CONFIRMED`, or
    `IN_PROGRESS`, and a suggested quantity of `max_stock_qty` minus the
    on-hand stock minus the pipeline quantity." PRD §3.6: "When the suggested
    quantity is greater than zero, the system creates a `REPLENISHMENT`
    production order in `QUOTED` for that quantity, against the program's
    specification and the locked cut program selected by the same rule used
    for release pricing."

    Design: Difficulty/transitive_cascade/release_ship_triggers_replenishment_below_reorder
    """
    ctx, rel = _setup_ship_ready_release()
    program = ctx["program"]
    validate_success(api.ship_release(rel["id"], PLANT))

    # Post-ship on_hand 150 < reorder 200 -> suggested 1000 - 150 - 0 = 850.
    orders, meta = validate_paginated(
        api.list_production_orders(
            PLANT,
            params={"inventory_program_id": program["id"], "fab_status": "QUOTED"},
        )
    )
    assert meta["total_count"] == 1, (
        "exactly the auto-created replenishment order is still QUOTED"
    )
    auto = orders[0]
    assert auto["qty"] == 850
    assert auto["order_kind"] == "REPLENISHMENT"
    assert auto["fab_status"] == "QUOTED"
