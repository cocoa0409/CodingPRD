"""Order lifecycle and parallel state axes:
- parallel fulfillment x billing axes
- delivery reassignment cycle (decline reverts order)
- optimistic concurrency on dispatch (stale vs fresh)
- scheduled orders (start SCHEDULED, release before/after due)
- invalid transitions, terminal-state lockdown, restaurant deactivation cascade
- partial cascade on cancel.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    api_client, ApiErrorId,
    make_admin_headers, make_customer_headers, make_dasher_headers,
    make_restaurant_headers,
    create_zone, create_restaurant, create_menu_item, create_customer, create_dasher,
    place_simple_order, place_order, line_item, dispatch,
    setup_market, setup_order_routed, setup_order_accepted,
    setup_order_picked_up, setup_order_delivered, setup_scheduled_order,
    set_clock,
)

ADMIN = make_admin_headers()


# ===========================================================================
# non_linear_state_machine — parallel fulfillment x billing axes
# ===========================================================================
class TestParallelAxes:
    def test_picked_up_order_is_still_unsettled(self, api):
        """PRD §2.5: "a `PICKED_UP` order is still `UNSETTLED`, a `DELIVERED`
        order may later become `REFUNDED`, and the pairing of `DELIVERED` with
        `UNSETTLED` never occurs by design because completing delivery is exactly
        what settles billing."

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_and_billing_axes
        """
        ctx = setup_order_picked_up()
        order = validate_success(
            api_client.get_order(ctx["order"]["id"],
                                 make_customer_headers(ctx["customer"]["id"])))
        assert order["fulfillment_status"] == "PICKED_UP"
        assert order["billing_status"] == "UNSETTLED", \
            "the billing axis must stay UNSETTLED until drop-off settles it"

    def test_delivered_flips_both_axes(self, api):
        """PRD §3.8: "On drop-off the delivery moves from `EN_ROUTE` to
        `DELIVERED` and the order from `PICKED_UP` to `DELIVERED`"
        PRD §3.8: "the order's `billing_status` moves from `UNSETTLED` to
        `SETTLED`"

        The same drop-off advances fulfillment to DELIVERED AND billing to SETTLED.

        Design: Difficulty/non_linear_state_machine/order_parallel_fulfillment_and_billing_axes
        """
        ctx = setup_order_delivered()
        order = validate_success(
            api_client.get_order(ctx["order"]["id"],
                                 make_customer_headers(ctx["customer"]["id"])))
        assert order["fulfillment_status"] == "DELIVERED"
        assert order["billing_status"] == "SETTLED"


# ===========================================================================
# non_linear_state_machine — delivery reassignment cycle
# ===========================================================================
class TestDeclineReassignCycle:
    def test_decline_moves_delivery_to_reassigned(self, api):
        """PRD §3.8: "A decline moves the delivery from `OFFERED` to `REASSIGNED`, reverses its earnings record from `ACCRUED` to `REVERSED`, and reverts the parent order from `ROUTED` back to `PLACED` so it can be dispatched afresh"

        Design: Difficulty/non_linear_state_machine/delivery_reassign_cycle_reverts_order_to_placed
        """
        ctx = setup_order_routed()
        dh = make_dasher_headers(ctx["dasher"]["id"])
        declined = validate_success(api_client.decline_delivery(ctx["delivery"]["id"], dh))
        assert declined["fulfillment_status"] == "REASSIGNED"

    def test_decline_reverts_parent_order_to_placed(self, api):
        """PRD §3.8: "and reverts the parent order from `ROUTED` back to `PLACED` so it can be dispatched afresh — a fresh `OFFERED` delivery will be created on the next dispatch, forming the reassignment loop."

        Design: Difficulty/non_linear_state_machine/delivery_reassign_cycle_reverts_order_to_placed
        """
        ctx = setup_order_routed()
        dh = make_dasher_headers(ctx["dasher"]["id"])
        validate_success(api_client.decline_delivery(ctx["delivery"]["id"], dh))
        order = validate_success(
            api_client.get_order(ctx["order"]["id"],
                                 make_customer_headers(ctx["customer"]["id"])))
        assert order["fulfillment_status"] == "PLACED", \
            "declined offer must revert the order ROUTED -> PLACED"


# ===========================================================================
# cross_entity_state_dependency — dispatch requires eligible dasher
# ===========================================================================
class TestDispatchRequiresEligibleDasher:
    def test_dispatch_with_only_offline_dasher_rejected(self, api):
        """PRD §3.7: "requires that at least one eligible dasher exists (otherwise `ERR_NO_DASHER_AVAILABLE`). The eligible pool is exactly those dashers whose `availability` is `ONLINE`, whose `home_zone_id` equals the order's `zone_id`, and whose `active_delivery_count` is strictly less than their `max_batch_size`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_eligible_dasher_order_to_dasher
        """
        zone, restaurant, item, dasher, customer = setup_market(
            dasher_overrides={"availability": "OFFLINE"})
        order = place_simple_order(customer["id"], restaurant["id"], item["id"], tip_cents=0)
        resp = api_client.dispatch_order(
            order["id"], {"expected_order_version": order["version"]},
            make_restaurant_headers(restaurant["id"]))
        validate_error(resp, ApiErrorId.ERR_NO_DASHER_AVAILABLE.value, expected_status=409)

    def test_order_stays_placed_after_failed_dispatch(self, api):
        """PRD §3.7: "if the pool is empty, the dispatch is rejected with `ERR_NO_DASHER_AVAILABLE`." Dispatch is permitted only from PLACED (PRD
        §3.7), and a rejected dispatch does not advance the order.

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_eligible_dasher_order_to_dasher
        """
        zone, restaurant, item, dasher, customer = setup_market(
            dasher_overrides={"availability": "OFFLINE"})
        order = place_simple_order(customer["id"], restaurant["id"], item["id"], tip_cents=0)
        api_client.dispatch_order(
            order["id"], {"expected_order_version": order["version"]},
            make_restaurant_headers(restaurant["id"]))
        after = validate_success(
            api_client.get_order(order["id"], make_customer_headers(customer["id"])))
        assert after["fulfillment_status"] == "PLACED"


# ===========================================================================
# Corner: cross_cutting (OCC)
# ===========================================================================
class TestOptimisticConcurrency:
    def test_stale_expected_version_rejected(self, api):
        """PRD §2.10: "If a prior dispatch has already advanced that order ... a later dispatch still carrying the previously observed value is operating on a stale view and is rejected with `ERR_STALE_ORDER_VERSION` at HTTP 412."
        and PRD §3.4: "Adding a line increments the order's `version` by 1."

        Place (v1), add a line item (v2), dispatch with stale v1 -> 412.

        Design: Corner/cross_cutting_complexity_layers/occ_stale_order_version_on_dispatch
        """
        zone, restaurant, item, dasher, customer = setup_market()
        order = place_simple_order(customer["id"], restaurant["id"], item["id"], tip_cents=0)
        stale_version = order["version"]
        ch = make_customer_headers(customer["id"])
        validate_success(api_client.add_line_item(
            order["id"], {"menu_item_id": item["id"], "quantity": 1}, ch),
            expected_status=201)
        resp = api_client.dispatch_order(
            order["id"], {"expected_order_version": stale_version},
            make_restaurant_headers(restaurant["id"]))
        validate_error(resp, ApiErrorId.ERR_STALE_ORDER_VERSION.value, expected_status=412)
        after = validate_success(api_client.get_order(order["id"], ch))
        assert after["fulfillment_status"] == "PLACED", "order stays PLACED after stale dispatch"

    def test_fresh_expected_version_dispatch_succeeds(self, api):
        """PRD §3.7: "A successful dispatch creates a **Delivery** in `fulfillment_status` `OFFERED ... The order advances from `PLACED` to `ROUTED`, and the order's `version` is incremented by 1."

        Design: Corner/cross_cutting_complexity_layers/occ_fresh_order_version_on_dispatch_succeeds
        """
        zone, restaurant, item, dasher, customer = setup_market()
        order = place_simple_order(customer["id"], restaurant["id"], item["id"], tip_cents=0)
        resp = api_client.dispatch_order(
            order["id"], {"expected_order_version": order["version"]},
            make_restaurant_headers(restaurant["id"]))
        delivery = validate_success(resp, expected_status=201)
        assert delivery["fulfillment_status"] == "OFFERED"
        after = validate_success(
            api_client.get_order(order["id"], make_customer_headers(customer["id"])))
        assert after["fulfillment_status"] == "ROUTED"
        assert after["version"] == 2, f"version must increment to 2, got {after['version']}"


# ===========================================================================
# Corner: scheduled actions
# ===========================================================================
class TestScheduledOrders:
    def test_future_scheduled_order_starts_in_scheduled(self, api):
        """PRD §3.4: "unless `scheduled_for` is set to a time in the future, in which case the order instead starts in `SCHEDULED` and is not counted toward zone demand until it is released."

        Design: Corner/cross_cutting_complexity_layers/scheduled_order_starts_in_scheduled_state
        """
        ctx = setup_scheduled_order(scheduled_for="2026-06-07T20:00:00Z")
        assert ctx["order"]["fulfillment_status"] == "SCHEDULED"
        zone = validate_success(api_client.get_zone(ctx["zone"]["id"], ADMIN))
        assert zone["active_order_count"] == 0, \
            "a SCHEDULED order must not count toward zone demand"

    def test_release_before_due_rejected(self, api):
        """PRD §3.6: "Releasing requires the order to be in `SCHEDULED` (otherwise `ERR_INVALID_ORDER_STATE`) and requires the current clock to be at or after the order's `scheduled_for` (otherwise `ERR_SCHEDULE_NOT_DUE`)."

        Clock 10:00, scheduled 18:00 -> release rejected; order stays SCHEDULED.

        Design: Corner/state_machines/release_scheduled_order_before_due_rejected
        """
        ctx = setup_scheduled_order(scheduled_for="2026-06-07T18:00:00Z",
                                    clock_iso="2026-06-07T10:00:00Z")
        ch = make_customer_headers(ctx["customer"]["id"])
        resp = api_client.release_order(ctx["order"]["id"], ch)
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_NOT_DUE.value)
        after = validate_success(api_client.get_order(ctx["order"]["id"], ch))
        assert after["fulfillment_status"] == "SCHEDULED"

    def test_release_when_due_moves_to_placed_and_counts_demand(self, api):
        """PRD §3.6: "On release, the order transitions from `SCHEDULED` to `PLACED`, the zone's `active_order_count` is re-derived upward to include it"

        Schedule 12:00, advance clock to 12:30, release -> PLACED and demand 1.

        Design: Corner/state_machines/release_scheduled_order_when_due_succeeds
        """
        ctx = setup_scheduled_order(scheduled_for="2026-06-07T12:00:00Z",
                                    clock_iso="2026-06-07T10:00:00Z")
        set_clock("2026-06-07T12:30:00Z")
        ch = make_customer_headers(ctx["customer"]["id"])
        released = validate_success(api_client.release_order(ctx["order"]["id"], ch))
        assert released["fulfillment_status"] == "PLACED"
        zone = validate_success(api_client.get_zone(ctx["zone"]["id"], ADMIN))
        assert zone["active_order_count"] == 1, \
            f"released order must raise demand to 1, got {zone['active_order_count']}"


# ===========================================================================
# Corner: state machine transitions
# ===========================================================================
def test_accept_already_accepted_delivery_invalid_state(api):
    """PRD §3.8: "Accepting an offer is permitted only from `OFFERED` (otherwise `ERR_INVALID_DELIVERY_STATE`)"

    Design: Corner/state_machines/accept_already_accepted_delivery_invalid_state
    """
    ctx = setup_order_accepted()
    dh = make_dasher_headers(ctx["dasher"]["id"])
    resp = api_client.accept_delivery(ctx["delivery"]["id"], dh)
    validate_error(resp, ApiErrorId.ERR_INVALID_DELIVERY_STATE.value)


def test_cancel_delivered_order_not_cancellable(api):
    """PRD §3.11: "A `Customer` may cancel their own order while it is in `SCHEDULED`, `PLACED`, or `ROUTED`; a cancel attempt from any other state is rejected with `ERR_ORDER_NOT_CANCELLABLE`."

    Design: Corner/state_machines/cancel_delivered_order_not_cancellable
    """
    ctx = setup_order_delivered()
    resp = api_client.cancel_order(ctx["order"]["id"],
                                   make_customer_headers(ctx["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ORDER_NOT_CANCELLABLE.value)


def test_deactivate_restaurant_cascades_delist_menu(api):
    """PRD §3.2: "When it succeeds, the restaurant moves from `ACTIVE` to `DEACTIVATED` and, as a cascade, every one of its menu items still `LISTED` is moved to `DELISTED`."

    Design: Corner/state_machines/deactivate_restaurant_cascades_delist_menu
    """
    zone = create_zone()
    restaurant = create_restaurant(zone["id"])
    item = create_menu_item(restaurant["id"])
    rh = make_restaurant_headers(restaurant["id"])
    deactivated = validate_success(api_client.deactivate_restaurant(restaurant["id"], rh))
    assert deactivated["status"] == "DEACTIVATED"
    after_item = validate_success(api_client.get_menu_item(item["id"], rh))
    assert after_item["status"] == "DELISTED", "menu item must cascade to DELISTED"


# ===========================================================================
# Corner: cascading side effects (partial cascade)
# ===========================================================================
def test_cancel_routed_order_cancels_offered_delivery(api):
    """PRD §3.11: "If a delivery exists in a non-terminal state — `OFFERED` or `ACCEPTED` — it is transitioned to `CANCELLED` and its earnings record is reversed from `ACCRUED` to `REVERSED`."

    Cancelling a ROUTED order with an OFFERED delivery cancels that delivery.

    Design: Corner/cross_cutting_complexity_layers/cascade_partial_only_non_terminal_delivery_cancelled
    """
    ctx = setup_order_routed()
    validate_success(api_client.cancel_order(
        ctx["order"]["id"], make_customer_headers(ctx["customer"]["id"])))
    delivery = validate_success(
        api_client.get_delivery(ctx["delivery"]["id"],
                                make_dasher_headers(ctx["dasher"]["id"])))
    assert delivery["fulfillment_status"] == "CANCELLED", \
        "the non-terminal OFFERED delivery must be cancelled by the order cancel"
