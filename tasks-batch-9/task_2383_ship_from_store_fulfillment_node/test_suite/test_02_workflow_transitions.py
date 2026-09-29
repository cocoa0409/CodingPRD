"""Workflow transitions: the carrier-pickup machine, the assignment machine and
the cascades that fire when a transition lands.

Every test starts against an empty database and builds its own state.
"""

from datetime import datetime

import pytest

from test_helpers import (
    CARE,
    CARRIER,
    PLANNER,
    cancel_pickup,
    close_pickup,
    cost_comparison,
    depart_pickup,
    find_notifications,
    make_store_associate_headers,
    pickup_version,
    read_assignment,
    read_inventory,
    read_order,
    read_order_line,
    read_packaging,
    read_pickup,
    read_store,
    register_node,
    schedule_pickup,
    set_clock,
    setup_accepted_assignment,
    setup_committed_assignment,
    setup_packed_assignment,
    setup_picked_assignment,
    setup_shipped_assignment,
    ship_payload,
    stock_packaging,
    validate_error,
    validate_paginated,
    validate_success,
)

# --------------------------------------------------------------- instants

_CLOCK_09_00 = "2026-08-03T09:00:00Z"
_ACCEPT_AT = "2026-08-03T09:05:00Z"
_PACK_AT = "2026-08-03T09:30:00Z"
_SHIP_AT = "2026-08-03T09:45:00Z"
_WINDOW_START = "2026-08-03T09:30:00Z"
_WINDOW_END = "2026-08-03T11:00:00Z"

# The reference in-store chain: node S1 (origin zone 4, cutoff minute 1020,
# labour standard 12 min + 3 min/unit at 42 cents/min), SKU-A (800 g, MEDIUM),
# 20 on hand behind a 2-unit floor buffer, one MEDIUM_BOX supply row of 2, a
# 09:30-11:00 pickup window of capacity 2 and a single-line order of 2 units to
# destination zone 4 on GROUND service.
_CHAIN_KWARGS = dict(
    clock=_CLOCK_09_00,
    accept_at=_ACCEPT_AT,
    pack_at=_PACK_AT,
    on_hand_units=20,
    safety_stock_units=2,
    quantity=2,
    destination_zone=4,
    service_level="GROUND",
    packaging_on_hand=2,
    pickup_start=_WINDOW_START,
    pickup_end=_WINDOW_END,
    parcel_capacity=2,
)


