"""Waybill rating arithmetic, through-route shape, filtered listing, on-line car
rules, and the movement-settlement billing cascade (PRD §3.2, §3.5)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_customer,
    create_movement,
    create_railcar,
    create_segment,
    create_siding,
    create_waybill,
    make_customer_rep_headers,
    place_car_order,
    setup_arrived_movement,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
DISPATCH = TEST_USERS["dispatcher_headers"]
CALLER = TEST_USERS["crew_caller_headers"]
CLERK = TEST_USERS["settlement_clerk_headers"]

SETTLE_CASCADE = (
    "The gate is that every waybill tied to the movement must already be `RATED` "
    "or `BILLED`; a waybill still in `CREATED` blocks settlement with "
    "`ERR_WAYBILL_NOT_RATED`. On success, four cascades run. Every `RATED` "
    "waybill on the movement becomes `BILLED`. For each through waybill, a "
    "**RevenueDivision** is auto-created in `DRAFT` with basis `MILEAGE_PRORATE`, "
    "its snapshot fields copied from the waybill. Each non-through waybill steps "
    "straight from `BILLED` to `SETTLED`. And every car order referenced by a "
    "billed waybill's `car_order_id` completes, moving `RELEASED` → `COMPLETED`."
)


def _settle_cascade_scenario(api):
    """Released order + ARRIVED movement + RATED through waybill (GRAIN 100t,
    our 87 of 241 miles) linked to both."""
    customer = create_customer(name="Genesee Feeds", billing_email="traffic@geneseefeeds.example")
    segment = create_segment(name="Main MP 10-14", milepost_start=10, milepost_end=14, fra_class="CLASS_3")
    siding = create_siding(customer["id"], segment["id"], name="Genesee Feeds Siding", capacity_cars=10)
    railcar = create_railcar(reporting_mark="GNWR 5001", car_type="BOX")
    order = place_car_order(customer["id"], siding["id"], car_type="BOX", quantity=1)
    validate_success(api.accept_car_order(order["id"], DISPATCH))
    validate_success(api.furnish_car_order(order["id"], {"count": 1}, DISPATCH))
    order = validate_success(api.release_car_order(order["id"], make_customer_rep_headers(customer["id"])))
    assert order["status"] == "RELEASED"

    ctx = setup_arrived_movement(symbol="GW-101")
    movement = ctx["movement"]
    waybill = create_waybill(
        railcar["id"], customer["id"], car_order_id=order["id"], movement_id=movement["id"],
        destination="CSX Buffalo Frontier Yard", commodity="GRAIN", weight_tons=100,
        through_route=True, our_miles=87, total_miles=241,
    )
    waybill = validate_success(api.rate_waybill(waybill["id"], CLERK))
    assert waybill["total_freight_charge_cents"] == 3850000
    return {"customer": customer, "segment": segment, "siding": siding, "railcar": railcar,
            "order": order, "movement": movement, "waybill": waybill}


class TestWaybillRating:
    def test_waybill_rating_uses_commodity_constant(self, api, settlement_clerk_headers):
        """PRD §3.5: "The `total_freight_charge_cents` is the billed `weight_tons`
        multiplied by the per-ton rate for the `commodity`: 38,500 cents — $385.00
        — per ton for `GRAIN`, 42,000 cents — $420.00 — per ton for `LUMBER`, and
        51,500 cents — $515.00 — per ton for `CHEMICALS`, an exact integer product
        with no rounding."
        PRD §3.5: "Rating is a `SettlementClerk` action that prices the waybill
        and moves it `CREATED` → `RATED`."

        Design: Corner/calculations/waybill_rating_uses_commodity_constant
        """
        customer = create_customer(name="Rate Co", billing_email="r@x.example")
        railcar = create_railcar(reporting_mark="GNWR 6100", car_type="FLAT")
        waybill = create_waybill(
            railcar["id"], customer["id"], destination="York PA", commodity="LUMBER",
            weight_tons=50, through_route=False,
        )
        rated = validate_success(api.rate_waybill(waybill["id"], settlement_clerk_headers))
        assert rated["total_freight_charge_cents"] == 2100000, (
            f"50 tons of LUMBER at 42000 cents per ton must rate 2100000, "
            f"got {rated['total_freight_charge_cents']}"
        )
        assert rated["status"] == "RATED", f"rating must move the waybill to RATED, got {rated['status']}"

    def test_through_waybill_requires_miles(self, api, dispatcher_headers):
        """PRD §3.5: "The `through_route` flag marks revenue that divides with a
        connecting road; when it is true, `our_miles` and `total_miles` are both
        required, with `total_miles` at least `our_miles` and `our_miles` at least
        zero — a through waybill submitted without both mileages, or with mileages
        violating that ordering, is rejected as `ERR_INVALID_REQUEST`."

        Design: Corner/validations/through_waybill_requires_miles
        """
        customer = create_customer(name="Miles Co", billing_email="m@x.example")
        railcar = create_railcar(reporting_mark="GNWR 6200", car_type="BOX")
        resp = api.create_waybill(
            {
                "railcar_id": railcar["id"], "origin_customer_id": customer["id"],
                "destination": "NS Buffalo", "commodity": "GRAIN", "weight_tons": 10,
                "through_route": True,
            },
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_waybill_for_bad_order_car_rejected(self, api, dispatcher_headers):
        """PRD §3.5: "At creation, and again at rating, the named car must be on
        the line: a car in `INTERCHANGED_OUT`, `BAD_ORDER`, or `HELD` fails with
        `ERR_CAR_NOT_ON_LINE`."

        Design: Corner/errors/waybill_for_bad_order_car_rejected
        """
        customer = create_customer(name="Badcar Co", billing_email="b@x.example")
        railcar = create_railcar(reporting_mark="GNWR 6950", car_type="BOX")
        validate_success(api.bad_order_railcar(railcar["id"], dispatcher_headers))
        resp = api.create_waybill(
            {
                "railcar_id": railcar["id"], "origin_customer_id": customer["id"],
                "destination": "Rochester", "commodity": "GRAIN", "weight_tons": 5,
                "through_route": False,
            },
            dispatcher_headers,
        )
        validate_error(resp, ApiErrorId.ERR_CAR_NOT_ON_LINE)


class TestWaybillListing:
    def test_waybill_filter_by_movement(self, api, dispatcher_headers):
        """PRD §3.5: "A new waybill rests in `CREATED`, and waybills can be listed
        filtered by `railcar_id`, `origin_customer_id`, `car_order_id`,
        `movement_id`, or `status`."

        Design: Corner/endpoints/waybill_filter_by_movement
        """
        segment = create_segment(name="Main MP 53-56", milepost_start=53, milepost_end=56, fra_class="CLASS_3")
        mov1 = create_movement([segment["id"]], symbol="GW-A1")
        mov2 = create_movement([segment["id"]], symbol="GW-A2")
        customer = create_customer(name="Filter Co", billing_email="f@x.example")
        rc1 = create_railcar(reporting_mark="GNWR 6701", car_type="BOX")
        rc2 = create_railcar(reporting_mark="GNWR 6702", car_type="BOX")
        create_waybill(rc1["id"], customer["id"], movement_id=mov1["id"], destination="A",
                       commodity="GRAIN", weight_tons=10)
        create_waybill(rc2["id"], customer["id"], movement_id=mov2["id"], destination="B",
                       commodity="GRAIN", weight_tons=20)

        data, meta = validate_paginated(
            api.list_waybills(dispatcher_headers, params={"movement_id": mov1["id"]})
        )
        assert meta["total_count"] == 1, f"the movement filter must return exactly 1 waybill, got {meta['total_count']}"
        assert len(data) == 1
        assert data[0]["movement_id"] == mov1["id"], (
            f"the returned waybill must be the one linked to movement {mov1['id']}"
        )


class TestMovementSettleCascade:
    def test_movement_settle_bills_waybill(self, api, dispatcher_headers, settlement_clerk_headers):
        """PRD §3.5: "On success, four cascades run. Every `RATED` waybill on the
        movement becomes `BILLED`. For each through waybill, a **RevenueDivision**
        is auto-created in `DRAFT` with basis `MILEAGE_PRORATE`, its snapshot
        fields copied from the waybill. Each non-through waybill steps straight
        from `BILLED` to `SETTLED`. And every car order referenced by a billed
        waybill's `car_order_id` completes, moving `RELEASED` → `COMPLETED`. The
        movement itself stands `SETTLED`, terminal, with its `version`
        incremented."

        Design: Difficulty/transitive_cascade/movement_settle_billing_cascade_depth2
        """
        ctx = _settle_cascade_scenario(api)
        settled = validate_success(api.settle_train_movement(ctx["movement"]["id"], settlement_clerk_headers))
        assert settled["status"] == "SETTLED", f"the movement must stand SETTLED, got {settled['status']}"

        waybill = validate_success(api.get_waybill(ctx["waybill"]["id"], settlement_clerk_headers))
        assert waybill["status"] == "BILLED", (
            f"the first cascade hop must bill the RATED waybill, got {waybill['status']}"
        )

    def test_movement_settle_spawns_division_and_completes_order(self, api, dispatcher_headers, settlement_clerk_headers):
        """PRD §3.5: "On success, four cascades run. Every `RATED` waybill on the
        movement becomes `BILLED`. For each through waybill, a **RevenueDivision**
        is auto-created in `DRAFT` with basis `MILEAGE_PRORATE`, its snapshot
        fields copied from the waybill. Each non-through waybill steps straight
        from `BILLED` to `SETTLED`. And every car order referenced by a billed
        waybill's `car_order_id` completes, moving `RELEASED` → `COMPLETED`. The
        movement itself stands `SETTLED`, terminal, with its `version`
        incremented."
        PRD §3.5: "Under `MILEAGE_PRORATE`, `our_share_cents` is the total charge
        times `our_miles` divided by `total_miles`, rounded half up to whole
        cents."

        Design: Difficulty/transitive_cascade/movement_settle_billing_cascade_depth2
        """
        ctx = _settle_cascade_scenario(api)
        validate_success(api.settle_train_movement(ctx["movement"]["id"], settlement_clerk_headers))

        divisions, meta = validate_paginated(
            api.list_revenue_divisions(settlement_clerk_headers, params={"waybill_id": ctx["waybill"]["id"]})
        )
        assert meta["total_count"] == 1, f"exactly one division must be spawned, got {meta['total_count']}"
        div = divisions[0]
        assert div["status"] == "DRAFT", f"the spawned division must rest in DRAFT, got {div['status']}"
        assert div["basis"] == "MILEAGE_PRORATE", f"settle-spawned divisions use MILEAGE_PRORATE, got {div['basis']}"
        assert div["our_share_cents"] == 1389834, (
            f"round_half_up(3850000 * 87 / 241) must yield 1389834, got {div['our_share_cents']}"
        )

        order = validate_success(api.get_car_order(ctx["order"]["id"], dispatcher_headers))
        assert order["status"] == "COMPLETED", (
            f"billing the waybill must complete the supplying RELEASED order, got {order['status']}"
        )
