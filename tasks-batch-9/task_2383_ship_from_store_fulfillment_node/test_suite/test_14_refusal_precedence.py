"""Refusal precedence: which single error comes back when a request breaks two
rules from two different evaluation bands of the PRD's pinned order (§2.11).

Every scenario below is built twice: once with both conditions true (the
conflict, which pins the winner) and once with only the lower-priority
condition true (the sibling, which proves that losing branch is live at all).
"""

from test_helpers import (
    accept,
    commit_routing,
    find_assignment,
    pack,
    pick_full,
    pickup_version,
    read_assignment,
    read_packaging,
    read_pickup,
    register_node,
    register_sku,
    schedule_pickup,
    set_clock,
    setup_order_with_lines,
    ship,
    stock_inventory,
    stock_packaging,
    make_store_associate_headers,
    ship_payload,
    validate_error,
)

CLOCK_OPEN = "2026-08-03T09:00:00Z"
CLOCK_FIRST_ACCEPT = "2026-08-03T09:05:00Z"
CLOCK_FIRST_PACK = "2026-08-03T09:20:00Z"
CLOCK_SECOND_ACCEPT = "2026-08-03T09:25:00Z"
CLOCK_SECOND_PACK = "2026-08-03T09:40:00Z"
WINDOW_START = "2026-08-03T09:00:00Z"
WINDOW_END = "2026-08-03T12:00:00Z"


# ======================================================================
# shared preambles
# ======================================================================


def _commit_single_line_order(sku, order_code, customer_ref, quantity=2):
    """Intake a one-line GROUND order to zone 4 and commit it to the network."""
    built = setup_order_with_lines(
        [(sku["id"], quantity, sku["unit_price_cents"])],
        order_code=order_code,
        customer_ref=customer_ref,
        destination_zone=4,
        service_level="GROUND",
        promised_ship_by_utc="2026-08-03T16:00:00Z",
    )
    commit_routing(built["order"]["id"])
    return built["order"]


def _packed_and_picked_sharing_one_box():
    """S1 holds a single MEDIUM_BOX. The first assignment consumes it at pack;
    the second is left at PICKED with the supply already at 0."""
    set_clock(CLOCK_OPEN)
    store = register_node("S1")
    sku = register_sku("SKU-A")
    inventory = stock_inventory(store["id"], sku["id"], 12, 2)
    supply = stock_packaging(store["id"], "MEDIUM_BOX", 1, 1)

    order_one = _commit_single_line_order(sku, "O-5001", "C-11")
    first = find_assignment(order_id=order_one["id"], store_id=store["id"])
    order_two = _commit_single_line_order(sku, "O-5002", "C-12")
    second = find_assignment(order_id=order_two["id"], store_id=store["id"])

    set_clock(CLOCK_FIRST_ACCEPT)
    accept(first["id"], store["id"])
    pick_full(first["id"], store["id"])
    set_clock(CLOCK_FIRST_PACK)
    pack(first["id"], store["id"], "MEDIUM_BOX")

    set_clock(CLOCK_SECOND_ACCEPT)
    accept(second["id"], store["id"])
    pick_full(second["id"], store["id"])

    return {
        "store": store,
        "sku": sku,
        "inventory": inventory,
        "supply": read_packaging(supply["id"]),
        "packed": read_assignment(first["id"]),
        "picked": read_assignment(second["id"]),
    }


def _full_pickup_with_packed_sibling():
    """S1's only pickup window has parcel_capacity 1 and is already full; a
    second assignment sits at PACKED, ready to tender into it."""
    set_clock(CLOCK_OPEN)
    store = register_node("S1")
    sku = register_sku("SKU-A")
    inventory = stock_inventory(store["id"], sku["id"], 12, 2)
    supply = stock_packaging(store["id"], "MEDIUM_BOX", 5, 1)
    pickup = schedule_pickup(
        store["id"],
        window_start_utc=WINDOW_START,
        window_end_utc=WINDOW_END,
        parcel_capacity=1,
    )

    order_one = _commit_single_line_order(sku, "O-5101", "C-13")
    shipped = find_assignment(order_id=order_one["id"], store_id=store["id"])
    order_two = _commit_single_line_order(sku, "O-5102", "C-14")
    waiting = find_assignment(order_id=order_two["id"], store_id=store["id"])

    set_clock(CLOCK_FIRST_ACCEPT)
    accept(shipped["id"], store["id"])
    pick_full(shipped["id"], store["id"])
    set_clock(CLOCK_FIRST_PACK)
    pack(shipped["id"], store["id"], "MEDIUM_BOX")
    ship(shipped["id"], store["id"], pickup["id"])

    set_clock(CLOCK_SECOND_ACCEPT)
    accept(waiting["id"], store["id"])
    pick_full(waiting["id"], store["id"])
    set_clock(CLOCK_SECOND_PACK)
    pack(waiting["id"], store["id"], "MEDIUM_BOX")

    return {
        "store": store,
        "inventory": inventory,
        "supply": supply,
        "pickup": read_pickup(pickup["id"]),
        "shipped": read_assignment(shipped["id"]),
        "packed": read_assignment(waiting["id"]),
    }


