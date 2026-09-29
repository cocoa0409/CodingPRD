"""Cycle window projection, floored elapsed minutes, and the mould service counter.

PRD.md section 2.8 projects a cycle's four window stamps from the scheduled
durations alone, butt-jointing the cooling window to the oven window with no gap.
PRD.md sections 3.5 and 2.4 then measure the *actual* legs by flooring whole
minutes, which is what the oven-energy line of the cost roll-up bills. The same
section 3.5 wears the tool by exactly one demould at a time and compares the
counter against the interval at-or-above, and PRD.md section 3.1 resets it to zero
rather than decrementing it.
"""

from test_helpers import (
    ADMIN_HEADERS,
    ApiErrorId,
    abort_payload,
    assert_cycle_window_projection,
    assert_elapsed_minutes_floored,
    assert_instant_equals,
    assert_money_equals,
    assert_resin_ledger_conserved,
    complete_service_payload,
    create_plant_baseline,
    create_production_order,
    create_resin_lot,
    dec,
    demold_payload,
    get_success_data,
    reserve_charge,
    run_cycle_to_cooling,
    run_cycle_to_demold,
    schedule_cycle,
    set_clock,
    validate_error,
    validate_paginated,
)


def _p5_single_cavity_plant(*, nominal_charge_kg, mold_overrides=None):
    """A plant whose only tool is single-cavity at the model's own nominal charge.

    PRD.md section 2.8 requires a tool's ``nominal_charge_kg`` to "equal the model's
    `nominal_charge_kg` multiplied by `cavity_count` and rounded to three decimals",
    so one charge of exactly the model figure clears the tolerance test.
    """
    overrides = {"cavity_count": 1, "nominal_charge_kg": nominal_charge_kg}
    overrides.update(mold_overrides or {})
    return create_plant_baseline(
        model_overrides={"nominal_charge_kg": nominal_charge_kg},
        mold_overrides=overrides,
    )


def _p5_charge_cycle(ctx, cycle, lot, **charge_overrides):
    """Attach one reserved charge to ``cycle`` and make it the context's cycle."""
    ctx["molding_cycle"] = cycle
    ctx["molding_cycle_id"] = cycle["id"]
    return reserve_charge(ctx, cycle, lot, **charge_overrides)


def test_cooling_window_is_butt_jointed_and_elapsed_minutes_are_floored(api, admin_headers):
    """A 60:59 oven leg bills 60 minutes, and a demould at 29:59 is refused.

    PRD.md section 2.8 projects the window from the scheduled durations only:
    "`oven_end_at` (`oven_start_at` advanced by `scheduled_oven_minutes`);
    `cooling_window_start_at` (equal to `oven_end_at`); `cooling_window_end_at`
    (`cooling_window_start_at` advanced by `scheduled_cooling_minutes`)".  PRD.md
    section 3.5 measures the actual legs by flooring: "`actual_oven_minutes` is
    recomputed as the floored whole minutes between `actual_oven_start_at` and
    `actual_oven_end_at`", and demoulding "requires that the floored whole minutes
    elapsed since `actual_oven_end_at` reach the model's `min_cooling_minutes`,
    equality passing, otherwise `ERR_COOLING_TIME_INSUFFICIENT` (HTTP 422)".  The
    floored figure is what the money reads: PRD.md section 3.3 bills "each
    contributes `actual_oven_minutes` multiplied by its station's
    `energy_cents_per_min`".

    Design: Corner/calculations/calc_interval_merge_butt_jointed_projection_and_floored_actual_minutes
    """
    ctx = _p5_single_cavity_plant(nominal_charge_kg=12.0)
    lot = create_resin_lot(cost_cents_per_kg=350, received_kg=100.0)
    order = create_production_order(ctx, ordered_qty=1)
    cycle = schedule_cycle(
        ctx, order, scheduled_oven_minutes=61, scheduled_cooling_minutes=32
    )

    assert_instant_equals(cycle["oven_end_at"], "2026-08-01T10:01:00Z", "oven_end_at")
    assert_instant_equals(
        cycle["cooling_window_start_at"],
        "2026-08-01T10:01:00Z",
        "cooling_window_start_at is butt-jointed to oven_end_at",
    )
    assert_instant_equals(
        cycle["cooling_window_end_at"],
        "2026-08-01T10:33:00Z",
        "cooling_window_end_at",
    )
    assert_cycle_window_projection(cycle)

    _p5_charge_cycle(ctx, cycle, lot, charge_kg=12.0, regrind_kg=1.2)
    run_cycle_to_cooling(
        ctx,
        actual_oven_start_at="2026-08-01T09:00:00Z",
        actual_oven_end_at="2026-08-01T10:00:59Z",
    )
    cooling = ctx["molding_cycle"]
    # 3659 seconds floor to 60 minutes, one short of the 61 scheduled.
    assert cooling["actual_oven_minutes"] == 60, (
        f"expected the floored 60 minutes, got {cooling['actual_oven_minutes']}"
    )
    assert_elapsed_minutes_floored(
        cooling, "actual_oven_minutes", "actual_oven_start_at", "actual_oven_end_at"
    )
    # The projection is never rewritten from the actual stamps.
    assert_instant_equals(
        cooling["oven_end_at"], "2026-08-01T10:01:00Z", "projected oven_end_at after the run"
    )

    set_clock("2026-08-01T10:30:58Z")
    validate_error(
        api.demold(
            cycle["id"],
            demold_payload("2026-08-01T10:30:58Z"),
            ctx["operator_headers"],
        ),
        ApiErrorId.COOLING_TIME_INSUFFICIENT,
    )
    unchanged = api.read_entity("get_molding_cycle", cycle["id"], admin_headers)
    assert unchanged["status"] == "COOLING", (
        f"the rejected demould changed nothing, got {unchanged['status']}"
    )
    assert unchanged["actual_cooling_end_at"] is None, (
        f"actual_cooling_end_at stays null, got {unchanged['actual_cooling_end_at']!r}"
    )
    # PRD.md section 2.8 gives actual_cooling_minutes a default of 0, so an
    # untouched cycle reports 0 rather than null.
    assert unchanged["actual_cooling_minutes"] == 0, (
        f"actual_cooling_minutes stays at its default, got {unchanged['actual_cooling_minutes']}"
    )

    set_clock("2026-08-01T10:30:59Z")
    demolded = get_success_data(
        api.demold(
            cycle["id"],
            demold_payload("2026-08-01T10:30:59Z"),
            ctx["operator_headers"],
        )
    )
    # 1800 seconds floor to exactly 30, and equality passes.
    assert demolded["status"] == "DEMOLDED", f"expected DEMOLDED, got {demolded['status']}"
    assert demolded["actual_cooling_minutes"] == 30, (
        f"expected 30 floored cooling minutes, got {demolded['actual_cooling_minutes']}"
    )

    summary = api.read_cost_summary(order["id"], admin_headers)
    assert_money_equals(summary["material_cost_cents"], 4200, "material")
    # The 61 scheduled minutes would bill 6100; the 60 floored actual minutes bill 6000.
    assert_money_equals(summary["oven_energy_cost_cents"], 6000, "oven energy")
    assert_money_equals(summary["pre_overhead_subtotal_cents"], 10200, "subtotal")
    assert dec(summary["overhead_rate_pct"]) == dec("18.00"), "overhead_rate_pct"
    assert_money_equals(summary["overhead_cents"], 1836, "overhead")
    assert_money_equals(summary["total_cost_cents"], 12036, "total")


