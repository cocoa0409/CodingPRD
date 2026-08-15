"""Production-order lifecycle: cross-entity confirm gates, validation-order
priority, half-open machine windows, the parallel quality-hold dimension,
and cancellation compensation."""
from test_helpers import (
    LAB_SLOT_B,
    PLANT,
    QUALITY,
    SALES,
    ApiErrorId,
    approve_spec,
    assert_program_stock_invariant,
    cancel_order,
    complete_order,
    confirm_order,
    create_approved_spec,
    create_locked_cnc_program,
    create_locked_die_program,
    create_quoted_order,
    create_validated_spec,
    get_order,
    get_program,
    get_spec,
    get_tooling,
    start_order,
    validate_error,
    validate_success,
    create_active_program,
)


def _validated_spec_with_locked_die_program():
    """Spec VALIDATED (not yet approved) + LOCKED DIE program + IN_SERVICE
    tooling + one QUOTED order."""
    customer, material, spec = create_validated_spec()
    program, tooling = create_locked_die_program(spec["id"])
    order = create_quoted_order(spec["id"], program["id"], 500)
    return customer, material, spec, program, tooling, order


def test_confirm_rejected_while_spec_not_approved(api):
    """PRD §3.5: "The specification must be `APPROVED`, or the confirm is
    rejected with `ERR_SPEC_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_spec_approved
    """
    _c, _m, spec, _p, _t, order = _validated_spec_with_locked_die_program()
    assert get_spec(spec["id"])["status"] == "VALIDATED"

    resp = api.confirm_production_order(
        order["id"],
        {"machine_id": "DIE-1",
         "window_start": "2026-08-03T08:00:00Z",
         "window_end": "2026-08-03T09:00:00Z"},
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_SPEC_NOT_APPROVED)
    assert get_order(order["id"])["fab_status"] == "QUOTED"


def test_confirm_succeeds_once_spec_approved(api):
    """PRD §3.5: "The specification must be `APPROVED`, or the confirm is
    rejected with `ERR_SPEC_NOT_APPROVED` (HTTP 409)." PRD §3.5:
    "Confirmation reprices the order with the final variant — the locked
    program's actual `parts_per_sheet` and the tooling's current remaining
    unamortized cents — setting `final_unit_price_cents` and
    `final_total_cents` by the shared recipe and pinned rounding."

    Design: Difficulty/cross_entity_state_dependency/confirm_requires_spec_approved
    """
    customer, _m, spec, _p, _t, order = _validated_spec_with_locked_die_program()
    approve_spec(spec["id"], customer["id"])

    confirmed = confirm_order(order["id"])
    assert confirmed["fab_status"] == "CONFIRMED"
    assert confirmed["final_unit_price_cents"] == 730
    assert confirmed["final_total_cents"] == 370000


def test_confirm_state_failure_masks_machine_window_conflict(api):
    """PRD §2.5: "Every request is validated against the following pipeline,
    evaluated in this order; the first failing check rejects the request, so
    an earlier failure masks every later check." PRD §3.5: "The
    specification must be `APPROVED`, or the confirm is rejected with
    `ERR_SPEC_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/confirm_spec_not_approved_beats_machine_conflict
    """
    # Spec A: VALIDATED only, with a QUOTED order.
    customer, material, spec_a, _pa, _ta, order_a = (
        _validated_spec_with_locked_die_program()
    )

    # Spec B: fully approved, with an order CONFIRMED onto CNC-1 08:00-09:00.
    # Its validation booking uses the second lab slot to respect the buffer.
    _cb, _mb, spec_b = create_approved_spec(
        customer=customer, material=material, part_name="Tray B",
        lab_slot=LAB_SLOT_B,
    )
    program_b, _tooling_b = create_locked_die_program(spec_b["id"])
    order_b = create_quoted_order(spec_b["id"], program_b["id"], 500)
    confirm_order(order_b["id"], "CNC-1",
                  "2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z")

    # Confirming order A with a window that overlaps order B's booking must
    # report the state failure, not the temporal one.
    resp = api.confirm_production_order(
        order_a["id"],
        {"machine_id": "CNC-1",
         "window_start": "2026-08-05T08:30:00Z",
         "window_end": "2026-08-05T09:30:00Z"},
        SALES,
    )
    err = validate_error(resp, ApiErrorId.ERR_SPEC_NOT_APPROVED)
    assert err["error_id"] != ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT


def test_confirm_machine_conflict_reported_when_state_gates_pass(api):
    """PRD §3.5: "And the requested machine window — `machine_id` with
    `window_start` and `window_end` — must clear the overlap rule of §2.8, or
    the confirm is rejected with `ERR_MACHINE_WINDOW_CONFLICT`." PRD §2.8:
    "An overlap is rejected with `ERR_MACHINE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/confirm_spec_not_approved_beats_machine_conflict
    """
    customer, material, spec = create_approved_spec()
    program, _tooling = create_locked_die_program(spec["id"])
    order_a = create_quoted_order(spec["id"], program["id"], 500)
    confirm_order(order_a["id"], "CNC-1",
                  "2026-08-05T08:00:00Z", "2026-08-05T09:00:00Z")

    order_b = create_quoted_order(spec["id"], program["id"], 500)
    resp = api.confirm_production_order(
        order_b["id"],
        {"machine_id": "CNC-1",
         "window_start": "2026-08-05T08:30:00Z",
         "window_end": "2026-08-05T09:30:00Z"},
        SALES,
    )
    # Spec APPROVED, program LOCKED, tooling IN_SERVICE: only the temporal
    # conflict can fire here.
    validate_error(resp, ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT)


def _cnc_setup_with_three_quotes():
    customer, material, spec = create_approved_spec()
    program = create_locked_cnc_program(spec["id"], machine_seconds_per_part=40)
    orders = [create_quoted_order(spec["id"], program["id"], 100) for _ in range(3)]
    return spec, program, orders


