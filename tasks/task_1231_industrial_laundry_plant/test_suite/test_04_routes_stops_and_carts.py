"""Route/stop/cart workflows: dispatch preconditions, pickup payload rules,
cart receive guards, pickup weight accumulation, and route reconciliation."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_plant, create_customer,
    create_route, create_stop, dispatch_route, arrive_stop, pickup_stop,
    receive_cart, receive_stop_carts, list_carts, find_cart_by_tag, get_stop,
    file_dispute,
    setup_stop_received, setup_delivery_delivered,
)

ADMIN = TEST_USERS["plant_admin_headers"]
DRIVER = TEST_USERS["route_driver_headers"]
OPERATOR = TEST_USERS["plant_operator_headers"]


class TestDispatchPreconditions:
    def test_route_dispatch_without_stops_rejected(self, api):
        """PRD §3.2: "Dispatch moves a route from `PLANNED` to `DISPATCHED` and requires at least one stop still in `SCHEDULED` state; dispatching a stop-less route fails with `ERR_ROUTE_HAS_NO_STOPS`."

        Design: Corner/state_machines/route_dispatch_without_stops_rejected
        """
        plant = create_plant()
        route = create_route(plant["id"])
        resp = api.dispatch_route(route["id"], DRIVER)
        validate_error(resp, ApiErrorId.ERR_ROUTE_HAS_NO_STOPS)

    def test_stop_arrive_blocked_until_route_dispatched(self, api):
        """PRD §3.2: "Arrival at a stop moves it from `SCHEDULED` to `ARRIVED`, and is only possible while the parent route is `DISPATCHED` — arriving under an undispatched route fails with `ERR_ROUTE_NOT_DISPATCHED`."

        Design: Difficulty/cross_entity_state_dependency/stop_arrive_requires_route_dispatched
        """
        plant = create_plant()
        customer = create_customer(plant["id"])
        route = create_route(plant["id"])
        stop = create_stop(route["id"], customer["id"], declared_soiled_weight_lb=10.0)

        blocked = api.arrive_stop(stop["id"], DRIVER)
        validate_error(blocked, ApiErrorId.ERR_ROUTE_NOT_DISPATCHED)

        dispatch_route(route["id"])
        arrived = validate_success(api.arrive_stop(stop["id"], DRIVER), 200)
        assert arrived["status"] == "ARRIVED", (
            f"arrive must succeed once the route is DISPATCHED, got {arrived['status']}"
        )

    def test_stop_arrive_in_wrong_stop_state_rejected(self, api):
        """PRD §3.2: "Arrival at a stop moves it from `SCHEDULED` to `ARRIVED`, and is only possible while the parent route is `DISPATCHED` — arriving under an undispatched route fails with `ERR_ROUTE_NOT_DISPATCHED`."
        PRD §2.9: "State admissibility: the target resource must be in a state that permits the requested transition — `ERR_INVALID_STATE` (HTTP 409). Applies to all state-transition endpoints."

        Design: Difficulty/cross_entity_state_dependency/stop_arrive_requires_route_dispatched
        """
        ctx = setup_stop_received(with_category=False)
        resp = api.arrive_stop(ctx["stop"]["id"], DRIVER)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPickupPayload:
    def test_empty_pickup_rejected(self, api):
        """PRD §3.2: "The cart list must be non-empty — an empty pickup fails with `ERR_EMPTY_PICKUP` — and every `cart_tag` must be unique within the stop, with duplicates rejected as `ERR_DUPLICATE_CART_TAG`."

        Design: Corner/validations/empty_pickup_rejected
        """
        plant = create_plant()
        customer = create_customer(plant["id"])
        route = create_route(plant["id"])
        stop = create_stop(route["id"], customer["id"])
        dispatch_route(route["id"])
        arrive_stop(stop["id"])
        resp = api.pickup_stop(stop["id"], {"carts": []}, DRIVER)
        validate_error(resp, ApiErrorId.ERR_EMPTY_PICKUP)

    def test_duplicate_cart_tag_within_stop_rejected(self, api):
        """PRD §3.2: "The cart list must be non-empty — an empty pickup fails with `ERR_EMPTY_PICKUP` — and every `cart_tag` must be unique within the stop, with duplicates rejected as `ERR_DUPLICATE_CART_TAG`."

        Design: Corner/validations/duplicate_cart_tag_within_stop_rejected
        """
        plant = create_plant()
        customer = create_customer(plant["id"])
        route = create_route(plant["id"])
        stop = create_stop(route["id"], customer["id"])
        dispatch_route(route["id"])
        arrive_stop(stop["id"])
        resp = api.pickup_stop(
            stop["id"],
            {"carts": [
                {"cart_tag": "CART-1", "scale_weight_lb": 5.0},
                {"cart_tag": "CART-1", "scale_weight_lb": 3.0},
            ]},
            DRIVER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_CART_TAG)


class TestCartReceive:
    def test_cart_receive_in_terminal_state_rejected(self, api):
        """PRD §3.2: "As carts later arrive at the plant gate, a `PlantOperator` receives each one, moving it from `DECLARED` to `RECEIVED`."
        PRD §2.9: "State admissibility: the target resource must be in a state that permits the requested transition — `ERR_INVALID_STATE` (HTTP 409). Applies to all state-transition endpoints."

        Design: Corner/state_machines/cart_receive_before_pickup_rejected_invalid_state
        """
        ctx = setup_stop_received(with_category=False)
        cart = ctx["carts"][0]
        assert cart["status"] == "RECEIVED"
        resp = api.receive_cart(cart["id"], OPERATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_pickup_weight_recomputed_on_each_receive(self, api):
        """PRD §3.2: "Each receive recomputes the stop's `actual_soiled_weight_lb` as the sum of `scale_weight_lb` over the stop's carts in `RECEIVED` or `SORTED` state — `DECLARED` and `VOIDED` carts are excluded — and, for chip-tracking customers, advances that customer's garments from `IN_TRANSIT_SOILED` to `SOILED_RECEIVED`."

        Design: Corner/calculations/pickup_weight_variance_recomputed_on_each_receive
        """
        plant = create_plant()
        customer = create_customer(plant["id"])
        route = create_route(plant["id"])
        stop = create_stop(
            route["id"], customer["id"], declared_soiled_weight_lb=100.0
        )
        dispatch_route(route["id"])
        arrive_stop(stop["id"])
        pickup_stop(
            stop["id"],
            carts=[
                {"cart_tag": "CART-1", "scale_weight_lb": 60.0},
                {"cart_tag": "CART-2", "scale_weight_lb": 45.0},
            ],
        )
        carts = list_carts(stop["id"])
        cart1 = find_cart_by_tag(carts, "CART-1")
        cart2 = find_cart_by_tag(carts, "CART-2")

        receive_cart(cart1["id"])
        mid = get_stop(stop["id"])
        assert mid["actual_soiled_weight_lb"] == 60.0, (
            f"only the RECEIVED cart counts; expected 60.0, "
            f"got {mid['actual_soiled_weight_lb']}"
        )

        receive_cart(cart2["id"])
        final = get_stop(stop["id"])
        assert final["actual_soiled_weight_lb"] == 105.0, (
            f"both RECEIVED carts count; expected 105.0, "
            f"got {final['actual_soiled_weight_lb']}"
        )


class TestRouteReconciliation:
    def test_route_reconcile_blocked_by_open_discrepancy(self, api):
        """PRD §3.2: "Reconciliation is the final, terminal step: moving from `COMPLETED` to `RECONCILED` requires every stop to be in `CLOSED` or `DISPUTED` — otherwise `ERR_ROUTE_STOPS_UNRESOLVED` — and additionally requires that no discrepancy on any delivery of any stop of the route still sits in `FILED`, `UNDER_REVIEW`, or `APPROVED`; open review work blocks reconciliation with `ERR_ROUTE_DISCREPANCIES_OPEN`."

        Design: Corner/state_machines/route_reconcile_blocked_by_open_discrepancy
        """
        ctx = setup_delivery_delivered(
            pieces_promised=10, pieces_delivered=8,
            customer_overrides={"billing_mode": "RENTAL"},
        )
        file_dispute(ctx["delivery"]["id"], 2, ctx["customer"]["id"])
        completed = validate_success(
            api.complete_route(ctx["route"]["id"], DRIVER), 200
        )
        assert completed["status"] == "COMPLETED"
        resp = api.reconcile_route(ctx["route"]["id"], DRIVER)
        validate_error(resp, ApiErrorId.ERR_ROUTE_DISCREPANCIES_OPEN)
