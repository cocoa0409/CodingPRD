"""Dispatch preconditions: broker status, OCC version, capacity boundary, SLA clock,
and role/ownership enforcement on dispatch and accept."""
from datetime import timedelta

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    broker_accept,
    broker_decline,
    create_broker_with_license,
    dispatch_to_broker,
    get_order,
    make_broker_headers,
    new_order,
    parse_utc,
    setup_market,
    submit_order,
    validate_error,
    validate_success,
)

COMPLIANCE = TEST_USERS["compliance_officer_headers"]
DISPATCH = TEST_USERS["dispatch_coordinator_headers"]


class TestDispatchRequiresActiveBroker:
    def test_dispatch_to_suspended_broker_rejected(self, api):
        """PRD §3.4: "the selected broker's `status` must be `ACTIVE`
        (`ERR_BROKER_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/order_dispatch_requires_broker_active
        """
        env = setup_market("MN", client_code="CLM", broker_code="BRKM")
        order = new_order(env)
        order = submit_order(env, order)
        validate_success(api.suspend_broker(env["broker"]["id"], COMPLIANCE))

        payload = {"broker_id": env["broker"]["id"],
                   "expected_order_version": order["version"]}
        resp = api.dispatch_order(order["id"], payload, DISPATCH)
        validate_error(resp, ApiErrorId.ERR_BROKER_NOT_ACTIVE)
        assert get_order(order["id"])["fulfillment_status"] == "READY_FOR_DISPATCH"

    def test_dispatch_to_pending_onboarding_broker_rejected(self, api):
        """PRD §3.4: "the selected broker's `status` must be `ACTIVE`
        (`ERR_BROKER_NOT_ACTIVE`)"

        Design: Difficulty/cross_entity_state_dependency/order_dispatch_requires_broker_active
        """
        env = setup_market("MN", client_code="CLM", broker_code="BRKM")
        # A second broker that is licensed but never activated stays
        # PENDING_ONBOARDING.
        pending = create_broker_with_license(
            "MN", broker_code="BRKP2", activate=False)
        order = new_order(env)
        order = submit_order(env, order)

        payload = {"broker_id": pending["id"],
                   "expected_order_version": order["version"]}
        resp = api.dispatch_order(order["id"], payload, DISPATCH)
        validate_error(resp, ApiErrorId.ERR_BROKER_NOT_ACTIVE)
        assert get_order(order["id"])["fulfillment_status"] == "READY_FOR_DISPATCH"


class TestSecondDispatch:
    def test_error_order_already_dispatched_on_second_dispatch(self, api):
        """PRD §2.9: "5. State legality: the target resource is in a state from
        which this transition is permitted (`ERR_INVALID_STATE`)."
        PRD §3.4: "Dispatch is the `DispatchCoordinator`'s exclusive act,
        transitioning the order from `READY_FOR_DISPATCH` to `DISPATCHED`"

        Design: Corner/errors/error_order_already_dispatched_on_second_dispatch
        """
        env = setup_market("AR", client_code="COD", broker_code="BOD")
        order = new_order(env)
        order = submit_order(env, order)
        dispatched = dispatch_to_broker(env, order)

        payload = {"broker_id": env["broker"]["id"],
                   "expected_order_version": dispatched["version"]}
        resp = api.dispatch_order(order["id"], payload, DISPATCH)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_order(order["id"])["fulfillment_status"] == "DISPATCHED"


class TestDispatchOptimisticConcurrency:
    def test_occ_stale_version_on_dispatch(self, api):
        """PRD §2.6: "If the order's current `version` does not match — for example
        because another dispatcher legitimately dispatched the same order moments
        earlier, which itself increments `version` — the dispatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_layers/occ_stale_version_on_dispatch
        """
        env = setup_market("ND", client_code="COCC", broker_code="BOCC")
        order = new_order(env)
        stale_version = order["version"]
        submitted = submit_order(env, order)
        assert submitted["version"] != stale_version, (
            "Setup requires submit to advance the order version")

        payload = {"broker_id": env["broker"]["id"],
                   "expected_order_version": stale_version}
        resp = api.dispatch_order(order["id"], payload, DISPATCH)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert get_order(order["id"])["fulfillment_status"] == "READY_FOR_DISPATCH"