def test_machine_window_back_to_back_adjacency_allowed(api):
    """PRD §2.8: "The new window must not overlap the window of any
    non-cancelled order on the same machine; because the intervals are
    half-open, two windows that merely touch — one ending exactly when the
    next begins — are allowed."

    Design: Difficulty/resource_temporal_overlap/machine_window_half_open_adjacency
    """
    _s, _p, (o1, o2, _o3) = _cnc_setup_with_three_quotes()
    c1 = confirm_order(o1["id"], "CNC-1",
                       "2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
    assert c1["fab_status"] == "CONFIRMED"
    # start == prior end is legal under half-open semantics.
    c2 = confirm_order(o2["id"], "CNC-1",
                       "2026-08-03T09:00:00Z", "2026-08-03T10:00:00Z")
    assert c2["fab_status"] == "CONFIRMED"


def test_machine_window_strict_overlap_rejected(api):
    """PRD §2.8: "An overlap is rejected with `ERR_MACHINE_WINDOW_CONFLICT`
    (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/machine_window_half_open_adjacency
    """
    _s, _p, (o1, _o2, o3) = _cnc_setup_with_three_quotes()
    confirm_order(o1["id"], "CNC-1",
                  "2026-08-03T08:00:00Z", "2026-08-03T09:00:00Z")
    resp = api.confirm_production_order(
        o3["id"],
        {"machine_id": "CNC-1",
         "window_start": "2026-08-03T08:30:00Z",
         "window_end": "2026-08-03T09:30:00Z"},
        SALES,
    )
    validate_error(resp, ApiErrorId.ERR_MACHINE_WINDOW_CONFLICT)
    assert get_order(o3["id"])["fab_status"] == "QUOTED"


def _in_progress_die_order():
    customer, material, spec = create_approved_spec()
    program, tooling = create_locked_die_program(spec["id"])
    order = create_quoted_order(spec["id"], program["id"], 500)
    confirm_order(order["id"])
    start_order(order["id"])
    return spec, program, tooling, get_order(order["id"])


def test_hold_is_independent_of_fab_status_and_blocks_completion(api):
    """PRD §3.5: "Each order carries `quality_hold` — `NONE` or `ON_HOLD` —
    evolving independently of `fab_status`." PRD §3.5: "Completion moves it
    from `IN_PROGRESS` to `COMPLETED` and is gated on quality: `quality_hold`
    must be `NONE`, or the completion is rejected with `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/production_order_parallel_hold_dimension
    """
    _s, _p, _t, order = _in_progress_die_order()
    held = validate_success(api.hold_production_order(order["id"], QUALITY))
    assert held["quality_hold"] == "ON_HOLD"
    assert held["fab_status"] == "IN_PROGRESS", (
        "the hold dimension evolves without moving fab_status"
    )

    resp = api.complete_production_order(order["id"], PLANT)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_release_hold_then_complete_and_hold_requires_fab_state(api):
    """PRD §3.5: "Releasing the hold returns `quality_hold` from `ON_HOLD` to
    `NONE`." PRD §3.5: "A `QualityEngineer` may place a hold, moving
    `quality_hold` from `NONE` to `ON_HOLD`, only while `fab_status` is
    `CONFIRMED` or `IN_PROGRESS`; while a hold stands, completion is blocked
    as described above."

    Design: Difficulty/non_linear_state_machine/production_order_parallel_hold_dimension
    """
    _s, _p, _t, order = _in_progress_die_order()
    validate_success(api.hold_production_order(order["id"], QUALITY))
    released = validate_success(api.release_hold_production_order(order["id"], QUALITY))
    assert released["quality_hold"] == "NONE"
    completed = complete_order(order["id"])
    assert completed["fab_status"] == "COMPLETED"

    # A hold cannot be placed on a merely QUOTED order.
    _c2, _m2, spec2 = create_approved_spec(lab_slot=LAB_SLOT_B)
    program2, _t2 = create_locked_die_program(spec2["id"])
    quoted = create_quoted_order(spec2["id"], program2["id"], 100)
    resp = api.hold_production_order(quoted["id"], QUALITY)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


def test_confirm_charges_die_amortization(api):
    """PRD §3.5: "For `DIE_CUT`, confirmation also charges the die: the
    order's `tooling_amort_cents` is the smaller of the remaining unamortized
    cents and the per-part amortization component times the smaller of the
    order `qty` and `amortization_qty`, and the tooling's `amortized_cents`
    increases by the charged amount."

    Design: Difficulty/compensating_invariant/confirm_cancel_conserves_tooling_amortization
    """
    _c, _m, spec = create_approved_spec()
    program, tooling = create_locked_die_program(spec["id"])
    order = create_quoted_order(spec["id"], program["id"], 500)
    confirmed = confirm_order(order["id"])
    assert confirmed["tooling_amort_cents"] == 125000
    assert get_tooling(tooling["id"])["amortized_cents"] == 125000


def test_cancel_returns_die_amortization(api):
    """PRD §3.5: "Cancelling a confirmed die-cut order compensates: the
    tooling's `amortized_cents` is reduced by the order's
    `tooling_amort_cents`, and the machine window is freed." PRD §3.5:
    "Cancellation, by a `SalesEngineer`, is available from `QUOTED` or
    `CONFIRMED`; the system also cancels an order in either of those states
    when its cut program is obsoleted."

    Design: Difficulty/compensating_invariant/confirm_cancel_conserves_tooling_amortization
    """
    _c, _m, spec = create_approved_spec()
    program, tooling = create_locked_die_program(spec["id"])
    order = create_quoted_order(spec["id"], program["id"], 500)
    confirm_order(order["id"])
    assert get_tooling(tooling["id"])["amortized_cents"] == 125000

    cancelled = cancel_order(order["id"])
    assert cancelled["fab_status"] == "CANCELLED"
    tooling_after = get_tooling(tooling["id"])
    assert tooling_after["amortized_cents"] == 0, (
        "amortized_cents == sum of tooling_amort_cents over non-CANCELLED "
        "orders; cancelling the only confirmed order returns it to 0"
    )


def test_replenishment_complete_credits_program_stock(api):
    """PRD §3.5: "Completing a `REPLENISHMENT` order credits its inventory
    program — the program's `produced_qty` and `on_hand_qty` each increase by
    the order `qty`." PRD §3.6: "A `PlantManager` may request replenishment
    of an `ACTIVE` program — anything else is rejected with
    `ERR_PROGRAM_NOT_ACTIVE` (HTTP 409) — with a caller-supplied `qty`; the
    system selects the cut program for the order as the specification's
    `LOCKED` program that was most recently updated, breaking ties by the
    earliest `created_at` and never by identifier, and creates a production
    order with `order_kind` of `REPLENISHMENT`, the program's
    `inventory_program_id` set, and `fab_status` of `QUOTED`."

    Design: Corner/state_machines/replenishment_complete_credits_program_stock
    """
    customer, material, spec = create_approved_spec()
    create_locked_cnc_program(spec["id"])
    program = create_active_program(customer["id"], spec["id"],
                                    max_stock_qty=500, reorder_point_qty=100,
                                    min_release_qty=50)

    order = validate_success(api.replenish_program(program["id"], 300, PLANT), 201)
    assert order["order_kind"] == "REPLENISHMENT"
    assert order["inventory_program_id"] == program["id"]
    assert order["fab_status"] == "QUOTED"

    confirm_order(order["id"], "CNC-1",
                  "2026-08-04T08:00:00Z", "2026-08-04T09:00:00Z")
    start_order(order["id"])
    completed = complete_order(order["id"])
    assert completed["fab_status"] == "COMPLETED"

    program_after = get_program(program["id"])
    assert program_after["produced_qty"] == 300
    assert program_after["on_hand_qty"] == 300
    assert_program_stock_invariant(program_after)
