"""Non-linear lifecycle paths.

The pick step forks and rejoins, an order's routing dimension re-enters a state
it already left, a node walks its whole posture cycle, and the order's two
status dimensions advance independently of one another.
"""

import pytest

from test_helpers import (
    PLANNER,
    accept,
    api_client,
    commit_routing,
    create_routing_run_payload,
    find_assignment_lines,
    find_assignments,
    find_notifications,
    find_windows,
    line_pick,
    make_store_associate_headers,
    pack,
    pick_full,
    pick_payload,
    pick_units,
    pickup_version,
    read_assignment,
    read_assignment_line,
    read_inventory,
    read_order,
    read_order_line,
    read_pickup,
    read_store,
    register_node,
    reject,
    set_clock,
    setup_committed_assignment,
    setup_deactivated_node,
    setup_multi_node_order,
    ship,
    ship_payload,
    stock_inventory,
    validate_success,
)

# ======================================================================
# Instance 1 preamble — one three-unit allocation held by S3, accepted
# ======================================================================


def _setup_short_pick_fork() -> dict:
    """S3 (created first, ATP 3) and S1 (ATP 10); a GROUND zone-4 order for
    three units of SKU-A that S3 covers on its own, accepted at 09:05."""
    ctx = setup_multi_node_order(
        node_stock=[("S3", 5, 2), ("S1", 12, 2)],
        sku_preset="SKU-A",
        quantity=3,
        destination_zone=4,
        service_level="GROUND",
        order_code="O-3001",
        customer_ref="C-4",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
        clock="2026-08-03T09:00:00Z",
        packaging=[("S3", "MEDIUM_BOX", 20)],
    )
    assert list(ctx["assignments"]) == ["S3"], (
        "the full-coverage waterfall should place all three units at S3 alone, got "
        f"{list(ctx['assignments'])}"
    )
    store_s3 = ctx["stores"]["S3"]
    assignment = ctx["assignments"]["S3"]
    set_clock("2026-08-03T09:05:00Z")
    accept(assignment["id"], store_s3["id"])
    ctx["assignment"] = read_assignment(assignment["id"])
    ctx["assignment_line"] = find_assignment_lines(assignment["id"])[0]
    return ctx


def _short_pick_two_of_three_then_pack(ctx: dict) -> None:
    pick_units(ctx["assignment"]["id"], ctx["stores"]["S3"]["id"], {0: 2})
    pack(ctx["assignment"]["id"], ctx["stores"]["S3"]["id"], "MEDIUM_BOX")


def test_short_pick_forks_to_short_picked_then_rejoins_at_packed():
    """PRD §3.5: "When `picked_units` is at least 1 but strictly below `assigned_units` the assignment moves `ACCEPTED → SHORT_PICKED` instead: `picked_at` and `picked_units` are set as before, `shortfall_units` becomes `assigned_units` minus `picked_units`, each line's `units_picked` is set from `line_picks` and its `units_cancelled` becomes its `units_assigned` minus its `units_picked`, and the shortfall triggers the release cascade described in §3.7."
    PRD §3.5: "From either `PICKED` or `SHORT_PICKED`, the associate records packing with the `package_type` actually used, moving the assignment to `PACKED`."
    PRD §3.5: "It is stamped with the `epoch` of its node's open window and with `assigned_units`, the unit count allocated at creation, which is immutable afterwards."

    Design: Difficulty/non_linear_state_machine/assignment_short_pick_fork_rejoins_at_packed
    """
    ctx = _setup_short_pick_fork()
    store_id = ctx["stores"]["S3"]["id"]
    assignment_id = ctx["assignment"]["id"]
    line_id = ctx["assignment_line"]["id"]

    picked = validate_success(
        api_client.pick_assignment(
            assignment_id,
            pick_payload(2, [line_pick(line_id, 2)]),
            make_store_associate_headers(store_id),
        )
    )
    assert picked["status"] == "SHORT_PICKED", (
        "picking 2 of 3 units must take the SHORT_PICKED arm of the fork, got "
        f"{picked['status']}"
    )
    assert picked["picked_units"] == 2, "picked_units is stored from the pick payload"
    assert picked["shortfall_units"] == 1, (
        "shortfall_units is assigned_units minus picked_units"
    )
    assert picked["assigned_units"] == 3, "assigned_units is immutable after creation"

    packed = validate_success(
        api_client.pack_assignment(
            assignment_id,
            {"package_type": "MEDIUM_BOX"},
            make_store_associate_headers(store_id),
        )
    )
    assert packed["status"] == "PACKED", (
        "the SHORT_PICKED arm rejoins the linear path at PACKED, got "
        f"{packed['status']}"
    )
    assert packed["picked_units"] == 2, "packing does not rewrite picked_units"
    assert packed["shortfall_units"] == 1, "packing does not clear the shortfall"
    assert packed["assigned_units"] == 3, "packing does not rewrite assigned_units"

    assignment_line = read_assignment_line(line_id)
    assert assignment_line["units_picked"] == 2, (
        "the line's units_picked comes from line_picks"
    )
    assert assignment_line["units_cancelled"] == 1, (
        "the line's units_cancelled is units_assigned minus units_picked"
    )


