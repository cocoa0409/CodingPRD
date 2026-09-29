"""Gates that live on a different row than the one being written, and the two slot geometries."""

from test_helpers import (
    ADMIN,
    CLOCK_CART,
    CLOCK_DISPATCH,
    EVENT_DISPATCH,
    FEED,
    LM_ALICE,
    LM_BOB,
    LM_CAROL,
    SEAL_PRIMARY,
    SEAL_SECONDARY,
    SUPERVISOR,
    WINDOW_END,
    WINDOW_START,
    ApiErrorId,
    assert_instant_equals,
    assert_total_count,
    cabin_cost_per_pax_cents,
    complete_batch,
    factories as f,
    issue_manifest,
    item_gross_cents,
    load_item,
    read_cart,
    read_flight,
    record_check,
    register_cart,
    register_truck,
    release_batch,
    reserve_run,
    run_event,
    seal_cart,
    set_clock,
    start_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

EARLY_START = "2026-09-15T07:00:00Z"
EARLY_END = "2026-09-15T07:30:00Z"
INSIDE_BUFFER_START = "2026-09-15T08:10:00Z"
INSIDE_BUFFER_END = "2026-09-15T08:40:00Z"
ON_BUFFER_START = "2026-09-15T08:20:00Z"
ON_BUFFER_END = "2026-09-15T08:50:00Z"
OVERLAP_START = "2026-09-15T07:45:00Z"
OVERLAP_END = "2026-09-15T08:15:00Z"
SHARED_INSTANT_END = "2026-09-15T08:30:00Z"
THIRD_END = "2026-09-15T08:20:00Z"
DELAYED_DISPATCH = "2026-09-15T08:05:00Z"
SHIFTED_START = "2026-09-15T09:00:00Z"
SHIFTED_END = "2026-09-15T09:30:00Z"


def _read_batch(api, batch_id):
    return validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)


def _refuse_load(api, cart_id, batch_id):
    """One load attempt that the batch's own state is expected to refuse."""
    validate_error(
        api.load_cart_item(cart_id, f.cart_item_payload(batch_id, 180), LM_ALICE),
        ApiErrorId.ERR_BATCH_NOT_RELEASED.value,
        409,
    )


def _cart_on_a_planned_flight(env):
    """An `EMPTY` cart at 06:10, while the batch is still `PLANNED`."""
    set_clock(env.api, CLOCK_CART)
    cart = register_cart(env.api, env.flight_id)
    assert cart["build_status"] == "EMPTY"
    assert cart["loaded_units"] == 0
    return cart