def _shipped_and_packed_with_foreign_pickup():
    """S1 fulfills everything; S2 stocks nothing so it never wins routing but
    still owns a pickup window pk2 that is foreign to every S1 assignment."""
    set_clock(CLOCK_OPEN)
    store = register_node("S1")
    other_store = register_node("S2")
    sku = register_sku("SKU-A")
    inventory = stock_inventory(store["id"], sku["id"], 12, 2)
    stock_packaging(store["id"], "MEDIUM_BOX", 5, 1)
    own_pickup = schedule_pickup(
        store["id"],
        window_start_utc=WINDOW_START,
        window_end_utc=WINDOW_END,
        parcel_capacity=5,
    )
    foreign_pickup = schedule_pickup(
        other_store["id"],
        window_start_utc=WINDOW_START,
        window_end_utc=WINDOW_END,
        parcel_capacity=5,
    )

    order_one = _commit_single_line_order(sku, "O-5201", "C-15")
    shipped = find_assignment(order_id=order_one["id"], store_id=store["id"])

    set_clock(CLOCK_FIRST_ACCEPT)
    accept(shipped["id"], store["id"])
    pick_full(shipped["id"], store["id"])
    set_clock(CLOCK_FIRST_PACK)
    pack(shipped["id"], store["id"], "MEDIUM_BOX")
    ship(shipped["id"], store["id"], own_pickup["id"])

    order_two = _commit_single_line_order(sku, "O-5202", "C-16")
    waiting = find_assignment(order_id=order_two["id"], store_id=store["id"])

    set_clock(CLOCK_SECOND_ACCEPT)
    accept(waiting["id"], store["id"])
    pick_full(waiting["id"], store["id"])
    set_clock(CLOCK_SECOND_PACK)
    pack(waiting["id"], store["id"], "MEDIUM_BOX")

    return {
        "store": store,
        "other_store": other_store,
        "inventory": inventory,
        "own_pickup": read_pickup(own_pickup["id"]),
        "foreign_pickup": read_pickup(foreign_pickup["id"]),
        "shipped": read_assignment(shipped["id"]),
        "packed": read_assignment(waiting["id"]),
    }


def _assigned_task_at_s1_with_second_node():
    """One S1 assignment deliberately left at ASSIGNED, plus a second node S2
    whose associate identity can be used to violate node scope."""
    set_clock(CLOCK_OPEN)
    store = register_node("S1")
    other_store = register_node("S2")
    sku = register_sku("SKU-A")
    inventory = stock_inventory(store["id"], sku["id"], 12, 2)
    supply = stock_packaging(store["id"], "MEDIUM_BOX", 5, 1)

    order = _commit_single_line_order(sku, "O-5301", "C-17")
    assignment = find_assignment(order_id=order["id"], store_id=store["id"])

    return {
        "store": store,
        "other_store": other_store,
        "inventory": inventory,
        "supply": supply,
        "assignment": read_assignment(assignment["id"]),
    }


# ======================================================================
# state band (sixth) versus capacity/constraint band (ninth), on pack
# ======================================================================