def test_short_pick_reroutes_only_the_shortfall_to_a_replacement_assignment():
    """PRD §3.7: "Its cascade releases only the shortfall: the shortfall raises the served demand lines' `open_units`, the node's inventory `reserved_units` for the shortfall SKUs decreases with `available_to_promise_units` recomputed, its `units_committed_epoch` decreases by `shortfall_units`, and a system reroute run at `mode` `COMMIT` and `initiated_by` `SYSTEM_REROUTE` is created covering only the shortfall units and excluding this node."
    PRD §3.5: "`reroute_generation` is 0 for an assignment born of a planner run and one greater than its predecessor's for each system reroute that produced it."
    PRD §3.7: "Read against the workflows above, that rule says a rejection whose reroute succeeded notifies `REJECTION_REROUTED`, one whose reroute stranded units at the three-split ceiling notifies `DC_FALLBACK`, and one whose reroute found nothing notifies `UNROUTABLE`; a short pick behaves identically with `SHORT_PICK_REROUTED` in place of `REJECTION_REROUTED`."
    PRD §3.7: "It carries a `channel` of `EMAIL` or `SMS`, defaulting to `EMAIL`, a `units_affected` count of the units the event moved or removed, a `sent_at_utc` clock instant, and a `body_summary` — a templated one-line summary containing the order's `order_code`, the `notification_type` and the `units_affected` count."
    PRD §3.7: "A notification records the `order_id` it concerns and, for assignment-level events, the `assignment_id` that triggered it; for order-level events `assignment_id` is null."
    PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."
    PRD §3.4: "A successful run re-derives the order's `routing_status`, recomputes `split_count` — the number of the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — recomputes `provisional_cost_cents`, `dc_baseline_cost_cents` and `cost_index_bps`, and increments the order's `version`."
    PRD §3.4: "`reroute_attempt_count` counts the order's runs whose `initiated_by` is `SYSTEM_REROUTE` or `SYSTEM_DEACTIVATION`."

    Design: Difficulty/non_linear_state_machine/assignment_short_pick_fork_rejoins_at_packed
    """
    ctx = _setup_short_pick_fork()
    _short_pick_two_of_three_then_pack(ctx)

    replacements = find_assignments(
        order_id=ctx["order"]["id"], store_id=ctx["stores"]["S1"]["id"]
    )
    assert len(replacements) == 1, (
        "the shortfall reroute should create exactly one replacement assignment at S1, "
        f"got {len(replacements)}"
    )
    replacement = replacements[0]
    assert replacement["store_id"] == ctx["stores"]["S1"]["id"], (
        "the reroute excluded the short-picking node, so S1 must own the replacement"
    )
    assert replacement["status"] == "ASSIGNED", (
        "a freshly created replacement assignment starts at ASSIGNED"
    )
    assert replacement["assigned_units"] == 1, (
        "the reroute covers only the one shortfall unit"
    )
    assert replacement["reroute_generation"] == 1, (
        "the replacement is one generation past the short-picked assignment"
    )

    short_pick_notes = [
        note
        for note in find_notifications(order_id=ctx["order"]["id"])
        if note["notification_type"] == "SHORT_PICK_REROUTED"
    ]
    assert len(short_pick_notes) == 1, (
        "a short pick whose reroute created a replacement emits exactly one "
        f"SHORT_PICK_REROUTED notification, got {len(short_pick_notes)}"
    )
    assert short_pick_notes[0]["units_affected"] == 1, (
        "units_affected counts the one unit the shortfall moved"
    )
    assert short_pick_notes[0]["assignment_id"] == ctx["assignment"]["id"], (
        "the notification names the assignment that triggered it"
    )

    line = read_order_line(ctx["line"]["id"])
    assert line["assigned_units"] == 3, (
        "the replacement re-covers the released unit, so all three units are assigned"
    )
    assert line["open_units"] == 0, "no open unit remains after the reroute"

    order = read_order(ctx["order"]["id"])
    assert order["routing_status"] == "ROUTED", (
        "covered units plus cancelled units equals total_units, so the order settles "
        f"back on ROUTED, got {order['routing_status']}"
    )
    assert order["reroute_attempt_count"] == 1, (
        "the one SYSTEM_REROUTE run is counted once"
    )
    assert order["split_count"] == 2, (
        "both the packed assignment and its replacement are neither REJECTED nor "
        "CANCELLED"
    )


