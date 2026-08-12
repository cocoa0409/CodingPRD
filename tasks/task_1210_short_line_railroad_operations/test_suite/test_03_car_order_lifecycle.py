"""Car order lifecycle: initial state, invalid transitions, amendment rules,
optimistic concurrency, furnish readback, and ownership denial
(PRD §2.1, §2.8, §2.9, §3.1, §3.2)."""
from test_helpers import (
    ApiErrorId,
    accept_order,
    assert_car_order,
    create_customer,
    create_segment,
    create_siding,
    furnish_order,
    make_customer_rep_headers,
    place_car_order,
    setup_accepted_order,
    setup_customer_with_siding,
    setup_furnished_order,
    setup_placed_order,
    validate_error,
    validate_success,
)


class TestCarOrderInitialState:
    def test_car_order_initial_state_placed(self, api, dispatcher_headers):
        """PRD §3.1: "A new order rests in `PLACED` with `cars_furnished_count`
        at zero and neither `furnished_at` nor `released_at` set."

        Design: Corner/state_machines/car_order_initial_state_placed
        """
        customer, segment, siding = setup_customer_with_siding(capacity_cars=4)
        order = place_car_order(customer["id"], siding["id"], car_type="BOX", quantity=2)
        assert_car_order(order)
        assert order["status"] == "PLACED", f"new order must rest in PLACED, got {order['status']}"
        assert order["cars_furnished_count"] == 0, (
            f"new order must have cars_furnished_count 0, got {order['cars_furnished_count']}"
        )

    def test_car_order_double_accept_rejected(self, api, dispatcher_headers):
        """PRD §3.2: "A successful acceptance moves the order from `PLACED` to
        `ACCEPTED` and increments its `version`."
        PRD §2.9: "Fourth, state legality: the target resource must be in a state
        from which the requested transition is defined, failing as
        `ERR_INVALID_STATE` (HTTP 409) — or the more specific state errors
        `ERR_ORDER_NOT_AMENDABLE` and `ERR_MEMBER_NOT_AVAILABLE` where §3 names
        them."

        Design: Corner/state_machines/car_order_double_accept_rejected
        """
        ctx = setup_accepted_order(quantity=1, capacity_cars=4)
        resp = api.accept_car_order(ctx["order"]["id"], dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCarOrderAmendment:
    def test_patch_quantity_below_furnished_rejected(self, api):
        """PRD §3.1: "When a replacement `quantity` is supplied, it must be at
        least the number of cars already furnished against the order
        (`cars_furnished_count`); a smaller value is rejected with
        `ERR_QUANTITY_BELOW_FURNISHED`."

        Design: Corner/validations/patch_quantity_below_furnished_rejected
        """
        ctx = setup_accepted_order(quantity=3, car_type="BOX", capacity_cars=6, num_cars=2)
        order = furnish_order(ctx["order"]["id"], 2)
        assert order["status"] == "PARTIALLY_FURNISHED"
        rep = make_customer_rep_headers(ctx["customer"]["id"])
        current = validate_success(api.get_car_order(order["id"], rep))

        resp = api.patch_car_order(
            order["id"],
            {"quantity": 1, "expected_car_order_version": current["version"]},
            rep,
        )
        validate_error(resp, ApiErrorId.ERR_QUANTITY_BELOW_FURNISHED)

    def test_patch_furnished_order_not_amendable(self, api):
        """PRD §3.1: "An order may be amended — a replacement `quantity`, a
        replacement `needed_by_date`, or both — only while it is `PLACED`,
        `ACCEPTED`, or `PARTIALLY_FURNISHED`; an amendment attempted in any other
        status is refused with `ERR_ORDER_NOT_AMENDABLE`."

        Design: Corner/validations/patch_furnished_order_not_amendable
        """
        ctx = setup_furnished_order(quantity=1, car_type="BOX", capacity_cars=4)
        rep = make_customer_rep_headers(ctx["customer"]["id"])
        current = validate_success(api.get_car_order(ctx["order"]["id"], rep))
        assert current["status"] == "FURNISHED"

        resp = api.patch_car_order(
            ctx["order"]["id"],
            {"quantity": 3, "expected_car_order_version": current["version"]},
            rep,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_AMENDABLE)

    def test_occ_car_order_amend_stale_version(self, api):
        """PRD §2.8: "Amending a car order through `PATCH /rail/car-orders/{id}`
        requires the request to carry `expected_car_order_version`, holding the
        order's `version` as the client last observed it. If the order's current
        `version` has advanced beyond that value — for example because a
        dispatcher accepted the order or furnished cars against it in the interim,
        both of which legitimately increment the version — the amendment is
        rejected with `ERR_STALE_VERSION` (HTTP 412), so the client cannot
        overwrite an order state it never observed."

        Design: Corner/cross_cutting_layers/occ_car_order_amend_stale_version
        """
        ctx = setup_placed_order(quantity=2, car_type="BOX", capacity_cars=4)
        stale_version = ctx["order"]["version"]
        accept_order(ctx["order"]["id"])  # advances the order's version
        rep = make_customer_rep_headers(ctx["customer"]["id"])

        resp = api.patch_car_order(
            ctx["order"]["id"],
            {"needed_by_date": "2026-07-01T00:00:00Z", "expected_car_order_version": stale_version},
            rep,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestFurnish:
    def test_furnish_insufficient_cars(self, api, dispatcher_headers):
        """PRD §3.2: "Eligible cars are fleet members whose `status` is
        `AVAILABLE` and whose `car_type` equals the order's; when fewer eligible
        cars exist than the requested `count`, the request fails with
        `ERR_INSUFFICIENT_AVAILABLE_CARS`."

        Design: Corner/validations/furnish_insufficient_cars
        """
        ctx = setup_accepted_order(quantity=5, car_type="BOX", capacity_cars=10, num_cars=1)
        resp = api.furnish_car_order(ctx["order"]["id"], {"count": 5}, dispatcher_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABLE_CARS)

        order = validate_success(api.get_car_order(ctx["order"]["id"], dispatcher_headers))
        assert order["cars_furnished_count"] == 0, (
            f"a rejected furnish must assign nothing, got cars_furnished_count "
            f"{order['cars_furnished_count']}"
        )

    def test_furnish_derived_count_immediate(self, api, dispatcher_headers):
        """PRD §3.2: "Furnishing fewer cars than the unfilled remainder (the
        `quantity` minus the `cars_furnished_count`) moves an `ACCEPTED` order to
        `PARTIALLY_FURNISHED`, or leaves a `PARTIALLY_FURNISHED` order in that
        status; furnishing exactly the remainder completes the assignment and the
        order stands `FURNISHED`."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/consistency_model/furnish_derived_count_immediate
        """
        ctx = setup_accepted_order(quantity=2, car_type="BOX", capacity_cars=4, num_cars=2)
        resp = api.furnish_car_order(ctx["order"]["id"], {"count": 2}, dispatcher_headers)
        order = validate_success(resp, expected_status=200)
        assert order["cars_furnished_count"] == 2, (
            f"the furnish response itself must carry cars_furnished_count 2, "
            f"got {order['cars_furnished_count']}"
        )
        assert order["status"] == "FURNISHED", (
            f"furnishing exactly the remainder must stand the order FURNISHED, got {order['status']}"
        )


class TestCarOrderOwnership:
    def test_customer_rep_cannot_cancel_others_order(self, api, dispatcher_headers):
        """PRD §2.1: "When `X-User-Role` is `CustomerRep`, `X-User-ID` is the `id`
        of the acting `Customer`; ownership checks on a car order compare the
        order's `customer_id` to `X-User-ID`, so a representative may place,
        amend, cancel, release, or read demurrage only for their own company's
        orders."
        PRD §3.1: "Because the `CustomerRep` identity is entity-backed, every
        order-scoped write compares the order's `customer_id` to the caller's
        `X-User-ID`, and a mismatch is refused as `ERR_FORBIDDEN_ROLE`."

        Design: Corner/rbac/customer_rep_cannot_cancel_others_order
        """
        owner_a = create_customer(name="Owner A", billing_email="oa@x.example")
        owner_b = create_customer(name="Owner B", billing_email="ob@x.example")
        segment = create_segment(name="Main MP 67-68", milepost_start=67, milepost_end=68)
        siding = create_siding(owner_a["id"], segment["id"], name="A Siding", capacity_cars=4)
        order = place_car_order(owner_a["id"], siding["id"], car_type="BOX", quantity=1)

        resp = api.cancel_car_order(order["id"], make_customer_rep_headers(owner_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

        reread = validate_success(api.get_car_order(order["id"], dispatcher_headers))
        assert reread["status"] == "PLACED", (
            f"a forbidden cancel must leave the order untouched, got {reread['status']}"
        )