class TestBrokerCapacityBoundary:
    def test_dispatch_at_max_capacity_rejected(self, api):
        """PRD §3.4: "the broker's count of orders in `DISPATCHED`, `IN_PROGRESS`,
        `REPORT_SUBMITTED`, `QC_REVIEW`, or `REVISION_REQUESTED` must be strictly
        below their `max_concurrent_orders` (`ERR_BROKER_CAPACITY_FULL`)"

        Design: Difficulty/boundary_precision_check/broker_capacity_at_max_minus_one_vs_max
        """
        env = setup_market("OH", client_code="CLL", broker_code="BRKL",
                           max_concurrent_orders=2)
        first = new_order(env)
        first = submit_order(env, first)
        dispatch_to_broker(env, first)
        second = new_order(env)
        second = submit_order(env, second)
        dispatch_to_broker(env, second)

        third = new_order(env)
        third = submit_order(env, third)
        payload = {"broker_id": env["broker"]["id"],
                   "expected_order_version": third["version"]}
        resp = api.dispatch_order(third["id"], payload, DISPATCH)
        validate_error(resp, ApiErrorId.ERR_BROKER_CAPACITY_FULL)
        assert get_order(third["id"])["fulfillment_status"] == "READY_FOR_DISPATCH"

    def test_dispatch_at_max_minus_one_succeeds(self, api):
        """PRD §3.4: "the broker's count of orders in `DISPATCHED`, `IN_PROGRESS`,
        `REPORT_SUBMITTED`, `QC_REVIEW`, or `REVISION_REQUESTED` must be strictly
        below their `max_concurrent_orders` (`ERR_BROKER_CAPACITY_FULL`)"

        Design: Difficulty/boundary_precision_check/broker_capacity_at_max_minus_one_vs_max
        """
        env = setup_market("OH", client_code="CLL", broker_code="BRKL",
                           max_concurrent_orders=2)
        first = new_order(env)
        first = submit_order(env, first)
        dispatch_to_broker(env, first)

        # Broker now holds 1 open order == max - 1; the strict-less-than check
        # must admit exactly one more.
        second = new_order(env)
        second = submit_order(env, second)
        dispatched = dispatch_to_broker(env, second)
        assert dispatched["fulfillment_status"] == "DISPATCHED"
        assert dispatched["assigned_broker_id"] == env["broker"]["id"]


class TestOpenOrderCountConservation:
    def test_decline_frees_capacity_for_next_dispatch(self, api):
        """PRD §3.4: "Declining returns the order to `READY_FOR_DISPATCH`: the
        `assigned_broker_id` is cleared, the broker's open-order count is
        decremented, and the broker's decline count is incremented, feeding the
        decline penalty in the composite score."

        Design: Difficulty/compensating_invariant/broker_open_order_count_conservation_across_decline
        """
        env = setup_market("IN", client_code="CLQ", broker_code="BRKQ",
                           max_concurrent_orders=2)
        first = new_order(env)
        first = submit_order(env, first)
        first = dispatch_to_broker(env, first)
        second = new_order(env)
        second = submit_order(env, second)
        second = dispatch_to_broker(env, second)

        declined = broker_decline(env, first)
        assert declined["fulfillment_status"] == "READY_FOR_DISPATCH"
        assert declined["assigned_broker_id"] is None

        # Capacity freed by the decline: a third dispatch now succeeds.
        third = new_order(env)
        third = submit_order(env, third)
        redispatched = dispatch_to_broker(env, third)
        assert redispatched["fulfillment_status"] == "DISPATCHED"

        assert get_order(second["id"])["fulfillment_status"] == "DISPATCHED"

    def test_accept_preserves_open_order_count(self, api):
        """PRD §3.4: "the broker's count of orders in `DISPATCHED`, `IN_PROGRESS`,
        `REPORT_SUBMITTED`, `QC_REVIEW`, or `REVISION_REQUESTED` must be strictly
        below their `max_concurrent_orders` (`ERR_BROKER_CAPACITY_FULL`)"

        Design: Difficulty/compensating_invariant/broker_open_order_count_conservation_across_decline
        """
        env = setup_market("IN", client_code="CLQ", broker_code="BRKQ",
                           max_concurrent_orders=2)
        first = new_order(env)
        first = submit_order(env, first)
        first = dispatch_to_broker(env, first)
        accepted = broker_accept(env, first)
        assert accepted["fulfillment_status"] == "IN_PROGRESS"

        second = new_order(env)
        second = submit_order(env, second)
        dispatch_to_broker(env, second)

        # Accepting moved the first order DISPATCHED -> IN_PROGRESS, which still
        # counts against capacity: the broker remains full at count == max.
        third = new_order(env)
        third = submit_order(env, third)
        payload = {"broker_id": env["broker"]["id"],
                   "expected_order_version": third["version"]}
        resp = api.dispatch_order(third["id"], payload, DISPATCH)
        validate_error(resp, ApiErrorId.ERR_BROKER_CAPACITY_FULL)