def test_short_pick_holds_the_picked_units_and_reprices_both_nodes():
    """PRD §3.1: "A row's `reserved_units` is always the sum, over the assignment lines whose owning assignment belongs to this node and whose served demand line references this SKU, of that line's `units_assigned` minus its `units_cancelled`, counting only assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."
    PRD §3.1: "`available_to_promise_units` is recomputed from the formula above whenever `reserved_units` moves, whenever the row is adjusted, and at row creation."
    PRD §2.9: "A node's `reserved_labor_minutes` equals the sum of `labor_minutes_reserved` over that node's assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."
    PRD §3.5: "Crucially, `labor_minutes_reserved` is *not* rewritten on a short pick — the labour standard was already committed — and only the final cost variant reflects the units actually picked."
    PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
    PRD §3.8: "The **provisional** variant, kept live in `provisional_cost_cents` after every routing change and every assignment status change, includes the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — that is, the five non-terminal statuses plus `SHIPPED` — using each one's `provisional_cost_cents`."
    PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."
    PRD §3.8: "The order's `cost_index_bps` uses `final_cost_cents` once that is set and `provisional_cost_cents` before then."
    PRD §3.3: "`eligibility_score` is the routing-time score, recomputed whenever the node's reservation levels change — on a routing-run commit, an accept, a reject, a cancel, a pick shortfall or a ship — on reactivation, on an inventory adjustment, on a posture adjustment, and at the final step of the operations run."
    PRD §3.3: "The score is the sum of three components, each rounded half-up to four decimal places, with the sum then rounded half-up to two decimal places."
    PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."

    Design: Difficulty/non_linear_state_machine/assignment_short_pick_fork_rejoins_at_packed
    """
    ctx = _setup_short_pick_fork()
    _short_pick_two_of_three_then_pack(ctx)

    inventory_s3 = read_inventory(ctx["inventories"]["S3"]["id"])
    assert inventory_s3["reserved_units"] == 2, (
        "the short-picking node still reserves the two units it holds at PACKED, got "
        f"{inventory_s3['reserved_units']}"
    )
    assert inventory_s3["available_to_promise_units"] == 1, (
        "on_hand 5 minus reserved 2 minus safety 2 leaves one promise-able unit"
    )

    store_s3 = read_store(ctx["stores"]["S3"]["id"])
    assert store_s3["reserved_labor_minutes"] == pytest.approx(16.00, abs=0.01), (
        "the committed labour standard of 16 minutes survives the shortfall, got "
        f"{store_s3['reserved_labor_minutes']}"
    )

    short_picked = read_assignment(ctx["assignment"]["id"])
    assert short_picked["provisional_cost_cents"] == 1065, (
        "the provisional variant keeps charging the three assigned units, got "
        f"{short_picked['provisional_cost_cents']}"
    )
    replacement = find_assignments(
        order_id=ctx["order"]["id"], store_id=ctx["stores"]["S1"]["id"]
    )[0]
    assert replacement["provisional_cost_cents"] == 1145, (
        "the one-unit replacement is priced on S1's standards, got "
        f"{replacement['provisional_cost_cents']}"
    )

    order = read_order(ctx["order"]["id"])
    assert order["provisional_cost_cents"] == 2586, (
        "both live assignments plus the split penalty, the one reroute overhead and "
        f"the network fee, got {order['provisional_cost_cents']}"
    )
    assert order["cost_index_bps"] == 11701, (
        "the index compares the provisional store cost with the DC baseline, got "
        f"{order['cost_index_bps']}"
    )

    store_s1 = read_store(ctx["stores"]["S1"]["id"])
    assert store_s1["eligibility_score"] == pytest.approx(70.86, abs=0.01), (
        "the rerouted-to node is rescored from its new reservation levels, got "
        f"{store_s1['eligibility_score']}"
    )


# ======================================================================
# Instance 2 preamble — a rejected sole node leaves the order at ROUTING
# ======================================================================


def _setup_routing_status_cycle() -> dict:
    """S3 alone covers a two-unit order; the associate rejects, the immediate
    reroute finds nothing, and only then is a second node stood up."""
    ctx = setup_committed_assignment(
        node_preset="S3",
        sku_preset="SKU-A",
        on_hand_units=5,
        safety_stock_units=2,
        quantity=2,
        destination_zone=4,
        service_level="GROUND",
        order_code="O-3002",
        customer_ref="C-5",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
        clock="2026-08-03T09:00:00Z",
        with_packaging=False,
        with_pickup=False,
    )
    assert ctx["order"]["routing_status"] == "ROUTED", (
        "the committing run should cover both units, got "
        f"{ctx['order']['routing_status']}"
    )
    set_clock("2026-08-03T09:05:00Z")
    reject(ctx["assignment"]["id"], ctx["store"]["id"], "LABOR_UNAVAILABLE")
    ctx["store_s5"] = register_node("S5")
    ctx["inventory_s5"] = stock_inventory(ctx["store_s5"]["id"], ctx["sku"]["id"], 10, 0)
    ctx["order_in_cycle"] = read_order(ctx["order"]["id"])
    return ctx


def test_order_routing_status_returns_to_routing_then_back_to_routed():
    """PRD §3.2: "`routing_status` — one of `UNROUTED`, `ROUTING`, `ROUTED`, `PARTIALLY_ROUTED` or `UNROUTABLE` — describes whether the network has coverage for the demand, and it is cyclic: an order that has reached `ROUTED` returns to `ROUTING` when a node fails and settles back on `ROUTED` once the reroute re-covers the units."
    PRD §3.4: "`ROUTED → ROUTING` happens when an assignment of the order reaches `REJECTED`, `SHORT_PICKED` or `CANCELLED`, open units remain after the release, the immediate system reroute run came back with `status` `NO_ELIGIBLE_NODE`, and the order's `reroute_attempt_count` is still below the two-attempt limit; the order is then queued for a retry at the operations run."
    PRD §3.4: "From `ROUTING`, a retry (or a planner `COMMIT` run) that covers every open unit returns the order to `ROUTED`, creating replacement assignments, raising `reroute_attempt_count` and recomputing the cost fields; a retry that covers some but not all open units lands on `PARTIALLY_ROUTED`, with the covered units assigned and the rest either staying open or becoming `dc_fallback_units` once `reroute_attempt_count` has reached the two-attempt limit; and a retry that finds no eligible node while `reroute_attempt_count` reaches that limit and no store-covered unit remains on the order lands on `UNROUTABLE`, turning the remaining open units into `dc_fallback_units` and emitting a `DC_FALLBACK` notification."
    PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."
    PRD §3.7: "An associate may reject an assignment from either `ASSIGNED` or `ACCEPTED`, supplying a `reject_reason_code` of `NO_STOCK_ON_FLOOR`, `LABOR_UNAVAILABLE`, `DAMAGED_UNITS` or `STORE_CLOSED`."
    PRD §3.7: "Rejection sets `status` to `REJECTED`, stores the `reject_reason_code`, and sets every assignment line's `units_cancelled` equal to its `units_assigned`."
    PRD §3.4: "`reroute_attempt_count` counts the order's runs whose `initiated_by` is `SYSTEM_REROUTE` or `SYSTEM_DEACTIVATION`."

    Design: Difficulty/non_linear_state_machine/order_routing_status_cycles_routed_to_routing_and_back_to_routed
    """
    ctx = _setup_routing_status_cycle()

    mid_cycle = ctx["order_in_cycle"]
    assert mid_cycle["routing_status"] == "ROUTING", (
        "with two units open, one REJECTED assignment and the immediate reroute empty, "
        f"the order re-enters ROUTING, got {mid_cycle['routing_status']}"
    )
    assert mid_cycle["reroute_attempt_count"] == 1, (
        "the failed system reroute counts as the first attempt"
    )

    rejected = read_assignment(ctx["assignment"]["id"])
    assert rejected["status"] == "REJECTED", "the rejected assignment is terminal"
    assert rejected["reject_reason_code"] == "LABOR_UNAVAILABLE", (
        "rejection stores the supplied reject_reason_code"
    )

    commit_routing(ctx["order"]["id"])

    recovered = read_order(ctx["order"]["id"])
    assert recovered["routing_status"] == "ROUTED", (
        "a COMMIT run that covers every open unit settles the order back on ROUTED, "
        f"got {recovered['routing_status']}"
    )
    assert recovered["reroute_attempt_count"] == 1, (
        "a planner run is not a system reroute, so the attempt count is unchanged"
    )

    line = read_order_line(ctx["line"]["id"])
    assert line["open_units"] == 0, "the recovery run leaves no open unit"
    assert line["assigned_units"] == 2, "both units are held by a live assignment again"