class TestPackStateOutranksPackagingDepletion:
    def test_pack_on_already_packed_assignment_reports_state_over_packaging_depleted(
        self, api
    ):
        """PRD §3.5: "Packing requires, in this order, the acting node to match, the assignment to be at `PICKED` or `SHORT_PICKED`, and the clock's minute-of-day to be within the node's cutoff."
        PRD §3.7: "A `PACKED` assignment can no longer be cancelled — the packaging has already been consumed — and neither can one already in a terminal state; either attempt is refused with `ERR_ASSIGNMENT_STATE_INVALID`."
        PRD §3.5: "A packaging row must exist at that node for the chosen `package_type` with `on_hand_units` of at least 1, or the request is refused with `ERR_PACKAGING_DEPLETED`."
        PRD §2.11: "Checks run in these bands, in this sequence."
        PRD §2.11: "State validity sixth: whether the assignment, order, pickup, node or window is in a status that permits the operation."
        PRD §2.11: "Capacity and constraint checks ninth: concurrent pick labour, parcel capacity, packaging availability and adequacy, pick-quantity arithmetic, and uniqueness."
        PRD §3.5: "The packaging row's `on_hand_units` is decremented by 1, its `lifetime_consumed_units` is incremented by 1, and its `reorder_flag` is re-derived."

        Design: Difficulty/priority_pair_validation_conflict/assignment_state_error_outranks_packaging_depletion_on_repack
        """
        ctx = _packed_and_picked_sharing_one_box()
        assert ctx["packed"]["status"] == "PACKED", (
            "setup expected the first assignment to have reached PACKED"
        )
        assert ctx["supply"]["on_hand_units"] == 0, (
            "setup expected that pack to have consumed the node's last MEDIUM_BOX"
        )

        response = api.pack_assignment(
            ctx["packed"]["id"],
            {"package_type": "MEDIUM_BOX"},
            make_store_associate_headers(ctx["store"]["id"]),
        )

        validate_error(response, "ERR_ASSIGNMENT_STATE_INVALID")

        after = read_assignment(ctx["packed"]["id"])
        assert after["status"] == "PACKED", (
            "the refused re-pack must leave the assignment at PACKED"
        )
        assert after["package_type"] == "MEDIUM_BOX", (
            "the refused re-pack must leave the recorded package_type untouched"
        )
        supply = read_packaging(ctx["supply"]["id"])
        assert supply["on_hand_units"] == 0, (
            "a refused pack consumes no packaging unit"
        )
        assert supply["reorder_flag"] is True, (
            "a depleted packaging row at or below its reorder point flags reorder"
        )

    def test_pack_on_picked_assignment_with_no_box_left_reports_packaging_depleted(
        self, api
    ):
        """PRD §3.5: "A packaging row must exist at that node for the chosen `package_type` with `on_hand_units` of at least 1, or the request is refused with `ERR_PACKAGING_DEPLETED`."
        PRD §3.5: "Packing requires, in this order, the acting node to match, the assignment to be at `PICKED` or `SHORT_PICKED`, and the clock's minute-of-day to be within the node's cutoff."
        PRD §3.5: "On success `packed_at` is set to the clock instant, `package_type` is stored, and `labor_minutes_actual` is computed as the elapsed time from `accepted_at` to `packed_at` expressed in whole minutes with any remaining seconds discarded."

        Design: Difficulty/priority_pair_validation_conflict/assignment_state_error_outranks_packaging_depletion_on_repack
        """
        ctx = _packed_and_picked_sharing_one_box()
        assert ctx["picked"]["status"] == "PICKED", (
            "setup expected the sibling assignment to sit at PICKED"
        )

        response = api.pack_assignment(
            ctx["picked"]["id"],
            {"package_type": "MEDIUM_BOX"},
            make_store_associate_headers(ctx["store"]["id"]),
        )

        validate_error(response, "ERR_PACKAGING_DEPLETED")

        after = read_assignment(ctx["picked"]["id"])
        assert after["status"] == "PICKED", (
            "a pack refused for packaging depletion must not move the assignment"
        )
        assert after["package_type"] is None, (
            "package_type is only stored on a successful pack"
        )
        assert after["packed_at"] is None, (
            "packed_at is only stamped on a successful pack"
        )


# ======================================================================
# temporal band (eighth) versus capacity/constraint band (ninth), on ship
# ======================================================================


