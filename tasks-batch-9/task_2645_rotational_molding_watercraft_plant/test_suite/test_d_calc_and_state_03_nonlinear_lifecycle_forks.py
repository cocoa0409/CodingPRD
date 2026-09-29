"""Non-linear lifecycles: a branch, a loop and a destructive backward edge.

Three entities each bend their state machine a different way, and in each case
the shape of the non-linearity is what decides the observable outcome.

* **MoldingCycle** branches: `SCHEDULED` has two outgoing edges, and the *same*
  abort endpoint compensates differently depending on which one was taken —
  resin reserved is returned, resin consumed is scrapped (PRD.md section 3.5).
* **FinishedUnit** loops: `REWORK` travels backward to `TRIMMED`, so the hull
  occupies the same states twice, with its hardware kit cleared in between, and
  the loop is closed from the *other* state axis (PRD.md section 3.6).
* **Shipment** reverts destructively: `SEALED` back to `LOADING` destroys the
  quote rather than preserving it, so re-entering `SEALED` recomputes the whole
  freight from scratch over a line set that grew — and on a different discount
  tier (PRD.md section 3.8).
"""

from test_helpers import (
    ADMIN_HEADERS,
    PASSING_WALL_THICKNESS_POINTS,
    PLANNER_HEADERS,
    ApiErrorId,
    Q_CUBE,
    Q_MASS,
    Q_PERCENT,
    Q_WARPAGE,
    abort_payload,
    advance_unit_to_outfitted,
    api_client,
    assert_decimal_equals,
    assert_instant_equals,
    assert_money_equals,
    assert_resin_ledger_conserved,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    inspect_payload,
    outfit_payload,
    reserve_charge,
    schedule_cycle,
    set_clock,
    setup_demolded_units,
    setup_loaded_shipment,
    shipment_line_payload,
    shipment_version,
    start_oven_payload,
    store_unit,
    trim_payload,
    unique_suffix,
    unseal_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


_P1_CYCLE_A_START = "2026-08-01T09:00:00Z"
_P1_CYCLE_B_START = "2026-08-01T11:00:00Z"
_P1_CYCLE_B_ABORT = "2026-08-01T11:30:00Z"


def _p1_two_scheduled_cycles_sharing_one_lot():
    """One 24.000 kg lot, one single-cavity tool and two SCHEDULED cycles.

    Each cycle holds a RESERVED 12.000 kg charge, so the lot ends setup with
    available_kg 0.000 and status DEPLETED. The two oven windows, 09:00-10:00 and
    11:00-12:00 on the same arm, are far enough apart that the station's
    changeover buffer never brings them into contact.
    """
    ctx = create_plant_baseline(
        mold_overrides={"cavity_count": 1, "nominal_charge_kg": 12.0},
    )
    lot = create_resin_lot(received_kg=24.0)
    order = create_production_order(ctx, ordered_qty=2)
    cycle_a = schedule_cycle(ctx, order, oven_start_at=_P1_CYCLE_A_START)
    cycle_b = schedule_cycle(ctx, order, oven_start_at=_P1_CYCLE_B_START)
    charge_a = reserve_charge(ctx, cycle_a, lot, charge_kg=12.0, regrind_kg=1.2)
    charge_b = reserve_charge(ctx, cycle_b, lot, charge_kg=12.0, regrind_kg=1.2)
    ctx.update(
        {
            "resin_lot": lot,
            "production_order": order,
            "cycle_a": cycle_a,
            "cycle_b": cycle_b,
            "charge_a": charge_a,
            "charge_b": charge_b,
        }
    )
    depleted = _p1_read_lot(ctx)
    assert depleted["status"] == "DEPLETED", (
        "two 12.000 kg reservations must drive a 24.000 kg lot to DEPLETED, got "
        f"{depleted['status']}"
    )
    return ctx


def _p1_read_lot(ctx):
    return api_client.read_entity("get_resin_lot", ctx["resin_lot"]["id"], ADMIN_HEADERS)


def _p1_read_charge(charge):
    return api_client.read_entity("get_resin_charge", charge["id"], ADMIN_HEADERS)


def _p1_read_order(ctx):
    return api_client.read_entity(
        "get_production_order", ctx["production_order"]["id"], ADMIN_HEADERS
    )


def _p1_abort(ctx, cycle):
    return validate_success(
        api_client.abort_molding_cycle(
            cycle["id"], abort_payload(), ctx["operator_headers"]
        ),
        200,
    )


def _p1_assert_lot_buckets(lot, *, available, reserved, consumed):
    assert_decimal_equals(lot["available_kg"], available, Q_MASS, "available_kg")
    assert_decimal_equals(lot["reserved_kg"], reserved, Q_MASS, "reserved_kg")
    assert_decimal_equals(lot["consumed_kg"], consumed, Q_MASS, "consumed_kg")
    assert_resin_ledger_conserved(lot)


class TestScheduledForkWithDivergentAbortCompensation:
    """The same abort endpoint compensates differently on each edge out of SCHEDULED."""

    def test_aborting_from_scheduled_returns_the_reserved_shot_to_the_lot(self):
        """The unheated branch is fully compensated and revives a depleted lot.

        PRD.md section 3.5: "Aborting from `SCHEDULED` is the head of
        **CASCADE-A**: (1) the cycle becomes `ABORTED` with `abort_reason`
        `OPERATOR_ABORT`; (2) every charge of the cycle in `RESERVED` becomes
        `RELEASED` with `released_reason` `CYCLE_ABORTED`, moving `charge_kg` from
        `reserved_kg` back to `available_kg`; (3) lots whose `available_kg` rose
        above 0.000 move `DEPLETED` to `AVAILABLE`."

        PRD.md section 3.5: "No hull is ever created by an abort."

        The cycle never entered the oven, so `actual_oven_start_at` is still null
        and the whole 12.000 kg reservation comes back.

        Design: Difficulty/non_linear_state_machine/molding_cycle_scheduled_fork_with_divergent_abort_compensation
        """
        ctx = _p1_two_scheduled_cycles_sharing_one_lot()

        aborted = _p1_abort(ctx, ctx["cycle_a"])

        assert aborted["status"] == "ABORTED", (
            f"the SCHEDULED branch ends in ABORTED, got {aborted['status']}"
        )
        assert aborted["abort_reason"] == "OPERATOR_ABORT", (
            f"the supplied reason is recorded, got {aborted['abort_reason']}"
        )
        assert aborted["actual_oven_start_at"] is None, (
            "this branch never entered the oven, so no actual start was stamped"
        )

        charge = _p1_read_charge(ctx["charge_a"])
        assert charge["status"] == "RELEASED", (
            f"a reserved charge is released by the abort, got {charge['status']}"
        )
        assert charge["released_reason"] == "CYCLE_ABORTED", (
            f"the release reason is CYCLE_ABORTED, got {charge['released_reason']}"
        )

        lot = _p1_read_lot(ctx)
        _p1_assert_lot_buckets(lot, available="12.000", reserved="12.000", consumed="0.000")
        assert lot["status"] == "AVAILABLE", (
            "the lot regained mass above 0.000 and must leave DEPLETED, got "
            f"{lot['status']}"
        )

    def test_aborting_from_oven_running_scraps_the_consumed_shot(self):
        """The heated branch frees the tool but never returns the resin.

        PRD.md section 3.5: "Every `RESERVED` charge on the cycle becomes
        `CONSUMED`, moving `charge_kg` from its lot's `reserved_kg` to its lot's
        `consumed_kg` while `available_kg` is untouched."

        PRD.md section 3.5: "Aborting from `OVEN_RUNNING` or from `COOLING` returns
        the tool `IN_CYCLE` to `AVAILABLE` *without* incrementing
        `cycles_since_service`, but charges already `CONSUMED` are **not**
        restored: `consumed_kg` stays on the lot as a scrapped shot,
        `available_kg` does not rise, and consequently no order is unblocked."

        PRD.md section 2.10: "Consumption is irreversible — `consumed_kg` is never
        decremented — which is why an abort after the oven has started returns no
        resin."

        The first cycle's abort put 12.000 kg back; the second cycle's oven start
        moves the other 12.000 kg to consumed, and its abort leaves it there. The
        two branches split one lot into 12.000 restored and 12.000 scrapped.

        Design: Difficulty/non_linear_state_machine/molding_cycle_scheduled_fork_with_divergent_abort_compensation
        """
        ctx = _p1_two_scheduled_cycles_sharing_one_lot()
        _p1_abort(ctx, ctx["cycle_a"])

        set_clock(_P1_CYCLE_B_START)
        running = validate_success(
            api_client.start_oven(
                ctx["cycle_b"]["id"],
                start_oven_payload(_P1_CYCLE_B_START),
                ctx["operator_headers"],
            ),
            200,
        )
        assert running["status"] == "OVEN_RUNNING", (
            f"the other edge out of SCHEDULED is OVEN_RUNNING, got {running['status']}"
        )
        consumed = _p1_read_charge(ctx["charge_b"])
        assert consumed["status"] == "CONSUMED", (
            f"oven start consumes the reserved charge, got {consumed['status']}"
        )
        mid = _p1_read_lot(ctx)
        _p1_assert_lot_buckets(mid, available="12.000", reserved="0.000", consumed="12.000")
        assert mid["status"] == "AVAILABLE", (
            "consumption leaves available_kg untouched, so the lot does not "
            f"re-deplete, got {mid['status']}"
        )
        in_cycle = api_client.read_entity(
            "get_mold", running["mold_id"], ADMIN_HEADERS
        )
        assert in_cycle["status"] == "IN_CYCLE", (
            f"the running cycle holds the tool, got {in_cycle['status']}"
        )

        set_clock(_P1_CYCLE_B_ABORT)
        aborted = _p1_abort(ctx, ctx["cycle_b"])

        assert aborted["status"] == "ABORTED", (
            f"an OVEN_RUNNING cycle may still be aborted, got {aborted['status']}"
        )
        assert aborted["abort_reason"] == "OPERATOR_ABORT", (
            f"the supplied reason is recorded, got {aborted['abort_reason']}"
        )
        still_consumed = _p1_read_charge(ctx["charge_b"])
        assert still_consumed["status"] == "CONSUMED", (
            "a consumed charge is never released by an abort, got "
            f"{still_consumed['status']}"
        )
        assert still_consumed["released_reason"] is None, (
            "nothing released this charge, so released_reason stays null, got "
            f"{still_consumed['released_reason']}"
        )

        lot = _p1_read_lot(ctx)
        _p1_assert_lot_buckets(lot, available="12.000", reserved="0.000", consumed="12.000")
        assert lot["status"] == "AVAILABLE", (
            f"the scrapped shot does not change the lot's status, got {lot['status']}"
        )

        freed = api_client.read_entity("get_mold", running["mold_id"], ADMIN_HEADERS)
        assert freed["status"] == "AVAILABLE", (
            f"the abort returns the tool to the pool, got {freed['status']}"
        )
        assert freed["cycles_since_service"] == 0, (
            "only a completed demould wears a tool, got "
            f"{freed['cycles_since_service']}"
        )

    def test_neither_branch_mints_a_hull_and_only_the_consumed_shot_is_costed(self):
        """The cost roll-up counts the scrapped shot but no oven energy at all.

        PRD.md section 3.3: "over the order's charges in `status` `CONSUMED` —
        reached through the order's cycles — each charge contributes `charge_kg`
        multiplied by its lot's `cost_cents_per_kg`, **rounded half-up to whole
        cents per charge and only then summed** into `material_cost_cents`."

        PRD.md section 3.3: "over the order's cycles in `status` `DEMOLDED` only,
        each contributes `actual_oven_minutes` multiplied by its station's
        `energy_cents_per_min`, again rounded to whole cents per cycle before
        summation into `oven_energy_cost_cents`; cycles in `SCHEDULED`,
        `OVEN_RUNNING`, `COOLING` or `ABORTED` contribute nothing."

        PRD.md section 3.3: "`unit_cost_cents` is the **floor** of
        `total_cost_cents` divided by `completed_qty` when `completed_qty` is at
        least 1, and null otherwise."

        Both branches ended in ABORTED, so no cycle ever reached DEMOLDED: the
        material line carries the one consumed charge at 2520 cents, energy is 0,
        overhead is the 18.00 percent tier on 2520 and the unit cost stays null.

        Design: Difficulty/non_linear_state_machine/molding_cycle_scheduled_fork_with_divergent_abort_compensation
        """
        ctx = _p1_two_scheduled_cycles_sharing_one_lot()
        _p1_abort(ctx, ctx["cycle_a"])
        set_clock(_P1_CYCLE_B_START)
        validate_success(
            api_client.start_oven(
                ctx["cycle_b"]["id"],
                start_oven_payload(_P1_CYCLE_B_START),
                ctx["operator_headers"],
            ),
            200,
        )
        set_clock(_P1_CYCLE_B_ABORT)
        _p1_abort(ctx, ctx["cycle_b"])

        hulls, _meta = validate_paginated(
            api_client.list_finished_units(
                {"production_order_id": ctx["production_order"]["id"]}, ADMIN_HEADERS
            )
        )
        assert hulls == [], f"an abort never mints a hull, got {len(hulls)} rows"

        order = _p1_read_order(ctx)
        assert order["status"] == "IN_PRODUCTION", (
            f"the order stays in production, got {order['status']}"
        )
        assert order["completed_qty"] == 0, (
            f"no hull was completed, got {order['completed_qty']}"
        )
        assert order["scrapped_qty"] == 0, (
            f"no hull was scrapped, got {order['scrapped_qty']}"
        )
        assert_money_equals(order["material_cost_cents"], 2520, "material_cost_cents")
        assert_money_equals(
            order["oven_energy_cost_cents"], 0, "oven_energy_cost_cents"
        )
        assert_money_equals(order["overhead_cents"], 454, "overhead_cents")
        assert_money_equals(order["total_cost_cents"], 2974, "total_cost_cents")
        assert order["unit_cost_cents"] is None, (
            f"unit cost is null while completed_qty is 0, got {order['unit_cost_cents']}"
        )


_P1_REWORK_POINTS = [4.6, 7.4, 4.6, 7.4, 4.6, 7.4]
_P1_STORE_AT = "2026-08-01T13:00:00Z"


def _p1_outfitted_single_hull():
    """One hull from a single-cavity cycle, OUTFITTED with its first kit.

    The order is for exactly one hull, the cycle ran 09:00-10:00 and demoulded at
    10:35, so ``actual_oven_minutes`` is 60 and ``actual_cooling_minutes`` is 35 —
    above the model's 30 minute floor, which zeroes the cooling term of the
    warpage index and leaves the distribution term as the only live input.
    """
    suffix = unique_suffix()
    ctx = setup_demolded_units(
        mold_overrides={"cavity_count": 1, "nominal_charge_kg": 12.0},
        order_overrides={"ordered_qty": 1},
        charge_overrides={"charge_kg": 12.0, "regrind_kg": 1.2},
    )
    ctx["first_kit"] = f"HKA{suffix}"
    ctx["second_kit"] = f"HKB{suffix}"
    unit = ctx["finished_units"][0]
    ctx["unit"] = advance_unit_to_outfitted(
        ctx, unit, hardware_kit_serial=ctx["first_kit"]
    )
    ctx["unit_id"] = unit["id"]
    return ctx


def _p1_inspect(ctx, points):
    return validate_success(
        api_client.inspect_finished_unit(
            ctx["unit_id"],
            inspect_payload(wall_thickness_points=list(points)),
            ctx["inspector_headers"],
        ),
        200,
    )


def _p1_reworked_then_resellable(ctx):
    """Run the whole loop: REWORK, back to TRIMMED, re-outfit, then PASS."""
    _p1_inspect(ctx, _P1_REWORK_POINTS)
    validate_success(
        api_client.trim_finished_unit(
            ctx["unit_id"], trim_payload(0.35), ctx["assembly_headers"]
        ),
        200,
    )
    validate_success(
        api_client.outfit_finished_unit(
            ctx["unit_id"], outfit_payload(ctx["second_kit"]), ctx["assembly_headers"]
        ),
        200,
    )
    return _p1_inspect(ctx, PASSING_WALL_THICKNESS_POINTS)


class TestReworkLoopClosedByTheLogisticsAxis:
    """A backward build edge, a second lap, and a loop closed from the other axis."""

    def test_the_rework_verdict_travels_backward_and_clears_the_hardware_kit(self):
        """Clause 5 of the ladder reworks the hull and trimming re-enters TRIMMED.

        PRD.md section 3.6: "(5) `wall_cv_pct` strictly greater than the model's
        `wall_cv_max_pct` gives `REWORK`; exactly equal passes."

        PRD.md section 3.6: "a `REWORK` moves `OUTFITTED` to `REWORK` and
        increments `rework_count`."

        PRD.md section 3.6: "Trimming is legal from `build_status` `DEMOLDED` or
        `REWORK` and moves the hull to `TRIMMED`... On the `REWORK` entry the
        previously recorded `hardware_kit_serial` is cleared to null, so outfitting
        must be redone from scratch."

        The six alternating readings give a mean of 6.000 with a standard deviation
        of 1.400 and so a variation of 23.33 percent, far over the model's 12.00
        ceiling. The final warpage index of 0.510 stays under the 1.200 rework
        threshold, so clause 5 — not clause 6 — is provably what fired. The
        logistics axis does not move at all.

        Design: Difficulty/non_linear_state_machine/finished_unit_rework_loop_edge_closed_by_logistics_axis
        """
        ctx = _p1_outfitted_single_hull()

        judged = _p1_inspect(ctx, _P1_REWORK_POINTS)

        assert judged["inspection_verdict"] == "REWORK", (
            f"a 23.33 percent variation reworks, got {judged['inspection_verdict']}"
        )
        assert judged["build_status"] == "REWORK", (
            f"the build axis moves to REWORK, got {judged['build_status']}"
        )
        assert judged["rework_count"] == 1, (
            f"the rework budget is consumed once, got {judged['rework_count']}"
        )
        assert_decimal_equals(
            judged["mean_wall_thickness_mm"], "6.000", Q_MASS, "mean_wall_thickness_mm"
        )
        assert_decimal_equals(judged["wall_sd_mm"], "1.400", Q_MASS, "wall_sd_mm")
        assert_decimal_equals(judged["wall_cv_pct"], "23.33", Q_PERCENT, "wall_cv_pct")
        assert_decimal_equals(
            judged["min_wall_thickness_mm"],
            "4.60",
            Q_PERCENT,
            "min_wall_thickness_mm clears the 4.50 floor, so clause 1 cannot fire",
        )
        assert_decimal_equals(
            judged["final_warpage_index"], "0.510", Q_WARPAGE, "final_warpage_index"
        )
        assert judged["logistics_status"] == "UNALLOCATED", (
            "the two axes are independent and the logistics axis did not move, got "
            f"{judged['logistics_status']}"
        )

        order = api_client.read_entity(
            "get_production_order", ctx["production_order_id"], ADMIN_HEADERS
        )
        assert order["status"] == "IN_PRODUCTION", (
            f"a reworked hull does not complete the order, got {order['status']}"
        )
        assert order["completed_qty"] == 0, (
            f"a reworked hull does not count as completed, got {order['completed_qty']}"
        )

        looped = validate_success(
            api_client.trim_finished_unit(
                ctx["unit_id"], trim_payload(0.35), ctx["assembly_headers"]
            ),
            200,
        )
        assert looped["build_status"] == "TRIMMED", (
            "the backward edge re-enters a state the hull already occupied, got "
            f"{looped['build_status']}"
        )
        assert looped["hardware_kit_serial"] is None, (
            "the REWORK entry clears the kit, got "
            f"{looped['hardware_kit_serial']}"
        )
        assert_decimal_equals(
            looped["trim_waste_kg"], "0.350", Q_MASS, "trim_waste_kg is overwritten"
        )

    def test_the_second_lap_reaches_sellable_without_refunding_the_rework_budget(self):
        """The loop closes on a PASS, but `rework_count` keeps its 1.

        PRD.md section 3.6: "The tenth build edge is the rework loop itself: a hull
        in `REWORK` re-enters `TRIMMED` through trimming, is outfitted again, and is
        inspected again, and that loop may run at most twice before the budget
        override forces `SCRAP`."

        PRD.md section 3.6: "a `PASS` moves `OUTFITTED` to `SELLABLE`."

        PRD.md section 3.6: "Only the array supplied on this call participates, in
        the order given; a re-inspection replaces the previous array wholesale
        rather than merging it."

        PRD.md section 3.3: "the pre-overhead subtotal is `material_cost_cents` plus
        `oven_energy_cost_cents`, and the overhead rate is the rate of the *first*
        tier whose ceiling is at or above that subtotal — 18.00 percent up to
        500000 cents."

        The second lap carries a different kit serial, and the replacement readings
        give a variation of 1.08 percent and a final index of 0.000, so the ladder
        falls through to PASS. Only now does the order complete, at 2520 cents of
        resin plus 6000 cents of oven energy, 1534 of overhead and a unit cost equal
        to the whole total because exactly one hull counts.

        Design: Difficulty/non_linear_state_machine/finished_unit_rework_loop_edge_closed_by_logistics_axis
        """
        ctx = _p1_outfitted_single_hull()

        passed = _p1_reworked_then_resellable(ctx)

        assert passed["inspection_verdict"] == "PASS", (
            f"the replacement readings pass every clause, got {passed['inspection_verdict']}"
        )
        assert passed["build_status"] == "SELLABLE", (
            f"a PASS moves the hull to SELLABLE, got {passed['build_status']}"
        )
        assert passed["rework_count"] == 1, (
            "completing the loop does not refund the rework budget, got "
            f"{passed['rework_count']}"
        )
        assert passed["hardware_kit_serial"] == ctx["second_kit"], (
            "the second lap's kit serial is the one that survives, got "
            f"{passed['hardware_kit_serial']}"
        )
        assert_decimal_equals(passed["wall_cv_pct"], "1.08", Q_PERCENT, "wall_cv_pct")
        assert_decimal_equals(passed["wall_sd_mm"], "0.065", Q_MASS, "wall_sd_mm")
        assert_decimal_equals(
            passed["final_warpage_index"], "0.000", Q_WARPAGE, "final_warpage_index"
        )
        assert passed["logistics_status"] == "UNALLOCATED", (
            f"the logistics axis never moved, got {passed['logistics_status']}"
        )

        order = api_client.read_entity(
            "get_production_order", ctx["production_order_id"], ADMIN_HEADERS
        )
        assert order["status"] == "COMPLETE", (
            f"one completed hull satisfies an ordered_qty of 1, got {order['status']}"
        )
        assert order["completed_qty"] == 1, (
            f"the sellable hull counts once, got {order['completed_qty']}"
        )
        assert_money_equals(order["material_cost_cents"], 2520, "material_cost_cents")
        assert_money_equals(
            order["oven_energy_cost_cents"], 6000, "oven_energy_cost_cents"
        )
        assert_money_equals(order["overhead_cents"], 1534, "overhead_cents")
        assert_money_equals(order["total_cost_cents"], 10054, "total_cost_cents")
        assert_money_equals(order["unit_cost_cents"], 10054, "unit_cost_cents")

    def test_storing_the_hull_closes_the_edge_out_of_sellable_for_good(self):
        """The other axis bounds the loop: a stored hull can never be re-inspected.

        PRD.md section 3.6: "A hull whose `logistics_status` has left `UNALLOCATED`
        cannot be re-inspected at all and is refused with
        `ERR_UNIT_NOT_REINSPECTABLE`."

        PRD.md section 3.6: "Inspection requires `build_status` `OUTFITTED` (a first
        inspection) or `SELLABLE` (a re-inspection), requires `logistics_status`
        `UNALLOCATED`."

        The hull is `SELLABLE`, which is a legal state to re-inspect from, so the
        refusal can only come from the logistics axis. Storing moved that axis and
        left the build axis exactly where it was, which is what makes the loop
        bounded rather than endless.

        Design: Difficulty/non_linear_state_machine/finished_unit_rework_loop_edge_closed_by_logistics_axis
        """
        ctx = _p1_outfitted_single_hull()
        _p1_reworked_then_resellable(ctx)

        set_clock(_P1_STORE_AT)
        stored = store_unit(ctx, {"id": ctx["unit_id"]})

        assert stored["logistics_status"] == "STORED", (
            f"the logistics axis moves to STORED, got {stored['logistics_status']}"
        )
        assert stored["build_status"] == "SELLABLE", (
            f"the build axis is untouched by storing, got {stored['build_status']}"
        )
        assert stored["storage_zone_code"] == "Z-A", (
            f"the site's only zone takes the hull, got {stored['storage_zone_code']}"
        )
        assert stored["is_zone_anchor"] is True, (
            "the first hull of its model in that zone anchors the nest group"
        )
        assert_decimal_equals(
            stored["stored_footprint_cube_m3"],
            "2.0000",
            Q_CUBE,
            "an anchor pays the full gross cube",
        )

        refused = api_client.inspect_finished_unit(
            ctx["unit_id"],
            inspect_payload(wall_thickness_points=list(_P1_REWORK_POINTS)),
            ctx["inspector_headers"],
        )
        validate_error(refused, ApiErrorId.UNIT_NOT_REINSPECTABLE, expected_status=409)

        unchanged = api_client.read_entity(
            "get_finished_unit", ctx["unit_id"], PLANNER_HEADERS
        )
        assert unchanged["build_status"] == "SELLABLE", (
            f"the rejected call wrote nothing, got {unchanged['build_status']}"
        )
        assert unchanged["inspection_verdict"] == "PASS", (
            f"the earlier verdict stands, got {unchanged['inspection_verdict']}"
        )
        assert unchanged["rework_count"] == 1, (
            f"no second rework was recorded, got {unchanged['rework_count']}"
        )


_P1_FIRST_SEAL_AT = "2026-08-01T14:00:00Z"
_P1_SECOND_SEAL_AT = "2026-08-01T15:00:00Z"


def _p1_sealed_trailer_with_a_spare_hull():
    """A trailer sealed on two of three stored hulls, with the third left behind.

    One three-cavity cycle mints three hulls of the same model; two are loaded, so
    the nested cube is 3.0000 of the trailer's 5.0000 capacity — a utilisation of
    exactly 60.00 percent, which is both the seal minimum and the boundary of the
    3.00 percent discount tier. The quote is 23325: per-line 14640 plus 7320 is
    21960, less a 659 discount is 21301, plus 2024 of fuel.
    """
    ctx = setup_loaded_shipment(
        line_count=2,
        model_overrides={"nominal_charge_kg": 8.0},
        mold_overrides={"cavity_count": 3, "nominal_charge_kg": 24.0},
        order_overrides={"ordered_qty": 3},
    )
    set_clock(_P1_FIRST_SEAL_AT)
    ctx["shipment"] = validate_success(
        api_client.seal_shipment(ctx["shipment_id"], PLANNER_HEADERS), 200
    )
    ctx["spare_hull"] = ctx["stored_units"][2]
    sealed = ctx["shipment"]
    assert sealed["status"] == "SEALED", f"setup must seal, got {sealed['status']}"
    assert_instant_equals(sealed["sealed_at"], _P1_FIRST_SEAL_AT, "sealed_at")
    assert_decimal_equals(sealed["nested_cube_m3"], "3.0000", Q_CUBE, "nested_cube_m3")
    assert_decimal_equals(
        sealed["cube_utilization_pct"], "60.00", Q_PERCENT, "cube_utilization_pct"
    )
    assert_money_equals(sealed["quoted_freight_cents"], 23325, "quoted_freight_cents")
    return ctx


def _p1_read_shipment(ctx):
    return api_client.read_entity("get_shipment", ctx["shipment_id"], PLANNER_HEADERS)


def _p1_read_line(line):
    return api_client.read_entity("get_shipment_line", line["id"], PLANNER_HEADERS)


def _p1_unseal(ctx):
    return validate_success(
        api_client.unseal_shipment(
            ctx["shipment_id"], unseal_payload(), PLANNER_HEADERS
        ),
        200,
    )


class TestUnsealRevertForcesAFreshQuote:
    """The backward edge destroys the quote, and re-entering SEALED recomputes it."""

    def test_unsealing_destroys_the_quote_and_the_seal_stamp(self):
        """Nothing but the shipment moves, and the two derived fields go to null.

        PRD.md section 3.8: "**Unsealing** carries an `unseal_reason` and is
        permitted only while `departed_at` is null; it returns the shipment from
        `SEALED` to `LOADING` and clears both `quoted_freight_cents` and `sealed_at`
        to null."

        PRD.md section 3.8: "**Cube rollups** are recomputed from scratch on every
        line addition and every line removal, never patched incrementally."

        The revert is not a rollback of the load: both lines stay `LOADED` at their
        positions, both hulls stay `LOADED`, and the cube rollups are untouched
        because no line changed. Only the priced fields are destroyed.

        Design: Difficulty/non_linear_state_machine/shipment_unseal_revert_forces_requote_on_a_new_discount_tier
        """
        ctx = _p1_sealed_trailer_with_a_spare_hull()

        reverted = _p1_unseal(ctx)

        assert reverted["status"] == "LOADING", (
            f"the backward edge returns the trailer to LOADING, got {reverted['status']}"
        )
        assert reverted["quoted_freight_cents"] is None, (
            "the stale quote is destroyed rather than retained, got "
            f"{reverted['quoted_freight_cents']}"
        )
        assert reverted["sealed_at"] is None, (
            f"the seal stamp is cleared, got {reverted['sealed_at']}"
        )
        assert reverted["billed_freight_cents"] is None, (
            "nothing has been delivered, so the billed figure is still null"
        )
        assert_decimal_equals(
            reverted["nested_cube_m3"], "3.0000", Q_CUBE, "nested_cube_m3"
        )
        assert_decimal_equals(
            reverted["loaded_cube_m3"], "4.0000", Q_CUBE, "loaded_cube_m3"
        )
        assert_decimal_equals(
            reverted["cube_utilization_pct"],
            "60.00",
            Q_PERCENT,
            "cube_utilization_pct",
        )

        for expected_position, line in enumerate(ctx["shipment_lines"], start=1):
            row = _p1_read_line(line)
            assert row["status"] == "LOADED", (
                f"line {expected_position} is untouched by the unseal, got {row['status']}"
            )
            assert row["nest_position"] == expected_position, (
                "the nest sequence is unchanged, got "
                f"{row['nest_position']} at line {expected_position}"
            )
            hull = api_client.read_entity(
                "get_finished_unit", row["finished_unit_id"], PLANNER_HEADERS
            )
            assert hull["logistics_status"] == "LOADED", (
                "only the shipment moved backward, got "
                f"{hull['logistics_status']}"
            )

    def test_resealing_requotes_from_scratch_on_a_newly_selected_tier(self):
        """The same state is re-entered with a different stamp and a different quote.

        PRD.md section 3.8: "Sealing sets `quoted_freight_cents` and stamps
        `sealed_at` from the logical clock."

        PRD.md section 3.8: "A volume discount is then chosen by walking a fixed
        ordered tier list and taking the **first** row whose minimum utilisation is
        at or below the shipment's `cube_utilization_pct`: 90.00 percent utilisation
        earns 12.00 percent, 75.00 earns 7.50, 60.00 earns 3.00, and anything below
        60.00 earns 0.00. That tier is selected once, from the utilisation at seal
        time, and is never re-selected later in the computation."

        PRD.md section 3.8: "The pre-discount total is the sum of the
        **already-rounded** per-line amounts... Finally a fuel surcharge of 9.50
        percent is applied, rounded half-up, to the **discounted** base."

        PRD.md section 3.8: "Its `line_nested_cube_m3` is the full gross cube when
        its `nest_position` is 1, and `gross_cube_m3` multiplied by `nest_factor`,
        rounded to four decimals, for every position after the first."

        The third hull joins at position 3 for 1.0000 nested cube, which lifts
        utilisation from 60.00 to 80.00 and so moves the tier from 3.00 percent to
        7.50 percent. The re-seal therefore prices 29280 pre-discount, less 2196,
        plus 2573 of fuel — 29657. That is neither the 23325 it left, nor 23325 plus
        one line at 7320, nor the 31100 the old tier would have produced.

        Design: Difficulty/non_linear_state_machine/shipment_unseal_revert_forces_requote_on_a_new_discount_tier
        """
        ctx = _p1_sealed_trailer_with_a_spare_hull()
        _p1_unseal(ctx)

        third = validate_success(
            api_client.create_shipment_line(
                shipment_line_payload(
                    ctx["shipment_id"],
                    ctx["spare_hull"]["id"],
                    shipment_version(ctx["shipment_id"]),
                ),
                PLANNER_HEADERS,
            ),
            201,
        )

        assert third["nest_position"] == 3, (
            "numbering is per product model over the surviving loaded lines, got "
            f"{third['nest_position']}"
        )
        assert_decimal_equals(
            third["line_gross_cube_m3"], "2.0000", Q_CUBE, "line_gross_cube_m3"
        )
        assert_decimal_equals(
            third["line_nested_cube_m3"], "1.0000", Q_CUBE, "line_nested_cube_m3"
        )

        grown = _p1_read_shipment(ctx)
        assert_decimal_equals(grown["nested_cube_m3"], "4.0000", Q_CUBE, "nested_cube_m3")
        assert_decimal_equals(grown["loaded_cube_m3"], "6.0000", Q_CUBE, "loaded_cube_m3")
        assert_decimal_equals(
            grown["loaded_weight_kg"], "72.000", Q_MASS, "loaded_weight_kg"
        )
        assert_decimal_equals(
            grown["cube_utilization_pct"], "80.00", Q_PERCENT, "cube_utilization_pct"
        )
        assert_decimal_equals(
            grown["density_kg_per_m3"], "18.000", Q_MASS, "density_kg_per_m3"
        )
        assert grown["quoted_freight_cents"] is None, (
            "adding a line does not price anything, got "
            f"{grown['quoted_freight_cents']}"
        )

        set_clock(_P1_SECOND_SEAL_AT)
        resealed = validate_success(
            api_client.seal_shipment(ctx["shipment_id"], PLANNER_HEADERS), 200
        )

        assert resealed["status"] == "SEALED", (
            f"the same state is re-entered, got {resealed['status']}"
        )
        assert_instant_equals(
            resealed["sealed_at"], _P1_SECOND_SEAL_AT, "the second seal stamp"
        )
        assert_money_equals(
            resealed["quoted_freight_cents"], 29657, "requoted_freight_cents"
        )
        assert resealed["quoted_freight_cents"] != 23325, (
            "the pre-unseal quote must not be restored"
        )
        assert resealed["quoted_freight_cents"] != 30645, (
            "the quote must not be patched incrementally by one line's 7320"
        )
        assert resealed["quoted_freight_cents"] != 31100, (
            "the discount tier must be re-selected from the new utilisation"
        )
