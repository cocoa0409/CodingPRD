"""Multi-hop release/reroute cascades.

Two triggering events are exercised end to end: an assignment-level rejection
(§3.7) and a node deactivation produced by the operations run (§3.9). In both
cases the release at the failing node, the replacement assignment at the winning
node, the order's repricing and the customer notification are asserted as
separate links of the same synchronous chain (§2.10).
"""

import pytest

from test_helpers import (
    add_order_line,
    cancel_assignment,
    close_windows,
    commit_routing,
    find_assignment,
    find_assignment_lines,
    find_notifications,
    find_routing_runs,
    find_windows,
    intake_order,
    read_assignment,
    read_inventory,
    read_order,
    read_order_line,
    read_store,
    register_node,
    register_sku,
    reject,
    set_clock,
    setup_node_with_one_breached_window,
    stock_inventory,
)


# ======================================================================
# Shared preambles (each test starts against an empty database)
# ======================================================================


def _reject_reroute_chain() -> dict:
    """Two cold-start nodes, a two-unit GROUND order committed to the cheaper
    node, then that node rejects the task at 09:05.

    S3 is registered first and wins the first waterfall; S1 is the only node
    left for the reroute that the rejection triggers.
    """
    set_clock("2026-08-03T09:00:00Z")
    origin_node = register_node("S3")
    winning_node = register_node("S1")
    sku = register_sku("SKU-A")
    origin_inventory = stock_inventory(
        origin_node["id"], sku["id"], on_hand_units=5, safety_stock_units=2
    )
    winning_inventory = stock_inventory(
        winning_node["id"], sku["id"], on_hand_units=12, safety_stock_units=2
    )

    order = intake_order(
        order_code="O-4001",
        customer_ref="C-8",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T15:00:00Z",
    )
    order_line = add_order_line(order["id"], sku["id"], quantity=2, unit_price_cents=4500)
    commit_routing(order["id"])
    origin_assignment = find_assignment(
        order_id=order["id"], store_id=origin_node["id"]
    )

    set_clock("2026-08-03T09:05:00Z")
    reject(origin_assignment["id"], origin_node["id"], "LABOR_UNAVAILABLE")

    return {
        "origin_node": origin_node,
        "winning_node": winning_node,
        "sku": sku,
        "origin_inventory": origin_inventory,
        "winning_inventory": winning_inventory,
        "order": order,
        "order_line": order_line,
        "origin_assignment": origin_assignment,
    }


def _deactivation_cascade_chain() -> dict:
    """Drive S1 to its second consecutive breached window while it still holds a
    live assignment for a second order, with a fresh node S5 available.

    Timeline: 09:00 S1 + stock + O-4002 committed and rejected at 09:05; 09:30
    ops-run #1 puts S1 on PROBATION and re-commits O-4002 into epoch 2; 09:32
    O-4003 is committed to S1 in epoch 2; 09:34 care cancels the epoch-2
    assignment of O-4002 so the epoch-2 window shows 2 created / 1 cancelled;
    09:36 S5 is registered and stocked; 09:40 the ops-run closes epoch 2.
    """
    probation = setup_node_with_one_breached_window(
        node_preset="S1",
        sku_preset="SKU-A",
        on_hand_units=12,
        safety_stock_units=2,
        quantity=2,
        order_code="O-4002",
        customer_ref="C-9",
        clock="2026-08-03T09:00:00Z",
        reject_at="2026-08-03T09:05:00Z",
        close_at="2026-08-03T09:30:00Z",
    )
    failing_node = probation["store"]
    sku = probation["sku"]
    first_order_epoch_2 = probation["assignment_epoch_2"]
    assert first_order_epoch_2 is not None, (
        "setup expected the first ops-run's retry to recreate an assignment in epoch 2"
    )

    set_clock("2026-08-03T09:32:00Z")
    second_order = intake_order(
        order_code="O-4003",
        customer_ref="C-10",
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T16:00:00Z",
    )
    second_line = add_order_line(
        second_order["id"], sku["id"], quantity=2, unit_price_cents=4500
    )
    commit_routing(second_order["id"])
    doomed_assignment = find_assignment(
        order_id=second_order["id"], store_id=failing_node["id"]
    )

    set_clock("2026-08-03T09:34:00Z")
    cancel_assignment(first_order_epoch_2["id"], "CUSTOMER_REQUEST", reroute=False)

    set_clock("2026-08-03T09:36:00Z")
    replacement_node = register_node("S5")
    replacement_inventory = stock_inventory(
        replacement_node["id"], sku["id"], on_hand_units=10, safety_stock_units=0
    )

    set_clock("2026-08-03T09:40:00Z")
    closed_windows = close_windows()

    return {
        "failing_node": failing_node,
        "failing_inventory": probation["inventory"],
        "replacement_node": replacement_node,
        "replacement_inventory": replacement_inventory,
        "sku": sku,
        "second_order": second_order,
        "second_line": second_line,
        "doomed_assignment": doomed_assignment,
        "closed_windows": closed_windows,
    }


