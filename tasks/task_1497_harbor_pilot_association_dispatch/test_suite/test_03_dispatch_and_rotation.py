"""Dispatch: selector policy, gating, rotation bookkeeping (PRD §2.9, §2.10, §3.3, §3.5)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, NON_EXISTENT_UUID,
    ApiErrorId, TEST_USERS, make_agent_headers, make_pilot_headers,
    assert_assignment,
    make_dispatch_payload, create_main_tariff, place_order, dispatch,
    register_endorsed_pilot, register_boat, register_pilot, issue_endorsement,
    cancel_assignment, recall, rotation_entry_of,
    get_order_fresh, get_assignment_fresh, setup_assigned_scenario,
    setup_two_pilots,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestDispatchInitialState:
    def test_assignment_dispatch_response_initial_state(self, api):
        """PRD §3.3: "A successful dispatch creates the assignment with
        `service_status` `ASSIGNED` and `billing_status` `UNBILLED`, recording
        the selected or supplied `boat_id`, any `apprentice_id`, and the planned
        window."
        PRD §3.5: "recalling an `ASSIGNED` assignment moves it to `RECALLED`,
        increments its `recall_count`" (a fresh assignment has never been
        recalled: recall_count is 0).

        Design: Corner/state_machines/assignment_dispatch_response_initial_state
        """
        ctx = setup_assigned_scenario()
        asg = ctx["assignment"]
        assert_assignment(asg)
        assert asg["service_status"] == "ASSIGNED"
        assert asg["billing_status"] == "UNBILLED"
        assert asg["recall_count"] == 0
        assert asg["version"] == 1
        assert asg["order_id"] == ctx["order"]["id"]
        assert asg["pilot_id"] == ctx["pilot"]["id"]


class TestSelectorRanking:
    def test_xlayer_selector_rank_by_position_then_front_pilot_picked(self, api):
        """PRD §3.3: "The pool is ranked by board `position` ascending, ties
        broken by the entry's `created_at` ascending, and the top candidate is
        selected."
        PRD §2.9: "a pilot selected at dispatch is demoted to the bottom the
        same way, with their prior slot recorded in `previous_position`".

        P1 (position 1) is picked first; the demotion puts P2 (position 2) at
        the front for the second dispatch.

        Design: Corner/cross_cutting_layers/xlayer_selector_rank_by_position_then_front_pilot_picked
        """
        create_main_tariff()
        p1, p2 = setup_two_pilots()
        register_boat("Boat A")
        register_boat("Boat B")
        o1 = place_order(vessel_name="MV One")
        o2 = place_order(vessel_name="MV Two", order_type="DEPARTURE",
                         eta="2026-08-11T00:00:00Z")

        a1 = dispatch(o1["id"], "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        assert a1["pilot_id"] == p1["id"], "lowest position wins"

        a2 = dispatch(o2["id"], "2026-08-11T10:00:00Z", "2026-08-11T11:00:00Z")
        assert a2["pilot_id"] == p2["id"], "after demotion the next pilot leads"


class TestDispatchGating:
    def test_dispatch_with_unknown_apprentice_returns_404(self, api):
        """PRD §2.8: "Existence of every referenced resource — path identifiers
        and body-supplied identifiers alike, covering orders, assignments,
        pilots, boats, invoices, incidents, apprentices, distribution runs, and
        endorsements — is validated next, strictly left-to-right across the
        request, with the first missing reference yielding `ERR_NOT_FOUND`."

        Design: Corner/entities/dispatch_with_unknown_apprentice_returns_404
        """
        ctx = setup_assigned_scenario()  # leaves an order already dispatched;
        # build a fresh BOOKED order for the trigger
        order = place_order(vessel_name="MV Fresh", order_type="DEPARTURE",
                            eta="2026-08-12T00:00:00Z")
        res = api.dispatch_order(order["id"], make_dispatch_payload(
            "2026-08-12T10:00:00Z", "2026-08-12T11:00:00Z",
            apprentice_id=NON_EXISTENT_UUID), DISPATCHER)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND)

    def test_error_no_eligible_pilot_when_endorsement_expired(self, api):
        """PRD §3.3: "The candidate pool is every pilot who is simultaneously:
        `ACTIVE`; `IN_ROTATION` on the board; holding at least one `CURRENT`
        endorsement with `expires_at` strictly after the logical clock and
        `tonnage_cap_gt` at least the order's `gt`; ..." "An empty pool rejects
        the dispatch with `ERR_NO_ELIGIBLE_PILOT`, leaving the order `BOOKED`
        with no partial write."

        The only pilot's endorsement expired before the default clock, so the
        pool is empty.

        Design: Corner/errors/error_no_eligible_pilot_when_endorsement_expired
        """
        create_main_tariff()
        pilot = register_pilot()
        issue_endorsement(pilot["id"], expires_at="2026-06-01T00:00:00Z")
        register_boat("Boat A")
        order = place_order()

        res = api.dispatch_order(order["id"], make_dispatch_payload(), DISPATCHER)
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_PILOT)
        assert get_order_fresh(order["id"])["status"] == "BOOKED", "no partial write"

    def test_rbac_pilot_cannot_dispatch_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted on the targeted
        endpoint, or that fails an ownership check, is rejected with
        `ERR_FORBIDDEN` (HTTP 403)."
        PRD §4: "| POST | `/pilotage/vessel-orders/{id}/dispatch` | Dispatch
        the order: rotation selector picks the pilot; boat selector picks the
        boat unless `boat_id` given | Dispatcher |".

        Design: Corner/rbac/rbac_pilot_cannot_dispatch_forbidden
        """
        create_main_tariff()
        pilot = register_endorsed_pilot()
        register_boat("Boat A")
        order = place_order()

        res = api.dispatch_order(order["id"], make_dispatch_payload(),
                                 make_pilot_headers(pilot["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN)


class TestDispatchStateGuardBeatsEmptyPool:
    def test_dispatch_cancelled_order_returns_not_dispatchable(self, api):
        """PRD §3.3: "Dispatch is only legal while the order is `BOOKED`; any
        other status is rejected with `ERR_ORDER_NOT_DISPATCHABLE` (HTTP 409)."
        PRD §2.8: "State-machine guards come after that — the generic from-state
        guard (`ERR_INVALID_STATE`) plus the order-specific guards
        `ERR_ORDER_LOCKED` and `ERR_ORDER_NOT_DISPATCHABLE`." — evaluated before
        "selector pool emptiness (`ERR_NO_ELIGIBLE_PILOT`, `ERR_NO_ELIGIBLE_BOAT`)".

        The order is CANCELLED and the pilot pool is empty; the state error wins.

        Design: Difficulty/priority_pair_validation_conflict/dispatch_cancelled_order_state_beats_empty_pool_constraint
        """
        create_main_tariff()
        order = place_order(vessel_name="MV Dead", gt=4000, draft_dm=90)
        validate_success(api.cancel_order(order["id"], make_agent_headers("agent-1")), 200)

        res = api.dispatch_order(order["id"], make_dispatch_payload(), DISPATCHER)
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_DISPATCHABLE)

    def test_dispatch_cancelled_order_creates_no_assignment(self, api):
        """PRD §3.3: "Dispatch is only legal while the order is `BOOKED`; any
        other status is rejected with `ERR_ORDER_NOT_DISPATCHABLE` (HTTP 409)."

        The rejected dispatch writes nothing: no assignment exists for the order
        and the order stays CANCELLED.

        Design: Difficulty/priority_pair_validation_conflict/dispatch_cancelled_order_state_beats_empty_pool_constraint
        """
        create_main_tariff()
        order = place_order(vessel_name="MV Dead", gt=4000, draft_dm=90)
        validate_success(api.cancel_order(order["id"], make_agent_headers("agent-1")), 200)

        api.dispatch_order(order["id"], make_dispatch_payload(), DISPATCHER)
        data, meta = validate_paginated(
            api.list_assignments(DISPATCHER, params={"order_id": order["id"]}))
        assert meta["total_count"] == 0 and data == []
        assert get_order_fresh(order["id"])["status"] == "CANCELLED"


class TestDispatchRequiresBooked:
    def _dispatched_order(self):
        create_main_tariff()
        pilot = register_endorsed_pilot(tonnage_cap_gt=100000)
        register_boat("Boat A")
        order = place_order(gt=4000, draft_dm=90)
        assignment = dispatch(order["id"])
        return order, assignment

    def test_second_dispatch_rejected_not_dispatchable(self, api):
        """PRD §3.3: "Dispatch is only legal while the order is `BOOKED`; any
        other status is rejected with `ERR_ORDER_NOT_DISPATCHABLE` (HTTP 409)."

        The order is already DISPATCHED, so a second dispatch is rejected.

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_order_booked_state
        """
        order, _a1 = self._dispatched_order()
        res = api.dispatch_order(order["id"], make_dispatch_payload(
            "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z"), DISPATCHER)
        validate_error(res, ApiErrorId.ERR_ORDER_NOT_DISPATCHABLE)

    def test_second_dispatch_creates_no_additional_assignment(self, api):
        """PRD §3.3: "Dispatch is only legal while the order is `BOOKED`; any
        other status is rejected with `ERR_ORDER_NOT_DISPATCHABLE` (HTTP 409)."

        The order remains DISPATCHED with exactly its one original assignment.

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_order_booked_state
        """
        order, a1 = self._dispatched_order()
        api.dispatch_order(order["id"], make_dispatch_payload(
            "2026-08-10T12:00:00Z", "2026-08-10T13:00:00Z"), DISPATCHER)
        data, meta = validate_paginated(
            api.list_assignments(DISPATCHER, params={"order_id": order["id"]}))
        assert meta["total_count"] == 1
        assert data[0]["id"] == a1["id"]
        assert get_order_fresh(order["id"])["status"] == "DISPATCHED"


class TestBoatBufferSemantics:
    def _setup_single_boat_with_morning_run(self):
        create_main_tariff()
        p1, p2 = setup_two_pilots()
        boat = register_boat("Boat A")
        o1 = place_order(vessel_name="MV One")
        a1 = dispatch(o1["id"], "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        return p1, p2, boat, o1, a1

    def test_boat_dispatch_at_buffer_edge_allowed(self, api):
        """PRD §2.10: "A pilot boat's committed intervals are **half-open with
        a turnaround buffer**: the boat remains occupied for 45 minutes beyond
        each booking's end, and a new request whose start falls exactly at the
        buffered edge is allowed."

        The morning run occupies the boat over [10:00, 12:45); a dispatch at
        exactly 12:45 is adjacent at the buffer edge and succeeds.

        Design: Difficulty/resource_temporal_overlap/boat_halfopen_buffer_adjacency_vs_inside_buffer
        """
        p1, p2, boat, _o1, _a1 = self._setup_single_boat_with_morning_run()
        o2 = place_order(vessel_name="MV Two", order_type="DEPARTURE",
                         eta="2026-08-10T06:00:00Z")
        res = api.dispatch_order(o2["id"], make_dispatch_payload(
            "2026-08-10T12:45:00Z", "2026-08-10T14:00:00Z"), DISPATCHER)
        a2 = validate_success(res, 201)
        assert a2["boat_id"] == boat["id"]
        assert a2["pilot_id"] == p2["id"], "P1 was demoted after the first dispatch"

    def test_boat_dispatch_inside_buffer_rejected(self, api):
        """PRD §2.10: "A pilot boat's committed intervals are **half-open with
        a turnaround buffer**: the boat remains occupied for 45 minutes beyond
        each booking's end".
        PRD §3.3: "An empty boat pool rejects the dispatch with
        `ERR_NO_ELIGIBLE_BOAT`."

        A 12:44 start falls inside the buffered occupation [10:00, 12:45) of
        the fleet's only boat, emptying the pool; the order stays BOOKED.

        Design: Difficulty/resource_temporal_overlap/boat_halfopen_buffer_adjacency_vs_inside_buffer
        """
        self._setup_single_boat_with_morning_run()
        o3 = place_order(vessel_name="MV Three", order_type="SHIFT",
                         eta="2026-08-10T06:00:00Z")
        res = api.dispatch_order(o3["id"], make_dispatch_payload(
            "2026-08-10T12:44:00Z", "2026-08-10T14:00:00Z"), DISPATCHER)
        validate_error(res, ApiErrorId.ERR_NO_ELIGIBLE_BOAT)
        assert get_order_fresh(o3["id"])["status"] == "BOOKED", "empty pool writes nothing"


class TestDispatchCancelRotationInvariant:
    def _dispatched_with_two_pilots(self):
        create_main_tariff()
        p1, p2 = setup_two_pilots()
        register_boat("Boat A")
        o1 = place_order(vessel_name="MV One")
        a1 = dispatch(o1["id"], "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        return p1, p2, o1, a1

    def test_dispatch_demotes_picked_pilot_to_board_bottom(self, api):
        """PRD §3.3: "The selected pilot's rotation entry records the demotion:
        `previous_position` captures the current `position`, then `position`
        moves to one greater than the current board maximum."

        With a two-pilot board the picked pilot moves 1 -> 3.

        Design: Difficulty/compensating_invariant/dispatch_then_cancel_restores_rotation_ordering
        """
        p1, p2, _o1, a1 = self._dispatched_with_two_pilots()
        assert a1["pilot_id"] == p1["id"], "front of board picked"
        entry = rotation_entry_of(p1["id"])
        assert entry["position"] == 3
        assert entry["previous_position"] == 1

    def test_cancel_restores_pre_dispatch_board_order(self, api):
        """PRD §3.5: "Cancelling an `ASSIGNED` assignment restores the pilot's
        board slot as compensation for the dispatch demotion — `position`
        reverts to `previous_position` and `previous_position` is cleared to
        null — and releases the boat's booked interval." "When the direct
        cancellation fires while the order is still `DISPATCHED`, the order
        reverts `DISPATCHED → BOOKED` so it can be dispatched again".

        Design: Difficulty/compensating_invariant/dispatch_then_cancel_restores_rotation_ordering
        """
        p1, p2, o1, a1 = self._dispatched_with_two_pilots()
        cancelled = cancel_assignment(a1["id"])
        assert cancelled["service_status"] == "CANCELLED"

        entry1 = rotation_entry_of(p1["id"])
        assert entry1["position"] == 1 and entry1["previous_position"] is None
        entry2 = rotation_entry_of(p2["id"])
        assert entry2["position"] == 2, "board position multiset {1, 2} conserved"
        assert get_order_fresh(o1["id"])["status"] == "BOOKED"


class TestOrderCancelCascadeCompensation:
    def test_order_cancel_cancels_assignment(self, api, vessel_agent_headers):
        """PRD §3.2: "Cancelling a `DISPATCHED` order triggers a two-hop cascade:
        the order's non-terminal assignment moves to `CANCELLED` service status,
        and that assignment cancellation in turn restores the displaced pilot's
        board slot (`position` reverts to `previous_position`) and releases the
        boat's booked interval. The order ends `CANCELLED`."

        Design: Difficulty/transitive_cascade/order_cancel_assignment_rotation_compensation_depth2
        """
        create_main_tariff()
        p1, _p2 = setup_two_pilots()
        register_boat("Boat A")
        order = place_order()
        a1 = dispatch(order["id"])

        res = api.cancel_order(order["id"], vessel_agent_headers)
        cancelled_order = validate_success(res, 200)
        assert cancelled_order["status"] == "CANCELLED"
        assert get_assignment_fresh(a1["id"])["service_status"] == "CANCELLED"

    def test_order_cancel_restores_rotation_position(self, api, vessel_agent_headers):
        """PRD §3.2: "Cancelling a `DISPATCHED` order triggers a two-hop cascade:
        the order's non-terminal assignment moves to `CANCELLED` service status,
        and that assignment cancellation in turn restores the displaced pilot's
        board slot (`position` reverts to `previous_position`) and releases the
        boat's booked interval."

        Hop 2 restores the dispatched pilot from position 3 back to slot 1 and
        leaves the other pilot's slot untouched.

        Design: Difficulty/transitive_cascade/order_cancel_assignment_rotation_compensation_depth2
        """
        create_main_tariff()
        p1, p2 = setup_two_pilots()
        register_boat("Boat A")
        order = place_order()
        dispatch(order["id"])

        validate_success(api.cancel_order(order["id"], vessel_agent_headers), 200)
        entry1 = rotation_entry_of(p1["id"])
        assert entry1["position"] == 1 and entry1["previous_position"] is None
        assert rotation_entry_of(p2["id"])["position"] == 2


class TestImmediateConsistency:
    def test_consistency_immediate_read_after_dispatch(self, api):
        """PRD §3.3: "The order advances `BOOKED → DISPATCHED`."
        PRD §4: "GET `/pilotage/assignments` | List assignments; filters for
        `order_id`, `pilot_id`, `boat_id`, `apprentice_id`, `service_status`,
        `billing_status` | Any".

        The GET immediately following the dispatch shows the order DISPATCHED
        and the new assignment visible through the order_id filter.

        Design: Corner/consistency_model/consistency_immediate_read_after_dispatch
        """
        ctx = setup_assigned_scenario()
        order = get_order_fresh(ctx["order"]["id"])
        assert order["status"] == "DISPATCHED"
        data, meta = validate_paginated(
            api.list_assignments(DISPATCHER, params={"order_id": ctx["order"]["id"]}))
        assert [row["id"] for row in data] == [ctx["assignment"]["id"]]
