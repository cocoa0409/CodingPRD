"""Assignment state machine and rider lifecycle (PRD §3.3, §3.6).

Covers:
- Rider go-online / go-offline gating
- Rider suspend: requires performance threshold breach
- Assignment OFFERED → ACCEPTED transitions rider to ON_DELIVERY
- Assignment accept uniqueness: another Assignment in OFFERED/ACCEPTED/PICKED_UP → ERR_ORDER_ALREADY_ASSIGNED
- Rider cancel after acceptance creates RIDER_NO_SHOW fine
"""

import pytest

from test_helpers import (
    TEST_USERS,
    accept_assignment_as_rider,
    api_client,
    create_active_restaurant,
    create_available_rider,
    create_customer,
    dispatch_order_as_admin,
    get_success_data,
    make_rider_headers,
    place_order,
    restaurant_accept_order,
    run_order_to_picked_up,
    setup_customer_restaurant_menu,
    start_preparing,
    take_other_riders_offline,
    validate_error,
    validate_success,
)


class TestRiderGoOnlineOffline:
    def test_go_online_from_offline(self, api):
        """PRD §3.3: "To begin receiving dispatch offers, a rider invokes their go-online
        capability, transitioning from OFFLINE to AVAILABLE."

        Claim: /go-online on OFFLINE rider → status=AVAILABLE.
        """
        from test_helpers import create_rider_payload
        from test_helpers.fixtures import _CREATED_RIDER_IDS
        admin = TEST_USERS["admin_headers"]
        rider = get_success_data(api.create_rider(create_rider_payload(), admin))
        headers = make_rider_headers(rider["id"])
        data = validate_success(api.rider_go_online(rider["id"], headers), 200)
        assert data["status"] == "AVAILABLE"
        # Register so subsequent tests can take this rider offline via
        # take_other_riders_offline — PRD has no list-riders endpoint so this is the
        # only way downstream fixtures can narrow the dispatch candidate pool.
        _CREATED_RIDER_IDS.add(rider["id"])

    def test_go_offline_blocked_while_active_assignment(self, api):
        """PRD §3.3: "a rider may go offline only when no Assignment referring to them
        is currently in OFFERED, ACCEPTED, or PICKED_UP; attempting to go offline while
        any such assignment exists fails the state-machine precondition with
        ERR_INVALID_STATE."

        Claim: rider with PICKED_UP assignment → /go-offline returns ERR_INVALID_STATE.
        """
        ctx = run_order_to_picked_up(distance_km=2.0)
        rider = ctx["rider"]
        headers = make_rider_headers(rider["id"])
        res = api.rider_go_offline(rider["id"], headers)
        validate_error(res, "ERR_INVALID_STATE")


class TestRiderSuspendGating:
    def test_suspend_blocked_when_metrics_within_threshold(self, api, admin_headers):
        """PRD §3.3: "A PlatformAdmin may suspend an AVAILABLE rider, but only when at
        least one of two performance thresholds is breached: the rider's on_time_rate
        must be strictly below 0.70, or the rider's acceptance_rate must be strictly
        below 0.50. Attempting to suspend a rider whose metrics are both at or above
        these thresholds is rejected with ERR_SUSPEND_CRITERIA_NOT_MET."

        Claim: fresh rider (metrics 1.0 / 1.0) → /suspend returns
        ERR_SUSPEND_CRITERIA_NOT_MET.
        """
        rider = create_available_rider()
        res = api.suspend_rider(rider["id"], admin_headers)
        validate_error(res, "ERR_SUSPEND_CRITERIA_NOT_MET")