def _window_for(store_id: str, epoch: int) -> dict:
    rows = find_windows(store_id=store_id, epoch=epoch)
    assert len(rows) == 1, (
        f"expected exactly one performance window for node {store_id} at epoch "
        f"{epoch}, got {len(rows)}"
    )
    return rows[0]


# ======================================================================
# Instance 1 — rejection releases, reroutes and reprices two nodes
# ======================================================================


class TestRejectReleaseRerouteChain:
    def test_reject_releases_reservations_and_rescores_origin_node(self):
        """PRD §3.7: "Rejection sets `status` to `REJECTED`, stores the `reject_reason_code`, and sets every assignment line's `units_cancelled` equal to its `units_assigned`."
        PRD §3.7: "Second, because the node's reservations dropped, its inventory `reserved_units` decreases and `available_to_promise_units` is recomputed, while its `units_committed_epoch` and `reserved_labor_minutes` decrease, which in turn recomputes that node's `eligibility_score`."
        PRD §2.9: "A forward action such as a routing commit and its compensating action — a reject, a cancel, or a supersede — must return `available_to_promise_units` to exactly its pre-action value."
        PRD §2.9: "Reaching `SHIPPED`, `REJECTED` or `CANCELLED` releases the full labour standard, so a create-then-release round trip leaves `reserved_labor_minutes` exactly where it started — even when the assignment was short-picked, because a shortfall never re-prices the labour standard."
        PRD §3.3: "That headroom is divided by a reference of 200 units, the quotient is capped at 1, and the result is multiplied by a weight of 40."
        PRD §3.3: "That headroom is divided by a reference of eight staffed hours, the quotient is capped at 1, and the result is multiplied by a weight of 30."
        PRD §3.3: "The **performance component** is a weight of 30 multiplied by a performance ratio between 0 and 1."
        PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."

        Design: Difficulty/transitive_cascade/reject_release_reroute_chain_reprices_two_nodes
        """
        ctx = _reject_reroute_chain()

        rejected = read_assignment(ctx["origin_assignment"]["id"])
        assert rejected["status"] == "REJECTED", (
            f"a rejected assignment must sit at REJECTED, got {rejected['status']}"
        )
        assert rejected["reject_reason_code"] == "LABOR_UNAVAILABLE", (
            "the rejection must store the supplied reject_reason_code, got "
            f"{rejected['reject_reason_code']}"
        )

        for line in find_assignment_lines(rejected["id"]):
            assert line["units_cancelled"] == line["units_assigned"], (
                "rejection sets every assignment line's units_cancelled equal to "
                f"its units_assigned: {line['units_cancelled']} != "
                f"{line['units_assigned']}"
            )

        origin_inventory = read_inventory(ctx["origin_inventory"]["id"])
        assert origin_inventory["reserved_units"] == 0, (
            "the rejecting node's reserved_units must drop back to 0, got "
            f"{origin_inventory['reserved_units']}"
        )
        assert origin_inventory["available_to_promise_units"] == 3, (
            "available_to_promise_units must return to its pre-commit value of 3 "
            f"(5 on hand less 2 safety stock), got "
            f"{origin_inventory['available_to_promise_units']}"
        )

        origin_node = read_store(ctx["origin_node"]["id"])
        assert origin_node["units_committed_epoch"] == 0, (
            "the rejecting node's units_committed_epoch must drop back to 0, got "
            f"{origin_node['units_committed_epoch']}"
        )
        assert origin_node["reserved_labor_minutes"] == pytest.approx(0.00, abs=0.01), (
            "rejection releases the full labour standard, so reserved_labor_minutes "
            f"must return to 0.00, got {origin_node['reserved_labor_minutes']}"
        )
        assert origin_node["eligibility_score"] == pytest.approx(88.00, abs=0.01), (
            "a fully released cold-start node scores 40 capacity + 30 labour + "
            f"30*0.60 performance = 88.00, got {origin_node['eligibility_score']}"
        )

    def test_reject_reroute_run_places_replacement_assignment_at_winning_node(self):
        """PRD §3.7: "Third, because open units now exist, a system reroute run is created for the order — `mode` `COMMIT`, `initiated_by` `SYSTEM_REROUTE` — with this node added to the run's `excluded_store_ids`."
        PRD §3.7: "Fourth, that run's waterfall may create a replacement assignment at the winning node whose `reroute_generation` is one greater than the rejected assignment's, which reserves the winning node's inventory `reserved_units` and raises its `units_committed_epoch` and `reserved_labor_minutes`."
        PRD §3.7: "Fifth, the winning node's `eligibility_score` is recomputed from its new reservation levels."
        PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."
        PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."
        PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
        PRD §3.8: "**Labour cost** is the charged labour minutes multiplied by the node's `labor_rate_cents_per_minute`, rounded up to the next whole cent."
        PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."

        Design: Difficulty/transitive_cascade/reject_release_reroute_chain_reprices_two_nodes
        """
        ctx = _reject_reroute_chain()

        reroute_runs = find_routing_runs(
            order_id=ctx["order"]["id"], initiated_by="SYSTEM_REROUTE"
        )
        assert len(reroute_runs) == 1, (
            f"the rejection must create exactly one system reroute run, got "
            f"{len(reroute_runs)}"
        )
        reroute_run = reroute_runs[0]
        assert reroute_run["initiated_by"] == "SYSTEM_REROUTE", (
            f"the reroute run's initiated_by must be SYSTEM_REROUTE, got "
            f"{reroute_run['initiated_by']}"
        )
        assert reroute_run["mode"] == "COMMIT", (
            f"the reroute run's mode must be COMMIT, got {reroute_run['mode']}"
        )
        assert reroute_run["excluded_store_ids"] == [ctx["origin_node"]["id"]], (
            "the rejecting node must be the run's only excluded node, got "
            f"{reroute_run['excluded_store_ids']}"
        )
        assert reroute_run["selected_store_count"] == 1, (
            "the reroute selected exactly one node, so selected_store_count must be "
            f"1, got {reroute_run['selected_store_count']}"
        )

        replacement = find_assignment(
            order_id=ctx["order"]["id"], store_id=ctx["winning_node"]["id"]
        )
        assert replacement["store_id"] == ctx["winning_node"]["id"], (
            "the replacement assignment must sit at the winning node"
        )
        assert replacement["assigned_units"] == 2, (
            "the replacement covers both released units, got "
            f"{replacement['assigned_units']}"
        )
        assert replacement["reroute_generation"] == 1, (
            "reroute_generation must be one greater than the rejected assignment's "
            f"0, got {replacement['reroute_generation']}"
        )
        assert replacement["provisional_cost_cents"] == 1336, (
            "the replacement's provisional cost is 756 labour + 160 packaging + 420 "
            f"ship = 1336 cents, got {replacement['provisional_cost_cents']}"
        )

        winning_inventory = read_inventory(ctx["winning_inventory"]["id"])
        assert winning_inventory["reserved_units"] == 2, (
            "the winning node must reserve the two rerouted units, got "
            f"{winning_inventory['reserved_units']}"
        )
        assert winning_inventory["available_to_promise_units"] == 8, (
            "available_to_promise_units must be 12 on hand less 2 reserved less 2 "
            f"safety stock = 8, got {winning_inventory['available_to_promise_units']}"
        )

        winning_node = read_store(ctx["winning_node"]["id"])
        assert winning_node["units_committed_epoch"] == 2, (
            "the winning node's units_committed_epoch must rise to 2, got "
            f"{winning_node['units_committed_epoch']}"
        )
        assert winning_node["reserved_labor_minutes"] == pytest.approx(18.00, abs=0.01), (
            "the winning node reserves 12 + 3*2 = 18.00 labour minutes, got "
            f"{winning_node['reserved_labor_minutes']}"
        )
        assert winning_node["eligibility_score"] == pytest.approx(70.48, abs=0.01), (
            "the winning node is rescored from its new reservation levels to 70.48, "
            f"got {winning_node['eligibility_score']}"
        )

    def test_reject_reroute_reprices_order_and_notifies_customer(self):
        """PRD §3.7: "Exactly one customer notification is emitted, the order's `routing_status` is re-derived, its `provisional_cost_cents` and `cost_index_bps` are recomputed, and the assignment's `version` increments."
        PRD §3.7: "Read against the workflows above, that rule says a rejection whose reroute succeeded notifies `REJECTION_REROUTED`, one whose reroute stranded units at the three-split ceiling notifies `DC_FALLBACK`, and one whose reroute found nothing notifies `UNROUTABLE`; a short pick behaves identically with `SHORT_PICK_REROUTED` in place of `REJECTION_REROUTED`."
        PRD §3.7: "It carries a `channel` of `EMAIL` or `SMS`, defaulting to `EMAIL`, a `units_affected` count of the units the event moved or removed, a `sent_at_utc` clock instant, and a `body_summary` — a templated one-line summary containing the order's `order_code`, the `notification_type` and the `units_affected` count."
        PRD §3.7: "A notification records the `order_id` it concerns and, for assignment-level events, the `assignment_id` that triggered it; for order-level events `assignment_id` is null."
        PRD §3.4: "`reroute_attempt_count` counts the order's runs whose `initiated_by` is `SYSTEM_REROUTE` or `SYSTEM_DEACTIVATION`."
        PRD §3.8: "The pre-fee subtotal is that component sum, plus a split penalty of 175 cents for each parcel beyond the first, plus a reroute overhead of 90 cents multiplied by the order's `reroute_attempt_count`."
        PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
        PRD §3.8: "The **provisional** variant, kept live in `provisional_cost_cents` after every routing change and every assignment status change, includes the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — that is, the five non-terminal statuses plus `SHIPPED` — using each one's `provisional_cost_cents`."
        PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."
        PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."

        Design: Difficulty/transitive_cascade/reject_release_reroute_chain_reprices_two_nodes
        """
        ctx = _reject_reroute_chain()

        order = read_order(ctx["order"]["id"])
        assert order["routing_status"] == "ROUTED", (
            "the successful reroute re-covers every unit, so routing_status must "
            f"settle back on ROUTED, got {order['routing_status']}"
        )
        assert order["reroute_attempt_count"] == 1, (
            "the single SYSTEM_REROUTE run must raise reroute_attempt_count to 1, "
            f"got {order['reroute_attempt_count']}"
        )
        assert order["provisional_cost_cents"] == 1512, (
            "the order reprices to 1336 component + 90 reroute overhead + 86 network "
            f"fee = 1512 cents, got {order['provisional_cost_cents']}"
        )
        assert order["cost_index_bps"] == 7234, (
            "cost_index_bps must be 1512 * 10000 / 2090 rounded half-up = 7234, got "
            f"{order['cost_index_bps']}"
        )

        order_line = read_order_line(ctx["order_line"]["id"])
        assert order_line["assigned_units"] == 2, (
            "the replacement assignment re-holds both units, got "
            f"{order_line['assigned_units']}"
        )
        assert order_line["open_units"] == 0, (
            f"no open unit may remain after the reroute, got {order_line['open_units']}"
        )

        notifications = find_notifications(
            order_id=ctx["order"]["id"], notification_type="REJECTION_REROUTED"
        )
        assert len(notifications) == 1, (
            "a rejection whose reroute created a replacement emits exactly one "
            f"REJECTION_REROUTED notification, got {len(notifications)}"
        )
        notification = notifications[0]
        assert notification["notification_type"] == "REJECTION_REROUTED", (
            f"notification_type must be REJECTION_REROUTED, got "
            f"{notification['notification_type']}"
        )
        assert notification["units_affected"] == 2, (
            "units_affected must count the two units the rejection moved, got "
            f"{notification['units_affected']}"
        )
        assert notification["assignment_id"] == ctx["origin_assignment"]["id"], (
            "the notification must name the rejected assignment that triggered it, "
            f"got {notification['assignment_id']}"
        )