class TestShipWindowClosedOutranksPickupCapacity:
    def test_ship_at_window_end_reports_window_closed_over_capacity_exceeded(self, api):
        """PRD §3.6: "The preconditions are checked in this order: the acting node must match the assignment's node; the assignment must be at `PACKED`; the pickup's `status` must be `SCHEDULED`; the node's `node_status` must be `ELIGIBLE` or `PROBATION`; the clock's minute-of-day must still be within the node's cutoff; the clock must sit inside the half-open window, at or after `window_start_utc` and strictly before `window_end_utc`, or the tender is refused with `ERR_PICKUP_WINDOW_CLOSED`; `reserved_parcels` must be strictly below `parcel_capacity`, or the tender is refused with `ERR_PICKUP_CAPACITY_EXCEEDED`; and last of all the named pickup must belong to the same node as the assignment, or the request is refused with `ERR_PICKUP_STORE_MISMATCH`."
        PRD §2.11: "Checks run in these bands, in this sequence."
        PRD §2.11: "Temporal gates eighth: cutoffs, pick deadlines, carrier windows, window geometry and clock monotonicity."
        PRD §2.11: "Capacity and constraint checks ninth: concurrent pick labour, parcel capacity, packaging availability and adequacy, pick-quantity arithmetic, and uniqueness."
        PRD §3.6: "The pickup's `reserved_parcels` increases by 1 and its `version` increments."

        Design: Difficulty/priority_pair_validation_conflict/pickup_window_closed_outranks_pickup_capacity_on_ship
        """
        ctx = _full_pickup_with_packed_sibling()
        assert ctx["pickup"]["reserved_parcels"] == 1, (
            "setup expected the window to be full at its parcel_capacity of 1"
        )

        # The clock lands exactly on the exclusive window end, so the window is
        # closed AND the window is full at the same instant.
        set_clock(WINDOW_END)
        response = api.ship_assignment(
            ctx["packed"]["id"],
            ship_payload(ctx["pickup"]["id"], pickup_version(ctx["pickup"]["id"])),
            make_store_associate_headers(ctx["store"]["id"]),
        )

        validate_error(response, "ERR_PICKUP_WINDOW_CLOSED")

        after = read_assignment(ctx["packed"]["id"])
        assert after["status"] == "PACKED", (
            "the refused tender must leave the assignment at PACKED"
        )
        assert after["carrier_pickup_id"] is None, (
            "carrier_pickup_id is only stored on a successful tender"
        )
        pickup = read_pickup(ctx["pickup"]["id"])
        assert pickup["reserved_parcels"] == 1, (
            "a refused tender claims no parcel slot"
        )
        assert pickup["status"] == "SCHEDULED", (
            "an expired window is still SCHEDULED until a coordinator closes it"
        )

    def test_ship_into_full_pickup_inside_window_reports_capacity_exceeded(self, api):
        """PRD §3.6: "The preconditions are checked in this order: the acting node must match the assignment's node; the assignment must be at `PACKED`; the pickup's `status` must be `SCHEDULED`; the node's `node_status` must be `ELIGIBLE` or `PROBATION`; the clock's minute-of-day must still be within the node's cutoff; the clock must sit inside the half-open window, at or after `window_start_utc` and strictly before `window_end_utc`, or the tender is refused with `ERR_PICKUP_WINDOW_CLOSED`; `reserved_parcels` must be strictly below `parcel_capacity`, or the tender is refused with `ERR_PICKUP_CAPACITY_EXCEEDED`; and last of all the named pickup must belong to the same node as the assignment, or the request is refused with `ERR_PICKUP_STORE_MISMATCH`."
        PRD §3.6: "The pickup's `reserved_parcels` increases by 1 and its `version` increments."

        Design: Difficulty/priority_pair_validation_conflict/pickup_window_closed_outranks_pickup_capacity_on_ship
        """
        ctx = _full_pickup_with_packed_sibling()

        # 11:00 is strictly inside the half-open window, so capacity is the
        # only precondition that can fail.
        set_clock("2026-08-03T11:00:00Z")
        response = api.ship_assignment(
            ctx["packed"]["id"],
            ship_payload(ctx["pickup"]["id"], pickup_version(ctx["pickup"]["id"])),
            make_store_associate_headers(ctx["store"]["id"]),
        )

        validate_error(response, "ERR_PICKUP_CAPACITY_EXCEEDED")

        after = read_assignment(ctx["packed"]["id"])
        assert after["status"] == "PACKED", (
            "a tender refused for capacity must leave the assignment at PACKED"
        )
        assert after["shipped_at"] is None, (
            "shipped_at is only stamped on a successful tender"
        )
        assert after["final_cost_cents"] is None, (
            "final_cost_cents is sealed at ship, so a refused tender leaves it null"
        )
        pickup = read_pickup(ctx["pickup"]["id"])
        assert pickup["reserved_parcels"] == 1, (
            "reserved_parcels must stay at the capacity it already reached"
        )


# ======================================================================
# state band (sixth) versus referential band (tenth), on ship
# ======================================================================


