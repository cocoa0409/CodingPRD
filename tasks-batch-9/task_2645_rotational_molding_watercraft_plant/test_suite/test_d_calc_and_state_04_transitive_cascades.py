"""Transitive cascades: five links from a demould, three links from a demotion.

Both chains start from a request that mentions none of the rows it ends up
changing, and in both cases every link is caused strictly by the one before it.

* A successful `COOLING` to `DEMOLDED` transition wears the tool past its service
  interval, and that alone aborts the tool's *other* cycle, releases that cycle's
  charge, revives the depleted lot the charge came from and unblocks every order
  waiting on qualified resin (PRD.md sections 3.5 and 3.3).
* A re-inspection demotion recomputes a roll-up rather than a status chain: the
  order's `completed_qty` falls, a `COMPLETE` order re-opens, and the unchanged
  total cost is divided by a smaller quantity (PRD.md sections 3.6 and 3.3).
"""

from test_helpers import (
    ADMIN_HEADERS,
    PASSING_WALL_THICKNESS_POINTS,
    PLANNER_HEADERS,
    ApiErrorId,
    Q_MASS,
    Q_PERCENT,
    Q_WARPAGE,
    api_client,
    assert_decimal_equals,
    assert_money_equals,
    assert_resin_ledger_conserved,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    demold_payload,
    enter_cooling_payload,
    inspect_payload,
    molding_cycle_payload,
    outfit_payload,
    production_order_version,
    reserve_charge,
    schedule_cycle,
    set_clock,
    setup_sellable_units,
    start_oven_payload,
    trim_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


_P1_SWEEP_AT = "2026-08-03T00:00:00Z"
_P1_OVEN_START = "2026-08-03T09:00:00Z"
_P1_OVEN_END = "2026-08-03T10:00:00Z"
_P1_COOLING_END = "2026-08-03T10:35:00Z"
_P1_SECOND_WINDOW = "2026-08-03T11:00:00Z"
_P1_REWORK_POINTS = [4.6, 7.4, 4.6, 7.4, 4.6, 7.4]


def _p1_three_blocked_orders_and_one_cooling_cycle():
    """One tool due for service after a single demould, and three starved orders.

    Lot A is drawn down to 0.500 kg, which is above zero — so the lot is still
    AVAILABLE — but below the model's 11.400 kg minimum shot mass, so it no longer
    qualifies. Lot B is drawn to exactly 0.000 and goes DEPLETED. A third lot
    keeps the qualified count at 1 until the clock sweep expires it, at which point
    all three orders fall to BLOCKED_RESIN together.
    """
    ctx = create_plant_baseline(
        mold_overrides={
            "cavity_count": 1,
            "nominal_charge_kg": 12.0,
            "service_interval_cycles": 1,
        },
    )
    lot_a = create_resin_lot(received_kg=12.5, expires_on="2035-12-31")
    lot_b = create_resin_lot(received_kg=12.0, expires_on="2035-12-31")
    lot_tmp = create_resin_lot(received_kg=12.0, expires_on="2026-08-02")
    orders = [create_production_order(ctx, ordered_qty=1) for _ in range(3)]
    cycle_one = schedule_cycle(ctx, orders[0], oven_start_at=_P1_OVEN_START)
    cycle_two = schedule_cycle(ctx, orders[1], oven_start_at=_P1_SECOND_WINDOW)
    charge_one = reserve_charge(ctx, cycle_one, lot_a, charge_kg=12.0, regrind_kg=1.2)
    charge_two = reserve_charge(ctx, cycle_two, lot_b, charge_kg=12.0, regrind_kg=1.2)

    sweep = set_clock(_P1_SWEEP_AT)

    set_clock(_P1_OVEN_START)
    validate_success(
        api_client.start_oven(
            cycle_one["id"], start_oven_payload(_P1_OVEN_START), ctx["operator_headers"]
        ),
        200,
    )
    set_clock(_P1_OVEN_END)
    validate_success(
        api_client.enter_cooling(
            cycle_one["id"], enter_cooling_payload(_P1_OVEN_END), ctx["operator_headers"]
        ),
        200,
    )
    ctx.update(
        {
            "lot_a": lot_a,
            "lot_b": lot_b,
            "lot_tmp": lot_tmp,
            "orders": orders,
            "cycle_one": cycle_one,
            "cycle_two": cycle_two,
            "charge_one": charge_one,
            "charge_two": charge_two,
            "sweep": sweep,
        }
    )
    for order in orders:
        blocked = _p1_read_order(order)
        assert blocked["status"] == "BLOCKED_RESIN", (
            "setup must leave every order resin-starved, got "
            f"{blocked['status']}"
        )
    return ctx


def _p1_read_order(order):
    return api_client.read_entity("get_production_order", order["id"], ADMIN_HEADERS)


def _p1_read_lot(lot):
    return api_client.read_entity("get_resin_lot", lot["id"], ADMIN_HEADERS)


def _p1_demold(ctx):
    set_clock(_P1_COOLING_END)
    return validate_success(
        api_client.demold(
            ctx["cycle_one"]["id"],
            demold_payload(_P1_COOLING_END),
            ctx["operator_headers"],
        ),
        200,
    )


class TestDemouldServiceCascadeUnblocksResinStarvedOrders:
    """One demould, five links, and three orders that nobody touched."""

    def test_the_demould_wears_the_tool_into_maintenance_and_aborts_its_other_cycle(self):
        """Links 1 and 2: the counter reaching the interval is what aborts the sibling.

        PRD.md section 3.5: "The tool moves `IN_CYCLE` to `AVAILABLE` and its
        `cycles_since_service` is incremented by 1 — only a completed demould wears
        a tool; an abort never does."

        PRD.md section 3.5: "**CASCADE-B** runs in five links: (1) when the
        incremented `cycles_since_service` has reached the tool's
        `service_interval_cycles`, using an at-or-above comparison, the tool moves
        `AVAILABLE` to `MAINTENANCE`; (2) because that tool is in `MAINTENANCE`,
        every *other* cycle on it in `SCHEDULED` becomes `ABORTED` with
        `abort_reason` `MOLD_SERVICE_DUE`."

        The demould request names a cycle and a cooling instant and nothing else.
        The tool's interval of 1 means the very first demould demotes it, and the
        second cycle — a disjoint window on the same tool that nobody addressed —
        is aborted with the cascade's own reason rather than `OPERATOR_ABORT`.

        Design: Difficulty/transitive_cascade/demold_service_cascade_unblocks_three_resin_blocked_orders
        """
        ctx = _p1_three_blocked_orders_and_one_cooling_cycle()

        demolded = _p1_demold(ctx)

        assert demolded["status"] == "DEMOLDED", (
            f"the cycle completes rather than aborting, got {demolded['status']}"
        )
        tool = api_client.read_entity("get_mold", demolded["mold_id"], ADMIN_HEADERS)
        assert tool["cycles_since_service"] == 1, (
            f"a completed demould wears the tool once, got {tool['cycles_since_service']}"
        )
        assert tool["status"] == "MAINTENANCE", (
            "the counter reached the interval, so the tool does not settle in "
            f"AVAILABLE, got {tool['status']}"
        )

        sibling = api_client.read_entity(
            "get_molding_cycle", ctx["cycle_two"]["id"], ADMIN_HEADERS
        )
        assert sibling["status"] == "ABORTED", (
            "the tool's demotion aborts its other scheduled cycle, got "
            f"{sibling['status']}"
        )
        assert sibling["abort_reason"] == "MOLD_SERVICE_DUE", (
            "nobody called abort, so the reason names the originating cascade, got "
            f"{sibling['abort_reason']}"
        )

        hulls, _meta = validate_paginated(
            api_client.list_finished_units(
                {"molding_cycle_id": ctx["cycle_two"]["id"]}, ADMIN_HEADERS
            )
        )
        assert hulls == [], (
            f"the aborted branch mints no hull, got {len(hulls)} rows"
        )

    def test_the_released_charge_revives_its_lot_and_unblocks_all_three_orders(self):
        """Links 3, 4 and 5 reach rows the request never named.

        PRD.md section 3.5: "(3) those cycles' `RESERVED` charges become `RELEASED`
        with `released_reason` `MOLD_SERVICE_DUE`, moving `charge_kg` from
        `reserved_kg` back to `available_kg`; (4) lots whose `available_kg` rose
        above 0.000 move `DEPLETED` to `AVAILABLE`; and (5) orders in
        `BLOCKED_RESIN` that those lots qualify for move to `READY_TO_SCHEDULE`."

        PRD.md section 3.3: "An order in `BLOCKED_RESIN` for which a qualified lot
        has returned to `AVAILABLE` moves to `READY_TO_SCHEDULE` with
        `blocked_reason` cleared **only if** the target site's `posture` is not
        `FROZEN`."

        PRD.md section 3.2: "the lot's `available_kg` is at least the model's
        minimum shot mass, computed as `nominal_charge_kg` multiplied by one minus
        `charge_tolerance_pct` divided by 100, with that threshold rounded to three
        decimals *before* the comparison."

        The revived lot carries 12.000 kg, over the 11.400 kg minimum, so it
        qualifies again and every waiting order is released — including the one that
        was already in production, which lands in `READY_TO_SCHEDULE` because the
        unblock edge has a single destination. The lot that was merely drawn down to
        0.500 kg is not what fired link 5: it is still unqualified.

        Design: Difficulty/transitive_cascade/demold_service_cascade_unblocks_three_resin_blocked_orders
        """
        ctx = _p1_three_blocked_orders_and_one_cooling_cycle()

        _p1_demold(ctx)

        released = api_client.read_entity(
            "get_resin_charge", ctx["charge_two"]["id"], ADMIN_HEADERS
        )
        assert released["status"] == "RELEASED", (
            f"the aborted cycle's charge is released, got {released['status']}"
        )
        assert released["released_reason"] == "MOLD_SERVICE_DUE", (
            "the release reason matches the originating cascade, got "
            f"{released['released_reason']}"
        )

        revived = _p1_read_lot(ctx["lot_b"])
        assert_decimal_equals(revived["available_kg"], "12.000", Q_MASS, "available_kg")
        assert_decimal_equals(revived["reserved_kg"], "0.000", Q_MASS, "reserved_kg")
        assert_decimal_equals(revived["consumed_kg"], "0.000", Q_MASS, "consumed_kg")
        assert_resin_ledger_conserved(revived)
        assert revived["status"] == "AVAILABLE", (
            f"a depleted lot that regains mass returns to AVAILABLE, got {revived['status']}"
        )

        for index, order in enumerate(ctx["orders"], start=1):
            unblocked = _p1_read_order(order)
            assert unblocked["status"] == "READY_TO_SCHEDULE", (
                f"order {index} must be unblocked by the revived lot, got "
                f"{unblocked['status']}"
            )
            assert unblocked["blocked_reason"] is None, (
                f"order {index} keeps a stale blocked_reason, got "
                f"{unblocked['blocked_reason']}"
            )

        untouched = _p1_read_lot(ctx["lot_a"])
        assert_decimal_equals(
            untouched["available_kg"],
            "0.500",
            Q_MASS,
            "the drawn-down lot is not what the cascade revived",
        )
        assert_decimal_equals(untouched["consumed_kg"], "12.000", Q_MASS, "consumed_kg")
        assert untouched["status"] == "AVAILABLE", (
            "only exactly 0.000 depletes a lot, got " f"{untouched['status']}"
        )
        expired = _p1_read_lot(ctx["lot_tmp"])
        assert expired["status"] == "EXPIRED", (
            f"an expired lot is terminal and never revives, got {expired['status']}"
        )

    def test_the_unblocked_order_is_schedulable_yet_has_no_eligible_tool(self):
        """One refused booking corroborates both ends of the chain at once.

        PRD.md section 3.4: "The candidate pool is every tool whose
        `product_model_id` equals the order's, whose `status` is exactly
        `AVAILABLE` — `MAINTENANCE`, `IN_CYCLE` and `RETIRED` tools are excluded
        before ranking — ... whose `cycles_since_service` is **strictly less** than
        its `service_interval_cycles` (a tool sitting exactly at its interval is
        *not* eligible)."

        PRD.md section 3.4: "The order's `status` must be `READY_TO_SCHEDULE` or
        `IN_PRODUCTION`; a `DRAFT`, `BLOCKED_RESIN`, `BLOCKED_WAREHOUSE`, `COMPLETE`
        or `CANCELLED` order cannot take a new cycle and is refused with
        `ERR_ORDER_NOT_SCHEDULABLE` (HTTP 409)."

        PRD.md section 3.4: "otherwise — no available tool at all, or an
        `exclude_mold_ids` list that emptied the pool — it fails with
        `ERR_NO_ELIGIBLE_MOLD` (HTTP 409)."

        The order-state check would have fired had link 5 not run, and the mould-pool
        check would not have fired had link 1 not run. Getting
        `ERR_NO_ELIGIBLE_MOLD` rather than `ERR_ORDER_NOT_SCHEDULABLE` therefore
        proves the first and the last link of the chain in a single request.

        Design: Difficulty/transitive_cascade/demold_service_cascade_unblocks_three_resin_blocked_orders
        """
        ctx = _p1_three_blocked_orders_and_one_cooling_cycle()

        demolded = _p1_demold(ctx)

        third = ctx["orders"][2]
        schedulable = _p1_read_order(third)
        assert schedulable["status"] == "READY_TO_SCHEDULE", (
            "the order-state check must pass, or the refusal below would be "
            f"ambiguous, got {schedulable['status']}"
        )

        refused = api_client.create_molding_cycle(
            molding_cycle_payload(
                third["id"],
                ctx["oven_station_id"],
                ctx["cooling_bay_id"],
                production_order_version(third["id"]),
                oven_start_at="2026-08-03T14:00:00Z",
            ),
            ctx["operator_headers"],
        )
        validate_error(refused, ApiErrorId.NO_ELIGIBLE_MOLD, expected_status=409)

        hulls, _meta = validate_paginated(
            api_client.list_finished_units(
                {"molding_cycle_id": ctx["cycle_one"]["id"]}, ADMIN_HEADERS
            )
        )
        assert len(hulls) == 1, (
            f"a single-cavity tool mints exactly one hull, got {len(hulls)}"
        )
        assert hulls[0]["build_status"] == "DEMOLDED", (
            f"a freshly minted hull starts DEMOLDED, got {hulls[0]['build_status']}"
        )
        assert hulls[0]["logistics_status"] == "UNALLOCATED", (
            "a freshly minted hull is not in any warehouse, got "
            f"{hulls[0]['logistics_status']}"
        )
        assert hulls[0]["molding_cycle_id"] == demolded["id"], (
            "the minted hull belongs to the demoulded cycle, got "
            f"{hulls[0]['molding_cycle_id']}"
        )


def _p1_complete_order_with_two_sellable_hulls():
    """A two-cavity cycle inspected PASS twice, so the order is COMPLETE.

    One 24.000 kg charge at 210 cents per kilogram gives 5040 cents of resin, and
    60 oven minutes at 100 cents a minute give 6000, so the pre-overhead subtotal
    is 11040, the 18.00 percent tier adds 1987 and the total is 13027. Divided by
    two completed hulls and floored, the unit cost is 6513.
    """
    ctx = setup_sellable_units()
    hulls = ctx["sellable_units"]
    assert len(hulls) == 2, f"expected two sellable hulls, got {len(hulls)}"
    ctx["keeper"] = hulls[0]
    ctx["demoted"] = hulls[1]
    order = _p1_read_order(ctx["production_order"])
    assert order["status"] == "COMPLETE", (
        f"setup must complete the order, got {order['status']}"
    )
    assert order["completed_qty"] == 2, (
        f"both hulls must count, got {order['completed_qty']}"
    )
    assert_money_equals(order["total_cost_cents"], 13027, "total_cost_cents")
    assert_money_equals(order["unit_cost_cents"], 6513, "unit_cost_cents")
    return ctx


def _p1_reinspect(ctx, unit, points):
    return validate_success(
        api_client.inspect_finished_unit(
            unit["id"],
            inspect_payload(wall_thickness_points=list(points)),
            ctx["inspector_headers"],
        ),
        200,
    )


class TestReinspectDemotionReopensTheOrderAndRaisesUnitCost:
    """A demotion travels through a roll-up into money, and it is re-entrant."""

    def test_the_demotion_lowers_the_rollup_and_reopens_the_complete_order(self):
        """CASCADE-D links 1 to 3, with the sibling hull left alone.

        PRD.md section 3.6: "an adverse verdict moves the hull `SELLABLE` to
        `REWORK` (incrementing `rework_count`) or `SELLABLE` to `SCRAPPED`; (2)
        because the hull no longer counts, the order's `completed_qty` is recomputed
        downward and its cost roll-up and `unit_cost_cents` are recomputed —
        upward, since the same total is divided by a smaller quantity; and (3) an
        order that was `COMPLETE` and now has `completed_qty` below `ordered_qty`
        returns to `IN_PRODUCTION`, which re-opens cycle scheduling for that order."

        PRD.md section 3.6: "No sibling hull and no cycle-level average
        participates — each hull is judged alone."

        The re-inspection replaces the hull's readings with a dispersed set whose
        variation of 23.33 percent trips clause 5, while its minimum of 4.60 mm and
        its final index of 0.510 keep it clear of every scrap clause. The order's
        `scrapped_qty` therefore stays 0 and the sibling keeps its PASS.

        Design: Difficulty/transitive_cascade/reinspect_demotion_reopens_complete_order_and_raises_unit_cost
        """
        ctx = _p1_complete_order_with_two_sellable_hulls()

        demoted = _p1_reinspect(ctx, ctx["demoted"], _P1_REWORK_POINTS)

        assert demoted["inspection_verdict"] == "REWORK", (
            f"clause 5 reworks the hull, got {demoted['inspection_verdict']}"
        )
        assert demoted["build_status"] == "REWORK", (
            f"the hull leaves SELLABLE, got {demoted['build_status']}"
        )
        assert demoted["rework_count"] == 1, (
            f"the demotion consumes one rework, got {demoted['rework_count']}"
        )
        assert_decimal_equals(demoted["wall_cv_pct"], "23.33", Q_PERCENT, "wall_cv_pct")
        assert_decimal_equals(
            demoted["min_wall_thickness_mm"],
            "4.60",
            Q_PERCENT,
            "min_wall_thickness_mm clears the model floor, so no scrap clause fires",
        )
        assert_decimal_equals(
            demoted["final_warpage_index"], "0.510", Q_WARPAGE, "final_warpage_index"
        )

        order = _p1_read_order(ctx["production_order"])
        assert order["completed_qty"] == 1, (
            f"the demoted hull no longer counts, got {order['completed_qty']}"
        )
        assert order["scrapped_qty"] == 0, (
            f"a rework is not a scrap, got {order['scrapped_qty']}"
        )
        assert order["status"] == "IN_PRODUCTION", (
            f"a COMPLETE order is re-opened by the demotion, got {order['status']}"
        )

        keeper = api_client.read_entity(
            "get_finished_unit", ctx["keeper"]["id"], PLANNER_HEADERS
        )
        assert keeper["build_status"] == "SELLABLE", (
            f"the sibling is judged alone and is untouched, got {keeper['build_status']}"
        )
        assert keeper["inspection_verdict"] == "PASS", (
            f"the sibling keeps its verdict, got {keeper['inspection_verdict']}"
        )
        assert keeper["rework_count"] == 0, (
            f"the sibling's rework budget is untouched, got {keeper['rework_count']}"
        )
        assert_decimal_equals(keeper["wall_cv_pct"], "1.08", Q_PERCENT, "wall_cv_pct")

    def test_the_unit_cost_doubles_although_no_cost_input_moved(self):
        """The terminal effect is a number, and it is recomputed both ways.

        PRD.md section 3.3: "`unit_cost_cents` is the **floor** of
        `total_cost_cents` divided by `completed_qty` when `completed_qty` is at
        least 1, and null otherwise; because it is floored, the summed unit costs may
        fall below `total_cost_cents` and the remainder is deliberately not
        redistributed."

        PRD.md section 3.3: "When a demotion drops `completed_qty` below
        `ordered_qty` while the order is `COMPLETE`, the order returns to
        `IN_PRODUCTION` and the cost roll-up is recomputed — this edge makes the
        machine cyclic, and `COMPLETE` to `IN_PRODUCTION` to `COMPLETE` may repeat
        with each demotion and re-pass."

        No charge was consumed and no cycle demoulded between the two reads, so
        material, energy, overhead and total are all unchanged; only the divisor
        moved. Sending the reworked hull round the loop to a second PASS restores
        both the quantity and the unit cost, which is why the figure has to be
        recomputed on every roll-up rather than stored once.

        Design: Difficulty/transitive_cascade/reinspect_demotion_reopens_complete_order_and_raises_unit_cost
        """
        ctx = _p1_complete_order_with_two_sellable_hulls()

        _p1_reinspect(ctx, ctx["demoted"], _P1_REWORK_POINTS)

        reopened = _p1_read_order(ctx["production_order"])
        assert_money_equals(reopened["material_cost_cents"], 5040, "material_cost_cents")
        assert_money_equals(
            reopened["oven_energy_cost_cents"], 6000, "oven_energy_cost_cents"
        )
        assert_money_equals(reopened["overhead_cents"], 1987, "overhead_cents")
        assert_money_equals(reopened["total_cost_cents"], 13027, "total_cost_cents")
        assert_money_equals(
            reopened["unit_cost_cents"],
            13027,
            "unit_cost_cents after the divisor fell to 1",
        )

        validate_success(
            api_client.trim_finished_unit(
                ctx["demoted"]["id"], trim_payload(0.4), ctx["assembly_headers"]
            ),
            200,
        )
        validate_success(
            api_client.outfit_finished_unit(
                ctx["demoted"]["id"], outfit_payload(), ctx["assembly_headers"]
            ),
            200,
        )
        repassed = _p1_reinspect(
            ctx, ctx["demoted"], PASSING_WALL_THICKNESS_POINTS
        )
        assert repassed["build_status"] == "SELLABLE", (
            f"the second pass restores the hull, got {repassed['build_status']}"
        )

        closed = _p1_read_order(ctx["production_order"])
        assert closed["status"] == "COMPLETE", (
            f"the order completes again, got {closed['status']}"
        )
        assert closed["completed_qty"] == 2, (
            f"both hulls count again, got {closed['completed_qty']}"
        )
        assert_money_equals(closed["total_cost_cents"], 13027, "total_cost_cents")
        assert_money_equals(
            closed["unit_cost_cents"], 6513, "unit_cost_cents back at the halved figure"
        )