def test_commit_run_out_of_routing_recovers_full_coverage_in_one_assignment():
    """PRD §3.4: "A run initiated this way records `initiated_by` as `PLANNER`; runs the system starts for itself record `SYSTEM_REROUTE` when they follow a reject, a short pick, a cancel-with-reroute or a pick-deadline expiry, and `SYSTEM_DEACTIVATION` when they follow a node deactivation cascade."
    PRD §3.4: "Otherwise a `COMMIT` run's `status` is `COMMITTED`."
    PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."
    PRD §3.4: "Split minimisation then overrides pure scoring: if any eligible candidate can cover the entire remaining demand on its own, the selectable set is restricted to those full-coverage candidates and the winner is the best-ranked among them, even when a partial-coverage candidate has a strictly higher `routing_score`."
    PRD §3.5: "It is created only by a routing run and carries, as system-set references, the `order_id` it serves, the `store_id` that will fulfill it, the `routing_run_id` that created it, and a `carrier_pickup_id` that stays null until the parcel is tendered."

    Design: Difficulty/non_linear_state_machine/order_routing_status_cycles_routed_to_routing_and_back_to_routed
    """
    ctx = _setup_routing_status_cycle()

    run = validate_success(
        api_client.create_routing_run(
            ctx["order"]["id"],
            create_routing_run_payload(ctx["order_in_cycle"]["version"], "COMMIT"),
            PLANNER,
        ),
        expected_status=201,
    )
    assert run["initiated_by"] == "PLANNER", (
        "a run a planner starts records PLANNER, got " f"{run['initiated_by']}"
    )
    assert run["status"] == "COMMITTED", (
        f"a COMMIT run that selected a node ends COMMITTED, got {run['status']}"
    )
    assert run["selected_store_count"] == 1, (
        "one full-coverage node absorbs both open units, so exactly one node is "
        f"selected, got {run['selected_store_count']}"
    )

    live = [
        row
        for row in find_assignments(order_id=ctx["order"]["id"])
        if row["status"] == "ASSIGNED"
    ]
    assert len(live) == 1, (
        f"the recovery run should create exactly one assignment, got {len(live)}"
    )
    assert live[0]["assigned_units"] == 2, (
        "the single winner covers the whole remaining demand of two units, got "
        f"{live[0]['assigned_units']}"
    )
    assert live[0]["routing_run_id"] == run["id"], (
        "the replacement assignment names the run that created it"
    )


# ======================================================================
# Instance 3 preamble — the full ELIGIBLE → PROBATION → DEACTIVATED cycle
# ======================================================================


def _setup_posture_cycle() -> dict:
    """Two consecutive cancellation-rate breaches at one node: epoch 1 closes on
    a rejection, epoch 2 closes on a care cancellation."""
    return setup_deactivated_node(
        node_preset="S1",
        sku_preset="SKU-A",
        clock="2026-08-03T09:00:00Z",
        reject_at="2026-08-03T09:05:00Z",
        first_close_at="2026-08-03T09:30:00Z",
        cancel_at="2026-08-03T09:35:00Z",
        second_close_at="2026-08-03T09:40:00Z",
    )


def _setup_reactivated_node() -> dict:
    ctx = _setup_posture_cycle()
    ctx["store_before_reactivation"] = ctx["store"]
    validate_success(api_client.reactivate_store(ctx["store"]["id"], PLANNER))
    ctx["store"] = read_store(ctx["store"]["id"])
    ctx["open_windows"] = find_windows(store_id=ctx["store"]["id"], status="OPEN")
    return ctx