class TestShipStateOutranksPickupStoreMismatch:
    def test_reship_of_shipped_assignment_onto_foreign_pickup_reports_state_error(
        self, api
    ):
        """PRD §3.6: "The preconditions are checked in this order: the acting node must match the assignment's node; the assignment must be at `PACKED`; the pickup's `status` must be `SCHEDULED`; the node's `node_status` must be `ELIGIBLE` or `PROBATION`; the clock's minute-of-day must still be within the node's cutoff; the clock must sit inside the half-open window, at or after `window_start_utc` and strictly before `window_end_utc`, or the tender is refused with `ERR_PICKUP_WINDOW_CLOSED`; `reserved_parcels` must be strictly below `parcel_capacity`, or the tender is refused with `ERR_PICKUP_CAPACITY_EXCEEDED`; and last of all the named pickup must belong to the same node as the assignment, or the request is refused with `ERR_PICKUP_STORE_MISMATCH`."
        PRD §3.7: "A `PACKED` assignment can no longer be cancelled — the packaging has already been consumed — and neither can one already in a terminal state; either attempt is refused with `ERR_ASSIGNMENT_STATE_INVALID`."
        PRD §2.11: "Checks run in these bands, in this sequence."
        PRD §2.11: "State validity sixth: whether the assignment, order, pickup, node or window is in a status that permits the operation."
        PRD §2.11: "Referential coupling tenth: whether a pickup belongs to the assignment's node, whether a pick line belongs to the assignment, whether a pickup is empty enough to cancel."
        PRD §3.6: "The assignment's `status` becomes `SHIPPED`, `shipped_at` is set to the clock instant, `carrier_pickup_id` is stored, and `cycle_time_minutes` is computed as the elapsed time from `created_at` to `shipped_at` in whole minutes with remaining seconds discarded."

        Design: Difficulty/priority_pair_validation_conflict/assignment_state_error_outranks_pickup_store_mismatch_on_reship
        """
        ctx = _shipped_and_packed_with_foreign_pickup()
        assert ctx["shipped"]["status"] == "SHIPPED", (
            "setup expected the first assignment to be terminal at SHIPPED"
        )

        response = api.ship_assignment(
            ctx["shipped"]["id"],
            ship_payload(
                ctx["foreign_pickup"]["id"], pickup_version(ctx["foreign_pickup"]["id"])
            ),
            make_store_associate_headers(ctx["store"]["id"]),
        )

        validate_error(response, "ERR_ASSIGNMENT_STATE_INVALID")

        after = read_assignment(ctx["shipped"]["id"])
        assert after["status"] == "SHIPPED", (
            "the refused re-tender must leave the assignment at SHIPPED"
        )
        assert after["carrier_pickup_id"] == ctx["own_pickup"]["id"], (
            "the refused re-tender must not repoint carrier_pickup_id at the "
            "other node's window"
        )
        foreign = read_pickup(ctx["foreign_pickup"]["id"])
        assert foreign["reserved_parcels"] == 0, (
            "the other node's window must claim no parcel slot"
        )
        assert foreign["status"] == "SCHEDULED", (
            "the other node's window is untouched by the refused tender"
        )

    def test_ship_of_packed_assignment_onto_foreign_pickup_reports_store_mismatch(
        self, api
    ):
        """PRD §3.6: "The preconditions are checked in this order: the acting node must match the assignment's node; the assignment must be at `PACKED`; the pickup's `status` must be `SCHEDULED`; the node's `node_status` must be `ELIGIBLE` or `PROBATION`; the clock's minute-of-day must still be within the node's cutoff; the clock must sit inside the half-open window, at or after `window_start_utc` and strictly before `window_end_utc`, or the tender is refused with `ERR_PICKUP_WINDOW_CLOSED`; `reserved_parcels` must be strictly below `parcel_capacity`, or the tender is refused with `ERR_PICKUP_CAPACITY_EXCEEDED`; and last of all the named pickup must belong to the same node as the assignment, or the request is refused with `ERR_PICKUP_STORE_MISMATCH`."
        PRD §3.6: "The pickup's `reserved_parcels` increases by 1 and its `version` increments."

        Design: Difficulty/priority_pair_validation_conflict/assignment_state_error_outranks_pickup_store_mismatch_on_reship
        """
        ctx = _shipped_and_packed_with_foreign_pickup()
        assert ctx["packed"]["status"] == "PACKED", (
            "setup expected the sibling assignment to sit at PACKED"
        )

        response = api.ship_assignment(
            ctx["packed"]["id"],
            ship_payload(
                ctx["foreign_pickup"]["id"], pickup_version(ctx["foreign_pickup"]["id"])
            ),
            make_store_associate_headers(ctx["store"]["id"]),
        )

        validate_error(response, "ERR_PICKUP_STORE_MISMATCH")

        after = read_assignment(ctx["packed"]["id"])
        assert after["status"] == "PACKED", (
            "a tender refused for pickup ownership must leave the assignment at PACKED"
        )
        assert after["carrier_pickup_id"] is None, (
            "carrier_pickup_id is only stored on a successful tender"
        )
        foreign = read_pickup(ctx["foreign_pickup"]["id"])
        assert foreign["reserved_parcels"] == 0, (
            "the other node's window must claim no parcel slot"
        )