class TestSlaDueAtComputation:
    def test_sla_due_at_standard_vs_rush_difference(self, api):
        """PRD §3.4: "`sla_due_at` is set to the dispatch instant plus
        `sla_hours_standard` hours if the `priority` is `STANDARD`, or plus
        `sla_hours_rush` hours if the `priority` is `RUSH`, both drawn from the
        owning `ClientAccount`"

        Design: Corner/calculations/sla_due_at_standard_vs_rush_difference
        """
        env = setup_market("PA", client_code="CSL", broker_code="BSLA",
                           client_overrides={"sla_hours_standard": 72,
                                             "sla_hours_rush": 12},
                           max_concurrent_orders=10)
        standard = new_order(env, priority="STANDARD")
        standard = submit_order(env, standard)
        standard = dispatch_to_broker(env, standard)

        rush = new_order(env, priority="RUSH")
        rush = submit_order(env, rush)
        rush = dispatch_to_broker(env, rush)

        due_standard = parse_utc(standard["sla_due_at"])
        due_rush = parse_utc(rush["sla_due_at"])
        dispatch_instant = parse_utc("2026-08-01T00:00:00Z")
        assert due_standard == dispatch_instant + timedelta(hours=72), (
            f"STANDARD sla_due_at must be dispatch + 72h, got {standard['sla_due_at']}")
        assert due_rush == dispatch_instant + timedelta(hours=12), (
            f"RUSH sla_due_at must be dispatch + 12h, got {rush['sla_due_at']}")
        assert (due_standard - due_rush) == timedelta(hours=60)


class TestDispatchAndAcceptRbac:
    def test_client_admin_cannot_dispatch(self, api):
        """PRD §2.1: "If the headers are present but the named role is not
        permitted to invoke the target endpoint, the request is rejected with
        `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: POST /bpo/valuation-orders/{id}/dispatch is authorized for
        DispatchCoordinator only.

        Design: Corner/rbac/client_admin_cannot_dispatch
        """
        env = setup_market("LA", client_code="CCAD", broker_code="BCAD")
        order = new_order(env)
        order = submit_order(env, order)

        payload = {"broker_id": env["broker"]["id"],
                   "expected_order_version": order["version"]}
        resp = api.dispatch_order(order["id"], payload, env["client_headers"])
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)

    def test_broker_ownership_check_on_accept(self, api):
        """PRD §3.4: "Accepting the order — allowed only when the caller's
        `X-User-ID` equals the order's `assigned_broker_id`, else `ERR_FORBIDDEN`,
        and only while the order is `DISPATCHED`, else `ERR_INVALID_STATE`"

        Design: Corner/rbac/broker_ownership_check_on_accept
        """
        env = setup_market("MT", client_code="COC", broker_code="BOCA")
        other_broker = create_broker_with_license("MT", broker_code="BOCB")
        order = new_order(env)
        order = submit_order(env, order)
        dispatch_to_broker(env, order)

        resp = api.accept_order(order["id"], make_broker_headers(other_broker["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        assert get_order(order["id"])["fulfillment_status"] == "DISPATCHED"