def test_first_breached_window_moves_the_node_from_eligible_to_probation():
    """PRD §2.10: "A node's posture is carried by `node_status`, which is one of `ELIGIBLE`, `PROBATION` or `DEACTIVATED` and begins at `ELIGIBLE`."
    PRD §3.9: "A `PROBATION` action moves the node `ELIGIBLE → PROBATION` and sets `consecutive_breach_windows` to 1."
    PRD §3.9: "Otherwise it is `DEACTIVATION` when the window is breached and the node's `consecutive_breach_windows` plus 1 reaches 2; `PROBATION` when the window is breached, the node's `node_status` is `ELIGIBLE`, and `consecutive_breach_windows` plus 1 is still below 2; `RECOVERY` when the window is not breached and the node's `node_status` is `PROBATION`; and `NONE` in every other case."
    PRD §3.9: "`breach_flags` is then built as a subset of three markers appended in this fixed order: `FILL_RATE` when `assignments_shipped` is at least 1 and `fill_rate` is strictly below 0.9000; `CYCLE_TIME` when `assignments_shipped` is at least 1 and `avg_cycle_time_minutes` is strictly greater than four hours; and `CANCELLATION_RATE` when `assignments_created` is at least 1 and `cancellation_rate` is strictly greater than 0.0500."
    PRD §3.9: "`cancellation_rate` is exactly 0.0000 when `assignments_created` is 0, and otherwise `assignments_rejected` plus `assignments_cancelled`, divided by `assignments_created`, rounded half-up to four decimal places."
    PRD §3.9: "`fill_rate` is exactly 1.0000 when `units_promised` is 0, and otherwise `units_shipped` divided by `units_promised` rounded half-up to four decimal places."

    Design: Difficulty/non_linear_state_machine/store_node_status_cycles_eligible_probation_deactivated_eligible
    """
    ctx = _setup_posture_cycle()
    window = ctx["window_epoch_1"]
    assert window is not None, "the first ops-run must have closed the epoch-1 window"

    assert window["epoch"] == 1, f"the first window closes at epoch 1, got {window['epoch']}"
    assert window["node_action"] == "PROBATION", (
        "a first breached window on an ELIGIBLE node yields the PROBATION action, got "
        f"{window['node_action']}"
    )
    assert window["breach_flags"] == ["CANCELLATION_RATE"], (
        "with nothing shipped only the cancellation-rate marker can fire, got "
        f"{window['breach_flags']}"
    )
    assert window["cancellation_rate"] == pytest.approx(1.0000, abs=0.01), (
        "one rejected assignment out of one created is a cancellation rate of 1, got "
        f"{window['cancellation_rate']}"
    )
    assert window["fill_rate"] == pytest.approx(0.0000, abs=0.01), (
        "two units were promised and none shipped, got " f"{window['fill_rate']}"
    )


def test_second_consecutive_breach_deactivates_the_probation_node():
    """PRD §3.9: "A `DEACTIVATION` action moves the node `PROBATION → DEACTIVATED` on a second consecutive breached window, sets `node_status` to `DEACTIVATED` and records `deactivated_at_epoch` as the closing window's `epoch`."
    PRD §3.9: "From that set: `assignments_created` is the count of all of them; `assignments_shipped`, `assignments_rejected` and `assignments_cancelled` are the counts at `status` `SHIPPED`, `REJECTED` and `CANCELLED` respectively; `units_promised` is the sum of `assigned_units` over all of them; and `units_shipped` is the sum of `picked_units` over those at `SHIPPED`."
    PRD §2.10: "Every assignment is stamped at creation with the `epoch` of its node's open window, and that stamp — not the node's current epoch — is what binds the assignment to a window for measurement."
    PRD §3.7: "All four permitted source states carry the same cascade: `status` becomes `CANCELLED` and the `cancel_reason_code` is stored; each assignment line's `units_cancelled` becomes its `units_assigned` minus its `units_picked`, releasing that much of the served demand line's `assigned_units`; the node's inventory `reserved_units`, `units_committed_epoch` and `reserved_labor_minutes` all decrease and its `eligibility_score` is recomputed — including, for a `PICKED` or `SHORT_PICKED` source, the units already physically picked, which are returned to the node's reservations and then released; when `reroute` is true a system reroute run excluding this node is created, at `initiated_by` `SYSTEM_REROUTE` or, for a deactivation cascade, `SYSTEM_DEACTIVATION`, while when `reroute` is false the released units become the demand lines' `cancelled_units`; a customer notification is emitted; the order's `routing_status` and `fulfillment_status` are re-derived; and the assignment's `version` increments."
    PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."

    Design: Difficulty/non_linear_state_machine/store_node_status_cycles_eligible_probation_deactivated_eligible
    """
    ctx = _setup_posture_cycle()
    window = ctx["window_epoch_2"]
    assert window is not None, "the second ops-run must have closed the epoch-2 window"

    assert window["epoch"] == 2, (
        f"the second window closes at epoch 2, got {window['epoch']}"
    )
    assert window["node_action"] == "DEACTIVATION", (
        "a second consecutive breached window deactivates the node, got "
        f"{window['node_action']}"
    )
    assert window["assignments_created"] == 1, (
        "the epoch-2 window measures the one replacement assignment stamped with "
        f"epoch 2, got {window['assignments_created']}"
    )
    assert window["assignments_cancelled"] == 1, (
        "that assignment reached CANCELLED, got " f"{window['assignments_cancelled']}"
    )

    assert ctx["store"]["node_status"] == "DEACTIVATED", (
        "the node sits at DEACTIVATED before any planner reactivation, got "
        f"{ctx['store']['node_status']}"
    )

    cancelled = ctx["assignment_epoch_2"]
    assert cancelled["epoch"] == 2, (
        "the replacement was stamped with the epoch open at its creation, got "
        f"{cancelled['epoch']}"
    )
    assert cancelled["status"] == "CANCELLED", (
        f"the care cancellation is terminal, got {cancelled['status']}"
    )
    assert cancelled["provisional_cost_cents"] == 1336, (
        "the replacement was priced on the node's standards for two assigned units, "
        f"got {cancelled['provisional_cost_cents']}"
    )

    line = read_order_line(ctx["line"]["id"])
    assert line["cancelled_units"] == 2, (
        "a cancel with reroute false turns the released units into cancelled_units, got "
        f"{line['cancelled_units']}"
    )
    assert line["open_units"] == 0, "no unit is left open after the cancellation"


