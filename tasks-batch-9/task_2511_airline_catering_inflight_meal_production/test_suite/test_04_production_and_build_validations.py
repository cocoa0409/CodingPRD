"""Kitchen-floor and equipment-build refusals: food-safety gates, plan capacity, seals."""

from test_helpers import (
    CART_CODE_CHILL,
    CART_CODE_CHILL_2,
    CLOCK_CART,
    CLOCK_COMPLETE,
    CLOCK_LOCK,
    CLOCK_PLAN,
    CLOCK_PRODUCTION,
    CLOCK_QA,
    LM_ALICE,
    QA,
    SEAL_PRIMARY,
    SEAL_SECONDARY,
    SPEC_AN_Y,
    SUPERVISOR,
    SUPERVISOR_2,
    ApiErrorId,
    add_flight,
    advance_to_locked,
    advance_to_planned,
    assert_cart_axes,
    assert_decimal_equals,
    assert_instant_equals,
    assert_total_count,
    cut_plan,
    factories as f,
    get_success_data,
    ingest_flight,
    load_item,
    lock_counts,
    produce_and_release,
    read_cart,
    read_flight,
    record_check,
    record_passing_checks,
    register_cart,
    set_clock,
    sign_off_build,
    start_batch,
    validate_error,
    validate_paginated,
    validate_success,
)


def _hold_then_rework(env):
    """Take the chill batch to `COMPLETED` with a failing newest `HOLD_TEMP` check.

    A measurement is only accepted while the batch is `IN_PRODUCTION` or
    `RELEASED`, so the failing re-check is taken before completion; the hold it
    causes is worked off with one restart, which is what leaves the batch
    completable while its newest reading is still a `FAIL`.
    """
    api = env.api
    batch_id = env.batch["id"]
    set_clock(api, CLOCK_PRODUCTION)
    start_batch(api, batch_id)
    set_clock(api, CLOCK_QA)
    return api, batch_id