class TestTheGateOnTheSourceBatch:
    """The load is refused for a state that lives on the batch, not the cart."""

    def test_one_payload_is_refused_and_then_accepted_on_the_batchs_state_alone(
        self, planned_env
    ):
        """Nothing changes between the two calls except the batch's `production_status`.

        PRD §3.6: "The source batch must be `RELEASED`, or the load is refused with `ERR_BATCH_NOT_RELEASED`; it must not be past its `release_deadline_utc`, or the load is refused with `ERR_RELEASE_DEADLINE_PASSED`; its `store_zone` must equal the cart's own `storage_class`, or the load is refused with `ERR_STORAGE_CLASS_MISMATCH`; its `flight_id` must equal the cart's `flight_id`, or the load is refused with `ERR_CART_FLIGHT_MISMATCH`; the cart's `loaded_units` plus the new `qty_units` may not exceed `capacity_units`, or the load is refused with `ERR_CART_CAPACITY_EXCEEDED`; and finally, the flight's resulting `cost_per_pax_cents` may not exceed the airline's `cost_cap_per_pax_cents`, or the load is refused with `ERR_COST_CAP_EXCEEDED`."

        PRD §3.6: "The service creates a cart item in `ACTIVE` recording its `cart_id`, the source batch, the quantity, and a `meal_code` copied from the batch's specification, with `voided_at` null."

        Design: Difficulty/cross_entity_state_dependency/cart_item_load_requires_the_source_batch_to_be_released
        """
        env = planned_env
        api = env.api
        batch_id = env.batch["id"]
        cart = _cart_on_a_planned_flight(env)
        assert _read_batch(api, batch_id)["production_status"] == "PLANNED"

        _refuse_load(api, cart["id"], batch_id)
        untouched = read_cart(api, cart["id"])
        assert untouched["build_status"] == "EMPTY"
        assert untouched["loaded_units"] == 0
        _, empty = validate_paginated(
            api.list_cart_items(LM_ALICE, {"cart_id": cart["id"]})
        )
        assert_total_count(empty, 0)

        start_batch(api, batch_id)
        record_check(api, batch_id, "CHILL_DOWN")
        record_check(api, batch_id, "HOLD_TEMP")
        complete_batch(api, batch_id, 180)
        released = release_batch(api, batch_id)
        assert released["production_status"] == "RELEASED"
        assert_instant_equals(released["released_at"], CLOCK_CART)

        item = load_item(api, cart["id"], batch_id, 180)
        assert item["status"] == "ACTIVE"
        assert item["qty_units"] == 180
        assert item["meal_code"] == "STANDARD"

        loaded = read_cart(api, cart["id"])
        assert loaded["build_status"] == "BUILDING"
        assert loaded["loaded_units"] == 180
        assert loaded["seal_status"] == "UNSEALED"
        flight = read_flight(api, env.flight_id)
        assert flight["units_loaded"] == 180
        assert flight["cost_per_pax_cents"] == 1624 == cabin_cost_per_pax_cents(
            item_gross_cents(180, 1450), 180
        )
        _, one = validate_paginated(
            api.list_cart_items(LM_ALICE, {"cart_id": cart["id"]})
        )
        assert_total_count(one, 1)

    def test_every_pre_release_batch_state_refuses_the_load_with_the_same_code(
        self, planned_env
    ):
        """`PLANNED`, `IN_PRODUCTION`, `HACCP_HOLD` and `COMPLETED` all answer identically.

        PRD §2.6: "Three specialisations share this same band: writing passenger counts or capturing a special meal order once the flight has left `SCHEDULED` reports `ERR_FLIGHT_COUNTS_LOCKED`; loading a cart item from a batch that is not `RELEASED` reports `ERR_BATCH_NOT_RELEASED`; and dispatching a run whose manifest is not `ISSUED` reports `ERR_MANIFEST_NOT_ISSUED`."

        PRD §3.6: "Loading is accepted only while `build_status` is `EMPTY` or `BUILDING`, and any other build state is refused with `ERR_INVALID_CART_STATE`."

        Design: Difficulty/cross_entity_state_dependency/cart_item_load_requires_the_source_batch_to_be_released
        """
        env = planned_env
        api = env.api
        batch_id = env.batch["id"]
        cart = _cart_on_a_planned_flight(env)

        _refuse_load(api, cart["id"], batch_id)

        assert start_batch(api, batch_id)["production_status"] == "IN_PRODUCTION"
        _refuse_load(api, cart["id"], batch_id)

        record_check(api, batch_id, "CHILL_DOWN")
        assert record_check(api, batch_id, "HOLD_TEMP", 5.1)["verdict"] == "FAIL"
        assert _read_batch(api, batch_id)["production_status"] == "HACCP_HOLD"
        _refuse_load(api, cart["id"], batch_id)

        restarted = start_batch(api, batch_id)
        assert restarted["haccp_rework_rounds"] == 1
        record_check(api, batch_id, "HOLD_TEMP")
        assert complete_batch(api, batch_id, 180)["production_status"] == "COMPLETED"
        _refuse_load(api, cart["id"], batch_id)

        # Four refusals, and the cart never left its opening state.
        still_empty = read_cart(api, cart["id"])
        assert still_empty["build_status"] == "EMPTY"
        assert still_empty["loaded_units"] == 0
        assert still_empty["version"] == 1

        release_batch(api, batch_id)
        load_item(api, cart["id"], batch_id, 180)
        assert read_cart(api, cart["id"])["loaded_units"] == 180
        assert read_flight(api, env.flight_id)["units_loaded"] == 180