def test_reactivation_returns_the_deactivated_node_to_eligible_on_a_new_epoch():
    """PRD §2.10: "The posture cycle is `ELIGIBLE → PROBATION → DEACTIVATED → ELIGIBLE`, with a recovery shortcut `PROBATION → ELIGIBLE`."
    PRD §3.9: "A `NetworkPlanner` returns a node from `DEACTIVATED → ELIGIBLE`; a node whose `node_status` is not `DEACTIVATED` is refused with `ERR_STORE_NOT_DEACTIVATED`."
    PRD §3.9: "Reactivation sets `node_status` to `ELIGIBLE`, resets `consecutive_breach_windows` to 0, clears `deactivated_at_epoch` back to null, and increments `reactivation_count` by 1."
    PRD §3.9: "When the node has no open window, one is created at an `epoch` equal to the greater of the network's current epoch and this node's highest existing epoch plus 1 — epochs are unique per node, so a reactivated node never re-uses a closed epoch."

    Design: Difficulty/non_linear_state_machine/store_node_status_cycles_eligible_probation_deactivated_eligible
    """
    ctx = _setup_reactivated_node()

    assert ctx["store_before_reactivation"]["node_status"] == "DEACTIVATED", (
        "the cycle must reach DEACTIVATED before the reactivation hop, got "
        f"{ctx['store_before_reactivation']['node_status']}"
    )

    store = ctx["store"]
    assert store["node_status"] == "ELIGIBLE", (
        "reactivation closes the posture cycle back at ELIGIBLE, got "
        f"{store['node_status']}"
    )
    assert store["consecutive_breach_windows"] == 0, (
        "reactivation resets the breach counter, got "
        f"{store['consecutive_breach_windows']}"
    )
    assert store["deactivated_at_epoch"] is None, (
        "reactivation clears deactivated_at_epoch, got "
        f"{store['deactivated_at_epoch']}"
    )
    assert store["reactivation_count"] == 1, (
        f"reactivation_count increments by 1, got {store['reactivation_count']}"
    )

    open_windows = ctx["open_windows"]
    assert len(open_windows) == 1, (
        f"a reactivated node gets exactly one open window, got {len(open_windows)}"
    )
    assert open_windows[0]["epoch"] == 3, (
        "the new window sits past both closed epochs, got "
        f"{open_windows[0]['epoch']}"
    )
    assert open_windows[0]["status"] == "OPEN", (
        f"the new window is OPEN, got {open_windows[0]['status']}"
    )


def test_reactivated_node_scores_governance_and_routing_from_its_closed_windows():
    """PRD §3.9: "Each window's `node_action` is decided and applied, and each node's `review_score` is written on the governance-blended basis of §3.3 from the pre-reset counters."
    PRD §3.3: "`review_score` blends two windows: seven tenths of the performance ratio of the window being closed plus three tenths of the performance ratio of the previous closed window, or, when no previous closed window exists, the ratio of the window being closed on its own."
    PRD §3.3: "The score is the sum of three components, each rounded half-up to four decimal places, with the sum then rounded half-up to two decimal places."
    PRD §3.3: "For any closed performance window, that window's performance ratio is one half of its `fill_rate`, plus three tenths of one minus its `cancellation_rate`, plus two tenths of its cycle-time factor."
    PRD §3.9: "Finally `eligibility_score` is recomputed, with `eligibility_score_basis` set to `TRAILING_WINDOW` when the node has at least one closed window and `COLD_START` when it has none."

    Design: Difficulty/non_linear_state_machine/store_node_status_cycles_eligible_probation_deactivated_eligible
    """
    ctx = _setup_reactivated_node()
    store = ctx["store"]

    assert store["review_score"] == pytest.approx(60.00, abs=0.01), (
        "the governance score blends the two breached windows' ratios, got "
        f"{store['review_score']}"
    )
    assert store["eligibility_score"] == pytest.approx(60.00, abs=0.01), (
        "reactivation rescores the node against its latest closed window, got "
        f"{store['eligibility_score']}"
    )
    assert store["eligibility_score_basis"] == "TRAILING_WINDOW", (
        "the node has closed windows, so the basis is TRAILING_WINDOW, got "
        f"{store['eligibility_score_basis']}"
    )


# ======================================================================
# Instance 4 preamble — a two-node split with only the S1 parcel packed
# ======================================================================