def test_mold_service_counter_reaches_the_interval_then_resets_to_zero(api, admin_headers):
    """The counter reads 1, then 2 which flips the tool, then 0 after servicing.

    PRD.md section 3.5 wears the tool once per demould and compares at-or-above:
    "The tool moves `IN_CYCLE` to `AVAILABLE` and its `cycles_since_service` is
    incremented by 1 — only a completed demould wears a tool; an abort never does",
    and "**CASCADE-B** runs in five links: (1) when the incremented
    `cycles_since_service` has reached the tool's `service_interval_cycles`, using an
    at-or-above comparison, the tool moves `AVAILABLE` to `MAINTENANCE`; (2) because
    that tool is in `MAINTENANCE`, every *other* cycle on it in `SCHEDULED` becomes
    `ABORTED` with `abort_reason` `MOLD_SERVICE_DUE`; (3) those cycles' `RESERVED`
    charges become `RELEASED` with `released_reason` `MOLD_SERVICE_DUE`, moving
    `charge_kg` from `reserved_kg` back to `available_kg`".  PRD.md section 3.1 makes
    the reset total: "Completing service requires `status` `MAINTENANCE`, may carry a
    `service_note`, resets `cycles_since_service` to zero — a full reset, never a
    decrement by the interval, so a serviced tool with a hundred lifetime demoulds
    reads 0 — and returns `status` to `AVAILABLE`, restoring the tool to the selection
    pool."  The same section confirms the abort case: "an abort returns it `IN_CYCLE`
    to `AVAILABLE` without wearing it."

    Design: Corner/calculations/calc_threshold_mold_service_counter_reaches_interval_then_full_reset
    """
    ctx = _p5_single_cavity_plant(
        nominal_charge_kg=15.0, mold_overrides={"service_interval_cycles": 2}
    )
    mold_id = ctx["mold_id"]
    lot = create_resin_lot(received_kg=300.0)
    # floor(4 * 1.20) = 4 hulls may be built, so three cycles fit under the ceiling.
    order = create_production_order(ctx, ordered_qty=4)

    first = schedule_cycle(ctx, order)
    _p5_charge_cycle(ctx, first, lot, charge_kg=15.0, regrind_kg=1.5)
    run_cycle_to_demold(
        ctx,
        actual_oven_start_at="2026-08-01T09:00:00Z",
        actual_oven_end_at="2026-08-01T10:00:00Z",
        actual_cooling_end_at="2026-08-01T10:35:00Z",
    )

    after_one = api.read_entity("get_mold", mold_id, admin_headers)
    assert after_one["cycles_since_service"] == 1, (
        f"one demould increments by exactly 1, got {after_one['cycles_since_service']}"
    )
    assert after_one["status"] == "AVAILABLE", (
        f"1 is below the interval 2, got {after_one['status']}"
    )

    second = schedule_cycle(ctx, order, oven_start_at="2026-08-01T11:00:00Z")
    _p5_charge_cycle(ctx, second, lot, charge_kg=15.0, regrind_kg=1.5)
    third = schedule_cycle(ctx, order, oven_start_at="2026-08-01T14:00:00Z")
    third_charge = _p5_charge_cycle(ctx, third, lot, charge_kg=15.0, regrind_kg=1.5)

    ctx["molding_cycle"] = second
    ctx["molding_cycle_id"] = second["id"]
    run_cycle_to_demold(
        ctx,
        actual_oven_start_at="2026-08-01T11:00:00Z",
        actual_oven_end_at="2026-08-01T12:00:00Z",
        actual_cooling_end_at="2026-08-01T12:35:00Z",
    )

    at_interval = api.read_entity("get_mold", mold_id, admin_headers)
    assert at_interval["cycles_since_service"] == 2, (
        f"the second demould reads 2, got {at_interval['cycles_since_service']}"
    )
    assert at_interval["status"] == "MAINTENANCE", (
        "reaching the interval exactly is enough under an at-or-above comparison; "
        f"a strict greater-than would still read AVAILABLE, got {at_interval['status']}"
    )

    aborted = api.read_entity("get_molding_cycle", third["id"], admin_headers)
    assert aborted["status"] == "ABORTED", (
        f"the tool's other SCHEDULED cycle is swept, got {aborted['status']}"
    )
    assert aborted["abort_reason"] == "MOLD_SERVICE_DUE", (
        f"expected MOLD_SERVICE_DUE, got {aborted['abort_reason']!r}"
    )
    released = api.read_entity("get_resin_charge", third_charge["id"], admin_headers)
    assert released["status"] == "RELEASED", f"expected RELEASED, got {released['status']}"
    assert released["released_reason"] == "MOLD_SERVICE_DUE", (
        f"expected MOLD_SERVICE_DUE, got {released['released_reason']!r}"
    )

    ledger = api.read_entity("get_resin_lot", lot["id"], admin_headers)
    assert dec(ledger["consumed_kg"]) == dec("30.000"), "two demoulded shots are consumed"
    assert dec(ledger["reserved_kg"]) == dec("0.000"), "the swept charge left reserved_kg"
    assert dec(ledger["available_kg"]) == dec("270.000"), "the swept 15.000 kg came back"
    assert_resin_ledger_conserved(ledger)

    serviced = get_success_data(
        api.complete_service_mold(
            mold_id,
            complete_service_payload("two-cycle interval reached, tool cleaned and re-waxed"),
            ADMIN_HEADERS,
        )
    )
    assert serviced["cycles_since_service"] == 0, (
        f"servicing is a full reset to zero, got {serviced['cycles_since_service']}"
    )
    assert serviced["status"] == "AVAILABLE", f"expected AVAILABLE, got {serviced['status']}"

    demolded_rows, _meta = validate_paginated(
        api.list_molding_cycles({"mold_id": mold_id, "status": "DEMOLDED"}, admin_headers)
    )
    assert len(demolded_rows) == 2, (
        "the counter is stored state with an explicit reset, not a count derived from "
        f"cycle history, which still holds 2 demoulded cycles, got {len(demolded_rows)}"
    )

    # The tool left MAINTENANCE, so it re-enters the selection pool.
    fourth = schedule_cycle(ctx, order, oven_start_at="2026-08-01T16:00:00Z")
    assert fourth["mold_id"] == mold_id, (
        f"the serviced tool is selected again, got {fourth['mold_id']!r}"
    )
    _p5_charge_cycle(ctx, fourth, lot, charge_kg=15.0, regrind_kg=1.5)
    get_success_data(
        api.abort_molding_cycle(
            fourth["id"], abort_payload("OPERATOR_ABORT"), ctx["operator_headers"]
        )
    )

    after_abort = api.read_entity("get_mold", mold_id, admin_headers)
    assert after_abort["cycles_since_service"] == 0, (
        f"an aborted cycle never wears the tool, got {after_abort['cycles_since_service']}"
    )
    assert after_abort["status"] == "AVAILABLE", f"expected AVAILABLE, got {after_abort['status']}"

    final_ledger = api.read_entity("get_resin_lot", lot["id"], admin_headers)
    assert dec(final_ledger["consumed_kg"]) == dec("30.000"), "consumed_kg is never reversed"
    assert dec(final_ledger["reserved_kg"]) == dec("0.000"), "the aborted charge is released"
    assert dec(final_ledger["available_kg"]) == dec("270.000"), "available_kg is restored"
    assert_resin_ledger_conserved(final_ledger)
