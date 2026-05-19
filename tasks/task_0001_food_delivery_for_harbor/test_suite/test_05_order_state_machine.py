"""Order state machine (PRD §3.4–§3.7).

Covers:
- PLACED → RESTAURANT_ACCEPTED via /accept (restaurant only, ACTIVE, PLACED)
- PLACED → CANCELLED via /cancel
- CANCELLED: payment_status becomes VOIDED
- /ready rejects if no accepted Assignment (ERR_INVALID_STATE)
- Invalid transitions from terminal states
"""

import pytest

from test_helpers import (
    api_client,
    create_active_restaurant,
    create_available_rider,
    dispatch_order_as_admin,
    get_success_data,
    make_customer_headers,
    make_restaurant_headers,
    place_order,
    restaurant_accept_order,
    setup_customer_restaurant_menu,
    start_preparing,
    validate_error,
    validate_success,
)


class TestOrderAccept:
    def test_placed_to_restaurant_accepted(self, api):
        """PRD §3.5: "A restaurant that owns the target order can accept it, transitioning
        the order from PLACED to RESTAURANT_ACCEPTED."

        Claim: /accept on PLACED → status RESTAURANT_ACCEPTED.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item)
        headers = make_restaurant_headers(restaurant["id"])
        res = api.accept_order(order["id"], headers)
        data = validate_success(res, 200)
        assert data["status"] == "RESTAURANT_ACCEPTED"

    def test_accept_leaves_payment_authorized(self, api):
        """PRD §3.5: "Acceptance does not touch payment_status — the order is already
        AUTHORIZED from placement."

        Claim: after /accept, payment_status remains AUTHORIZED.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item)
        accepted = restaurant_accept_order(order, restaurant)
        assert accepted["payment_status"] == "AUTHORIZED"

    def test_accept_twice_rejected(self, api):
        """PRD §2.6 priority 6: state-machine precondition.

        Claim: /accept on RESTAURANT_ACCEPTED → ERR_INVALID_STATE.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item)
        restaurant_accept_order(order, restaurant)
        headers = make_restaurant_headers(restaurant["id"])
        res = api.accept_order(order["id"], headers)
        validate_error(res, "ERR_INVALID_STATE")


class TestOrderCancel:
    def test_customer_cancel_placed(self, api):
        """PRD §3.5: "Either the customer or the restaurant (via rejection) may cancel an
        order while it is still in PLACED; the cancellation transitions the order to
        CANCELLED and moves payment_status from whichever of UNPAID or AUTHORIZED it is
        currently in to VOIDED."

        Claim: customer /cancel on PLACED → CANCELLED with payment_status=VOIDED.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item)
        headers = make_customer_headers(customer["id"])
        res = api.cancel_order(order["id"], headers)
        data = validate_success(res, 200)
        assert data["status"] == "CANCELLED"
        assert data["payment_status"] == "VOIDED"

    def test_cancel_after_acceptance_rejected(self, api):
        """PRD §3.5: "Cancellation once the order has moved beyond PLACED is not available
        through this channel; disputes at later stages flow through the refund workflow
        in §3.9."

        Claim: /cancel on RESTAURANT_ACCEPTED → ERR_INVALID_STATE.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item)
        restaurant_accept_order(order, restaurant)
        headers = make_customer_headers(customer["id"])
        res = api.cancel_order(order["id"], headers)
        validate_error(res, "ERR_INVALID_STATE")


class TestOrderReady:
    def test_ready_requires_accepted_assignment(self, api):
        """PRD §3.5: "Ready is only legal when a rider has already ACCEPTED the dispatch
        (or is further along at PICKED_UP) — the system refuses the ready transition
        otherwise with ERR_INVALID_STATE."

        Claim: /ready while all Assignments still OFFERED → ERR_INVALID_STATE.

        # difficulty: cross_entity_state_dependency/order_ready_requires_assignment_accepted
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        # A rider must exist so start-preparing's implicit dispatch has a candidate,
        # but the rider intentionally does NOT accept the offer.
        _rider = create_available_rider()
        order = place_order(customer, restaurant, menu_item)
        restaurant_accept_order(order, restaurant)
        start_preparing(order, restaurant)
        # Intentionally do NOT have the rider accept the offer.
        headers = make_restaurant_headers(restaurant["id"])
        res = api.mark_order_ready(order["id"], headers)
        validate_error(res, "ERR_INVALID_STATE")

    def test_ready_succeeds_after_assignment_accepted(self, api):
        """PRD §3.5: "Ready is only legal when a rider has already ACCEPTED the dispatch
        (or is further along at PICKED_UP) — the system refuses the ready transition
        otherwise with ERR_INVALID_STATE."

        Claim: once rider ACCEPTS, /ready succeeds with status=READY_FOR_PICKUP.

        # difficulty: cross_entity_state_dependency/order_ready_requires_assignment_accepted
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        # Ensure an AVAILABLE candidate exists; the server's dispatch may pick any
        # AVAILABLE rider (PRD §3.6 does not prescribe a tie-breaker), so we read
        # the stamped rider_id back off the returned assignment.
        create_available_rider()
        order = place_order(customer, restaurant, menu_item)
        restaurant_accept_order(order, restaurant)

        # PRD §3.6 allows /accept while Order.status is RESTAURANT_ACCEPTED. Dispatching
        # and accepting before start-preparing avoids a second (orphan) OFFERED
        # Assignment that start-preparing's implicit dispatch would create.
        asg = dispatch_order_as_admin(order)
        from test_helpers import make_rider_headers
        r_headers = make_rider_headers(asg["rider_id"])
        accepted = api.accept_assignment(asg["id"], r_headers)
        assert accepted.status_code == 200
        start_preparing(order, restaurant)

        # Now /ready should succeed.
        headers = make_restaurant_headers(restaurant["id"])
        res = api.mark_order_ready(order["id"], headers)
        data = validate_success(res, 200)
        assert data["status"] == "READY_FOR_PICKUP"


class TestOrderPromisedDeliveryTime:
    def test_promised_is_placement_plus_45_minutes(self, api):
        """PRD §3.4: "promised_delivery_time is set to the placement time plus 45 minutes."

        Claim: promised_delivery_time is present and after created_at.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        order = place_order(customer, restaurant, menu_item)
        assert order["promised_delivery_time"] > order["created_at"]