def _setup_two_node_split_with_one_packed_parcel() -> dict:
    """S1 (ATP 4) and S3 (ATP 3) split a six-unit order; the S1 parcel is
    accepted at 09:05, fully picked, and packed at 09:25."""
    ctx = setup_multi_node_order(
        node_stock=[("S1", 6, 2), ("S3", 5, 2)],
        sku_preset="SKU-A",
        quantity=6,
        destination_zone=4,
        service_level="GROUND",
        order_code="O-3004",
        customer_ref="C-7",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
        clock="2026-08-03T09:00:00Z",
        packaging=[("S1", "MEDIUM_BOX", 20)],
        pickups=[("S1", "2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z", 5)],
    )
    assert set(ctx["assignments"]) == {"S1", "S3"}, (
        "the six units need both nodes, got " f"{sorted(ctx['assignments'])}"
    )
    store_s1 = ctx["stores"]["S1"]
    assignment_s1 = ctx["assignments"]["S1"]
    assert assignment_s1["assigned_units"] == 4, (
        "S1's promise-able units cap its allocation at 4, got "
        f"{assignment_s1['assigned_units']}"
    )
    set_clock("2026-08-03T09:05:00Z")
    accept(assignment_s1["id"], store_s1["id"])
    pick_full(assignment_s1["id"], store_s1["id"])
    set_clock("2026-08-03T09:25:00Z")
    pack(assignment_s1["id"], store_s1["id"], "MEDIUM_BOX")
    ctx["assignment_s1"] = read_assignment(assignment_s1["id"])
    ctx["assignment_s3"] = ctx["assignments"]["S3"]
    return ctx


def test_partial_ship_advances_fulfillment_status_while_routing_status_stays_routed():
    """PRD §3.2: "The order carries two independent status dimensions that never read one another."
    PRD §3.2: "The two genuinely diverge: an order may be `PARTIALLY_SHIPPED` while its `routing_status` is `ROUTING`, and it may be `SHIPPED` while its `routing_status` is still `PARTIALLY_ROUTED` because the residual units went to the distribution centre."
    PRD §3.6: "From `PENDING`, a ship that leaves the order with `shipped_units` above 0 while `shipped_units` plus the sum of the lines' `cancelled_units` plus `dc_fallback_units` is still strictly below `total_units` moves it to `PARTIALLY_SHIPPED`, recomputing `shipped_units` and refreshing the provisional cost fields."
    PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."
    PRD §3.4: "A successful run re-derives the order's `routing_status`, recomputes `split_count` — the number of the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — recomputes `provisional_cost_cents`, `dc_baseline_cost_cents` and `cost_index_bps`, and increments the order's `version`."
    PRD §3.6: "Each served demand line has its `shipped_units` raised by the line's `units_picked` and its `assigned_units` reduced by its `units_assigned`."

    Design: Difficulty/non_linear_state_machine/order_ships_partially_while_routing_dimension_stays_routed
    """
    ctx = _setup_two_node_split_with_one_packed_parcel()
    ship(
        ctx["assignment_s1"]["id"],
        ctx["stores"]["S1"]["id"],
        ctx["pickups"]["S1"]["id"],
    )

    order = read_order(ctx["order"]["id"])
    assert order["fulfillment_status"] == "PARTIALLY_SHIPPED", (
        "four of six units shipped moves the execution dimension to "
        f"PARTIALLY_SHIPPED, got {order['fulfillment_status']}"
    )
    assert order["routing_status"] == "ROUTED", (
        "the routing dimension is untouched by the ship because every unit is still "
        f"covered, got {order['routing_status']}"
    )
    assert order["shipped_units"] == 4, (
        f"the order's shipped_units is recomputed to 4, got {order['shipped_units']}"
    )
    assert order["split_count"] == 2, (
        "the shipped parcel and the untouched assignment are both counted, got "
        f"{order['split_count']}"
    )

    assert read_assignment(ctx["assignment_s1"]["id"])["status"] == "SHIPPED", (
        "the tendered parcel is SHIPPED"
    )
    assert read_assignment(ctx["assignment_s3"]["id"])["status"] == "ASSIGNED", (
        "the other node's assignment is untouched by the tender"
    )

    line = read_order_line(ctx["line"]["id"])
    assert line["shipped_units"] == 4, (
        f"the demand line records the four shipped units, got {line['shipped_units']}"
    )
    assert line["assigned_units"] == 2, (
        "only the second node's two units remain assigned, got "
        f"{line['assigned_units']}"
    )
    assert line["open_units"] == 0, "no unit of the line is open"