class TestTheGateOnTheManifestTwoHopsAway:
    """A write on the cart, and a write on the flight, each flip the run's dispatch."""

    def test_a_reseal_two_hops_away_blocks_dispatch_until_the_manifest_is_re_issued(
        self, issued_env
    ):
        """The run never moves, and the clock never moves, yet dispatch flips twice.

        PRD §3.6: "When the cart being resealed is already pinned in an `ISSUED` manifest, the supersede drives that manifest `ISSUED → AMENDED` and its flight `LOADED → PLANNED`."

        PRD §3.7: "Dispatching moves a run `RESERVED → EN_ROUTE` (and identically `RESCHEDULED → EN_ROUTE`), requires the manifest to still be `ISSUED` — a manifest that fell back to `AMENDED` refuses dispatch with `ERR_MANIFEST_NOT_ISSUED` — and requires the logical clock to be at or after `window_start_utc` pulled back by one hour of dispatch lead."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_the_manifest_to_be_issued_after_a_reseal_amended_it
        """
        env = issued_env
        api = env.api
        run = reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])
        assert run["status"] == "RESERVED"
        set_clock(api, CLOCK_DISPATCH)

        resealed = seal_cart(
            api, env.cart["id"], SEAL_SECONDARY, headers=LM_CAROL
        )
        assert resealed["seal_status"] == "RESEALED"
        assert resealed["seal_count"] == 2
        assert resealed["seal_number"] == SEAL_SECONDARY
        # The build axis did not move with the seal axis.
        assert resealed["build_status"] == "BUILT"

        amended = validate_success(
            api.get_loading_manifest(env.manifest["id"], LM_BOB), 200
        )
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1
        assert read_flight(api, env.flight_id)["status"] == "PLANNED"

        # 07:25 is well inside the one-hour dispatch lead on a 07:30 window.
        validate_error(
            api.record_run_event(
                run["id"], f.event_payload(EVENT_DISPATCH), LM_BOB
            ),
            ApiErrorId.ERR_MANIFEST_NOT_ISSUED.value,
            409,
        )
        refused = validate_success(api.get_delivery_run(run["id"], LM_BOB), 200)
        assert refused["status"] == "RESERVED"
        assert refused["dispatched_at_utc"] is None

        reissued = issue_manifest(api, env.manifest["id"], headers=LM_BOB)
        assert reissued["status"] == "ISSUED"
        assert reissued["amendment_count"] == 1
        assert reissued["total_units"] == 180
        assert [
            entry["seal_number"] for entry in reissued["cart_seal_snapshot"]
        ] == [SEAL_SECONDARY]
        assert read_flight(api, env.flight_id)["status"] == "LOADED"

        dispatched = run_event(api, run["id"], EVENT_DISPATCH)
        assert dispatched["status"] == "EN_ROUTE"
        assert_instant_equals(dispatched["dispatched_at_utc"], CLOCK_DISPATCH)

    def test_a_reslotting_delay_blocks_dispatch_of_the_run_it_just_moved(
        self, issued_env
    ):
        """The delay cascade amends the manifest, so the run it rescheduled cannot leave.

        PRD §3.8: "Any moved run whose `loading_manifest_id` points at an `ISSUED` manifest drives that manifest `ISSUED → AMENDED` with `amendment_count` incremented, which in turn drives its flight `LOADED → PLANNED`."

        PRD §3.8: "When it has, every run of the flight in `RESERVED` or `RESCHEDULED` has both `window_start_utc` and `window_end_utc` shifted forward by the cumulative `delay_minutes` — not by this request's increment — and its status set to `RESCHEDULED`."

        Design: Difficulty/cross_entity_state_dependency/dispatch_requires_the_manifest_to_be_issued_after_a_reseal_amended_it
        """
        env = issued_env
        api = env.api
        run = reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])
        assert_instant_equals(run["window_start_utc"], WINDOW_START)

        delayed = validate_success(
            api.record_delay(
                env.flight_id, f.delay_payload(90, reason="ATC_SLOT"), FEED
            ),
            200,
        )
        assert delayed["delay_minutes"] == 90

        moved = validate_success(api.get_delivery_run(run["id"], LM_BOB), 200)
        assert moved["status"] == "RESCHEDULED"
        assert_instant_equals(moved["window_start_utc"], SHIFTED_START)
        assert_instant_equals(moved["window_end_utc"], SHIFTED_END)
        assert moved["version"] == run["version"] + 1

        amended = validate_success(
            api.get_loading_manifest(env.manifest["id"], LM_BOB), 200
        )
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1
        assert read_flight(api, env.flight_id)["status"] == "PLANNED"

        # 08:05 is at or after 09:00 less the one-hour lead, so only the manifest is at fault.
        set_clock(api, DELAYED_DISPATCH)
        validate_error(
            api.record_run_event(
                run["id"], f.event_payload(EVENT_DISPATCH), LM_BOB
            ),
            ApiErrorId.ERR_MANIFEST_NOT_ISSUED.value,
            409,
        )
        assert (
            validate_success(api.get_delivery_run(run["id"], LM_BOB), 200)["status"]
            == "RESCHEDULED"
        )

        reissued = issue_manifest(api, env.manifest["id"], headers=LM_BOB)
        assert reissued["status"] == "ISSUED"
        assert [
            entry["seal_number"] for entry in reissued["cart_seal_snapshot"]
        ] == [SEAL_PRIMARY]
        dispatched = run_event(api, run["id"], EVENT_DISPATCH)
        assert dispatched["status"] == "EN_ROUTE"
        assert_instant_equals(dispatched["dispatched_at_utc"], DELAYED_DISPATCH)