class TestAssignmentAcceptCascade:
    def test_accept_cascades_rider_to_on_delivery(self, api):
        """PRD §3.6: "Acceptance stamps accepted_at, cascades the rider's status to
        ON_DELIVERY if they were AVAILABLE, and triggers a recomputation of
        acceptance_rate over the rider's last 30 offers."

        Claim: after /accept, Rider.status moves AVAILABLE → ON_DELIVERY.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        rider = create_available_rider()
        # Take prior-test AVAILABLE riders offline so dispatch picks THIS rider — the
        # /accept below uses make_rider_headers(rider["id"]) and will fail with
        # ERR_FORBIDDEN if the server dispatched to a different rider (PRD §3.6 does
        # not prescribe a tie-breaker among AVAILABLE candidates).
        take_other_riders_offline(keep_rider_id=rider["id"])
        order = place_order(customer, restaurant, menu_item)
        restaurant_accept_order(order, restaurant)
        asg = dispatch_order_as_admin(order)

        headers = make_rider_headers(rider["id"])
        data = validate_success(api.accept_assignment(asg["id"], headers), 200)
        assert data["status"] == "ACCEPTED"

        admin = TEST_USERS["admin_headers"]
        rider_after = get_success_data(api.get_rider(rider["id"], admin))
        assert rider_after["status"] == "ON_DELIVERY"


class TestAssignmentRiderCancellation:
    def test_rider_cancel_after_acceptance_creates_no_show_fine(self, api):
        """PRD §3.6: "Cancellation creates a Fine whose subject is the rider and whose
        reason is RIDER_NO_SHOW, with amount_cents fixed at 500 — the flat no-show
        penalty. That fine in turn debits the rider's wallet_balance_cents by 500 cents
        and triggers a bonus_tier recomputation."

        Claim: /cancel after ACCEPT (order not yet PICKED_UP) → Fine(subject=RIDER,
        reason=RIDER_NO_SHOW, amount=500) and rider.wallet_balance_cents goes to -500.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        rider = create_available_rider()
        # Take all prior-test AVAILABLE riders offline so dispatch picks THIS rider.
        # Needed because PRD §3.6 does not prescribe a tie-breaker among AVAILABLE
        # riders and the wallet-assertion below relies on the rider's starting balance
        # being 0 (a carry-over rider from a prior test would have a nonzero balance).
        take_other_riders_offline(keep_rider_id=rider["id"])
        order = place_order(customer, restaurant, menu_item)
        restaurant_accept_order(order, restaurant)
        # Dispatch + accept BEFORE start-preparing per PRD §3.6: /accept is legal while
        # Order.status is in {RESTAURANT_ACCEPTED, PREPARING, READY_FOR_PICKUP}.
        asg = dispatch_order_as_admin(order)
        headers = make_rider_headers(rider["id"])
        asg = validate_success(api.accept_assignment(asg["id"], headers), 200)

        # Rider cancels before pickup.
        validate_success(api.cancel_assignment(asg["id"], headers), 200)

        admin = TEST_USERS["admin_headers"]
        res = api.list_fines(
            admin,
            params={"subject_type": "RIDER", "subject_id": rider["id"],
                    "settlement_status": "PENDING"},
        )
        body = res.json()
        assert body["response_type"] == "array"
        no_show = [f for f in body["data"] if f.get("reason") == "RIDER_NO_SHOW"]
        assert len(no_show) >= 1
        assert no_show[0]["amount_cents"] == 500

        rider_after = get_success_data(api.get_rider(rider["id"], admin))
        assert rider_after["wallet_balance_cents"] == -500


class TestAssignmentUniqueness:
    def test_second_accept_same_order_conflicts(self, api):
        """PRD §3.6: "no other Assignment already exists for the same order_id in
        OFFERED, ACCEPTED, or PICKED_UP. … the losing attempt is rejected with
        ERR_ORDER_ALREADY_ASSIGNED."

        Claim: after rider A accepts Assignment X for order O (X is now ACCEPTED),
        /dispatch is re-triggered for the same order targeting rider B with a fresh
        Assignment Y in OFFERED; when rider B attempts to accept Y, the uniqueness
        check trips because an ACCEPTED peer already exists → ERR_ORDER_ALREADY_ASSIGNED.

        This sequence is the PRD-faithful construction of the race: it avoids staging
        two concurrent OFFERED rows (which §3.6's uniqueness literally forbids and
        which would cause the FIRST accept to fail, not the second). Dispatching Y
        AFTER X has already ACCEPTED is explicitly permitted by the §4 table's
        "Trigger or re-trigger dispatch of a fresh assignment" language, because the
        Order's own state stays in RESTAURANT_ACCEPTED when an Assignment is accepted.
        """
        restaurant, menu_item, customer = setup_customer_restaurant_menu()
        rider_a = create_available_rider()
        rider_b = create_available_rider()
        order = place_order(customer, restaurant, menu_item)
        restaurant_accept_order(order, restaurant)

        # Dispatch first; whichever rider the server stamped accepts their offer.
        asg_x = dispatch_order_as_admin(order)
        headers_x = make_rider_headers(asg_x["rider_id"])
        validate_success(api.accept_assignment(asg_x["id"], headers_x), 200)

        # Re-dispatch after X is ACCEPTED. Server must pick a DIFFERENT rider because
        # X's rider already has an ACCEPTED peer (/dispatch excludes them). PRD §4
        # explicitly calls this out: "Trigger or re-trigger dispatch of a fresh
        # assignment."
        asg_y = dispatch_order_as_admin(order)
        assert asg_y["rider_id"] != asg_x["rider_id"], (
            "Re-dispatch must target a different rider when the first rider already "
            "holds an ACCEPTED assignment for the same order."
        )

        # Rider B accepts Y: uniqueness check fires on the ACCEPTED peer X →
        # ERR_ORDER_ALREADY_ASSIGNED (PRD §3.6).
        headers_y = make_rider_headers(asg_y["rider_id"])
        res = api.accept_assignment(asg_y["id"], headers_y)
        validate_error(res, "ERR_ORDER_ALREADY_ASSIGNED")
