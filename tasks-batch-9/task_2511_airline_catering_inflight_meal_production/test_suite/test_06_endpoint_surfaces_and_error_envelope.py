"""Endpoint surfaces — CRUD, partial patches, filters, soft delete — and the error envelope."""

from test_helpers import (
    ADMIN,
    CLOCK_CART,
    CLOCK_LOCK,
    CLOCK_PLAN,
    CLOCK_PRODUCTION,
    CLOCK_QA,
    FEED,
    LM_ALICE,
    LM_BOB,
    NON_EXISTENT_UUID,
    QA,
    SUPERVISOR,
    ApiErrorId,
    add_flight,
    advance_to_locked,
    advance_to_planned,
    assert_error_envelope_shape,
    assert_instant_equals,
    assert_total_count,
    capture_order,
    cut_plan,
    factories as f,
    ingest_flight,
    load_item,
    lock_counts,
    read_cart,
    read_flight,
    record_check,
    register_cart,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestReferenceAndScheduleSurfaces:
    """The reference CRUD surface and the two feed operations that keep a flight current."""

    def test_the_truck_surface_creates_reads_lists_and_patches_partially(self, api):
        """A patch that names one field leaves the other at the value it already held.

        PRD §3.7: "Amending either resource may change its `status` and, for a truck, its `buffer_minutes` or, for a stand, its `max_concurrent_runs`; the amendment increments that row's `version` and deliberately does **not** revalidate delivery run windows that were already reserved against it."

        Design: Corner/endpoints/the_truck_reference_endpoints_form_a_complete_crud_surface
        """
        created = validate_success(
            api.create_truck(
                f.truck_payload(registration="HL-201", buffer_minutes=15), ADMIN
            ),
            201,
        )
        assert created["status"] == "ACTIVE"
        assert created["buffer_minutes"] == 15
        assert created["version"] == 1

        fetched = validate_success(api.get_truck(created["id"], LM_BOB), 200)
        assert fetched["id"] == created["id"]
        assert fetched["version"] == 1

        rebuffered = validate_success(
            api.amend_truck(created["id"], {"buffer_minutes": 25}, ADMIN), 200
        )
        assert rebuffered["buffer_minutes"] == 25
        # The omitted field was not reset to its default.
        assert rebuffered["status"] == "ACTIVE"
        assert rebuffered["version"] == 2

        grounded = validate_success(
            api.amend_truck(created["id"], {"status": "MAINTENANCE"}, ADMIN), 200
        )
        assert grounded["status"] == "MAINTENANCE"
        assert grounded["buffer_minutes"] == 25
        assert grounded["version"] == 3

        rows, meta = validate_paginated(
            api.list_trucks(LM_BOB, {"station_code": "OSL", "status": "MAINTENANCE"})
        )
        assert_total_count(meta, 1)
        assert rows[0]["id"] == created["id"]
        _, active_meta = validate_paginated(
            api.list_trucks(LM_BOB, {"station_code": "OSL", "status": "ACTIVE"})
        )
        assert_total_count(active_meta, 0)

    def test_a_passenger_refresh_after_the_lock_gets_its_own_specialised_code(
        self, locked_env
    ):
        """The refusal is the counts-locked specialisation, not the generic state code.

        PRD §3.2: "It is accepted only while the flight is `SCHEDULED` — once counts are locked, a refresh is refused with `ERR_FLIGHT_COUNTS_LOCKED`, and the three cabin counts become immutable for the rest of the flight's life."

        Design: Corner/endpoints/writing_pax_counts_after_the_count_lock_returns_flight_counts_locked
        """
        env = locked_env
        api = env.api
        validate_error(
            api.update_pax_counts(
                env.flight_id, f.pax_counts_payload(pax_economy=200), FEED
            ),
            ApiErrorId.ERR_FLIGHT_COUNTS_LOCKED.value,
            409,
        )

        flight = read_flight(api, env.flight_id)
        assert flight["pax_economy"] == 180
        assert flight["total_pax"] == 180
        # 180 economy trays uplifted by 2.50 percent, rounded up per cabin.
        assert flight["units_planned_provisional"] == 185
        assert flight["status"] == "COUNTS_LOCKED"
        assert flight["version"] == 2

    def test_retiming_earlier_then_delaying_walks_an_order_out_of_and_back_into_confirmation(
        self, base_env
    ):
        """The retime leaves the order alone; the lock judges it late; the delay reopens it.

        PRD §3.2: "Crucially, a retime does **not** touch `delay_minutes`, does **not** touch `units_planned`, and does **not** re-evaluate any special meal order's `status`."

        PRD §3.8: "Because the cutoff has moved later, every special meal order in `LATE_REJECTED` whose `requested_at` now falls at or before the recomputed `special_meal_cutoff_utc` is reopened, moving `LATE_REJECTED → REQUESTED` and incrementing that order's `version`; and when `counts_locked_at` is not null — that is, when the counts were already locked — each reopened order is immediately re-evaluated in the same cascade and continues `REQUESTED → CONFIRMED`."

        Design: Corner/endpoints/retiming_a_flight_earlier_then_delaying_it_walks_an_order_out_of_and_back_into_confirmation
        """
        env = base_env
        api = env.api
        flight = ingest_flight(
            api,
            env.airline_id,
            flight_number="AN416",
            service_date="2026-09-16",
            std_utc="2026-09-16T10:00:00Z",
            tail_number="LN-HHH",
            pax_economy=60,
        )
        set_clock(api, "2026-09-15T12:00:00Z")
        order = capture_order(
            api,
            env.airline_id,
            flight["id"],
            env.specs["V"]["id"],
            "30A",
            passenger_ref="PNR-E1",
        )
        assert order["status"] == "REQUESTED"
        assert_instant_equals(order["requested_at"], "2026-09-15T12:00:00Z")

        retimed = validate_success(
            api.retime_flight(
                flight["id"], f.retime_payload("2026-09-15T20:00:00Z"), FEED
            ),
            200,
        )
        assert_instant_equals(retimed["std_utc"], "2026-09-15T20:00:00Z")
        assert_instant_equals(
            retimed["special_meal_cutoff_utc"], "2026-09-15T08:00:00Z"
        )
        after_retime = validate_success(
            api.get_special_meal_order(order["id"], env.rep_headers), 200
        )
        assert after_retime["status"] == "REQUESTED"

        set_clock(api, "2026-09-15T13:00:00Z")
        lock_counts(api, flight["id"])
        late = validate_success(
            api.get_special_meal_order(order["id"], env.rep_headers), 200
        )
        assert late["status"] == "LATE_REJECTED"

        delayed = validate_success(
            api.record_delay(
                flight["id"],
                f.delay_payload(300, reason="AIRCRAFT_ROTATION"),
                FEED,
            ),
            200,
        )
        assert_instant_equals(delayed["revised_std_utc"], "2026-09-16T01:00:00Z")
        assert_instant_equals(
            delayed["special_meal_cutoff_utc"], "2026-09-15T13:00:00Z"
        )
        assert delayed["status"] == "COUNTS_LOCKED"
        reopened = validate_success(
            api.get_special_meal_order(order["id"], env.rep_headers), 200
        )
        assert reopened["status"] == "CONFIRMED"

    def test_retiring_the_only_standard_tray_empties_the_next_plan_only(self, base_env):
        """Retirement is forward-only: the batch already cut keeps its quantity.

        PRD §3.4: "A flight with at least one booked passenger whose every matching standard specification has been retired still moves to `PLANNED`, with `units_planned` at 0 and no batches at all."

        Design: Corner/endpoints/retiring_the_only_standard_specification_empties_the_next_plan_without_touching_the_last
        """
        env = base_env
        api = env.api
        add_flight(env)
        advance_to_locked(env)
        advance_to_planned(env)
        assert env.batch["planned_qty"] == 180

        retired = validate_success(
            api.amend_meal_specification(
                env.specs["Y"]["id"],
                {"status": "RETIRED", "unit_cost_cents": 1500},
                ADMIN,
            ),
            200,
        )
        assert retired["status"] == "RETIRED"
        assert retired["unit_cost_cents"] == 1500
        assert retired["version"] == 2

        assert env.reload_batches()[0]["planned_qty"] == 180
        assert read_flight(api, env.flight_id)["units_planned"] == 180

        later = ingest_flight(
            api,
            env.airline_id,
            flight_number="AN425",
            std_utc="2026-09-15T14:00:00Z",
            tail_number="LN-JJJ",
            pax_economy=50,
        )
        # No `ACTIVE` standard economy tray remains to select.
        assert later["units_planned_provisional"] == 0
        lock_counts(api, later["id"])
        batches = cut_plan(api, later["id"])
        assert batches == []
        empty_plan = read_flight(api, later["id"])
        assert empty_plan["status"] == "PLANNED"
        assert empty_plan["units_planned"] == 0


class TestFilterSurfacesAndSoftDelete:
    """The link expressed purely by filters, and the delete that is really a void."""

    def test_the_batchs_checks_are_reachable_by_composing_filters(self, planned_env):
        """Batch to checks is a filter-only link, and the filters narrow cumulatively.

        PRD §4: "Lists HACCP checks, filterable by `production_batch_id`, `step_code` and `verdict`; ordered by `sequence_no` ascending within a batch."

        Design: Corner/endpoints/haccp_checks_are_reachable_from_the_batch_by_filter_including_by_verdict
        """
        env = planned_env
        api = env.api
        batch_id = env.batch["id"]
        set_clock(api, CLOCK_PRODUCTION)
        validate_success(api.start_batch(batch_id, {}, SUPERVISOR), 200)
        set_clock(api, CLOCK_QA)
        record_check(api, batch_id, "CHILL_DOWN", 6.0)
        record_check(api, batch_id, "HOLD_TEMP", 4.0)
        failed = record_check(api, batch_id, "HOLD_TEMP", 5.1)

        _, all_meta = validate_paginated(
            api.list_haccp_checks(QA, {"production_batch_id": batch_id})
        )
        assert_total_count(all_meta, 3)

        fails, fail_meta = validate_paginated(
            api.list_haccp_checks(
                QA, {"production_batch_id": batch_id, "verdict": "FAIL"}
            )
        )
        assert_total_count(fail_meta, 1)
        assert fails[0]["id"] == failed["id"]
        assert fails[0]["sequence_no"] == 2

        chilled, chill_meta = validate_paginated(
            api.list_haccp_checks(
                QA,
                {
                    "production_batch_id": batch_id,
                    "step_code": "CHILL_DOWN",
                    "verdict": "PASS",
                },
            )
        )
        assert_total_count(chill_meta, 1)
        assert chilled[0]["step_code"] == "CHILL_DOWN"
        assert chilled[0]["sequence_no"] == 1

        held = validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)
        assert held["production_status"] == "HACCP_HOLD"

    def test_voiding_an_already_void_item_is_a_state_refusal_not_a_miss(
        self, released_env
    ):
        """The row survives the first void, so the second attempt is refused on state.

        PRD §3.6: "Voiding an item that is already `VOID` is refused with `ERR_INVALID_RESOURCE_STATE`."

        Design: Corner/endpoints/deleting_an_already_voided_cart_item_returns_invalid_resource_state
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id)
        item = load_item(api, cart["id"], env.batch["id"], 180)

        voided = validate_success(
            api.void_cart_item(cart["id"], item["id"], LM_ALICE), 200
        )
        assert voided["status"] == "VOID"
        first_voided_at = voided["voided_at"]
        after_first = read_cart(api, cart["id"])
        assert after_first["loaded_units"] == 0
        assert after_first["build_status"] == "BUILDING"

        validate_error(
            api.void_cart_item(cart["id"], item["id"], LM_ALICE),
            ApiErrorId.ERR_INVALID_RESOURCE_STATE.value,
            409,
        )

        # The row is still there, with its original stamp.
        still_there = validate_success(api.get_cart_item(item["id"], LM_ALICE), 200)
        assert still_there["status"] == "VOID"
        assert still_there["voided_at"] == first_voided_at
        assert read_cart(api, cart["id"])["loaded_units"] == 0
        assert read_flight(api, env.flight_id)["units_loaded"] == 0


class TestTheErrorEnvelopeAndItsCodes:
    """The failure envelope itself, and two codes reached from the load path."""

    def test_a_failure_keeps_the_three_key_envelope_with_a_two_key_data_object(
        self, api
    ):
        """The failure body is the same outer shape as a success, with a narrower meta.

        PRD §2.2: "The `meta` object for error responses contains only `api_request_id` and `api_request_timestamp`."

        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."

        Design: Corner/errors/the_error_envelope_carries_only_an_error_id_and_a_message
        """
        response = api.get_flight(NON_EXISTENT_UUID, FEED)
        assert response.status_code == 404
        body = response.json()
        assert set(body.keys()) == {"meta", "response_type", "data"}
        assert body["response_type"] == "error"
        assert set(body["data"].keys()) == {"error_id", "message"}
        assert body["data"]["error_id"] == ApiErrorId.ERR_FLIGHT_NOT_FOUND.value
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip() != ""
        assert_error_envelope_shape(body)
        # The correlation id is present on a failure exactly as on a success.
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_the_capacity_bound_is_inclusive_and_the_surplus_is_never_clipped(
        self, released_env
    ):
        """101 into a 100-unit cart writes nothing at all; 100 fills it exactly.

        PRD §3.6: "Each successful load recomputes the cart's `loaded_units` — the sum of `qty_units` over that cart's `ACTIVE` items — along with the flight's `units_loaded`, `unit_balance` and `cost_per_pax_cents`."

        PRD §2.6: "A cart's active units may not exceed its declared capacity (`ERR_CART_CAPACITY_EXCEEDED`); zone allocation may not leave units unplaced after the overflow chain (`ERR_STORE_CAPACITY_EXCEEDED`); a seal number is unique across carts and waste manifests alike (`ERR_SEAL_NUMBER_DUPLICATE`); a seat may hold only one non-terminal special meal order per flight (`ERR_DUPLICATE_SEAT_ORDER`); produced quantity may not exceed planned quantity (`ERR_PRODUCED_QTY_EXCEEDS_PLAN`); submitted consumed plus returned units must equal the units actually uplifted (`ERR_UPLIFT_UNITS_MISMATCH`); and each disposition line's re-used plus donated plus destroyed units must equal that line's returned units (`ERR_DISPOSITION_UNITS_MISMATCH`)."

        Design: Corner/errors/loading_one_unit_beyond_a_carts_capacity_is_rejected
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(
            api,
            env.flight_id,
            cart_code="CHL-02",
            cart_type="STD_HALF",
            capacity_units=100,
            galley_position="G2",
        )

        validate_error(
            api.load_cart_item(
                cart["id"], f.cart_item_payload(env.batch["id"], 101), LM_ALICE
            ),
            ApiErrorId.ERR_CART_CAPACITY_EXCEEDED.value,
            422,
        )
        _, meta = validate_paginated(
            api.list_cart_items(LM_ALICE, {"cart_id": cart["id"]})
        )
        assert_total_count(meta, 0)

        load_item(api, cart["id"], env.batch["id"], 100)
        filled = read_cart(api, cart["id"])
        assert filled["loaded_units"] == 100 == filled["capacity_units"]
        assert filled["build_status"] == "BUILDING"
        flight = read_flight(api, env.flight_id)
        assert flight["units_loaded"] == 100
        assert flight["unit_balance"] == 80

    def test_one_first_class_tray_can_breach_the_contractual_cap_on_its_own(self, api):
        """The ceiling is read off the resulting blend, and it is checked last of all.

        PRD §3.6: "Those six sit in four different priority bands, so a load that trips several of them reports the earliest band, as §2.6 sets out."

        Design: Corner/errors/a_single_first_class_meal_above_the_contractual_cap_is_rejected
        """
        set_clock(api, "2026-09-12T09:00:00Z")
        airline = validate_success(
            api.create_airline(
                f.airline_payload(
                    name="CostCap Air",
                    iata_code="CC",
                    waste_regime="DOMESTIC",
                    cost_cap_per_pax_cents=1500,
                ),
                ADMIN,
            ),
            201,
        )
        spec = validate_success(
            api.create_meal_specification(
                f.spec_first_payload(airline["id"], spec_code="CC-F-STD"), ADMIN
            ),
            201,
        )
        flight = validate_success(
            api.create_flight(
                f.flight_payload(
                    airline["id"],
                    flight_number="CC902",
                    tail_number="SE-CCC",
                    pax_first=1,
                ),
                FEED,
            ),
            201,
        )

        set_clock(api, CLOCK_LOCK)
        lock_counts(api, flight["id"])
        set_clock(api, CLOCK_PLAN)
        batches = cut_plan(api, flight["id"])
        assert len(batches) == 1
        batch = batches[0]
        assert batch["planned_qty"] == 1

        set_clock(api, CLOCK_PRODUCTION)
        validate_success(api.start_batch(batch["id"], {}, SUPERVISOR), 200)
        set_clock(api, CLOCK_QA)
        record_check(api, batch["id"], "COOK_TEMP", 80.0)
        record_check(api, batch["id"], "HOLD_TEMP", 4.0)
        set_clock(api, "2026-09-15T05:30:00Z")
        validate_success(
            api.complete_batch(batch["id"], f.complete_payload(1), SUPERVISOR), 200
        )
        released = validate_success(api.release_batch(batch["id"], {}, SUPERVISOR), 200)
        # The hot-zone deadline lies ahead, so this is not a deadline refusal.
        assert_instant_equals(
            released["release_deadline_utc"], "2026-09-15T08:00:00Z"
        )

        set_clock(api, "2026-09-15T06:00:00Z")
        cart = validate_success(
            api.create_cart(
                f.cart_payload(
                    flight["id"], "HOT-01", "OVEN_RACK", "HOT", 10, galley_position="F1"
                ),
                LM_ALICE,
            ),
            201,
        )
        validate_error(
            api.load_cart_item(
                cart["id"], f.cart_item_payload(batch["id"], 1), LM_ALICE
            ),
            ApiErrorId.ERR_COST_CAP_EXCEEDED.value,
            422,
        )

        # A single 4200-cent tray blends to 4704 cents per passenger.
        stored_cart = read_cart(api, cart["id"])
        assert stored_cart["loaded_units"] == 0
        assert stored_cart["build_status"] == "EMPTY"
        _, meta = validate_paginated(
            api.list_cart_items(LM_ALICE, {"cart_id": cart["id"]})
        )
        assert_total_count(meta, 0)
        stored_flight = read_flight(api, flight["id"])
        assert stored_flight["cost_per_pax_cents"] == 0
        assert stored_flight["units_loaded"] == 0
        assert spec["unit_cost_cents"] == 4200
        assert airline["cost_cap_per_pax_cents"] == 1500