class TestTheTrucksHalfOpenBuffer:
    """Ten minutes inside the buffer, and exactly on it."""

    def test_the_buffer_refuses_ten_minutes_early_and_clears_exactly_on_the_boundary(
        self, issued_env
    ):
        """Two candidate windows on the same truck, ten minutes apart in start time.

        PRD §3.7: "Truck occupancy is half-open and buffered: a run is refused when its `window_start_utc` falls before an existing run's `window_end_utc` advanced by the truck's `buffer_minutes` **and** its `window_end_utc` falls after that existing run's `window_start_utc`, and the refusal is `ERR_TRUCK_SLOT_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/truck_half_open_window_plus_buffer_rejects_and_accepts_at_the_boundary
        """
        env = issued_env
        api = env.api
        assert env.truck["buffer_minutes"] == 20
        first = reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])

        # 08:10 is before 08:00 + 20 minutes, and 08:40 is after 07:30.
        validate_error(
            api.create_delivery_run(
                f.run_payload(
                    env.manifest["id"],
                    env.truck["id"],
                    env.stand["id"],
                    INSIDE_BUFFER_START,
                    INSIDE_BUFFER_END,
                ),
                LM_BOB,
            ),
            ApiErrorId.ERR_TRUCK_SLOT_CONFLICT.value,
            422,
        )

        # 08:20 is not strictly before 08:20, so the buffer is exactly cleared.
        second = reserve_run(
            api,
            env.manifest["id"],
            env.truck["id"],
            env.stand["id"],
            window_start_utc=ON_BUFFER_START,
            window_end_utc=ON_BUFFER_END,
        )
        assert second["status"] == "RESERVED"
        assert_instant_equals(second["window_start_utc"], ON_BUFFER_START)

        runs, meta = validate_paginated(
            api.list_delivery_runs(LM_BOB, {"loading_manifest_id": env.manifest["id"]})
        )
        assert_total_count(meta, 2)
        assert {row["id"] for row in runs} == {first["id"], second["id"]}

        unchanged = validate_success(api.get_delivery_run(first["id"], LM_BOB), 200)
        assert unchanged["status"] == "RESERVED"
        assert_instant_equals(unchanged["window_end_utc"], WINDOW_END)
        assert unchanged["dispatched_at_utc"] is None
        assert read_flight(api, env.flight_id)["status"] == "LOADED"

    def test_a_window_ending_exactly_at_the_existing_start_fails_only_the_first_condition(
        self, issued_env
    ):
        """Both halves of the conjunction must hold, so touching the start is admitted.

        PRD §3.7: "Truck occupancy is half-open and buffered: a run is refused when its `window_start_utc` falls before an existing run's `window_end_utc` advanced by the truck's `buffer_minutes` **and** its `window_end_utc` falls after that existing run's `window_start_utc`, and the refusal is `ERR_TRUCK_SLOT_CONFLICT`."

        PRD §3.7: "Stand occupancy is a closed interval with an aggregate limit: a run is refused when adding it would make more than `max_concurrent_runs` non-cancelled runs cover any common instant, where a shared endpoint instant counts as common, and the refusal is `ERR_STAND_CAPACITY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/truck_half_open_window_plus_buffer_rejects_and_accepts_at_the_boundary
        """
        env = issued_env
        api = env.api
        first = reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])

        # 07:00 is before 08:20, but 07:30 is not after 07:30 — the second half fails.
        earlier = reserve_run(
            api,
            env.manifest["id"],
            env.truck["id"],
            env.stand["id"],
            window_start_utc=EARLY_START,
            window_end_utc=EARLY_END,
        )
        assert earlier["status"] == "RESERVED"
        assert_instant_equals(earlier["window_end_utc"], EARLY_END)
        assert_instant_equals(first["window_start_utc"], EARLY_END)

        # A genuinely overlapping window satisfies both halves and is refused.
        validate_error(
            api.create_delivery_run(
                f.run_payload(
                    env.manifest["id"],
                    env.truck["id"],
                    env.stand["id"],
                    OVERLAP_START,
                    OVERLAP_END,
                ),
                LM_BOB,
            ),
            ApiErrorId.ERR_TRUCK_SLOT_CONFLICT.value,
            422,
        )
        _, meta = validate_paginated(
            api.list_delivery_runs(LM_BOB, {"loading_manifest_id": env.manifest["id"]})
        )
        assert_total_count(meta, 2)


