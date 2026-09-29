"""Initial states, refused transitions, terminal lockdown and the cancel cascade."""

from test_helpers import (
    ACTION_DISPOSE,
    ACTION_SEAL,
    CLOCK_COMPLETE,
    CLOCK_MANIFEST,
    CLOCK_PRODUCTION,
    CLOCK_QA,
    ApiErrorId,
    COMPLIANCE,
    EVENT_DELIVER,
    EVENT_DISPATCH,
    FEED,
    LM_ALICE,
    LM_BOB,
    SUPERVISOR,
    assert_cart_axes,
    assert_flight_ledger,
    assert_instant_equals,
    assert_total_count,
    factories as f,
    open_manifest,
    raise_waste_manifest,
    read_cart,
    read_flight,
    record_passing_checks,
    register_cart,
    reserve_run,
    run_event,
    set_clock,
    start_batch,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestInitialStatesAndRefusedTransitions:
    """Rows are born in their declared states, and undefined triggers are refused."""

    def test_locking_the_counts_a_second_time_is_refused(self, locked_env):
        """The lock is not idempotent, and the refused replay re-stamps nothing.

        PRD §3.4: "It requires the flight to be in `SCHEDULED` and to have at least one booked passenger across all cabins; a second attempt, or an attempt on a flight already past `SCHEDULED`, is refused with `ERR_INVALID_FLIGHT_STATE`."

        Design: Corner/state_machines/locking_the_counts_twice_returns_invalid_flight_state
        """
        env = locked_env
        api = env.api
        set_clock(api, "2026-09-15T03:30:00Z")
        validate_error(
            api.lock_counts(env.flight_id, {}, FEED),
            ApiErrorId.ERR_INVALID_FLIGHT_STATE.value,
            409,
        )
        flight = read_flight(api, env.flight_id)
        assert flight["status"] == "COUNTS_LOCKED"
        assert_instant_equals(flight["counts_locked_at"], "2026-09-15T03:00:00Z")
        assert flight["version"] == 2

    def test_batch_cart_and_manifest_open_in_their_declared_initial_states(
        self, planned_env
    ):
        """Three entities are born in three different initial states in one chain.

        PRD §3.6: "A new cart opens with `build_status` `EMPTY`, `seal_status` `UNSEALED`, `seal_count` 0, `loaded_units` 0, and no `seal_number` or `sealed_by_user_id` yet."

        Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
        """
        env = planned_env
        api = env.api
        batches, meta = validate_paginated(
            api.list_production_batches(SUPERVISOR, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)
        batch = batches[0]
        assert batch["production_status"] == "PLANNED"
        assert batch["produced_qty"] == 0
        assert batch["scrapped_qty"] == 0
        assert batch["haccp_rework_rounds"] == 0
        assert float(batch["haccp_risk_score"]) == 0.0
        assert batch["is_overflow"] is False
        assert batch["store_zone"] == "CHILL"
        assert batch["planned_qty"] == 180
        assert batch["released_at"] is None
        assert batch["released_by_user_id"] is None

        cart = register_cart(api, env.flight_id, galley_position="G1")
        assert_cart_axes(cart, "EMPTY", "UNSEALED")
        assert cart["seal_count"] == 0
        assert cart["seal_number"] is None
        assert cart["loaded_units"] == 0

        manifest = open_manifest(api, env.flight_id, headers=LM_BOB)
        assert manifest["status"] == "DRAFT"
        assert manifest["amendment_count"] == 0
        assert manifest["total_units"] == 0
        assert manifest["issued_at"] is None
        assert manifest["issued_by_user_id"] is None
        assert manifest["manifest_number"] == "MFST-AN411-1"

    def test_completing_or_releasing_a_planned_batch_is_refused(self, planned_env):
        """From `PLANNED` the only defined trigger is the start, so both later acts are refused.

        PRD §3.5: "Closing production is a separate `ProductionSupervisor` act that carries the quantity actually produced as `produced_qty`. It applies only to a batch in `IN_PRODUCTION`, and `produced_qty` may not exceed `planned_qty`, or the request is refused with `ERR_PRODUCED_QTY_EXCEEDS_PLAN`."

        Design: Corner/state_machines/completing_or_releasing_a_planned_batch_returns_invalid_batch_state
        """
        env = planned_env
        api = env.api
        batch_id = env.batch["id"]
        validate_error(
            api.complete_batch(batch_id, f.complete_payload(10), SUPERVISOR),
            ApiErrorId.ERR_INVALID_BATCH_STATE.value,
            409,
        )
        validate_error(
            api.release_batch(batch_id, {}, SUPERVISOR),
            ApiErrorId.ERR_INVALID_BATCH_STATE.value,
            409,
        )
        batch = validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)
        assert batch["production_status"] == "PLANNED"
        assert batch["produced_qty"] == 0
        assert batch["scrapped_qty"] == 0
        assert batch["released_at"] is None
        flight = read_flight(api, env.flight_id)
        assert_flight_ledger(flight, units_produced=0, units_scrapped=0)

    def test_delivering_or_recovering_a_reserved_run_is_refused(self, issued_env):
        """`DELIVER` cannot skip the ramp, and a run that never missed cannot be recovered.

        PRD §3.7: "Any event applied from a state where it is undefined is refused with `ERR_INVALID_RUN_STATE`."

        Design: Corner/state_machines/delivering_or_recovering_a_reserved_run_returns_invalid_run_state
        """
        env = issued_env
        api = env.api
        run = reserve_run(
            api, env.manifest["id"], env.truck["id"], env.stand["id"]
        )
        validate_error(
            api.record_run_event(run["id"], f.event_payload(EVENT_DELIVER), LM_BOB),
            ApiErrorId.ERR_INVALID_RUN_STATE.value,
            409,
        )
        validate_error(
            api.create_recovery_run(
                run["id"],
                f.recovery_run_payload(
                    env.truck["id"],
                    env.stand["id"],
                    "2026-09-15T08:20:00Z",
                    "2026-09-15T08:50:00Z",
                ),
                LM_BOB,
            ),
            ApiErrorId.ERR_INVALID_RUN_STATE.value,
            409,
        )
        stored = validate_success(api.get_delivery_run(run["id"], LM_BOB), 200)
        assert stored["status"] == "RESERVED"
        assert stored["dispatched_at_utc"] is None
        assert stored["delivered_at_utc"] is None
        assert stored["version"] == 1
        _, meta = validate_paginated(
            api.list_delivery_runs(
                LM_BOB, {"loading_manifest_id": env.manifest["id"]}
            )
        )
        assert_total_count(meta, 1)
        assert read_flight(api, env.flight_id)["status"] == "LOADED"

    def test_a_reconciled_flight_refuses_every_further_operator_trigger(
        self, reconciled_env
    ):
        """`RECONCILED` is terminal, which is what makes the billing snapshot final.

        PRD §3.2: "`status` opens at `SCHEDULED`; the full lifecycle is `SCHEDULED`, `COUNTS_LOCKED`, `PLANNED`, `LOADED`, `DEPARTED`, `RECONCILED` and `CANCELLED`, with `RECONCILED` and `CANCELLED` terminal."

        Design: Corner/state_machines/a_reconciled_flight_refuses_every_further_transition
        """
        env = reconciled_env
        api = env.api
        flight_id = env.flight_id
        for response in (
            api.lock_counts(flight_id, {}, FEED),
            api.cut_production_plan(flight_id, {}, SUPERVISOR),
            api.record_delay(flight_id, f.delay_payload(30), FEED),
            api.cancel_flight(flight_id, {"reason": "TOO_LATE"}, FEED),
        ):
            validate_error(
                response, ApiErrorId.ERR_INVALID_FLIGHT_STATE.value, 409
            )
        flight = read_flight(api, flight_id)
        assert flight["status"] == "RECONCILED"
        assert flight["delay_minutes"] == 0
        assert flight["units_planned"] == 180

        record = env.reload_uplift()
        assert record["status"] == "DRAFT"
        assert record["uplifted_units"] == 180
        assert record["gross_cost_cents"] == 292320
        assert record["late_penalty_cents"] == 0

        batches, meta = validate_paginated(
            api.list_production_batches(SUPERVISOR, {"flight_id": flight_id})
        )
        assert_total_count(meta, 1)
        assert batches[0]["production_status"] == "RELEASED"


class TestSideEffectsAndCascades:
    """One request, many rows."""

    def test_completing_short_scraps_the_shortfall_and_syncs_the_ledger(
        self, planned_env
    ):
        """One submitted figure writes two quantities and reconciles three flight aggregates.

        PRD §3.5: "Completion moves the batch `IN_PRODUCTION → COMPLETED`, stores `produced_qty`, sets `scrapped_qty` to `planned_qty` minus `produced_qty`, and recomputes the flight's `units_produced`, `units_scrapped` and `unit_balance`."

        Design: Corner/state_machines/completing_a_batch_short_scraps_the_shortfall_and_syncs_the_flight_ledger
        """
        env = planned_env
        api = env.api
        set_clock(api, CLOCK_PRODUCTION)
        start_batch(api, env.batch["id"])
        set_clock(api, CLOCK_QA)
        record_passing_checks(api, env.batch["id"], ["CHILL_DOWN", "HOLD_TEMP"])
        set_clock(api, CLOCK_COMPLETE)
        batch = validate_success(
            api.complete_batch(env.batch["id"], f.complete_payload(170), SUPERVISOR),
            200,
        )
        assert batch["production_status"] == "COMPLETED"
        assert batch["produced_qty"] == 170
        assert batch["scrapped_qty"] == 10

        flight = read_flight(api, env.flight_id)
        assert_flight_ledger(
            flight,
            units_produced=170,
            units_scrapped=10,
            units_loaded=0,
            unit_balance=170,
        )
        assert flight["units_planned"] == 180

    def test_cancelling_a_loaded_flight_unwinds_five_entity_families(self, issued_env):
        """One cancel voids the orders, condemns the batch, breaks the cart and kills the run.

        PRD §3.8: "The flight moves to `CANCELLED` and every dependent row that is still non-terminal is unwound in one request: every special meal order in `REQUESTED` or `CONFIRMED` becomes `CANCELLED`; every production batch in `PLANNED`, `IN_PRODUCTION`, `HACCP_HOLD`, `COMPLETED` or `RELEASED` becomes `REJECTED` with `scrapped_qty` set to its full `planned_qty`; every cart item in `ACTIVE` becomes `VOID`; every loading manifest in `DRAFT`, `ISSUED` or `AMENDED` becomes `VOID`; and every delivery run in `RESERVED`, `RESCHEDULED`, `EN_ROUTE` or `AT_AIRCRAFT` becomes `CANCELLED` with `miss_reason` set to `SLOT_LOST`."

        Design: Corner/state_machines/cancelling_a_loaded_flight_cascades_to_batches_items_carts_manifest_and_runs
        """
        env = issued_env
        api = env.api
        run = reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])

        flight = validate_success(
            api.cancel_flight(env.flight_id, {"reason": "AIRCRAFT_SWAP"}, FEED), 200
        )
        assert flight["status"] == "CANCELLED"

        batch = validate_success(
            api.get_production_batch(env.batch["id"], SUPERVISOR), 200
        )
        assert batch["production_status"] == "REJECTED"
        assert batch["scrapped_qty"] == 180

        item = validate_success(api.get_cart_item(env.item["id"], LM_ALICE), 200)
        assert item["status"] == "VOID"
        assert_instant_equals(item["voided_at"], CLOCK_MANIFEST)

        # PRD §3.8 enumerates the cancel's side-effect set as five families —
        # orders, batches, cart items, manifests and runs — and says "Rows that
        # had already reached a terminal state are left exactly as they were";
        # the cart row itself is not named, and the §3.6 void ripple cannot be
        # in force here because the manifest goes `VOID` (not `AMENDED`) and the
        # flight goes `CANCELLED` (not `PLANNED`). So the two cart axes are not
        # determined by the PRD on this edge and are not asserted. What *is*
        # determined is the aggregate: `loaded_units` sums the cart's `ACTIVE`
        # items, and every one of them has just become `VOID`.
        cart = read_cart(api, env.cart["id"])
        assert cart["loaded_units"] == 0
        assert cart["seal_number"] == "SEAL-AN411-01"

        assert env.reload_manifest()["status"] == "VOID"

        stored_run = validate_success(api.get_delivery_run(run["id"], LM_BOB), 200)
        assert stored_run["status"] == "CANCELLED"
        assert stored_run["miss_reason"] == "SLOT_LOST"

        final = read_flight(api, env.flight_id)
        assert_flight_ledger(
            final, units_loaded=0, units_produced=0, units_scrapped=180
        )

    def test_voiding_a_cart_item_breaks_the_seal_and_reverts_the_flight(
        self, issued_env
    ):
        """One void walks four rows backwards and leaves `seal_number` in place for audit.

        PRD §3.6: "The owning cart, if `BUILT`, falls back `BUILT → BUILDING`, and its seal axis moves from `SEALED` or `RESEALED` to `BROKEN` on the same row — the break clears `sealed_by_user_id` but deliberately leaves `seal_number` in place for audit."

        Design: Corner/state_machines/deleting_a_cart_item_breaks_the_seal_and_reverts_the_flight_to_planned
        """
        env = issued_env
        api = env.api
        item = validate_success(
            api.void_cart_item(env.cart["id"], env.item["id"], LM_ALICE), 200
        )
        assert item["status"] == "VOID"
        assert_instant_equals(item["voided_at"], CLOCK_MANIFEST)

        cart = read_cart(api, env.cart["id"])
        assert_cart_axes(cart, "BUILDING", "BROKEN")
        assert cart["loaded_units"] == 0
        assert cart["seal_count"] == 1
        assert cart["seal_number"] == "SEAL-AN411-01"

        manifest = env.reload_manifest()
        assert manifest["status"] == "AMENDED"
        assert manifest["amendment_count"] == 1

        flight = read_flight(api, env.flight_id)
        assert flight["status"] == "PLANNED"
        assert_flight_ledger(flight, units_loaded=0, unit_balance=180)
        assert flight["cost_per_pax_cents"] == 0

    def test_a_recovery_run_delivering_bubbles_the_flight_up_to_departed(
        self, issued_env
    ):
        """A miss holds the flight at `LOADED`; only the recovery's delivery departs it.

        PRD §3.7: "This is the join point of the fork: the flight can only reach `DEPARTED` once the recovery run itself reaches `DELIVERED`."

        Design: Corner/state_machines/a_recovery_run_delivering_bubbles_the_missed_flight_up_to_departed
        """
        env = issued_env
        api = env.api
        run = reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])
        set_clock(api, "2026-09-15T07:25:00Z")
        run_event(api, run["id"], EVENT_DISPATCH)
        set_clock(api, "2026-09-15T07:35:00Z")
        missed = run_event(api, run["id"], "MISS", miss_reason="TRAFFIC")
        assert missed["status"] == "MISSED"
        assert missed["penalty_cents"] == 750000
        assert missed["lateness_minutes"] == 0
        assert missed["miss_reason"] == "TRAFFIC"
        assert read_flight(api, env.flight_id)["status"] == "LOADED"

        recovery = validate_success(
            api.create_recovery_run(
                run["id"],
                f.recovery_run_payload(
                    env.truck["id"],
                    env.stand["id"],
                    "2026-09-15T08:20:00Z",
                    "2026-09-15T08:50:00Z",
                ),
                LM_BOB,
            ),
            201,
        )
        assert recovery["status"] == "RESERVED"
        assert recovery["recovery_of_run_id"] == run["id"]
        assert recovery["loading_manifest_id"] == env.manifest["id"]
        assert (
            validate_success(api.get_delivery_run(run["id"], LM_BOB), 200)["status"]
            == "RECOVERED"
        )

        set_clock(api, "2026-09-15T08:15:00Z")
        run_event(api, recovery["id"], EVENT_DISPATCH)
        set_clock(api, "2026-09-15T08:45:00Z")
        run_event(api, recovery["id"], "ARRIVE")
        set_clock(api, "2026-09-15T08:50:00Z")
        delivered = run_event(api, recovery["id"], EVENT_DELIVER)
        assert delivered["status"] == "DELIVERED"
        assert_instant_equals(delivered["delivered_at_utc"], "2026-09-15T08:50:00Z")
        assert delivered["lateness_minutes"] == 0
        assert delivered["penalty_cents"] == 0

        assert read_flight(api, env.flight_id)["status"] == "DEPARTED"
        assert read_cart(api, env.cart["id"])["build_status"] == "LOADED"

        findings, meta = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)
        assert findings[0]["finding_type"] == "LATE_DELIVERY"
        assert findings[0]["severity"] == "MAJOR"
        assert findings[0]["penalty_cents"] == 200000
        assert findings[0]["source"] == "SYSTEM"

    def test_the_reslot_cascade_waits_for_the_cumulative_threshold(self, issued_env):
        """Sixty minutes moves only the instants; the next thirty shift the window by all ninety.

        PRD §3.8: "When it has, every run of the flight in `RESERVED` or `RESCHEDULED` has both `window_start_utc` and `window_end_utc` shifted forward by the cumulative `delay_minutes` — not by this request's increment — and its status set to `RESCHEDULED`."

        Design: Corner/state_machines/a_delay_below_the_reslot_threshold_leaves_the_runs_alone_and_at_it_reslots_them
        """
        env = issued_env
        api = env.api
        run = reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])

        first = validate_success(
            api.record_delay(
                env.flight_id, f.delay_payload(60, reason="ATC_SLOT"), FEED
            ),
            200,
        )
        assert first["delay_minutes"] == 60
        assert_instant_equals(first["revised_std_utc"], "2026-09-15T11:00:00Z")
        assert_instant_equals(
            first["special_meal_cutoff_utc"], "2026-09-14T23:00:00Z"
        )
        assert first["status"] == "LOADED"

        held = validate_success(api.get_delivery_run(run["id"], LM_BOB), 200)
        assert held["status"] == "RESERVED"
        assert_instant_equals(held["window_start_utc"], "2026-09-15T07:30:00Z")
        assert_instant_equals(held["window_end_utc"], "2026-09-15T08:00:00Z")
        manifest = env.reload_manifest()
        assert manifest["status"] == "ISSUED"
        assert manifest["amendment_count"] == 0

        second = validate_success(
            api.record_delay(
                env.flight_id, f.delay_payload(30, reason="ATC_SLOT"), FEED
            ),
            200,
        )
        assert second["delay_minutes"] == 90
        assert_instant_equals(second["revised_std_utc"], "2026-09-15T11:30:00Z")
        assert_instant_equals(
            second["special_meal_cutoff_utc"], "2026-09-14T23:30:00Z"
        )

        moved = validate_success(api.get_delivery_run(run["id"], LM_BOB), 200)
        assert moved["status"] == "RESCHEDULED"
        assert_instant_equals(moved["window_start_utc"], "2026-09-15T09:00:00Z")
        assert_instant_equals(moved["window_end_utc"], "2026-09-15T09:30:00Z")

        amended = env.reload_manifest()
        assert amended["status"] == "AMENDED"
        assert amended["amendment_count"] == 1
        assert read_flight(api, env.flight_id)["status"] == "PLANNED"

        batch = validate_success(
            api.get_production_batch(env.batch["id"], SUPERVISOR), 200
        )
        assert_instant_equals(
            batch["release_deadline_utc"], "2026-09-15T08:30:00Z"
        )

    def test_waste_manifest_transitions_refuse_out_of_order_actions(
        self, dispositioned_env
    ):
        """`DISPOSE` is legal only from `SEALED`, and the disposal closes the uplift record.

        PRD §3.9: "Disposing moves it `SEALED → DISPOSED` and drives the owning uplift record `DISPOSITIONED → CLOSED`."

        Design: Corner/state_machines/waste_manifest_transitions_refuse_out_of_order_actions_and_close_the_uplift_record
        """
        env = dispositioned_env
        api = env.api
        waste = raise_waste_manifest(api, env.uplift["id"], seal_number="WM-AN411-01")
        assert waste["status"] == "DRAFT"
        assert waste["regime"] == "BONDED"
        assert waste["sealed_weight_grams"] == 7000

        validate_error(
            api.transition_waste_manifest(
                waste["id"], f.waste_transition_payload(ACTION_DISPOSE), COMPLIANCE
            ),
            ApiErrorId.ERR_INVALID_RESOURCE_STATE.value,
            409,
        )
        assert (
            validate_success(api.get_waste_manifest(waste["id"], COMPLIANCE), 200)[
                "status"
            ]
            == "DRAFT"
        )
        assert env.reload_uplift()["status"] == "DISPOSITIONED"

        sealed = validate_success(
            api.transition_waste_manifest(
                waste["id"], f.waste_transition_payload(ACTION_SEAL), COMPLIANCE
            ),
            200,
        )
        assert sealed["status"] == "SEALED"

        disposed = validate_success(
            api.transition_waste_manifest(
                waste["id"], f.waste_transition_payload(ACTION_DISPOSE), COMPLIANCE
            ),
            200,
        )
        assert disposed["status"] == "DISPOSED"
        assert disposed["sealed_weight_grams"] == 7000
        assert env.reload_uplift()["status"] == "CLOSED"

        validate_error(
            api.transition_waste_manifest(
                waste["id"], f.waste_transition_payload(ACTION_SEAL), COMPLIANCE
            ),
            ApiErrorId.ERR_INVALID_RESOURCE_STATE.value,
            409,
        )

        cart = read_cart(api, env.cart["id"])
        assert_cart_axes(cart, "RETURNED", "BROKEN")