# ======================================================================
# node-scope band (fourth) versus state band (sixth), on pack
# ======================================================================


class TestPackStoreScopeOutranksAssignmentState:
    def test_foreign_associate_packing_assigned_task_reports_store_scope_violation(
        self, api
    ):
        """PRD §2.1: "Concretely, when a `StoreAssociate` accepts, rejects, picks, packs or ships an assignment, or posts an inventory adjustment, or restocks packaging, the `store_id` of the targeted assignment, inventory row or packaging row must equal `X-User-ID`; a mismatch is rejected with `ERR_STORE_SCOPE_VIOLATION` (HTTP 403)."
        PRD §3.5: "Packing requires, in this order, the acting node to match, the assignment to be at `PICKED` or `SHORT_PICKED`, and the clock's minute-of-day to be within the node's cutoff."
        PRD §2.11: "Checks run in these bands, in this sequence."
        PRD §2.11: "Node-scope ownership fourth, as `ERR_STORE_SCOPE_VIOLATION`."
        PRD §2.11: "State validity sixth: whether the assignment, order, pickup, node or window is in a status that permits the operation."
        PRD §3.5: "The packaging row's `on_hand_units` is decremented by 1, its `lifetime_consumed_units` is incremented by 1, and its `reorder_flag` is re-derived."

        Design: Difficulty/priority_pair_validation_conflict/store_scope_auth_error_outranks_assignment_state_on_pack
        """
        ctx = _assigned_task_at_s1_with_second_node()
        assert ctx["assignment"]["store_id"] == ctx["store"]["id"], (
            "setup expected the assignment to belong to the first node"
        )
        assert ctx["assignment"]["status"] == "ASSIGNED", (
            "setup expected the assignment to still be at ASSIGNED"
        )

        response = api.pack_assignment(
            ctx["assignment"]["id"],
            {"package_type": "MEDIUM_BOX"},
            make_store_associate_headers(ctx["other_store"]["id"]),
        )

        validate_error(response, "ERR_STORE_SCOPE_VIOLATION")

        after = read_assignment(ctx["assignment"]["id"])
        assert after["status"] == "ASSIGNED", (
            "the refused pack must leave the assignment at ASSIGNED"
        )
        assert after["package_type"] is None, (
            "package_type is only stored on a successful pack"
        )
        assert after["accepted_at"] is None, (
            "the assignment was never accepted, so accepted_at stays null"
        )
        assert read_packaging(ctx["supply"]["id"])["on_hand_units"] == 5, (
            "a refused pack consumes no packaging unit"
        )

    def test_owning_associate_packing_assigned_task_reports_assignment_state_invalid(
        self, api
    ):
        """PRD §3.5: "Packing requires, in this order, the acting node to match, the assignment to be at `PICKED` or `SHORT_PICKED`, and the clock's minute-of-day to be within the node's cutoff."
        PRD §3.7: "A `PACKED` assignment can no longer be cancelled — the packaging has already been consumed — and neither can one already in a terminal state; either attempt is refused with `ERR_ASSIGNMENT_STATE_INVALID`."
        PRD §2.11: "State validity sixth: whether the assignment, order, pickup, node or window is in a status that permits the operation."

        Design: Difficulty/priority_pair_validation_conflict/store_scope_auth_error_outranks_assignment_state_on_pack
        """
        ctx = _assigned_task_at_s1_with_second_node()

        response = api.pack_assignment(
            ctx["assignment"]["id"],
            {"package_type": "MEDIUM_BOX"},
            make_store_associate_headers(ctx["store"]["id"]),
        )

        validate_error(response, "ERR_ASSIGNMENT_STATE_INVALID")

        after = read_assignment(ctx["assignment"]["id"])
        assert after["status"] == "ASSIGNED", (
            "a pack refused for source state must leave the assignment at ASSIGNED"
        )
        assert after["package_type"] is None, (
            "package_type is only stored on a successful pack"
        )
        assert read_packaging(ctx["supply"]["id"])["on_hand_units"] == 5, (
            "a refused pack consumes no packaging unit"
        )