def _instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant so comparisons ignore fractional-digit
    formatting."""
    assert isinstance(value, str) and value, f"expected an ISO 8601 instant, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _node_with_scheduled_pickup(
    window_start_utc: str = _WINDOW_START,
    window_end_utc: str = _WINDOW_END,
    parcel_capacity: int = 2,
) -> tuple:
    """Clock at 09:00, one node, one SCHEDULED pickup window holding no parcels."""
    set_clock(_CLOCK_09_00)
    store = register_node("S1")
    pickup = schedule_pickup(
        store["id"],
        carrier_code="ACME",
        window_start_utc=window_start_utc,
        window_end_utc=window_end_utc,
        parcel_capacity=parcel_capacity,
    )
    return store, pickup


def _packed_chain(order_code: str) -> dict:
    """The reference chain driven to PACKED at 09:30."""
    return setup_packed_assignment(order_code=order_code, **_CHAIN_KWARGS)


def _shipped_chain(order_code: str) -> dict:
    """The reference chain driven to SHIPPED at 09:45."""
    return setup_shipped_assignment(
        order_code=order_code, ship_at=_SHIP_AT, **_CHAIN_KWARGS
    )


class TestCarrierPickupMachine:
    def test_pickup_walks_scheduled_to_closed_to_departed(self, api):
        """PRD §3.6: "A new window begins at `status` `SCHEDULED` with `reserved_parcels` 0."

        PRD §3.6: "A coordinator closes a `SCHEDULED` window, moving it `SCHEDULED → CLOSED`, after which no further parcel may be tendered to it — a later tender fails with `ERR_PICKUP_STATE_INVALID` — and the pickup's `version` increments."

        PRD §3.6: "A coordinator records the carrier's departure from a `CLOSED` window, moving it `CLOSED → DEPARTED`, which seals the pickup and freezes `reserved_parcels`, again incrementing `version`."

        PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

        Design: Corner/state_machines/carrier_pickup_walks_scheduled_to_closed_to_departed
        """
        _store, pickup = _node_with_scheduled_pickup()

        assert pickup["status"] == "SCHEDULED", "a new pickup window begins at SCHEDULED"
        assert pickup["reserved_parcels"] == 0, "a new pickup window holds no parcels"
        assert pickup["version"] == 1, "a freshly created pickup is at version 1"

        closed = validate_success(api.close_carrier_pickup(pickup["id"], CARRIER))
        assert closed["status"] == "CLOSED", "close moves the pickup SCHEDULED → CLOSED"
        assert closed["version"] == 2, "close is one mutation, so version becomes 2"

        departed = validate_success(api.depart_carrier_pickup(pickup["id"], CARRIER))
        assert departed["status"] == "DEPARTED", "depart moves the pickup CLOSED → DEPARTED"
        assert departed["version"] == 3, "depart is the second mutation, so version becomes 3"

        final = read_pickup(pickup["id"])
        assert final["status"] == "DEPARTED", "the walk ends at DEPARTED"
        assert final["carrier_code"] == "ACME", "the walk never rewrites carrier_code"
        assert final["parcel_capacity"] == 2, "the walk never rewrites parcel_capacity"
        assert final["reserved_parcels"] == 0, (
            "departure freezes reserved_parcels at the 0 parcels ever tendered"
        )

    def test_depart_is_refused_before_close_then_accepted_after_it(self, api):
        """PRD §3.6: "Attempting to close a window that is not `SCHEDULED`, to make a window depart that is not `CLOSED`, or to cancel a window that is not `SCHEDULED`, is refused with `ERR_PICKUP_STATE_INVALID`; for a cancel that state check precedes the emptiness check, so cancelling an already-departed window reports `ERR_PICKUP_STATE_INVALID` rather than `ERR_PICKUP_HAS_PARCELS`."

        PRD §3.6: "A coordinator records the carrier's departure from a `CLOSED` window, moving it `CLOSED → DEPARTED`, which seals the pickup and freezes `reserved_parcels`, again incrementing `version`."

        PRD §2.5: "Most resources — nodes, SKUs, inventory rows, packaging rows, carrier pickups, customer orders, demand lines, routing runs, fulfillment assignments and performance windows — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by exactly 1 on every mutation of that row."

        Design: Corner/state_machines/depart_is_refused_before_close_and_accepted_after_it
        """
        _store, pickup = _node_with_scheduled_pickup()

        validate_error(
            api.depart_carrier_pickup(pickup["id"], CARRIER),
            "ERR_PICKUP_STATE_INVALID",
        )

        untouched = read_pickup(pickup["id"])
        assert untouched["status"] == "SCHEDULED", (
            "the refused depart left the pickup at SCHEDULED"
        )
        assert untouched["version"] == 1, (
            "a refused transition is not a mutation, so version stays at 1"
        )

        closed = validate_success(api.close_carrier_pickup(pickup["id"], CARRIER))
        assert closed["status"] == "CLOSED", "close moves the pickup SCHEDULED → CLOSED"

        departed = validate_success(api.depart_carrier_pickup(pickup["id"], CARRIER))
        assert departed["status"] == "DEPARTED", (
            "the very same depart succeeds once the window is CLOSED"
        )
        assert departed["version"] == 3, (
            "only the two accepted transitions moved the version, to 3"
        )

    def test_close_is_refused_on_a_departed_pickup(self, api):
        """PRD §3.6: "Attempting to close a window that is not `SCHEDULED`, to make a window depart that is not `CLOSED`, or to cancel a window that is not `SCHEDULED`, is refused with `ERR_PICKUP_STATE_INVALID`; for a cancel that state check precedes the emptiness check, so cancelling an already-departed window reports `ERR_PICKUP_STATE_INVALID` rather than `ERR_PICKUP_HAS_PARCELS`."

        PRD §3.6: "The pickup lifecycle begins at `SCHEDULED` and ends at either `DEPARTED` or `CANCELLED`."

        Design: Corner/state_machines/closing_a_departed_pickup_and_departing_a_cancelled_pickup_are_refused
        """
        _store, pickup = _node_with_scheduled_pickup()
        close_pickup(pickup["id"])
        depart_pickup(pickup["id"])

        validate_error(
            api.close_carrier_pickup(pickup["id"], CARRIER),
            "ERR_PICKUP_STATE_INVALID",
        )

        after = read_pickup(pickup["id"])
        assert after["status"] == "DEPARTED", (
            "a DEPARTED pickup does not re-enter CLOSED"
        )
        assert after["version"] == 3, (
            "the refused close mutated nothing, so version stays at the 3 the walk reached"
        )

    def test_depart_and_close_are_refused_on_a_cancelled_pickup(self, api):
        """PRD §3.6: "Attempting to close a window that is not `SCHEDULED`, to make a window depart that is not `CLOSED`, or to cancel a window that is not `SCHEDULED`, is refused with `ERR_PICKUP_STATE_INVALID`; for a cancel that state check precedes the emptiness check, so cancelling an already-departed window reports `ERR_PICKUP_STATE_INVALID` rather than `ERR_PICKUP_HAS_PARCELS`."

        PRD §3.6: "A coordinator may also cancel a `SCHEDULED` window, moving it `SCHEDULED → CANCELLED`, which releases its slot so a new overlapping window may be scheduled at the node and increments `version`; cancellation is permitted only while `reserved_parcels` is exactly 0, and a window holding parcels is refused with `ERR_PICKUP_HAS_PARCELS`."

        Design: Corner/state_machines/closing_a_departed_pickup_and_departing_a_cancelled_pickup_are_refused
        """
        _store, pickup = _node_with_scheduled_pickup(
            window_start_utc="2026-08-03T12:00:00Z",
            window_end_utc="2026-08-03T13:00:00Z",
        )
        cancel_pickup(pickup["id"])

        validate_error(
            api.depart_carrier_pickup(pickup["id"], CARRIER),
            "ERR_PICKUP_STATE_INVALID",
        )
        validate_error(
            api.close_carrier_pickup(pickup["id"], CARRIER),
            "ERR_PICKUP_STATE_INVALID",
        )

        after = read_pickup(pickup["id"])
        assert after["status"] == "CANCELLED", (
            "CANCELLED has no outgoing edge, so the window stays CANCELLED"
        )
        assert after["version"] == 2, (
            "only the accepted cancel mutated the row, leaving version at 2"
        )


class TestAssignmentMachine:
    def test_assignment_is_born_assigned_with_a_pick_deadline_and_no_timestamps(self):
        """PRD §3.5: "Its `status` begins at `ASSIGNED` and ends at one of the three terminal states `SHIPPED`, `REJECTED` or `CANCELLED`."

        PRD §3.5: "`picked_units` and `shortfall_units` both start at 0; `labor_minutes_actual`, `package_type`, `final_cost_cents`, `cycle_time_minutes`, `accepted_at`, `picked_at`, `packed_at`, `shipped_at`, `reject_reason_code` and `cancel_reason_code` all start null."

        PRD §3.5: "It is created only by a routing run and carries, as system-set references, the `order_id` it serves, the `store_id` that will fulfill it, the `routing_run_id` that created it, and a `carrier_pickup_id` that stays null until the parcel is tendered."

        PRD §3.5: "`reroute_generation` is 0 for an assignment born of a planner run and one greater than its predecessor's for each system reroute that produced it."

        PRD §3.5: "And `pick_deadline_utc` is the earlier of two instants: four hours after the assignment's `created_at`, and the instant on the creation date's UTC calendar day that falls `cutoff_utc_minutes` minutes after midnight UTC."

        PRD §3.5: "`labor_minutes_reserved` is the node's `labor_standard_minutes_per_order` plus its `pick_labor_minutes_per_unit` multiplied by `assigned_units` — the labour standard, committed once and never rewritten."

        PRD §3.5: "`derived_package_type` is the package the provisional cost assumes: take the heaviest `package_class` among the allocation's SKUs by package rank and map it, so `SMALL` becomes `SMALL_BOX`, `MEDIUM` becomes `MEDIUM_BOX` and `LARGE` becomes `LARGE_BOX`."

        PRD §3.8: "The **provisional** variant, written to the assignment's `provisional_cost_cents` at candidate evaluation and at assignment creation, charges the labour *standard*: `labor_standard_minutes_per_order` plus `pick_labor_minutes_per_unit` multiplied by `assigned_units`."

        PRD §3.8: "The assignment's cost is labour cost plus packaging cost plus ship cost."

        PRD §3.4: "Otherwise a `COMMIT` run's `status` is `COMMITTED`."

        PRD §3.4: "When the loop ends, `unfulfillable_units` records whatever remaining demand is left, and `selected_store_count` and `planned_split_count` both equal the number of nodes selected."

        Design: Corner/state_machines/assignment_is_born_assigned_with_a_pick_deadline_and_no_timestamps
        """
        ctx = setup_committed_assignment(
            clock=_CLOCK_09_00,
            on_hand_units=20,
            safety_stock_units=2,
            quantity=2,
            order_code="O-9401",
            with_packaging=False,
            with_pickup=False,
        )
        assignment = ctx["assignment"]

        assert assignment["status"] == "ASSIGNED", "a committed assignment is born ASSIGNED"
        assert assignment["version"] == 1, "a freshly created assignment is at version 1"
        assert assignment["epoch"] == 1, (
            "the assignment is stamped with the epoch of its node's open window"
        )

        assert _instant(assignment["pick_deadline_utc"]) == _instant(
            "2026-08-03T13:00:00Z"
        ), (
            "pick_deadline_utc is the earlier of 09:00 plus four hours and the node's "
            "17:00 cutoff instant"
        )

        assert assignment["picked_units"] == 0, "picked_units starts at 0"
        assert assignment["shortfall_units"] == 0, "shortfall_units starts at 0"
        assert assignment["reroute_generation"] == 0, (
            "an assignment born of a planner run has reroute_generation 0"
        )

        for field in (
            "accepted_at",
            "picked_at",
            "packed_at",
            "shipped_at",
            "carrier_pickup_id",
            "package_type",
            "labor_minutes_actual",
            "final_cost_cents",
            "cycle_time_minutes",
        ):
            assert assignment[field] is None, f"{field} must start null on a new assignment"

        assert assignment["assigned_units"] == 2, (
            "assigned_units is the unit count allocated at creation"
        )
        assert assignment["labor_minutes_reserved"] == pytest.approx(18.00, abs=0.01), (
            "the labour standard is 12 minutes per order plus 3 minutes for each of 2 units"
        )
        assert assignment["derived_package_type"] == "MEDIUM_BOX", (
            "a MEDIUM package_class allocation derives MEDIUM_BOX"
        )
        assert assignment["provisional_cost_cents"] == 1336, (
            "provisional cost is 756 cents of standard labour plus 160 packaging plus 420 freight"
        )

        run = ctx["run"]
        assert run["status"] == "COMMITTED", "a COMMIT run that selected a node is COMMITTED"
        assert run["candidate_count"] == 1, (
            "the single node in the network produced exactly one candidate row"
        )
        assert run["selected_store_count"] == 1, "exactly one node was selected"

    def test_pack_consumes_one_package_and_stamps_actual_labor_minutes(self, api):
        """PRD §3.5: "From either `PICKED` or `SHORT_PICKED`, the associate records packing with the `package_type` actually used, moving the assignment to `PACKED`."

        PRD §3.5: "On success `packed_at` is set to the clock instant, `package_type` is stored, and `labor_minutes_actual` is computed as the elapsed time from `accepted_at` to `packed_at` expressed in whole minutes with any remaining seconds discarded."

        PRD §3.5: "The packaging row's `on_hand_units` is decremented by 1, its `lifetime_consumed_units` is incremented by 1, and its `reorder_flag` is re-derived."

        PRD §3.1: "Creation sets `lifetime_consumed_units` to 0 and derives `reorder_flag` as true exactly when `on_hand_units` is less than or equal to `reorder_point_units`."

        PRD §3.5: "`final_cost_cents` is deliberately *not* written at pack — the final cost variant is sealed at ship — and because both branches rejoin here, that variant consumes `picked_units` regardless of which branch arrived."

        Design: Corner/state_machines/pack_consumes_one_package_and_stamps_actual_labor_minutes
        """
        ctx = setup_picked_assignment(
            clock=_CLOCK_09_00,
            accept_at=_ACCEPT_AT,
            on_hand_units=20,
            safety_stock_units=2,
            quantity=2,
            order_code="O-9301",
            with_packaging=False,
            with_pickup=False,
        )
        store = ctx["store"]
        assignment = ctx["assignment"]

        supply = stock_packaging(store["id"], "MEDIUM_BOX", 2, 1)
        assert supply["reorder_flag"] is False, (
            "2 on hand above a reorder point of 1 leaves the flag down before the pack"
        )

        set_clock(_PACK_AT)
        packed = validate_success(
            api.pack_assignment(
                assignment["id"],
                {"package_type": "MEDIUM_BOX"},
                make_store_associate_headers(store["id"]),
            )
        )

        assert packed["status"] == "PACKED", "pack moves a PICKED assignment to PACKED"
        assert _instant(packed["packed_at"]) == _instant(_PACK_AT), (
            "packed_at is the clock instant of the pack"
        )
        assert packed["labor_minutes_actual"] == 25, (
            "09:05 accepted to 09:30 packed is 25 whole minutes of clocked labour"
        )
        assert packed["package_type"] == "MEDIUM_BOX", (
            "the package_type actually used is stored"
        )
        assert packed["derived_package_type"] == "MEDIUM_BOX", (
            "the allocation's MEDIUM package_class still derives MEDIUM_BOX"
        )
        assert packed["final_cost_cents"] is None, (
            "the final cost variant is sealed at ship, not at pack"
        )

        after = read_packaging(supply["id"])
        assert after["on_hand_units"] == 1, "pack consumes exactly one packaging unit"
        assert after["lifetime_consumed_units"] == 1, (
            "lifetime_consumed_units is incremented by 1"
        )
        assert after["reorder_flag"] is True, (
            "reorder_flag is re-derived and 1 on hand is at the reorder point of 1"
        )
        assert after["version"] == 2, "the packaging row was mutated exactly once"

    def test_repeating_accept_is_rejected_rather_than_absorbed(self, api):
        """PRD §3.5: "A `StoreAssociate` takes ownership of the task by accepting it, moving `ASSIGNED → ACCEPTED` and setting `accepted_at` to the clock instant."

        PRD §3.5: "Acceptance requires, in this order, the acting associate's node to match the assignment's node, the assignment to be at `ASSIGNED`, the owning order's `fulfillment_status` to be anything other than `CANCELLED`, the node's `node_status` to be `ELIGIBLE` or `PROBATION`, the node to have a performance window at `status` `OPEN` (else `ERR_NO_OPEN_WINDOW`), the clock's minute-of-day to be within the node's cutoff, the clock to be strictly before `pick_deadline_utc` (at or after it, the request is refused with `ERR_PICK_DEADLINE_PASSED`), and finally the node's concurrent pick labour to stay within its cap."

        PRD §2.11: "State validity sixth: whether the assignment, order, pickup, node or window is in a status that permits the operation."

        PRD §3.5: "Acceptance increments the assignment's `version`."

        PRD §2.9: "A node's `reserved_labor_minutes` equals the sum of `labor_minutes_reserved` over that node's assignments whose `status` is one of `ASSIGNED`, `ACCEPTED`, `PICKED`, `SHORT_PICKED` or `PACKED`."

        Design: Corner/state_machines/repeating_accept_is_rejected_rather_than_absorbed
        """
        ctx = setup_accepted_assignment(
            clock=_CLOCK_09_00,
            accept_at=_ACCEPT_AT,
            on_hand_units=20,
            safety_stock_units=2,
            quantity=2,
            order_code="O-9601",
            with_packaging=False,
            with_pickup=False,
        )
        store = ctx["store"]
        assignment = ctx["assignment"]

        set_clock("2026-08-03T09:20:00Z")
        validate_error(
            api.accept_assignment(
                assignment["id"], make_store_associate_headers(store["id"])
            ),
            "ERR_ASSIGNMENT_STATE_INVALID",
        )

        after = read_assignment(assignment["id"])
        assert _instant(after["accepted_at"]) == _instant(_ACCEPT_AT), (
            "the refused retry must not re-stamp accepted_at to the 09:20 clock"
        )
        assert after["status"] == "ACCEPTED", "the assignment is still ACCEPTED"
        assert after["version"] == 2, (
            "only the first accept was a mutation, so version stays at 2"
        )

        node = read_store(store["id"])
        assert node["reserved_labor_minutes"] == pytest.approx(18.00, abs=0.01), (
            "the retry did not double-reserve the node's labour standard"
        )

    def test_shipped_assignment_refuses_pack_ship_and_reject(self, api):
        """PRD §3.5: "Packing requires, in this order, the acting node to match, the assignment to be at `PICKED` or `SHORT_PICKED`, and the clock's minute-of-day to be within the node's cutoff."

        PRD §3.6: "The preconditions are checked in this order: the acting node must match the assignment's node; the assignment must be at `PACKED`; the pickup's `status` must be `SCHEDULED`; the node's `node_status` must be `ELIGIBLE` or `PROBATION`; the clock's minute-of-day must still be within the node's cutoff; the clock must sit inside the half-open window, at or after `window_start_utc` and strictly before `window_end_utc`, or the tender is refused with `ERR_PICKUP_WINDOW_CLOSED`; `reserved_parcels` must be strictly below `parcel_capacity`, or the tender is refused with `ERR_PICKUP_CAPACITY_EXCEEDED`; and last of all the named pickup must belong to the same node as the assignment, or the request is refused with `ERR_PICKUP_STORE_MISMATCH`."

        PRD §3.7: "An associate may reject an assignment from either `ASSIGNED` or `ACCEPTED`, supplying a `reject_reason_code` of `NO_STOCK_ON_FLOOR`, `LABOR_UNAVAILABLE`, `DAMAGED_UNITS` or `STORE_CLOSED`."

        PRD §2.11: "State validity sixth: whether the assignment, order, pickup, node or window is in a status that permits the operation."

        PRD §3.5: "The packaging row's `on_hand_units` is decremented by 1, its `lifetime_consumed_units` is incremented by 1, and its `reorder_flag` is re-derived."

        PRD §3.6: "The pickup's `reserved_parcels` increases by 1 and its `version` increments."

        Design: Corner/state_machines/a_shipped_assignment_refuses_pack_ship_reject_and_cancel
        """
        ctx = _shipped_chain("O-9501")
        store = ctx["store"]
        assignment = ctx["assignment"]
        pickup = ctx["pickup"]
        supply = ctx["supply"]
        shipped_version = assignment["version"]
        headers = make_store_associate_headers(store["id"])

        validate_error(
            api.pack_assignment(assignment["id"], {"package_type": "LARGE_BOX"}, headers),
            "ERR_ASSIGNMENT_STATE_INVALID",
        )
        validate_error(
            api.ship_assignment(
                assignment["id"],
                ship_payload(pickup["id"], pickup_version(pickup["id"])),
                headers,
            ),
            "ERR_ASSIGNMENT_STATE_INVALID",
        )
        validate_error(
            api.reject_assignment(
                assignment["id"], {"reject_reason_code": "DAMAGED_UNITS"}, headers
            ),
            "ERR_ASSIGNMENT_STATE_INVALID",
        )

        after = read_assignment(assignment["id"])
        assert after["status"] == "SHIPPED", "SHIPPED is terminal for the assignment"
        assert after["version"] == shipped_version, (
            "three refused transitions bumped nothing on the assignment"
        )
        assert after["reject_reason_code"] is None, (
            "the refused reject stored no reject_reason_code"
        )

        after_supply = read_packaging(supply["id"])
        assert after_supply["on_hand_units"] == 1, (
            "the refused pack consumed no second packaging unit"
        )
        assert after_supply["lifetime_consumed_units"] == 1, (
            "only the accepted pack was ever counted as consumption"
        )

        after_pickup = read_pickup(pickup["id"])
        assert after_pickup["reserved_parcels"] == 1, (
            "the refused ship claimed no second parcel slot"
        )

    def test_shipped_assignment_refuses_care_cancellation(self, api):
        """PRD §3.7: "A `PACKED` assignment can no longer be cancelled — the packaging has already been consumed — and neither can one already in a terminal state; either attempt is refused with `ERR_ASSIGNMENT_STATE_INVALID`."

        PRD §3.5: "Its `status` begins at `ASSIGNED` and ends at one of the three terminal states `SHIPPED`, `REJECTED` or `CANCELLED`."

        Design: Corner/state_machines/a_shipped_assignment_refuses_pack_ship_reject_and_cancel
        """
        ctx = _shipped_chain("O-9502")
        assignment = ctx["assignment"]
        shipped_version = assignment["version"]

        validate_error(
            api.cancel_assignment(
                assignment["id"],
                {"cancel_reason_code": "CUSTOMER_REQUEST", "reroute": False},
                CARE,
            ),
            "ERR_ASSIGNMENT_STATE_INVALID",
        )

        after = read_assignment(assignment["id"])
        assert after["status"] == "SHIPPED", "a SHIPPED assignment cannot be cancelled"
        assert after["cancel_reason_code"] is None, (
            "the refused cancel stored no cancel_reason_code"
        )
        assert after["version"] == shipped_version, (
            "the refused cancel was not a mutation"
        )


class TestTransitionCascades:
    def test_order_cancel_cascades_down_to_assignment_lines_and_inventory(self, api):
        """PRD §3.2: "A full cancel moves `fulfillment_status` from `PENDING` to `CANCELLED`, cancels every non-terminal assignment of the order with cancellation reason `CUSTOMER_REQUEST` and no reroute, turns all released units into each line's `cancelled_units` so that every line ends with `open_units` 0 and `line_status` `CANCELLED`, releases each affected node's inventory reservations along with its `units_committed_epoch` and `reserved_labor_minutes`, recomputes each affected node's `eligibility_score`, emits exactly one customer notification of type `CANCELLATION_FULL`, leaves `final_cost_cents` null, recomputes `provisional_cost_cents` and `cost_index_bps`, and increments the order's `version`."

        PRD §3.1: "Reaching `SHIPPED` decrements `on_hand_units` and drops the reservation in a single step; reaching `REJECTED` or `CANCELLED` drops the reservation and leaves `on_hand_units` untouched."

        PRD §3.1: "`available_to_promise_units` is recomputed from the formula above whenever `reserved_units` moves, whenever the row is adjusted, and at row creation."

        PRD §2.9: "For every demand line, `quantity` equals the sum of `assigned_units`, `shipped_units`, `cancelled_units`, `dc_fallback_units` and `open_units`."

        PRD §3.2: "With those in hand, the status is the first match in this fixed order: `UNROUTED` when no routing run exists for the order; otherwise `ROUTING` when open units is greater than 0 and the pending-reroute predicate holds; otherwise `UNROUTABLE` when covered units is 0; otherwise `ROUTED` when covered units plus cancelled units equals `total_units`; otherwise `PARTIALLY_ROUTED`."

        PRD §3.8: "The **provisional** variant, kept live in `provisional_cost_cents` after every routing change and every assignment status change, includes the order's assignments whose `status` is neither `REJECTED` nor `CANCELLED` — that is, the five non-terminal statuses plus `SHIPPED` — using each one's `provisional_cost_cents`."

        PRD §3.3: "A node with zero closed performance windows uses a flat performance ratio of 0.60 and records `eligibility_score_basis` as `COLD_START`."

        PRD §3.7: "It carries a `channel` of `EMAIL` or `SMS`, defaulting to `EMAIL`, a `units_affected` count of the units the event moved or removed, a `sent_at_utc` clock instant, and a `body_summary` — a templated one-line summary containing the order's `order_code`, the `notification_type` and the `units_affected` count."

        Design: Corner/state_machines/order_cancel_cascades_down_to_assignment_lines_and_inventory
        """
        ctx = setup_committed_assignment(
            clock=_CLOCK_09_00,
            on_hand_units=20,
            safety_stock_units=2,
            quantity=2,
            order_code="O-9701",
            with_packaging=False,
            with_pickup=False,
        )
        store = ctx["store"]
        order = ctx["order"]
        assignment = ctx["assignment"]

        cancelled = validate_success(
            api.cancel_order(order["id"], {"cancel_reason_code": "CUSTOMER_REQUEST"}, CARE)
        )
        assert cancelled["fulfillment_status"] == "CANCELLED", (
            "a full cancel moves fulfillment_status from PENDING to CANCELLED"
        )
        assert cancelled["final_cost_cents"] is None, (
            "a full cancel leaves final_cost_cents null"
        )
        assert cancelled["provisional_cost_cents"] == 0, (
            "the provisional variant excludes the now-CANCELLED assignment"
        )
        assert cancelled["routing_status"] == "UNROUTABLE", (
            "covered units are 0 and no open unit remains, so UNROUTABLE is the first match"
        )

        after_assignment = read_assignment(assignment["id"])
        assert after_assignment["status"] == "CANCELLED", (
            "the order cancel cancelled its non-terminal assignment"
        )
        assert after_assignment["cancel_reason_code"] == "CUSTOMER_REQUEST", (
            "an order-level cancel stamps the reason CUSTOMER_REQUEST"
        )

        line = read_order_line(ctx["line"]["id"])
        assert line["cancelled_units"] == 2, "both released units became cancelled_units"
        assert line["assigned_units"] == 0, "the line holds no assigned units any more"
        assert line["open_units"] == 0, "every line ends with open_units 0"
        assert line["line_status"] == "CANCELLED", "every line ends CANCELLED"

        inventory = read_inventory(ctx["inventory"]["id"])
        assert inventory["reserved_units"] == 0, "the node's reservation was released"
        assert inventory["on_hand_units"] == 20, (
            "a cancellation leaves on_hand_units untouched"
        )
        assert inventory["available_to_promise_units"] == 18, (
            "20 on hand less 0 reserved less the 2-unit floor buffer promises 18"
        )

        node = read_store(store["id"])
        assert node["units_committed_epoch"] == 0, (
            "the epoch commitment was released with the assignment"
        )
        assert node["reserved_labor_minutes"] == pytest.approx(0.00, abs=0.01), (
            "the node's reserved labour returned to 0"
        )
        assert node["eligibility_score"] == pytest.approx(72.00, abs=0.01), (
            "24 capacity plus 30 labour plus 18 cold-start performance is 72.00"
        )

        notifications = find_notifications(order_id=order["id"])
        assert len(notifications) == 1, "a full cancel emits exactly one notification"
        assert notifications[0]["notification_type"] == "CANCELLATION_FULL", (
            "the cancelled units equal total_units, so the type is CANCELLATION_FULL"
        )
        assert notifications[0]["units_affected"] == 2, (
            "units_affected counts the 2 units the cancel removed"
        )

    def test_assignment_ship_bubbles_up_to_order_shipped_with_final_cost(self, api):
        """PRD §3.6: "The assignment's `status` becomes `SHIPPED`, `shipped_at` is set to the clock instant, `carrier_pickup_id` is stored, and `cycle_time_minutes` is computed as the elapsed time from `created_at` to `shipped_at` in whole minutes with remaining seconds discarded."

        PRD §3.8: "The **final** variant, written to `final_cost_cents` at ship, charges *actual* clocked labour: the greater of `labor_minutes_actual` and a 10-minute billable minimum, where `labor_minutes_actual` is the whole minutes from `accepted_at` to `packed_at` with remaining seconds discarded."

        PRD §3.8: "Its charged units are `picked_units`, and its charged package is the `package_type` the associate actually recorded at pack."

        PRD §3.6: "From `PENDING`, a ship that leaves `shipped_units` above 0 with that same sum exactly equal to `total_units` moves the order straight to `SHIPPED`, writing `final_cost_cents` on the final variant, setting `cost_variance_cents` to `final_cost_cents` minus `provisional_cost_cents`, and recomputing `cost_index_bps` against the final figure."

        PRD §3.8: "The **final** variant, written to `final_cost_cents` when `fulfillment_status` becomes `SHIPPED`, includes only assignments at `status` `SHIPPED`, using each one's `final_cost_cents`; because the component sum changes, the fee tier can land in a different band than the provisional pass did, which is exactly what `cost_variance_cents` — `final_cost_cents` minus `provisional_cost_cents` — is there to expose."

        PRD §3.8: "The overhead fee rate is then keyed on the pre-fee subtotal: 6.0 percent when the subtotal is strictly below 2000 cents, 4.5 percent when it is strictly below 5000 cents, and 3.0 percent at or above 5000 cents."

        PRD §3.8: "The distribution-centre baseline is a per-zone handling figure plus a per-unit charge: 1450 cents for `destination_zone` 1, then 1560, 1700, 1850, 2010, 2180, 2360 and 2550 cents for zones 2 through 8, plus 120 cents multiplied by the order's `total_units`."

        PRD §3.8: "The cost index in basis points is the store cost multiplied by 10000, divided by the baseline, rounded half-up — and 0 when the baseline is 0."

        PRD §3.8: "Savings versus the distribution centre are the baseline minus the store cost, and may of course be negative."

        PRD §3.6: "For each line's SKU, the node's inventory row has `on_hand_units` reduced by the line's `units_picked` and `reserved_units` reduced by its `units_assigned`, and `available_to_promise_units` is recomputed."

        PRD §3.6: "Each served demand line has its `shipped_units` raised by the line's `units_picked` and its `assigned_units` reduced by its `units_assigned`."

        PRD §3.6: "The pickup's `reserved_parcels` increases by 1 and its `version` increments."

        Design: Corner/state_machines/assignment_ship_bubbles_up_to_order_shipped_with_final_cost
        """
        ctx = _packed_chain("O-9801")
        store = ctx["store"]
        assignment = ctx["assignment"]
        pickup = ctx["pickup"]

        set_clock(_SHIP_AT)
        shipped = validate_success(
            api.ship_assignment(
                assignment["id"],
                ship_payload(pickup["id"], pickup_version(pickup["id"])),
                make_store_associate_headers(store["id"]),
            )
        )

        assert shipped["status"] == "SHIPPED", "the tender moves the assignment PACKED → SHIPPED"
        assert _instant(shipped["shipped_at"]) == _instant(_SHIP_AT), (
            "shipped_at is the clock instant of the tender"
        )
        assert shipped["cycle_time_minutes"] == 45, (
            "09:00 created to 09:45 shipped is 45 whole minutes of cycle time"
        )
        assert shipped["final_cost_cents"] == 1630, (
            "1050 cents of clocked labour plus 160 packaging plus 420 freight"
        )

        order = read_order(ctx["order"]["id"])
        assert order["fulfillment_status"] == "SHIPPED", (
            "the last unresolved unit shipping moves the order to SHIPPED"
        )
        assert order["shipped_units"] == 2, "both ordered units have shipped"
        assert order["final_cost_cents"] == 1728, (
            "a 1630-cent component sum takes the 6.0 percent tier, adding a 98-cent fee"
        )
        assert order["provisional_cost_cents"] == 1416, (
            "the provisional pass carried a 1336-cent component sum plus an 80-cent fee"
        )
        assert order["cost_variance_cents"] == 312, (
            "cost_variance_cents is 1728 final minus 1416 provisional"
        )
        assert order["cost_index_bps"] == 8268, (
            "1728 * 10000 / 2090 rounds half up to 8268 basis points"
        )

        line = read_order_line(ctx["line"]["id"])
        assert line["shipped_units"] == 2, "the demand line's shipped_units rose by 2"
        assert line["assigned_units"] == 0, "the demand line no longer holds assigned units"
        assert line["open_units"] == 0, "no open unit remains on the line"
        assert line["line_status"] == "SHIPPED", "the line's units have shipped"

        inventory = read_inventory(ctx["inventory"]["id"])
        assert inventory["on_hand_units"] == 18, "the 2 picked units left the building"
        assert inventory["reserved_units"] == 0, "the reservation was dropped at ship"
        assert inventory["available_to_promise_units"] == 16, (
            "18 on hand less 0 reserved less the 2-unit floor buffer promises 16"
        )

        after_pickup = read_pickup(pickup["id"])
        assert after_pickup["reserved_parcels"] == 1, "the tender claimed one parcel slot"
        assert after_pickup["version"] == 2, "the tender mutated the pickup exactly once"

        comparison = cost_comparison(order["id"])
        assert comparison["variant"] == "FINAL", (
            "a SHIPPED order reports the FINAL variant"
        )
        assert comparison["dc_baseline_cost_cents"] == 2090, (
            "zone 4 handling of 1850 plus 120 cents for each of 2 units is 2090"
        )
        assert comparison["savings_vs_dc_cents"] == 362, (
            "2090 baseline less 1728 store cost saves 362 cents"
        )

    def test_window_close_promotes_no_node_when_the_window_is_clean(self, api):
        """PRD §3.9: "From that set: `assignments_created` is the count of all of them; `assignments_shipped`, `assignments_rejected` and `assignments_cancelled` are the counts at `status` `SHIPPED`, `REJECTED` and `CANCELLED` respectively; `units_promised` is the sum of `assigned_units` over all of them; and `units_shipped` is the sum of `picked_units` over those at `SHIPPED`."

        PRD §3.9: "`fill_rate` is exactly 1.0000 when `units_promised` is 0, and otherwise `units_shipped` divided by `units_promised` rounded half-up to four decimal places."

        PRD §3.9: "`avg_cycle_time_minutes` is exactly 0.00 when `assignments_shipped` is 0, and otherwise the sum of `cycle_time_minutes` over the shipped assignments divided by `assignments_shipped`, rounded half-up to two decimal places."

        PRD §3.9: "`cancellation_rate` is exactly 0.0000 when `assignments_created` is 0, and otherwise `assignments_rejected` plus `assignments_cancelled`, divided by `assignments_created`, rounded half-up to four decimal places."

        PRD §3.9: "`breached` is true exactly when `breach_flags` is non-empty."

        PRD §3.9: "`store_cost_per_order_cents` is 0 when `assignments_shipped` is 0, and otherwise the sum of `final_cost_cents` over the shipped assignments divided by `assignments_shipped`, rounded half-up to whole cents."

        PRD §3.9: "`dc_cost_per_order_cents` is 0 when `assignments_shipped` is 0, and otherwise computed by taking, for each shipped assignment, the distribution-centre base charge for its order's `destination_zone` plus 120 cents multiplied by that assignment's `picked_units`, summing those across the shipped assignments, dividing by `assignments_shipped`, and rounding half-up to whole cents."

        PRD §3.9: "The window's `cost_index_bps` is 0 when `dc_cost_per_order_cents` is 0, and otherwise `store_cost_per_order_cents` multiplied by 10000, divided by `dc_cost_per_order_cents`, rounded half-up."

        PRD §3.9: "`cost_disadvantaged` is true exactly when that index is strictly greater than 11000 basis points."

        PRD §3.9: "Otherwise it is `DEACTIVATION` when the window is breached and the node's `consecutive_breach_windows` plus 1 reaches 2; `PROBATION` when the window is breached, the node's `node_status` is `ELIGIBLE`, and `consecutive_breach_windows` plus 1 is still below 2; `RECOVERY` when the window is not breached and the node's `node_status` is `PROBATION`; and `NONE` in every other case."

        PRD §3.9: "`consecutive_breach_windows` is then set to 0 when the window was non-empty and not breached, incremented by 1 when the window was non-empty and breached, and left completely unchanged when the window was empty — so an empty window never changes posture and never resets the breach counter."

        PRD §3.9: "Each window's `status` becomes `CLOSED`, its `closed_at_utc` is set to the clock instant, and each node's `units_committed_epoch` is reset to 0."

        PRD §3.9: "A new performance window at `status` `OPEN` and at the previous `epoch` plus 1 is created for every node whose `node_status` is `ELIGIBLE` or `PROBATION`, with `opened_at_utc` at the clock instant and `closed_at_utc` null."

        PRD §3.9: "Every node whose `node_status` is `ELIGIBLE` or `PROBATION` has its `eligibility_score` recomputed against the just-closed window, with `eligibility_score_basis` set to `TRAILING_WINDOW`."

        PRD §3.9: "Each window's `node_action` is decided and applied, and each node's `review_score` is written on the governance-blended basis of §3.3 from the pre-reset counters."

        PRD §3.3: "`review_score` blends two windows: seven tenths of the performance ratio of the window being closed plus three tenths of the performance ratio of the previous closed window, or, when no previous closed window exists, the ratio of the window being closed on its own."

        PRD §3.3: "For any closed performance window, that window's performance ratio is one half of its `fill_rate`, plus three tenths of one minus its `cancellation_rate`, plus two tenths of its cycle-time factor."

        Design: Corner/state_machines/window_close_promotes_no_node_when_the_window_is_clean
        """
        ctx = _shipped_chain("O-9901")
        store = ctx["store"]

        set_clock("2026-08-03T18:00:00Z")
        closed_windows = validate_success(api.close_performance_windows(PLANNER))

        assert len(closed_windows) == 1, "the run closed exactly the one open window"
        window = closed_windows[0]
        assert window["epoch"] == 1, "the closed window is the node's epoch-1 window"
        assert window["status"] == "CLOSED", "step 4 moves the window to CLOSED"
        assert _instant(window["closed_at_utc"]) == _instant("2026-08-03T18:00:00Z"), (
            "closed_at_utc is the clock instant of the run"
        )

        assert window["assignments_created"] == 1, "the window holds one assignment"
        assert window["assignments_shipped"] == 1, "that assignment shipped"
        assert window["assignments_rejected"] == 0, "nothing was rejected"
        assert window["assignments_cancelled"] == 0, "nothing was cancelled"
        assert window["units_promised"] == 2, "2 units were promised in the epoch"
        assert window["units_shipped"] == 2, "both promised units shipped"
        assert window["fill_rate"] == pytest.approx(1.0000, abs=0.01), (
            "2 shipped over 2 promised is a fill rate of 1.0000"
        )
        assert window["avg_cycle_time_minutes"] == pytest.approx(45.00, abs=0.01), (
            "the single shipped assignment took 45 minutes"
        )
        assert window["cancellation_rate"] == pytest.approx(0.0000, abs=0.01), (
            "no rejection and no cancellation over one assignment is 0.0000"
        )
        assert window["breach_flags"] == [], "a clean window raises no breach marker"
        assert window["breached"] is False, "breached is false when breach_flags is empty"

        assert window["store_cost_per_order_cents"] == 1630, (
            "the one shipped assignment's final cost is the per-order store cost"
        )
        assert window["dc_cost_per_order_cents"] == 2090, (
            "zone 4 handling of 1850 plus 120 cents for each of 2 picked units is 2090"
        )
        assert window["cost_index_bps"] == 7799, (
            "1630 * 10000 / 2090 rounds half up to 7799 basis points"
        )
        assert window["cost_disadvantaged"] is False, (
            "7799 basis points is not above the 11000 threshold"
        )
        assert window["node_action"] == "NONE", (
            "an unbreached window at an ELIGIBLE node falls through to NONE"
        )

        node = read_store(store["id"])
        assert node["node_status"] == "ELIGIBLE", "a clean window changes no posture"
        assert node["consecutive_breach_windows"] == 0, (
            "a non-empty unbreached window sets the breach counter to 0"
        )
        assert node["review_score"] == pytest.approx(83.60, abs=0.01), (
            "23.6 capacity on the pre-reset commitment plus 30 labour plus 30 performance"
        )
        assert node["units_committed_epoch"] == 0, (
            "step 4 resets the node's epoch commitment to 0"
        )
        assert node["eligibility_score"] == pytest.approx(84.00, abs=0.01), (
            "step 7 rescores 24 capacity plus 30 labour plus 30 performance"
        )
        assert node["eligibility_score_basis"] == "TRAILING_WINDOW", (
            "step 7 re-bases the score on the just-closed window"
        )

        rows, meta = validate_paginated(
            api.list_performance_windows(PLANNER, params={"store_id": store["id"]})
        )
        assert meta["total_count"] == 2, (
            "the node now owns the closed epoch-1 window and a fresh one"
        )
        open_rows = [row for row in rows if row["status"] == "OPEN"]
        assert len(open_rows) == 1, "exactly one window is OPEN after the run"
        assert open_rows[0]["epoch"] == 2, "the new window opens at the previous epoch plus 1"
        assert open_rows[0]["closed_at_utc"] is None, "the new window is not closed"
