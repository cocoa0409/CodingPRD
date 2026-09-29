"""One request that breaks two bands at once, and the same break isolated in each band alone."""

from test_helpers import (
    CART_CODE_CHILL,
    CART_CODE_HOT,
    CLOCK_CART,
    CLOCK_LOCK,
    CLOCK_ORDERS,
    CLOCK_PLAN,
    CLOCK_SETUP,
    LM_ALICE,
    SPEC_AN_F,
    ApiErrorId,
    add_flight,
    assert_instant_equals,
    assert_total_count,
    cabin_cost_per_pax_cents,
    cut_plan,
    factories as f,
    ingest_flight,
    item_gross_cents,
    load_item,
    lock_counts,
    produce_and_release,
    read_cart,
    read_flight,
    register_airline,
    register_cart,
    register_spec,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CUTOFF_UTC = "2026-09-14T22:00:00Z"
DEADLINE_CHILL = "2026-09-15T08:30:00Z"
DEADLINE_HOT = "2026-09-15T08:00:00Z"
PAST_DEADLINE = "2026-09-15T08:45:00Z"
CONTROL_NUMBER = "AN413"
CONTROL_TAIL = "LN-DDD"


def _error_id(response):
    """The `error_id` the service actually put in the failure envelope."""
    return response.json()["data"]["error_id"]


def _first_class_world(api, cost_cap_per_pax_cents, iata_code):
    """One `FIRST` tray of 4200 cents, released, with a HOT cart and a CHILL cart."""
    set_clock(api, CLOCK_SETUP)
    airline = register_airline(
        api,
        name="CapCheck Air",
        iata_code=iata_code,
        waste_regime="DOMESTIC",
        cost_cap_per_pax_cents=cost_cap_per_pax_cents,
    )
    spec = register_spec(api, airline["id"], SPEC_AN_F, spec_code="CC-F-STD")
    flight = ingest_flight(
        api,
        airline["id"],
        flight_number="CC902",
        tail_number="OY-EEE",
        pax_first=1,
    )
    set_clock(api, CLOCK_LOCK)
    lock_counts(api, flight["id"])
    set_clock(api, CLOCK_PLAN)
    batches = cut_plan(api, flight["id"])
    assert len(batches) == 1
    batch = produce_and_release(
        api, batches[0], list(SPEC_AN_F["required_haccp_steps"])
    )
    set_clock(api, CLOCK_CART)
    hot_cart = register_cart(
        api,
        flight["id"],
        cart_code=CART_CODE_HOT,
        cart_type="OVEN_RACK",
        storage_class="HOT",
        capacity_units=10,
        galley_position="G1",
    )
    chill_cart = register_cart(
        api,
        flight["id"],
        cart_code=CART_CODE_CHILL,
        cart_type="STD_FULL",
        storage_class="CHILL",
        capacity_units=10,
        galley_position="G2",
    )
    return {
        "airline": airline,
        "spec": spec,
        "flight": flight,
        "batch": batch,
        "hot_cart": hot_cart,
        "chill_cart": chill_cart,
    }


class TestBandSeventyOverBandOneHundredTen:
    """The count lock beats the meal cutoff, and the lock refuses on its own."""

    def test_a_capture_that_is_both_locked_out_and_late_reports_the_lock(
        self, base_env
    ):
        """Same instant, same body shape, two flights: only the lock changes the answer.

        PRD §2.6: "A special meal order capture that both targets a flight whose counts are already locked and arrives after the cutoff returns `ERR_FLIGHT_COUNTS_LOCKED` from band 70, never `ERR_SPECIAL_MEAL_CUTOFF_PASSED` from band 110."

        PRD §2.6: "When a single request would fail two different bands, the response therefore always carries the error of the lower-numbered band."

        Design: Difficulty/priority_pair_validation_conflict/counts_locked_at_priority_70_outranks_the_special_meal_cutoff_at_110
        """
        env = base_env
        api = env.api
        add_flight(env)
        control = ingest_flight(
            api,
            env.airline_id,
            flight_number=CONTROL_NUMBER,
            tail_number=CONTROL_TAIL,
            pax_economy=120,
        )
        # Twelve hours before a 10:00 departure, for both flights alike.
        assert_instant_equals(env.flight["special_meal_cutoff_utc"], CUTOFF_UTC)
        assert_instant_equals(control["special_meal_cutoff_utc"], CUTOFF_UTC)

        set_clock(api, CLOCK_LOCK)
        locked = lock_counts(api, env.flight_id)
        assert locked["status"] == "COUNTS_LOCKED"

        # The unlocked flight proves band 110 really is violated at this instant.
        cutoff_only = api.create_special_meal_order(
            f.order_payload(
                control["id"], env.specs["V"]["id"], "22A", passenger_ref="PAX-101"
            ),
            env.rep_headers,
        )
        validate_error(
            cutoff_only, ApiErrorId.ERR_SPECIAL_MEAL_CUTOFF_PASSED.value, 422
        )

        conflict = api.create_special_meal_order(
            f.order_payload(
                env.flight_id, env.specs["V"]["id"], "22B", passenger_ref="PAX-102"
            ),
            env.rep_headers,
        )
        validate_error(conflict, ApiErrorId.ERR_FLIGHT_COUNTS_LOCKED.value, 409)
        assert (
            _error_id(conflict) != ApiErrorId.ERR_SPECIAL_MEAL_CUTOFF_PASSED.value
        )

        for flight_id in (env.flight_id, control["id"]):
            _, meta = validate_paginated(
                api.list_special_meal_orders(
                    env.rep_headers, {"flight_id": flight_id}
                )
            )
            assert_total_count(meta, 0)
        assert read_flight(api, env.flight_id)["status"] == "COUNTS_LOCKED"
        assert read_flight(api, control["id"])["status"] == "SCHEDULED"

    def test_the_lock_alone_refuses_a_capture_the_cutoff_would_have_allowed(
        self, base_env
    ):
        """Ten hours before the cutoff the only thing left to fail is band 70.

        PRD §2.6: "Three specialisations share this same band: writing passenger counts or capturing a special meal order once the flight has left `SCHEDULED` reports `ERR_FLIGHT_COUNTS_LOCKED`; loading a cart item from a batch that is not `RELEASED` reports `ERR_BATCH_NOT_RELEASED`; and dispatching a run whose manifest is not `ISSUED` reports `ERR_MANIFEST_NOT_ISSUED`."

        PRD §3.3: "Finally, the logical clock must be strictly before `special_meal_cutoff_utc`; at or after that instant the capture is refused with `ERR_SPECIAL_MEAL_CUTOFF_PASSED`."

        Design: Difficulty/priority_pair_validation_conflict/counts_locked_at_priority_70_outranks_the_special_meal_cutoff_at_110
        """
        env = base_env
        api = env.api
        add_flight(env)
        control = ingest_flight(
            api,
            env.airline_id,
            flight_number=CONTROL_NUMBER,
            tail_number=CONTROL_TAIL,
            pax_economy=120,
        )

        set_clock(api, CLOCK_ORDERS)
        lock_counts(api, env.flight_id)

        # Strictly before the cutoff, so the same body succeeds where nothing is locked.
        accepted = validate_success(
            api.create_special_meal_order(
                f.order_payload(
                    control["id"], env.specs["V"]["id"], "22A", passenger_ref="PAX-201"
                ),
                env.rep_headers,
            ),
            201,
        )
        assert accepted["status"] == "REQUESTED"
        assert accepted["cabin"] == "ECONOMY"
        assert_instant_equals(accepted["requested_at"], CLOCK_ORDERS)

        refused = api.create_special_meal_order(
            f.order_payload(
                env.flight_id, env.specs["V"]["id"], "22A", passenger_ref="PAX-202"
            ),
            env.rep_headers,
        )
        validate_error(refused, ApiErrorId.ERR_FLIGHT_COUNTS_LOCKED.value, 409)

        _, locked_meta = validate_paginated(
            api.list_special_meal_orders(env.rep_headers, {"flight_id": env.flight_id})
        )
        assert_total_count(locked_meta, 0)
        rows, control_meta = validate_paginated(
            api.list_special_meal_orders(env.rep_headers, {"flight_id": control["id"]})
        )
        assert_total_count(control_meta, 1)
        assert rows[0]["id"] == accepted["id"]


class TestBandEightyOverBandOneHundred:
    """The release deadline beats the cart capacity, and it refuses a perfect fit too."""

    def test_a_load_that_is_both_late_and_oversized_reports_the_deadline(
        self, released_env
    ):
        """The same ten units into the same five-unit cart, judged twice on the clock.

        PRD §2.6: "A cart-item load that both draws from a batch past its release deadline and would overfill the cart returns `ERR_RELEASE_DEADLINE_PASSED` from band 80, never `ERR_CART_CAPACITY_EXCEEDED` from band 100."

        PRD §2.6: "Starting a batch at or after its release deadline also reports `ERR_RELEASE_DEADLINE_PASSED`, and so does loading cart items from such a batch."

        Design: Difficulty/priority_pair_validation_conflict/release_deadline_at_priority_80_outranks_cart_capacity_at_100
        """
        env = released_env
        api = env.api
        assert_instant_equals(env.batch["release_deadline_utc"], DEADLINE_CHILL)

        set_clock(api, CLOCK_CART)
        small = register_cart(
            api,
            env.flight_id,
            cart_code="CHL-02",
            cart_type="STD_HALF",
            capacity_units=5,
            galley_position="G3",
        )

        # Before the deadline, only band 100 has anything to say.
        capacity_only = api.load_cart_item(
            small["id"], f.cart_item_payload(env.batch["id"], 10), LM_ALICE
        )
        validate_error(
            capacity_only, ApiErrorId.ERR_CART_CAPACITY_EXCEEDED.value, 422
        )

        set_clock(api, PAST_DEADLINE)
        conflict = api.load_cart_item(
            small["id"], f.cart_item_payload(env.batch["id"], 10), LM_ALICE
        )
        validate_error(conflict, ApiErrorId.ERR_RELEASE_DEADLINE_PASSED.value, 422)
        assert _error_id(conflict) != ApiErrorId.ERR_CART_CAPACITY_EXCEEDED.value

        _, meta = validate_paginated(
            api.list_cart_items(LM_ALICE, {"cart_id": small["id"]})
        )
        assert_total_count(meta, 0)
        stored = read_cart(api, small["id"])
        assert stored["build_status"] == "EMPTY"
        assert stored["loaded_units"] == 0
        flight = read_flight(api, env.flight_id)
        assert flight["units_loaded"] == 0
        assert flight["cost_per_pax_cents"] == 0

    def test_the_deadline_alone_refuses_a_load_that_fits_the_cart_easily(
        self, released_env
    ):
        """A hundred units go in before the deadline; fifty more do not go in at it.

        PRD §2.6: "Starting a batch at or after its release deadline also reports `ERR_RELEASE_DEADLINE_PASSED`, and so does loading cart items from such a batch."

        PRD §3.6: "Each successful load recomputes the cart's `loaded_units` — the sum of `qty_units` over that cart's `ACTIVE` items — along with the flight's `units_loaded`, `unit_balance` and `cost_per_pax_cents`."

        Design: Difficulty/priority_pair_validation_conflict/release_deadline_at_priority_80_outranks_cart_capacity_at_100
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id, cart_code=CART_CODE_CHILL)
        assert cart["capacity_units"] == 200

        load_item(api, cart["id"], env.batch["id"], 100)
        filled = read_cart(api, cart["id"])
        assert filled["loaded_units"] == 100
        assert filled["build_status"] == "BUILDING"
        priced = read_flight(api, env.flight_id)
        assert priced["units_loaded"] == 100
        assert priced["unit_balance"] == 80
        # 100 trays at 1450 cents plus 12 percent, spread over 180 economy seats.
        assert priced["cost_per_pax_cents"] == cabin_cost_per_pax_cents(
            item_gross_cents(100, 1450), 180
        )
        assert priced["cost_per_pax_cents"] == 902

        # Exactly at the deadline: fifty more units would still leave 50 spare.
        set_clock(api, DEADLINE_CHILL)
        at_deadline = api.load_cart_item(
            cart["id"], f.cart_item_payload(env.batch["id"], 50), LM_ALICE
        )
        validate_error(at_deadline, ApiErrorId.ERR_RELEASE_DEADLINE_PASSED.value, 422)
        assert _error_id(at_deadline) != ApiErrorId.ERR_CART_CAPACITY_EXCEEDED.value

        set_clock(api, PAST_DEADLINE)
        validate_error(
            api.load_cart_item(
                cart["id"], f.cart_item_payload(env.batch["id"], 50), LM_ALICE
            ),
            ApiErrorId.ERR_RELEASE_DEADLINE_PASSED.value,
            422,
        )

        _, meta = validate_paginated(
            api.list_cart_items(LM_ALICE, {"cart_id": cart["id"]})
        )
        assert_total_count(meta, 1)
        assert read_cart(api, cart["id"])["loaded_units"] == 100
        assert read_flight(api, env.flight_id)["units_loaded"] == 100


class TestBandNinetyOverBandOneHundredTwenty:
    """The storage-class mismatch beats the cost cap, and it survives a cap that is met."""

    def test_a_load_that_is_both_misclassed_and_unaffordable_reports_the_class(
        self, api
    ):
        """One 4200-cent tray, two carts: the wrongly classed one never reaches the money.

        PRD §2.6: "And a cart-item load that both puts a hot-store batch into a chilled cart and breaches the per-passenger cost cap returns `ERR_STORAGE_CLASS_MISMATCH` from band 90, never `ERR_COST_CAP_EXCEEDED` from band 120."

        PRD §2.6: "Checked last, deliberately, so that every safety, referential, capacity and temporal problem is reported before a money problem."

        Design: Difficulty/priority_pair_validation_conflict/storage_class_mismatch_at_priority_90_outranks_the_cost_cap_at_120
        """
        world = _first_class_world(api, 1500, "CC")
        batch = world["batch"]
        assert batch["store_zone"] == "HOT"
        assert batch["planned_qty"] == 1
        assert batch["is_overflow"] is False
        assert_instant_equals(batch["release_deadline_utc"], DEADLINE_HOT)

        # One tray blends to 4704 cents per passenger against a 1500-cent ceiling.
        would_be = cabin_cost_per_pax_cents(item_gross_cents(1, 4200), 1)
        assert would_be == 4704
        assert would_be > world["airline"]["cost_cap_per_pax_cents"] == 1500

        # Into the correctly classed cart, only band 120 has anything to say.
        cap_only = api.load_cart_item(
            world["hot_cart"]["id"], f.cart_item_payload(batch["id"], 1), LM_ALICE
        )
        validate_error(cap_only, ApiErrorId.ERR_COST_CAP_EXCEEDED.value, 422)

        conflict = api.load_cart_item(
            world["chill_cart"]["id"], f.cart_item_payload(batch["id"], 1), LM_ALICE
        )
        validate_error(conflict, ApiErrorId.ERR_STORAGE_CLASS_MISMATCH.value, 422)
        assert _error_id(conflict) != ApiErrorId.ERR_COST_CAP_EXCEEDED.value

        for cart in (world["hot_cart"], world["chill_cart"]):
            _, meta = validate_paginated(
                api.list_cart_items(LM_ALICE, {"cart_id": cart["id"]})
            )
            assert_total_count(meta, 0)
            assert read_cart(api, cart["id"])["loaded_units"] == 0
        flight = read_flight(api, world["flight"]["id"])
        assert flight["cost_per_pax_cents"] == 0
        assert flight["units_loaded"] == 0

    def test_the_class_mismatch_alone_refuses_a_load_the_cap_would_have_allowed(
        self, api
    ):
        """With the ceiling lifted to 6000 the chilled cart is refused for its zone alone.

        PRD §2.6: "A cart item's source batch must sit in the same store zone as the cart's own storage class (`ERR_STORAGE_CLASS_MISMATCH`) and must belong to the same flight as the cart (`ERR_CART_FLIGHT_MISMATCH`)."

        PRD §2.6: "Adding cart items whose resulting per-passenger cost would exceed the airline's contractual cap is refused with `ERR_COST_CAP_EXCEEDED` (422)."

        Design: Difficulty/priority_pair_validation_conflict/storage_class_mismatch_at_priority_90_outranks_the_cost_cap_at_120
        """
        world = _first_class_world(api, 6000, "CD")
        batch = world["batch"]
        assert world["airline"]["cost_cap_per_pax_cents"] == 6000
        assert world["spec"]["storage_class"] == "HOT"
        assert world["chill_cart"]["storage_class"] == "CHILL"

        # 4704 cents per passenger now sits under the ceiling, so band 120 is silent.
        mismatch = api.load_cart_item(
            world["chill_cart"]["id"], f.cart_item_payload(batch["id"], 1), LM_ALICE
        )
        validate_error(mismatch, ApiErrorId.ERR_STORAGE_CLASS_MISMATCH.value, 422)
        assert _error_id(mismatch) != ApiErrorId.ERR_COST_CAP_EXCEEDED.value
        assert read_cart(api, world["chill_cart"]["id"])["loaded_units"] == 0

        loaded = load_item(api, world["hot_cart"]["id"], batch["id"], 1)
        assert loaded["qty_units"] == 1
        assert read_cart(api, world["hot_cart"]["id"])["loaded_units"] == 1
        flight = read_flight(api, world["flight"]["id"])
        assert flight["units_loaded"] == 1
        assert flight["cost_per_pax_cents"] == 4704

        report = validate_success(
            api.get_cost_report(world["flight"]["id"], LM_ALICE), 200
        )
        assert report["cost_per_pax_cents"] == 4704
        assert report["cap_breached"] is False
