"""Route planning: stop planning, sequencing, capacity, and route cancellation."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    setup_customer, setup_two_customers, create_route, plan_stop, publish_route,
    create_stop_payload, create_customer_payload, create_deliver_payload,
    get_route, get_stop, NON_EXISTENT_UUID,
    OPS_ADMIN, DISPATCHER, DRIVER,
)


class TestStopPlanning:
    def test_stop_initial_state_planned(self, api):
        """PRD §3.3: "Each stop is born in `PLANNED` with
        `actual_bottles_delivered`, `actual_empties_collected`, and
        `shortage_count` all at zero, and its arrival increments the route's
        `committed_bottles` by `planned_bottles`."

        Design: Corner/state_machines/stop_initial_state_planned
        """
        world = setup_customer(account_type="OFFICE", business_name="InitCo",
                               billing_email="i@x.example", service_address="1 I",
                               service_mode="AUTO", par_level_bottles=2,
                               pricing_tier="STANDARD")
        route = create_route(world["zone"]["id"], "2026-06-01")
        stop = plan_stop(route["id"], world["customer"]["id"], sequence_index=1)
        assert stop["stop_status"] == "PLANNED", \
            f"a new stop must be born PLANNED, got {stop['stop_status']}"
        assert stop["actual_bottles_delivered"] == 0
        assert stop["actual_empties_collected"] == 0
        assert stop["shortage_count"] == 0

    def test_route_commit_aggregation(self, api):
        """PRD §3.3: "A route's `committed_bottles` — the sum of
        `planned_bottles` across its stops standing in `PLANNED`, `EN_ROUTE`, or
        `ARRIVED` — must never exceed `truck_capacity_bottles`."
        PRD §3.3: "For an `AUTO` customer, `planned_bottles` is the gap between
        target and reality: the customer's `par_level_bottles` minus their
        current `bottles_on_site`, floored at zero, measured at plan time."

        Design: Corner/calculations/route_commit_aggregation
        """
        world = setup_customer(account_type="OFFICE", business_name="AggA",
                               billing_email="a@x.example", service_address="1 A",
                               service_mode="AUTO", par_level_bottles=2)
        zone = world["zone"]
        customer_b = get_success_data(api_client.create_customer(
            create_customer_payload(zone["id"], account_type="HOME",
                                    business_name="AggB", billing_email="b@x.example",
                                    service_mode="AUTO", par_level_bottles=3),
            OPS_ADMIN))
        customer_c = get_success_data(api_client.create_customer(
            create_customer_payload(zone["id"], account_type="OFFICE",
                                    business_name="AggC", billing_email="c@x.example",
                                    service_mode="AUTO", par_level_bottles=4),
            OPS_ADMIN))
        route = create_route(zone["id"], "2026-06-01")
        plan_stop(route["id"], world["customer"]["id"], sequence_index=1)
        plan_stop(route["id"], customer_b["id"], sequence_index=2)
        plan_stop(route["id"], customer_c["id"], sequence_index=3)

        route_after = get_route(route["id"])
        assert route_after["committed_bottles"] == 9, (
            f"committed_bottles must sum planned bottles 2+3+4=9, "
            f"got {route_after['committed_bottles']}"
        )


class TestSequenceUniqueness:
    def test_duplicate_sequence_index_on_same_route_rejected(self, api):
        """PRD §3.3: "A `Dispatcher` plans a stop by naming the `customer_id`
        and a `sequence_index` — a positive integer giving the stop's order on
        the route, unique within that route; reusing an index is rejected with
        `ERR_DUPLICATE_SEQUENCE`."

        Design: Difficulty/resource_temporal_overlap/stop_sequence_uniqueness_per_route
        """
        world = setup_two_customers(
            a_overrides={"service_mode": "AUTO", "par_level_bottles": 1},
            b_overrides={"service_mode": "AUTO", "par_level_bottles": 1},
        )
        route = create_route(world["zone"]["id"], "2026-06-15")
        plan_stop(route["id"], world["customer_a"]["id"], sequence_index=1)

        res = api.create_stop(
            route["id"],
            create_stop_payload(world["customer_b"]["id"], 1),
            DISPATCHER,
        )
        validate_error(res, "ERR_DUPLICATE_SEQUENCE")

    def test_same_sequence_index_allowed_on_different_routes(self, api):
        """PRD §3.3: "A `Dispatcher` plans a stop by naming the `customer_id`
        and a `sequence_index` — a positive integer giving the stop's order on
        the route, unique within that route; reusing an index is rejected with
        `ERR_DUPLICATE_SEQUENCE`."

        Uniqueness is scoped to one route, so the same index on another route
        must be accepted.

        Design: Difficulty/resource_temporal_overlap/stop_sequence_uniqueness_per_route
        """
        world = setup_two_customers(
            a_overrides={"service_mode": "AUTO", "par_level_bottles": 1},
            b_overrides={"service_mode": "AUTO", "par_level_bottles": 1},
        )
        route_1 = create_route(world["zone"]["id"], "2026-06-15")
        route_2 = create_route(world["zone"]["id"], "2026-06-16")
        stop_1 = plan_stop(route_1["id"], world["customer_a"]["id"], sequence_index=1)
        stop_2 = plan_stop(route_2["id"], world["customer_b"]["id"], sequence_index=1)
        assert stop_1["sequence_index"] == 1
        assert stop_2["sequence_index"] == 1
        assert stop_1["route_id"] != stop_2["route_id"]


class TestTruckCapacity:
    def test_route_capacity_exceeded(self, api):
        """PRD §3.3: "A route's `committed_bottles` — the sum of
        `planned_bottles` across its stops standing in `PLANNED`, `EN_ROUTE`, or
        `ARRIVED` — must never exceed `truck_capacity_bottles`. Any stop
        insertion or work-order scheduling that would push the commitment over
        capacity is rejected with `ERR_ROUTE_CAPACITY_EXCEEDED`."

        Design: Corner/validations/route_capacity_exceeded
        """
        world = setup_customer(account_type="OFFICE", business_name="BigPar",
                               billing_email="b@x.example", service_address="1 B",
                               service_mode="AUTO", par_level_bottles=3,
                               pricing_tier="STANDARD")
        route = create_route(world["zone"]["id"], "2026-06-01", truck_capacity_bottles=2)
        res = api.create_stop(
            route["id"],
            create_stop_payload(world["customer"]["id"], 1),
            DISPATCHER,
        )
        validate_error(res, "ERR_ROUTE_CAPACITY_EXCEEDED")


class TestValidationOrdering:
    def test_invalid_reference_beats_capacity_on_full_route(self, api):
        """PRD §2.6: "Whether foreign-key references in the body resolve to
        existing, compatible entities — violations return `ERR_INVALID_REFERENCE`."
        PRD §2.6: "Every request passes through a fixed cascade of checks, and
        the order matters because an early failure masks all later ones."
        PRD §2.6: "Only after all seven generic stages pass do endpoint-specific
        business checks run, each with its own error code and each described in
        §3 next to the workflow it guards: stop-sequence uniqueness within a
        route (`ERR_DUPLICATE_SEQUENCE`), truck-capacity enforcement
        (`ERR_ROUTE_CAPACITY_EXCEEDED`), payment-amount sanity at apply time
        (`ERR_OVERPAYMENT`), the zero-balance gate on account closure
        (`ERR_OUTSTANDING_BALANCE`), the zero-bottle-custody gate on account
        closure (`ERR_BOTTLES_OUTSTANDING`), the mandatory skip explanation
        (`ERR_SKIP_REASON_REQUIRED`), credit expiry at apply time
        (`ERR_CREDIT_EXPIRED`), customer-self ownership (`ERR_FORBIDDEN`),
        pricing-configuration consistency (`ERR_INVALID_PRICING_CONFIG`),
        optimistic-concurrency freshness (`ERR_STALE_VERSION`), and the
        restricted source states for raising an invoice dispute
        (`ERR_INVALID_STATE`)."

        A stop insertion naming a non-existent customer on an already-full route
        violates both the foreign-key stage and the truck-capacity business
        check; the generic reference check runs first.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_capacity_and_invalid_zone
        """
        world = setup_customer(account_type="OFFICE", business_name="FullCo",
                               billing_email="f@x.example", service_address="1 F",
                               service_mode="AUTO", par_level_bottles=2,
                               pricing_tier="STANDARD")
        route = create_route(world["zone"]["id"], "2026-06-15", truck_capacity_bottles=2)
        plan_stop(route["id"], world["customer"]["id"], sequence_index=1)
        assert get_route(route["id"])["committed_bottles"] == 2

        res = api.create_stop(
            route["id"],
            create_stop_payload(NON_EXISTENT_UUID, 2),
            DISPATCHER,
        )
        validate_error(res, "ERR_INVALID_REFERENCE")

    def test_invalid_reference_on_route_with_spare_capacity(self, api):
        """PRD §2.6: "Whether foreign-key references in the body resolve to
        existing, compatible entities — violations return `ERR_INVALID_REFERENCE`."

        The same foreign-key stage fires when capacity is not at issue,
        isolating the reference check.

        Design: Difficulty/priority_pair_validation_conflict/business_safety_vs_business_referential_capacity_and_invalid_zone
        """
        world = setup_customer(account_type="OFFICE", business_name="SpareCo",
                               billing_email="s@x.example", service_address="1 S",
                               service_mode="AUTO", par_level_bottles=2)
        route = create_route(world["zone"]["id"], "2026-06-15", truck_capacity_bottles=50)
        res = api.create_stop(
            route["id"],
            create_stop_payload(NON_EXISTENT_UUID, 1),
            DISPATCHER,
        )
        validate_error(res, "ERR_INVALID_REFERENCE")


class TestStopExecutionGuard:
    def test_invalid_transition_stop_deliver_from_planned(self, api):
        """PRD §3.4: "Arrival moves a stop from `EN_ROUTE` to `ARRIVED`. From
        there the driver records the drop, and the record must carry three
        things: `actual_bottles_delivered`, `actual_empties_collected`, and —
        per §2.9 — `expected_route_version` matching the route's current
        `version`."
        PRD §2.6: "Whether the target resource is in a state that permits the
        requested transition — violations return `ERR_INVALID_STATE`; an
        operation attempted on a resource already sitting in a terminal state is
        instead rejected with `ERR_ALREADY_TERMINAL`."

        Design: Corner/state_machines/invalid_transition_stop_deliver_from_planned
        """
        world = setup_customer(account_type="OFFICE", business_name="InvT",
                               billing_email="i@x.example", service_address="1 I",
                               service_mode="AUTO", par_level_bottles=1,
                               pricing_tier="STANDARD")
        route = create_route(world["zone"]["id"], "2026-06-01")
        stop = plan_stop(route["id"], world["customer"]["id"], sequence_index=1)
        version = get_route(route["id"])["version"]

        res = api.deliver_stop(
            stop["id"],
            create_deliver_payload(version, 1, 0),
            DRIVER,
        )
        validate_error(res, "ERR_INVALID_STATE")


class TestRouteCancellation:
    def test_route_cancel_from_published_cancels_stops_and_resets_commitment(self, api):
        """PRD §3.3: "A `Dispatcher` may also cancel a route from `DRAFT` or
        `PUBLISHED`; cancellation moves every stop on the route to `CANCELLED`
        and resets `committed_bottles` to zero."

        Design: Difficulty/transitive_cascade/route_cancel_cascade_depth2
        """
        world = setup_two_customers(
            a_overrides={"service_mode": "AUTO", "par_level_bottles": 3},
            b_overrides={"service_mode": "AUTO", "par_level_bottles": 2},
        )
        zone = world["zone"]
        route = create_route(zone["id"], "2026-06-15")
        stop_a = plan_stop(route["id"], world["customer_a"]["id"], sequence_index=1)
        stop_b = plan_stop(route["id"], world["customer_b"]["id"], sequence_index=2)
        publish_route(route["id"])
        assert get_route(route["id"])["committed_bottles"] == 5  # par 3 + par 2

        cancelled = validate_success(api.cancel_route(route["id"], DISPATCHER), 200)
        assert cancelled["route_status"] == "CANCELLED"
        assert get_stop(stop_a["id"])["stop_status"] == "CANCELLED"
        assert get_stop(stop_b["id"])["stop_status"] == "CANCELLED"
        assert get_route(route["id"])["committed_bottles"] == 0

    def test_route_cancel_from_draft_cancels_stops_and_resets_commitment(self, api):
        """PRD §3.3: "A `Dispatcher` may also cancel a route from `DRAFT` or
        `PUBLISHED`; cancellation moves every stop on the route to `CANCELLED`
        and resets `committed_bottles` to zero."

        Design: Difficulty/transitive_cascade/route_cancel_cascade_depth2
        """
        world = setup_two_customers(
            a_overrides={"service_mode": "AUTO", "par_level_bottles": 3},
            b_overrides={"service_mode": "AUTO", "par_level_bottles": 2},
        )
        zone = world["zone"]
        route = create_route(zone["id"], "2026-06-15")
        stop_a = plan_stop(route["id"], world["customer_a"]["id"], sequence_index=1)
        stop_b = plan_stop(route["id"], world["customer_b"]["id"], sequence_index=2)
        assert get_route(route["id"])["committed_bottles"] == 5

        cancelled = validate_success(api.cancel_route(route["id"], DISPATCHER), 200)
        assert cancelled["route_status"] == "CANCELLED"
        assert get_stop(stop_a["id"])["stop_status"] == "CANCELLED"
        assert get_stop(stop_b["id"])["stop_status"] == "CANCELLED"
        assert get_route(route["id"])["committed_bottles"] == 0