def test_partial_ship_seals_the_assignment_final_cost_but_not_the_order_final_cost():
    """PRD §3.6: "The assignment's `status` becomes `SHIPPED`, `shipped_at` is set to the clock instant, `carrier_pickup_id` is stored, and `cycle_time_minutes` is computed as the elapsed time from `created_at` to `shipped_at` in whole minutes with remaining seconds discarded."
    PRD §3.8: "The **final** variant, written to `final_cost_cents` at ship, charges *actual* clocked labour: the greater of `labor_minutes_actual` and a 10-minute billable minimum, where `labor_minutes_actual` is the whole minutes from `accepted_at` to `packed_at` with remaining seconds discarded."
    PRD §3.8: "Its charged units are `picked_units`, and its charged package is the `package_type` the associate actually recorded at pack."
    PRD §3.5: "On success `packed_at` is set to the clock instant, `package_type` is stored, and `labor_minutes_actual` is computed as the elapsed time from `accepted_at` to `packed_at` expressed in whole minutes with any remaining seconds discarded."
    PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
    PRD §3.8: "The **final** variant, written to `final_cost_cents` when `fulfillment_status` becomes `SHIPPED`, includes only assignments at `status` `SHIPPED`, using each one's `final_cost_cents`; because the component sum changes, the fee tier can land in a different band than the provisional pass did, which is exactly what `cost_variance_cents` — `final_cost_cents` minus `provisional_cost_cents` — is there to expose."
    PRD §3.8: "The **provisional** variant, kept live in `provisional_cost_cents` after every routing change and every assignment status change, includes the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — that is, the five non-terminal statuses plus `SHIPPED` — using each one's `provisional_cost_cents`."
    PRD §3.8: "The order's `cost_index_bps` uses `final_cost_cents` once that is set and `provisional_cost_cents` before then."

    Design: Difficulty/non_linear_state_machine/order_ships_partially_while_routing_dimension_stays_routed
    """
    ctx = _setup_two_node_split_with_one_packed_parcel()
    pickup = ctx["pickups"]["S1"]

    shipped = validate_success(
        api_client.ship_assignment(
            ctx["assignment_s1"]["id"],
            ship_payload(pickup["id"], pickup_version(pickup["id"])),
            make_store_associate_headers(ctx["stores"]["S1"]["id"]),
        )
    )
    assert shipped["status"] == "SHIPPED", (
        f"the tender moves PACKED → SHIPPED, got {shipped['status']}"
    )
    assert shipped["labor_minutes_actual"] == 20, (
        "09:05 to 09:25 is twenty whole clocked minutes, got "
        f"{shipped['labor_minutes_actual']}"
    )
    assert shipped["cycle_time_minutes"] == 25, (
        "09:00 to 09:25 is twenty-five whole minutes, got "
        f"{shipped['cycle_time_minutes']}"
    )
    assert shipped["final_cost_cents"] == 1525, (
        "the final variant charges the clocked labour, the picked units and the box "
        f"actually used, got {shipped['final_cost_cents']}"
    )
    assert shipped["provisional_cost_cents"] == 1693, (
        "the provisional figure sealed at creation is not rewritten at ship, got "
        f"{shipped['provisional_cost_cents']}"
    )

    other = read_assignment(ctx["assignment_s3"]["id"])
    assert other["provisional_cost_cents"] == 985, (
        "the unshipped parcel keeps its own provisional price, got "
        f"{other['provisional_cost_cents']}"
    )

    order = read_order(ctx["order"]["id"])
    assert order["final_cost_cents"] is None, (
        "the order-level final variant waits for fulfillment_status SHIPPED, got "
        f"{order['final_cost_cents']}"
    )
    assert order["provisional_cost_cents"] == 2981, (
        "both assignments are still included in the live provisional total, got "
        f"{order['provisional_cost_cents']}"
    )
    assert order["cost_index_bps"] == 11599, (
        "with no final figure yet the index reads the provisional cost, got "
        f"{order['cost_index_bps']}"
    )


def test_partial_ship_releases_the_shipping_node_and_claims_one_parcel_slot():
    """PRD §3.6: "For each line's SKU, the node's inventory row has `on_hand_units` reduced by the line's `units_picked` and `reserved_units` reduced by its `units_assigned`, and `available_to_promise_units` is recomputed."
    PRD §3.6: "The pickup's `reserved_parcels` increases by 1 and its `version` increments."
    PRD §2.9: "A pickup's `reserved_parcels` equals the count of assignments whose `carrier_pickup_id` names that pickup and whose `status` is `SHIPPED`, and `reserved_parcels` never exceeds `parcel_capacity`."
    PRD §3.6: "The node's `reserved_labor_minutes` is reduced by the assignment's `labor_minutes_reserved` and its `eligibility_score` is recomputed."
    PRD §2.9: "Reaching `SHIPPED`, `REJECTED` or `CANCELLED` releases the full labour standard, so a create-then-release round trip leaves `reserved_labor_minutes` exactly where it started — even when the assignment was short-picked, because a shortfall never re-prices the labour standard."
    PRD §3.3: "`units_committed_epoch` here is itself derived: it is the sum of `assigned_units` over the node's assignments whose `epoch` equals the epoch of the node's open performance window and whose `status` is neither `REJECTED` nor `CANCELLED`, and it is reset to 0 when a window closes."
    PRD §3.3: "The score is the sum of three components, each rounded half-up to four decimal places, with the sum then rounded half-up to two decimal places."
    PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."

    Design: Difficulty/non_linear_state_machine/order_ships_partially_while_routing_dimension_stays_routed
    """
    ctx = _setup_two_node_split_with_one_packed_parcel()
    ship(
        ctx["assignment_s1"]["id"],
        ctx["stores"]["S1"]["id"],
        ctx["pickups"]["S1"]["id"],
    )

    inventory = read_inventory(ctx["inventories"]["S1"]["id"])
    assert inventory["on_hand_units"] == 2, (
        "the four picked units leave the building, got " f"{inventory['on_hand_units']}"
    )
    assert inventory["reserved_units"] == 0, (
        "the tender drops the assignment's reservation, got "
        f"{inventory['reserved_units']}"
    )
    assert inventory["available_to_promise_units"] == 0, (
        "the two remaining units are all safety stock, got "
        f"{inventory['available_to_promise_units']}"
    )

    pickup = read_pickup(ctx["pickups"]["S1"]["id"])
    assert pickup["reserved_parcels"] == 1, (
        f"the tender consumes one parcel slot, got {pickup['reserved_parcels']}"
    )

    store = read_store(ctx["stores"]["S1"]["id"])
    assert store["reserved_labor_minutes"] == pytest.approx(0.00, abs=0.01), (
        "shipping releases the whole labour standard, got "
        f"{store['reserved_labor_minutes']}"
    )
    assert store["units_committed_epoch"] == 4, (
        "a SHIPPED assignment still counts against the epoch's commitments, got "
        f"{store['units_committed_epoch']}"
    )
    assert store["eligibility_score"] == pytest.approx(71.20, abs=0.01), (
        "the node is rescored from its post-ship reservation levels, got "
        f"{store['eligibility_score']}"
    )