class TestTheStandsClosedInterval:
    """A shared endpoint instant counts, and the limit is the stand's own number."""

    def test_two_runs_may_share_one_instant_and_a_third_may_not(self, issued_env):
        """The stand convention is the opposite of the truck's: endpoints collide.

        PRD §3.7: "Stand occupancy is a closed interval with an aggregate limit: a run is refused when adding it would make more than `max_concurrent_runs` non-cancelled runs cover any common instant, where a shared endpoint instant counts as common, and the refusal is `ERR_STAND_CAPACITY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stand_closed_interval_aggregate_limit_rejects_the_third_run_sharing_one_instant
        """
        env = issued_env
        api = env.api
        assert env.stand["max_concurrent_runs"] == 2
        second_truck = register_truck(api, registration="HL-102")
        third_truck = register_truck(api, registration="HL-103")
        first = reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])

        # [07:30, 08:00] and [08:00, 08:30] both cover 08:00 — exactly two.
        second = reserve_run(
            api,
            env.manifest["id"],
            second_truck["id"],
            env.stand["id"],
            window_start_utc=WINDOW_END,
            window_end_utc=SHARED_INSTANT_END,
        )
        assert second["status"] == "RESERVED"
        assert second["truck_id"] == second_truck["id"]
        assert second["stand_id"] == env.stand["id"]

        # A third run covering 08:00 would make three.
        conflict = api.create_delivery_run(
            f.run_payload(
                env.manifest["id"],
                third_truck["id"],
                env.stand["id"],
                WINDOW_END,
                THIRD_END,
            ),
            LM_BOB,
        )
        validate_error(conflict, ApiErrorId.ERR_STAND_CAPACITY_CONFLICT.value, 422)
        # HL-103 holds no other run, so this is not the truck rule speaking.
        assert (
            conflict.json()["data"]["error_id"]
            != ApiErrorId.ERR_TRUCK_SLOT_CONFLICT.value
        )

        runs, meta = validate_paginated(
            api.list_delivery_runs(LM_BOB, {"loading_manifest_id": env.manifest["id"]})
        )
        assert_total_count(meta, 2)
        assert {row["id"] for row in runs} == {first["id"], second["id"]}
        assert read_flight(api, env.flight_id)["status"] == "LOADED"
        assert (
            validate_success(
                api.get_loading_manifest(env.manifest["id"], LM_BOB), 200
            )["amendment_count"]
            == 0
        )

    def test_raising_the_stands_limit_to_three_admits_the_run_it_had_refused(
        self, issued_env
    ):
        """The aggregate is read off the stand row, so amending it changes the answer.

        PRD §3.7: "Amending either resource may change its `status` and, for a truck, its `buffer_minutes` or, for a stand, its `max_concurrent_runs`; the amendment increments that row's `version` and deliberately does **not** revalidate delivery run windows that were already reserved against it."

        PRD §3.7: "Stand occupancy is a closed interval with an aggregate limit: a run is refused when adding it would make more than `max_concurrent_runs` non-cancelled runs cover any common instant, where a shared endpoint instant counts as common, and the refusal is `ERR_STAND_CAPACITY_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stand_closed_interval_aggregate_limit_rejects_the_third_run_sharing_one_instant
        """
        env = issued_env
        api = env.api
        second_truck = register_truck(api, registration="HL-102")
        third_truck = register_truck(api, registration="HL-103")
        reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])
        reserve_run(
            api,
            env.manifest["id"],
            second_truck["id"],
            env.stand["id"],
            window_start_utc=WINDOW_END,
            window_end_utc=SHARED_INSTANT_END,
        )

        validate_error(
            api.create_delivery_run(
                f.run_payload(
                    env.manifest["id"],
                    third_truck["id"],
                    env.stand["id"],
                    WINDOW_END,
                    THIRD_END,
                ),
                LM_BOB,
            ),
            ApiErrorId.ERR_STAND_CAPACITY_CONFLICT.value,
            422,
        )

        widened = validate_success(
            api.amend_stand(env.stand["id"], {"max_concurrent_runs": 3}, ADMIN), 200
        )
        assert widened["max_concurrent_runs"] == 3
        assert widened["version"] == env.stand["version"] + 1

        third = reserve_run(
            api,
            env.manifest["id"],
            third_truck["id"],
            env.stand["id"],
            window_start_utc=WINDOW_END,
            window_end_utc=THIRD_END,
        )
        assert third["status"] == "RESERVED"
        assert third["stand_id"] == env.stand["id"]
        _, meta = validate_paginated(
            api.list_delivery_runs(LM_BOB, {"loading_manifest_id": env.manifest["id"]})
        )
        assert_total_count(meta, 3)
        assert read_flight(api, env.flight_id)["status"] == "LOADED"