class TestTheFoodSafetyReleaseLadder:
    """The four release gates, in their pinned order."""

    def test_release_is_refused_while_the_newest_check_of_a_required_step_failed(
        self, planned_env
    ):
        """Gate two reads the highest-sequence check per step, not the batch's own status.

        PRD §3.5: "It applies only to a batch in `COMPLETED`, moving it `COMPLETED → RELEASED`, and it requires that for every step named in the specification's `required_haccp_steps` the check with the highest `sequence_no` for that batch-and-step pair exists and carries verdict `PASS`, that `haccp_rework_rounds` is strictly below two, and that the logical clock is at or before `release_deadline_utc`."

        Design: Corner/validations/releasing_a_batch_whose_latest_hold_temp_check_failed_returns_haccp_hold_active
        """
        env = planned_env
        api, batch_id = _hold_then_rework(env)
        record_check(api, batch_id, "CHILL_DOWN", 6.0)
        first_hold = record_check(api, batch_id, "HOLD_TEMP", 4.0)
        assert first_hold["verdict"] == "PASS"
        assert first_hold["sequence_no"] == 1

        recheck = record_check(api, batch_id, "HOLD_TEMP", 5.1)
        # 5.1 is above the 5.0 hold-temperature maximum.
        assert recheck["verdict"] == "FAIL"
        assert recheck["sequence_no"] == 2
        held = validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)
        assert held["production_status"] == "HACCP_HOLD"

        start_batch(api, batch_id)
        set_clock(api, CLOCK_COMPLETE)
        completed = validate_success(
            api.complete_batch(batch_id, f.complete_payload(180), SUPERVISOR), 200
        )
        assert completed["production_status"] == "COMPLETED"

        validate_error(
            api.release_batch(batch_id, {}, SUPERVISOR),
            ApiErrorId.ERR_HACCP_HOLD_ACTIVE.value,
            422,
        )
        batch = validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)
        assert batch["production_status"] == "COMPLETED"
        assert batch["released_at"] is None
        assert batch["released_by_user_id"] is None
        # One restart was consumed, so gate three is still satisfied.
        assert batch["haccp_rework_rounds"] == 1
        # 40.00 for the single failure plus 15.00 for the single rework round.
        assert_decimal_equals(batch["haccp_risk_score"], "55.00")

    def test_a_required_step_with_no_check_is_reported_before_a_failing_one(
        self, planned_env
    ):
        """Rung one short-circuits rung two even though both are violated at once.

        PRD §3.5: "The four gate failures are reported in the fixed order set out in §2.6: a required step with no check at all yields `ERR_HACCP_STEP_MISSING`, a required step whose newest check failed yields `ERR_HACCP_HOLD_ACTIVE`, an exhausted rework allowance yields `ERR_HACCP_REWORK_LIMIT`, and a passed deadline yields `ERR_RELEASE_DEADLINE_PASSED`."

        Design: Corner/validations/a_missing_haccp_step_is_reported_before_a_failing_one
        """
        env = planned_env
        api, batch_id = _hold_then_rework(env)
        assert record_check(api, batch_id, "HOLD_TEMP", 4.0)["verdict"] == "PASS"
        assert record_check(api, batch_id, "HOLD_TEMP", 5.1)["verdict"] == "FAIL"
        start_batch(api, batch_id)
        set_clock(api, CLOCK_COMPLETE)
        validate_success(
            api.complete_batch(batch_id, f.complete_payload(180), SUPERVISOR), 200
        )

        validate_error(
            api.release_batch(batch_id, {}, SUPERVISOR),
            ApiErrorId.ERR_HACCP_STEP_MISSING.value,
            422,
        )
        _, meta = validate_paginated(
            api.list_haccp_checks(
                QA, {"production_batch_id": batch_id, "step_code": "CHILL_DOWN"}
            )
        )
        assert_total_count(meta, 0)

        batch = validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)
        assert batch["production_status"] == "COMPLETED"
        assert batch["produced_qty"] == 180
        assert batch["released_at"] is None

    def test_a_fully_conforming_release_records_who_certified_it(self, planned_env):
        """Every rung satisfied, so the positive path stamps the certifying operator.

        PRD §3.5: "A successful release sets `released_at` to the logical clock and `released_by_user_id` to the acting operator, and increments the batch's `version`."

        Design: Corner/validations/a_fully_conforming_release_passes_every_band_in_order
        """
        env = planned_env
        api = env.api
        batch_id = env.batch["id"]
        set_clock(api, CLOCK_PRODUCTION)
        start_batch(api, batch_id)
        set_clock(api, CLOCK_QA)
        record_passing_checks(api, batch_id, list(SPEC_AN_Y["required_haccp_steps"]))
        set_clock(api, CLOCK_COMPLETE)
        validate_success(
            api.complete_batch(batch_id, f.complete_payload(180), SUPERVISOR), 200
        )

        released = validate_success(api.release_batch(batch_id, {}, SUPERVISOR_2), 200)
        assert released["production_status"] == "RELEASED"
        assert_instant_equals(released["released_at"], "2026-09-15T05:30:00Z")
        assert released["released_by_user_id"] == "ps_carol"
        assert released["haccp_rework_rounds"] == 0
        assert_decimal_equals(released["haccp_risk_score"], "0.00")
        # The clock stands at 05:30, comfortably before the pinned deadline.
        assert_instant_equals(
            released["release_deadline_utc"], "2026-09-15T08:30:00Z"
        )

    def test_produced_quantity_may_not_exceed_the_plan_and_the_bound_is_inclusive(
        self, planned_env
    ):
        """181 against a plan of 180 is refused; 180 exactly is accepted.

        PRD §3.5: "It applies only to a batch in `IN_PRODUCTION`, and `produced_qty` may not exceed `planned_qty`, or the request is refused with `ERR_PRODUCED_QTY_EXCEEDS_PLAN`."

        Design: Corner/validations/completing_a_batch_above_its_planned_quantity_is_rejected
        """
        env = planned_env
        api = env.api
        batch_id = env.batch["id"]
        set_clock(api, CLOCK_PRODUCTION)
        start_batch(api, batch_id)
        set_clock(api, CLOCK_QA)
        record_passing_checks(api, batch_id, list(SPEC_AN_Y["required_haccp_steps"]))
        set_clock(api, CLOCK_COMPLETE)

        validate_error(
            api.complete_batch(batch_id, f.complete_payload(181), SUPERVISOR),
            ApiErrorId.ERR_PRODUCED_QTY_EXCEEDS_PLAN.value,
            422,
        )
        refused = validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)
        assert refused["production_status"] == "IN_PRODUCTION"
        assert refused["produced_qty"] == 0
        assert refused["scrapped_qty"] == 0

        accepted = validate_success(
            api.complete_batch(batch_id, f.complete_payload(180), SUPERVISOR), 200
        )
        assert accepted["production_status"] == "COMPLETED"
        assert accepted["produced_qty"] == 180
        assert accepted["scrapped_qty"] == 0

        flight = read_flight(api, env.flight_id)
        assert flight["units_produced"] == 180
        assert flight["units_scrapped"] == 0