# ======================================================================
# Instance 2 — deactivation cascade reroutes to a replacement node
# ======================================================================


class TestNodeDeactivationCascade:
    def test_second_breached_window_deactivates_node_and_cancels_its_assignment(self):
        """PRD §3.9: "From that set: `assignments_created` is the count of all of them; `assignments_shipped`, `assignments_rejected` and `assignments_cancelled` are the counts at `status` `SHIPPED`, `REJECTED` and `CANCELLED` respectively; `units_promised` is the sum of `assigned_units` over all of them; and `units_shipped` is the sum of `picked_units` over those at `SHIPPED`."
        PRD §3.9: "`cancellation_rate` is exactly 0.0000 when `assignments_created` is 0, and otherwise `assignments_rejected` plus `assignments_cancelled`, divided by `assignments_created`, rounded half-up to four decimal places."
        PRD §3.9: "`breach_flags` is then built as a subset of three markers appended in this fixed order: `FILL_RATE` when `assignments_shipped` is at least 1 and `fill_rate` is strictly below 0.9000; `CYCLE_TIME` when `assignments_shipped` is at least 1 and `avg_cycle_time_minutes` is strictly greater than four hours; and `CANCELLATION_RATE` when `assignments_created` is at least 1 and `cancellation_rate` is strictly greater than 0.0500."
        PRD §3.9: "Otherwise it is `DEACTIVATION` when the window is breached and the node's `consecutive_breach_windows` plus 1 reaches 2; `PROBATION` when the window is breached, the node's `node_status` is `ELIGIBLE`, and `consecutive_breach_windows` plus 1 is still below 2; `RECOVERY` when the window is not breached and the node's `node_status` is `PROBATION`; and `NONE` in every other case."
        PRD §3.9: "`consecutive_breach_windows` is then set to 0 when the window was non-empty and not breached, incremented by 1 when the window was non-empty and breached, and left completely unchanged when the window was empty — so an empty window never changes posture and never resets the breach counter."
        PRD §3.9: "A `DEACTIVATION` action moves the node `PROBATION → DEACTIVATED` on a second consecutive breached window, sets `node_status` to `DEACTIVATED` and records `deactivated_at_epoch` as the closing window's `epoch`."
        PRD §3.9: "First, every assignment of this node whose `status` is `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED` is cancelled with cancellation reason `NODE_DEACTIVATED`, processed in ascending assignment `created_at` order."
        PRD §3.9: "Second, each of those cancellations releases the served demand lines' `assigned_units` and this node's inventory `reserved_units`, and re-derives the owning order's `routing_status` to `ROUTING` — the reroute is deliberately deferred to step 6, so that the replacement assignment is stamped with the *new* epoch rather than the one being closed."
        PRD §3.9: "Each window's `status` becomes `CLOSED`, its `closed_at_utc` is set to the clock instant, and each node's `units_committed_epoch` is reset to 0."

        Design: Difficulty/transitive_cascade/node_deactivation_cascade_reroutes_to_replacement_node
        """
        ctx = _deactivation_cascade_chain()

        window = _window_for(ctx["failing_node"]["id"], 2)
        assert window["store_id"] == ctx["failing_node"]["id"], (
            "the closed window must belong to the breaching node"
        )
        assert window["epoch"] == 2, (
            f"the window being closed is epoch 2, got {window['epoch']}"
        )
        assert window["assignments_created"] == 2, (
            "both epoch-2 assignments of this node count as created, got "
            f"{window['assignments_created']}"
        )
        assert window["assignments_cancelled"] == 1, (
            "exactly one epoch-2 assignment was cancelled before the close, got "
            f"{window['assignments_cancelled']}"
        )
        assert window["cancellation_rate"] == pytest.approx(0.5000, abs=0.0001), (
            "cancellation_rate must be (0 rejected + 1 cancelled) / 2 created = "
            f"0.5000, got {window['cancellation_rate']}"
        )
        assert window["breach_flags"] == ["CANCELLATION_RATE"], (
            "with nothing shipped, only the cancellation-rate marker may be raised, "
            f"got {window['breach_flags']}"
        )
        assert window["node_action"] == "DEACTIVATION", (
            "a breached window on a node already carrying one breach must resolve to "
            f"DEACTIVATION, got {window['node_action']}"
        )

        node = read_store(ctx["failing_node"]["id"])
        assert node["node_status"] == "DEACTIVATED", (
            f"the node must land on DEACTIVATED, got {node['node_status']}"
        )
        assert node["deactivated_at_epoch"] == 2, (
            "deactivated_at_epoch must record the closing window's epoch of 2, got "
            f"{node['deactivated_at_epoch']}"
        )
        assert node["consecutive_breach_windows"] == 2, (
            "the second consecutive breached window must leave "
            f"consecutive_breach_windows at 2, got {node['consecutive_breach_windows']}"
        )
        assert node["units_committed_epoch"] == 0, (
            "closing the window resets units_committed_epoch to 0, got "
            f"{node['units_committed_epoch']}"
        )
        assert node["reserved_labor_minutes"] == pytest.approx(0.00, abs=0.01), (
            "cancelling every live assignment releases the node's labour, so "
            f"reserved_labor_minutes must be 0.00, got {node['reserved_labor_minutes']}"
        )

        cancelled = read_assignment(ctx["doomed_assignment"]["id"])
        assert cancelled["status"] == "CANCELLED", (
            "the deactivated node's live assignment must be cancelled, got "
            f"{cancelled['status']}"
        )
        assert cancelled["cancel_reason_code"] == "NODE_DEACTIVATED", (
            "the deactivation cascade cancels with reason NODE_DEACTIVATED, got "
            f"{cancelled['cancel_reason_code']}"
        )

        failing_inventory = read_inventory(ctx["failing_inventory"]["id"])
        assert failing_inventory["reserved_units"] == 0, (
            "the deactivated node must hold no reservation afterwards, got "
            f"{failing_inventory['reserved_units']}"
        )

    def test_deactivation_retry_run_reassigns_order_to_replacement_node_in_new_epoch(
        self,
    ):
        """PRD §3.9: "Every order whose `routing_status` is `ROUTING` is retried with a run at `mode` `COMMIT`, processed in ascending order `created_at` order."
        PRD §3.9: "The retry run carries an *empty* `excluded_store_ids` — it is a fresh network-wide attempt, because per-event exclusion applies only to the immediate reroute run that followed the failure."
        PRD §3.9: "Its `initiated_by` is `SYSTEM_DEACTIVATION` when step 3 was what released this order's units, and `SYSTEM_REROUTE` otherwise."
        PRD §3.9: "Fourth, each such run creates a replacement assignment at its winning node, raising that node's inventory `reserved_units` and its `units_committed_epoch`."
        PRD §3.9: "A new performance window at `status` `OPEN` and at the previous `epoch` plus 1 is created for every node whose `node_status` is `ELIGIBLE` or `PROBATION`, with `opened_at_utc` at the clock instant and `closed_at_utc` null."
        PRD §2.10: "Every assignment is stamped at creation with the `epoch` of its node's open window, and that stamp — not the node's current epoch — is what binds the assignment to a window for measurement."
        PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."
        PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."
        PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."
        PRD §3.9: "Every node whose `node_status` is `ELIGIBLE` or `PROBATION` has its `eligibility_score` recomputed against the just-closed window, with `eligibility_score_basis` set to `TRAILING_WINDOW`."

        Design: Difficulty/transitive_cascade/node_deactivation_cascade_reroutes_to_replacement_node
        """
        ctx = _deactivation_cascade_chain()

        retry_runs = find_routing_runs(
            order_id=ctx["second_order"]["id"], initiated_by="SYSTEM_DEACTIVATION"
        )
        assert len(retry_runs) == 1, (
            "the deactivation must produce exactly one SYSTEM_DEACTIVATION run for "
            f"the affected order, got {len(retry_runs)}"
        )
        retry_run = retry_runs[0]
        assert retry_run["initiated_by"] == "SYSTEM_DEACTIVATION", (
            "a retry whose units were released by the re-posture step is stamped "
            f"SYSTEM_DEACTIVATION, got {retry_run['initiated_by']}"
        )
        assert retry_run["excluded_store_ids"] == [], (
            "the deferred retry is a fresh network-wide attempt with an empty "
            f"excluded_store_ids, got {retry_run['excluded_store_ids']}"
        )
        assert retry_run["selected_store_count"] == 1, (
            "the retry selected exactly one node, got "
            f"{retry_run['selected_store_count']}"
        )

        replacement = find_assignment(
            order_id=ctx["second_order"]["id"],
            store_id=ctx["replacement_node"]["id"],
        )
        assert replacement["store_id"] == ctx["replacement_node"]["id"], (
            "the replacement assignment must sit at the surviving node"
        )
        assert replacement["epoch"] == 3, (
            "the deferred replacement is stamped with the newly opened epoch 3, got "
            f"{replacement['epoch']}"
        )
        assert replacement["assigned_units"] == 2, (
            f"the replacement covers both units, got {replacement['assigned_units']}"
        )
        assert replacement["provisional_cost_cents"] == 990, (
            "the replacement's provisional cost is 350 labour + 160 packaging + 480 "
            f"ship = 990 cents, got {replacement['provisional_cost_cents']}"
        )

        replacement_inventory = read_inventory(ctx["replacement_inventory"]["id"])
        assert replacement_inventory["reserved_units"] == 2, (
            "the winning node must reserve the two rerouted units, got "
            f"{replacement_inventory['reserved_units']}"
        )
        assert replacement_inventory["available_to_promise_units"] == 8, (
            "available_to_promise_units must be 10 on hand less 2 reserved less 0 "
            f"safety stock = 8, got "
            f"{replacement_inventory['available_to_promise_units']}"
        )

        open_windows = find_windows(
            store_id=ctx["replacement_node"]["id"], status="OPEN"
        )
        assert len(open_windows) == 1, (
            "the surviving node must carry exactly one open window after the close, "
            f"got {len(open_windows)}"
        )
        assert open_windows[0]["epoch"] == 3, (
            "the next epoch opens at the previous epoch 2 plus 1, got "
            f"{open_windows[0]['epoch']}"
        )

        replacement_node = read_store(ctx["replacement_node"]["id"])
        assert replacement_node["eligibility_score"] == pytest.approx(73.73, abs=0.01), (
            "the winning node is rescored against its just-closed window to 73.73, "
            f"got {replacement_node['eligibility_score']}"
        )

    def test_deactivation_cascade_reprices_order_and_notifies_customer(self):
        """PRD §3.9: "One customer notification is emitted per affected order by the step-6 run, with its `notification_type` chosen by the pinned rule of §3.7."
        PRD §3.7: "The `notification_type` is chosen by a single pinned rule, first match winning: `CANCELLATION_FULL` when the event is a customer order cancel and the cancelled units equal the order's `total_units`; otherwise `CANCELLATION_PARTIAL` when the event is a customer order cancel or an assignment cancel with `reroute` false; otherwise `DC_FALLBACK` when the event raised the demand lines' `dc_fallback_units`; otherwise `REJECTION_REROUTED` when the event is a rejection whose reroute run created at least one replacement assignment; otherwise `SHORT_PICK_REROUTED` when the event is a short pick whose reroute run created at least one replacement assignment; otherwise `NODE_DEACTIVATED_REROUTED` when the event is a deactivation-driven retry run that created at least one replacement assignment; otherwise `UNROUTABLE`, meaning the released units are still open."
        PRD §3.7: "It carries a `channel` of `EMAIL` or `SMS`, defaulting to `EMAIL`, a `units_affected` count of the units the event moved or removed, a `sent_at_utc` clock instant, and a `body_summary` — a templated one-line summary containing the order's `order_code`, the `notification_type` and the `units_affected` count."
        PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."
        PRD §3.4: "`reroute_attempt_count` counts the order's runs whose `initiated_by` is `SYSTEM_REROUTE` or `SYSTEM_DEACTIVATION`."
        PRD §3.8: "The pre-fee subtotal is that component sum, plus a split penalty of 175 cents for each parcel beyond the first, plus a reroute overhead of 90 cents multiplied by the order's `reroute_attempt_count`."
        PRD §3.8: "The network fee is the pre-fee subtotal multiplied by that rate, rounded half-up to whole cents, and the store cost is the pre-fee subtotal plus the network fee."
        PRD §3.8: "The **provisional** variant, kept live in `provisional_cost_cents` after every routing change and every assignment status change, includes the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — that is, the five non-terminal statuses plus `SHIPPED` — using each one's `provisional_cost_cents`."
        PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."

        Design: Difficulty/transitive_cascade/node_deactivation_cascade_reroutes_to_replacement_node
        """
        ctx = _deactivation_cascade_chain()

        order = read_order(ctx["second_order"]["id"])
        assert order["routing_status"] == "ROUTED", (
            "the deferred retry re-covers every unit, so routing_status must settle "
            f"back on ROUTED, got {order['routing_status']}"
        )
        assert order["reroute_attempt_count"] == 1, (
            "the single SYSTEM_DEACTIVATION run must raise reroute_attempt_count to "
            f"1, got {order['reroute_attempt_count']}"
        )
        assert order["provisional_cost_cents"] == 1145, (
            "the order reprices to 990 component + 90 reroute overhead + 65 network "
            f"fee = 1145 cents, got {order['provisional_cost_cents']}"
        )
        assert order["cost_index_bps"] == 5478, (
            "cost_index_bps must be 1145 * 10000 / 2090 rounded half-up = 5478, got "
            f"{order['cost_index_bps']}"
        )

        order_line = read_order_line(ctx["second_line"]["id"])
        assert order_line["assigned_units"] == 2, (
            "the replacement assignment re-holds both units, got "
            f"{order_line['assigned_units']}"
        )

        notifications = find_notifications(
            order_id=ctx["second_order"]["id"],
            notification_type="NODE_DEACTIVATED_REROUTED",
        )
        assert len(notifications) == 1, (
            "the deactivation-driven retry that created a replacement emits exactly "
            f"one NODE_DEACTIVATED_REROUTED notification, got {len(notifications)}"
        )
        assert notifications[0]["units_affected"] == 2, (
            "units_affected must count the two units the deactivation moved, got "
            f"{notifications[0]['units_affected']}"
        )

    def test_ops_run_closes_empty_peer_window_without_changing_its_posture(self):
        """PRD §3.9: "It executes seven steps in exactly this order, and it answers with the windows it closed, in ascending node `created_at` order."
        PRD §3.9: "`fill_rate` is exactly 1.0000 when `units_promised` is 0, and otherwise `units_shipped` divided by `units_promised` rounded half-up to four decimal places."
        PRD §3.9: "`node_action` is `NONE` when `assignments_created` is 0 — an empty window is inert."
        PRD §3.9: "Each window's `node_action` is decided and applied, and each node's `review_score` is written on the governance-blended basis of §3.3 from the pre-reset counters."
        PRD §3.3: "`review_score` blends two windows: seven tenths of the performance ratio of the window being closed plus three tenths of the performance ratio of the previous closed window, or, when no previous closed window exists, the ratio of the window being closed on its own."
        PRD §3.3: "For any closed performance window, that window's performance ratio is one half of its `fill_rate`, plus three tenths of one minus its `cancellation_rate`, plus two tenths of its cycle-time factor."
        PRD §3.9: "Each window's `status` becomes `CLOSED`, its `closed_at_utc` is set to the clock instant, and each node's `units_committed_epoch` is reset to 0."

        Design: Difficulty/transitive_cascade/node_deactivation_cascade_reroutes_to_replacement_node
        """
        ctx = _deactivation_cascade_chain()

        closed = ctx["closed_windows"]
        assert len(closed) == 2, (
            f"the ops-run must close both nodes' open windows, got {len(closed)}"
        )
        assert closed[0]["store_id"] == ctx["failing_node"]["id"], (
            "closed windows come back in ascending node created_at order, so the "
            "older node's window is first"
        )
        assert closed[1]["store_id"] == ctx["replacement_node"]["id"], (
            "closed windows come back in ascending node created_at order, so the "
            "newer node's window is second"
        )

        peer_window = _window_for(ctx["replacement_node"]["id"], 2)
        assert peer_window["store_id"] == ctx["replacement_node"]["id"], (
            "the peer window must belong to the newly registered node"
        )
        assert peer_window["status"] == "CLOSED", (
            f"the peer window must be closed by the ops-run, got {peer_window['status']}"
        )
        assert peer_window["assignments_created"] == 0, (
            "the newly registered node did no work in epoch 2, got "
            f"{peer_window['assignments_created']}"
        )
        assert peer_window["fill_rate"] == pytest.approx(1.0000, abs=0.0001), (
            "fill_rate is exactly 1.0000 when nothing was promised, got "
            f"{peer_window['fill_rate']}"
        )
        assert peer_window["node_action"] == "NONE", (
            f"an empty window is inert, so node_action must be NONE, got "
            f"{peer_window['node_action']}"
        )

        peer_node = read_store(ctx["replacement_node"]["id"])
        assert peer_node["review_score"] == pytest.approx(75.00, abs=0.01), (
            "the peer node's governance score is 20 capacity + 25 labour + 30 "
            f"performance = 75.00, got {peer_node['review_score']}"
        )