class TestPlanCapacity:
    """The waterfall's aggregate refusal."""

    def test_hot_demand_with_nowhere_to_overflow_refuses_the_whole_plan(
        self, base_env
    ):
        """130 hot units exceed the store, and a four-hour shelf life may not spill.

        PRD §3.4: "If the specification's `shelf_life_hours` is below the minimum the primary store demands of overflowed food — 24 hours for food whose primary store is the hot store, and 72 hours for food whose primary store is the chill store — the plan is likewise refused with `ERR_STORE_CAPACITY_EXCEEDED`; the comparison is inclusive at the minimum, so a shelf life of exactly 72 hours may overflow out of the chill store."

        Design: Corner/validations/first_class_demand_above_the_hot_zone_capacity_with_nowhere_to_overflow_is_rejected
        """
        env = base_env
        api = env.api
        add_flight(
            env,
            flight_number="AN424",
            tail_number="LN-GGG",
            pax_first=130,
            pax_economy=0,
        )
        advance_to_locked(env)
        locked_version = env.flight["version"]
        set_clock(api, CLOCK_PLAN)

        validate_error(
            api.cut_production_plan(env.flight_id, {}, SUPERVISOR),
            ApiErrorId.ERR_STORE_CAPACITY_EXCEEDED.value,
            422,
        )
        _, meta = validate_paginated(
            api.list_production_batches(SUPERVISOR, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 0)

        flight = read_flight(api, env.flight_id)
        assert flight["status"] == "COUNTS_LOCKED"
        assert flight["units_planned"] == 0
        assert flight["version"] == locked_version


class TestCartStateAndSealUniqueness:
    """The build and seal axes refuse what they have no edge for."""

    def test_signing_off_or_sealing_an_empty_cart_is_refused(self, planned_env):
        """Neither axis has an edge out of an empty cart, and the seal's guard was current.

        PRD §3.6: "It requires the cart to be in `BUILDING` with `loaded_units` of at least 1; an `EMPTY` cart, or one in any other build state, is refused with `ERR_INVALID_CART_STATE`."

        PRD §3.6: "The cart must be `BUILT`, or the request is refused with `ERR_INVALID_CART_STATE`."

        Design: Corner/validations/signing_off_or_sealing_an_empty_cart_returns_invalid_cart_state
        """
        env = planned_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id, galley_position="G1")
        assert cart["version"] == 1

        validate_error(
            api.complete_cart_build(cart["id"], {}, LM_ALICE),
            ApiErrorId.ERR_INVALID_CART_STATE.value,
            409,
        )
        validate_error(
            api.seal_cart(
                cart["id"], f.seal_payload(cart["version"], SEAL_PRIMARY), LM_ALICE
            ),
            ApiErrorId.ERR_INVALID_CART_STATE.value,
            409,
        )

        stored = read_cart(api, cart["id"])
        assert_cart_axes(stored, "EMPTY", "UNSEALED")
        assert stored["seal_number"] is None
        assert stored["seal_count"] == 0
        assert stored["loaded_units"] == 0

    def test_a_seal_number_already_held_by_another_cart_cannot_be_reused(
        self, released_env
    ):
        """Uniqueness spans carts and waste manifests, and the refusal reserves nothing.

        PRD §3.6: "The `seal_number` must not be held by any other cart or by any waste manifest, or the request is refused with `ERR_SEAL_NUMBER_DUPLICATE`."

        Design: Corner/validations/reusing_a_live_seal_number_on_a_second_cart_is_rejected
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        first = register_cart(api, env.flight_id, cart_code=CART_CODE_CHILL)
        second = register_cart(
            api,
            env.flight_id,
            cart_code=CART_CODE_CHILL_2,
            cart_type="STD_HALF",
            capacity_units=100,
            galley_position="G2",
        )
        load_item(api, first["id"], env.batch["id"], 100)
        load_item(api, second["id"], env.batch["id"], 80)
        sign_off_build(api, first["id"])
        sign_off_build(api, second["id"])

        sealed_first = get_success_data(
            api.seal_cart(
                first["id"],
                f.seal_payload(read_cart(api, first["id"])["version"], SEAL_PRIMARY),
                LM_ALICE,
            )
        )
        assert sealed_first["seal_number"] == SEAL_PRIMARY

        second_version = read_cart(api, second["id"])["version"]
        validate_error(
            api.seal_cart(
                second["id"], f.seal_payload(second_version, SEAL_PRIMARY), LM_ALICE
            ),
            ApiErrorId.ERR_SEAL_NUMBER_DUPLICATE.value,
            422,
        )
        refused = read_cart(api, second["id"])
        assert refused["seal_status"] == "UNSEALED"
        assert refused["version"] == second_version
        assert refused["seal_number"] is None

        accepted = get_success_data(
            api.seal_cart(
                second["id"], f.seal_payload(second_version, SEAL_SECONDARY), LM_ALICE
            )
        )
        assert accepted["seal_status"] == "SEALED"
        assert accepted["seal_number"] == SEAL_SECONDARY
        assert accepted["seal_count"] == 1
        assert accepted["sealed_by_user_id"] == "lm_alice"
        assert read_cart(api, first["id"])["seal_number"] == SEAL_PRIMARY

    def test_a_batch_belonging_to_another_flight_cannot_be_loaded(self, base_env):
        """The check compares two rows the request never names against each other.

        PRD §3.6: "its `flight_id` must equal the cart's `flight_id`, or the load is refused with `ERR_CART_FLIGHT_MISMATCH`; the cart's `loaded_units` plus the new `qty_units` may not exceed `capacity_units`, or the load is refused with `ERR_CART_CAPACITY_EXCEEDED`; and finally, the flight's resulting `cost_per_pax_cents` may not exceed the airline's `cost_cap_per_pax_cents`, or the load is refused with `ERR_COST_CAP_EXCEEDED`."

        Design: Corner/validations/loading_another_flights_batch_into_this_flights_cart_is_rejected
        """
        env = base_env
        api = env.api
        add_flight(env)
        other = ingest_flight(
            api,
            env.airline_id,
            flight_number="AN412",
            std_utc="2026-09-15T12:00:00Z",
            tail_number="LN-BBB",
            pax_economy=100,
        )

        set_clock(api, CLOCK_LOCK)
        lock_counts(api, env.flight_id)
        lock_counts(api, other["id"])
        set_clock(api, CLOCK_PLAN)
        advance_to_planned(env)
        other_batches = cut_plan(api, other["id"])
        assert len(other_batches) == 1

        steps = list(SPEC_AN_Y["required_haccp_steps"])
        produce_and_release(api, env.batch, steps)
        produce_and_release(api, other_batches[0], steps)

        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id)
        validate_error(
            api.load_cart_item(
                cart["id"], f.cart_item_payload(other_batches[0]["id"], 10), LM_ALICE
            ),
            ApiErrorId.ERR_CART_FLIGHT_MISMATCH.value,
            422,
        )

        stored = read_cart(api, cart["id"])
        assert stored["loaded_units"] == 0
        assert stored["build_status"] == "EMPTY"
        _, meta = validate_paginated(
            api.list_cart_items(LM_ALICE, {"cart_id": cart["id"]})
        )
        assert_total_count(meta, 0)
        assert read_flight(api, other["id"])["units_loaded"] == 0
