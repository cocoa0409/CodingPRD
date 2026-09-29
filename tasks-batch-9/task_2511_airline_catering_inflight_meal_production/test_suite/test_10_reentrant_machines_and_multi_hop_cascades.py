"""Cycles and joins in the state machines, the two-axis cart, and the cascades that travel several hops."""

from test_helpers import (
    ACTION_ACCEPT,
    ACTION_DISPUTE,
    CLOCK_CART,
    CLOCK_COMPLETE,
    CLOCK_MANIFEST,
    CLOCK_PRODUCTION,
    CLOCK_QA,
    COMPLIANCE,
    EVENT_ARRIVE,
    EVENT_DELIVER,
    EVENT_DISPATCH,
    EVENT_MISS,
    LM_ALICE,
    LM_BOB,
    LM_CAROL,
    SEAL_PRIMARY,
    SEAL_SECONDARY,
    SUPERVISOR,
    ApiErrorId,
    add_flight,
    advance_to_issued,
    advance_to_locked,
    advance_to_planned,
    assert_decimal_equals,
    assert_instant_equals,
    assert_total_count,
    build_base,
    complete_batch,
    cut_plan,
    factories as f,
    finding_penalty_cents,
    get_success_data,
    ingest_flight,
    load_item,
    lock_counts,
    raise_finding,
    read_cart,
    read_flight,
    record_check,
    register_cart,
    reserve_run,
    resolve_finding,
    run_event,
    seal_cart,
    set_clock,
    sign_off_build,
    start_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

RECOVERY_WINDOW_START = "2026-09-15T09:10:00Z"
RECOVERY_WINDOW_END = "2026-09-15T09:15:00Z"
SECOND_WINDOW_START = "2026-09-15T08:20:00Z"
SECOND_WINDOW_END = "2026-09-15T08:50:00Z"


def _read_batch(api, batch_id):
    return validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)


class TestTheReworkLadder:
    """`POST /production-batches/{id}/start` as two different transitions."""

    def test_two_rework_rounds_still_finish_the_batch_and_still_bar_certification(
        self, planned_env
    ):
        """The exit gate is the loop counter, not the verdicts the loop ends on.

        PRD §3.5: "A restart is the same operation applied to a batch sitting in `HACCP_HOLD`, moving it `HACCP_HOLD → IN_PRODUCTION`; a restart requires only that the batch is in `HACCP_HOLD` and that the logical clock is strictly before `release_deadline_utc`, and it additionally increments `haccp_rework_rounds` by one and recomputes `haccp_risk_score`."

        PRD §3.5: "That score is the smaller of 100.00 and the quantity formed by weighting each failed check on the batch at 40.00 and each completed rework round at 15.00 and adding the two products together; the fail count includes every `FAIL` check on the batch regardless of `step_code` or `sequence_no`."

        PRD §3.5: "The four gate failures are reported in the fixed order set out in §2.6: a required step with no check at all yields `ERR_HACCP_STEP_MISSING`, a required step whose newest check failed yields `ERR_HACCP_HOLD_ACTIVE`, an exhausted rework allowance yields `ERR_HACCP_REWORK_LIMIT`, and a passed deadline yields `ERR_RELEASE_DEADLINE_PASSED`."

        Design: Difficulty/non_linear_state_machine/batch_cycles_twice_through_haccp_hold_and_is_then_barred_from_release
        """
        env = planned_env
        api = env.api
        batch_id = env.batch["id"]
        assert_instant_equals(
            env.batch["release_deadline_utc"], "2026-09-15T08:30:00Z"
        )

        set_clock(api, CLOCK_PRODUCTION)
        first_start = start_batch(api, batch_id)
        # The `PLANNED` entry through the same endpoint left the counter alone.
        assert first_start["production_status"] == "IN_PRODUCTION"
        assert first_start["haccp_rework_rounds"] == 0

        set_clock(api, CLOCK_QA)
        record_check(api, batch_id, "CHILL_DOWN")

        first_fail = record_check(api, batch_id, "HOLD_TEMP", 9.5)
        assert first_fail["verdict"] == "FAIL"
        held_once = _read_batch(api, batch_id)
        assert held_once["production_status"] == "HACCP_HOLD"
        assert_decimal_equals(held_once["haccp_risk_score"], "40.00")

        restarted_once = start_batch(api, batch_id)
        assert restarted_once["production_status"] == "IN_PRODUCTION"
        assert restarted_once["haccp_rework_rounds"] == 1
        # One failure and one completed round: 40.00 plus 15.00.
        assert_decimal_equals(restarted_once["haccp_risk_score"], "55.00")

        assert record_check(api, batch_id, "HOLD_TEMP", 9.0)["verdict"] == "FAIL"
        held_twice = _read_batch(api, batch_id)
        # Two failures is not more than two, so the batch was not condemned.
        assert held_twice["production_status"] == "HACCP_HOLD"
        assert_decimal_equals(held_twice["haccp_risk_score"], "95.00")

        restarted_twice = start_batch(api, batch_id)
        assert restarted_twice["production_status"] == "IN_PRODUCTION"
        assert restarted_twice["haccp_rework_rounds"] == 2
        # The raw arithmetic reaches 110.00 and is clamped.
        assert_decimal_equals(restarted_twice["haccp_risk_score"], "100.00")

        final_check = record_check(api, batch_id, "HOLD_TEMP", 4.0)
        assert final_check["verdict"] == "PASS"
        # Three readings at this one step, counted per batch-and-step pair.
        assert final_check["sequence_no"] == 3

        set_clock(api, CLOCK_COMPLETE)
        completed = complete_batch(api, batch_id, 180)
        assert completed["production_status"] == "COMPLETED"
        assert completed["produced_qty"] == 180
        assert completed["scrapped_qty"] == 0

        validate_error(
            api.release_batch(batch_id, {}, SUPERVISOR),
            ApiErrorId.ERR_HACCP_REWORK_LIMIT.value,
            422,
        )
        barred = _read_batch(api, batch_id)
        assert barred["production_status"] == "COMPLETED"
        assert barred["released_at"] is None
        assert barred["released_by_user_id"] is None

    def test_one_rework_round_leaves_the_allowance_intact_and_certification_succeeds(
        self, planned_env
    ):
        """The identical ladder stopped one loop earlier releases, so the gate is the count.

        PRD §3.5: "It applies only to a batch in `COMPLETED`, moving it `COMPLETED → RELEASED`, and it requires that for every step named in the specification's `required_haccp_steps` the check with the highest `sequence_no` for that batch-and-step pair exists and carries verdict `PASS`, that `haccp_rework_rounds` is strictly below two, and that the logical clock is at or before `release_deadline_utc`."

        PRD §3.5: "A restart out of `HACCP_HOLD` is *always* permitted while the deadline holds — the rework allowance is deliberately enforced later, at release, so a twice-reworked batch can still be finished and inspected but can never be certified."

        Design: Difficulty/non_linear_state_machine/batch_cycles_twice_through_haccp_hold_and_is_then_barred_from_release
        """
        env = planned_env
        api = env.api
        batch_id = env.batch["id"]

        set_clock(api, CLOCK_PRODUCTION)
        start_batch(api, batch_id)
        set_clock(api, CLOCK_QA)
        record_check(api, batch_id, "CHILL_DOWN")
        assert record_check(api, batch_id, "HOLD_TEMP", 9.5)["verdict"] == "FAIL"
        assert _read_batch(api, batch_id)["production_status"] == "HACCP_HOLD"

        restarted = start_batch(api, batch_id)
        assert restarted["haccp_rework_rounds"] == 1
        passing = record_check(api, batch_id, "HOLD_TEMP", 4.0)
        assert passing["verdict"] == "PASS"
        assert passing["sequence_no"] == 2
        # A `PASS` never moves the batch off `IN_PRODUCTION`.
        assert _read_batch(api, batch_id)["production_status"] == "IN_PRODUCTION"

        set_clock(api, CLOCK_COMPLETE)
        complete_batch(api, batch_id, 180)
        released = validate_success(api.release_batch(batch_id, {}, SUPERVISOR), 200)
        assert released["production_status"] == "RELEASED"
        assert released["haccp_rework_rounds"] == 1
        assert_decimal_equals(released["haccp_risk_score"], "55.00")
        assert_instant_equals(released["released_at"], CLOCK_COMPLETE)
        assert released["released_by_user_id"] == "ps_alice"


class TestTheCartsTwoAxes:
    """Four writes, two axes, and neither axis dragging the other along."""

    def test_the_build_axis_advances_twice_and_the_seal_axis_twice_with_no_crosstalk(
        self, released_env
    ):
        """Each write moves exactly one axis, and `seal_count` climbs 0, 1, 2.

        PRD §3.6: "The build axis runs `EMPTY`, `BUILDING`, `BUILT`, `LOADED` and `RETURNED`, with `RETURNED` terminal; the seal axis runs `UNSEALED`, `SEALED`, `BROKEN` and `RESEALED` and has no terminal state at all."

        PRD §3.6: "Signing off a build is a small, deliberately narrow operation: it moves the cart `BUILDING → BUILT` and touches nothing on the seal axis."

        PRD §3.6: "Both of those latter forms replace `seal_number`, replace `sealed_by_user_id` with the acting operator, and increment `seal_count` by one, so a `seal_count` of two or more is the durable evidence that the cart was resealed."

        Design: Difficulty/non_linear_state_machine/cart_build_axis_and_seal_axis_advance_without_touching_each_other
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        fresh = register_cart(api, env.flight_id)
        assert fresh["build_status"] == "EMPTY"
        assert fresh["seal_status"] == "UNSEALED"
        assert fresh["seal_count"] == 0

        load_item(api, fresh["id"], env.batch["id"], 180)
        loaded = read_cart(api, fresh["id"])
        assert loaded["build_status"] == "BUILDING"
        # The build axis moved and the seal axis did not.
        assert loaded["seal_status"] == "UNSEALED"

        built = sign_off_build(api, fresh["id"])
        assert built["build_status"] == "BUILT"
        # Two consecutive build-axis writes, seal axis still untouched.
        assert built["seal_status"] == "UNSEALED"
        assert built["seal_count"] == 0

        sealed = seal_cart(api, fresh["id"], SEAL_PRIMARY, headers=LM_ALICE)
        assert sealed["seal_status"] == "SEALED"
        assert sealed["seal_count"] == 1
        # The seal axis moved and the build axis did not.
        assert sealed["build_status"] == "BUILT"
        assert sealed["sealed_by_user_id"] == "lm_alice"

        resealed = seal_cart(api, fresh["id"], SEAL_SECONDARY, headers=LM_CAROL)
        assert resealed["seal_status"] == "RESEALED"
        assert resealed["seal_count"] == 2
        assert resealed["build_status"] == "BUILT"
        assert resealed["seal_number"] == SEAL_SECONDARY
        assert resealed["sealed_by_user_id"] == "lm_carol"

        assert resealed["loaded_units"] == 180
        flight = read_flight(api, env.flight_id)
        assert flight["units_loaded"] == 180
        # No manifest was ever issued, so no seal-axis write could move the flight.
        assert flight["status"] == "PLANNED"

    def test_the_seal_axis_survives_a_broken_seal_while_the_build_axis_rebuilds(
        self, released_env
    ):
        """`BROKEN` is not terminal, and the rebuild happens with the seal axis parked.

        PRD §3.6: "A first seal moves the cart `UNSEALED → SEALED` and sets `seal_count` to 1; a seal fitted over an existing one moves `SEALED → RESEALED`, and a seal fitted after a break moves `BROKEN → RESEALED`."

        PRD §3.6: "Sealing is the mirror-image operation: it moves the seal axis and leaves `build_status` exactly as it was."

        Design: Difficulty/non_linear_state_machine/cart_build_axis_and_seal_axis_advance_without_touching_each_other
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id)
        first_item = load_item(api, cart["id"], env.batch["id"], 180)
        sign_off_build(api, cart["id"])
        seal_cart(api, cart["id"], SEAL_PRIMARY, headers=LM_ALICE)

        validate_success(
            api.void_cart_item(cart["id"], first_item["id"], LM_ALICE), 200
        )
        broken = read_cart(api, cart["id"])
        assert broken["build_status"] == "BUILDING"
        assert broken["seal_status"] == "BROKEN"
        assert broken["seal_count"] == 1
        assert broken["loaded_units"] == 0

        # A seal write is gated on the build axis, so this one is premature.
        validate_error(
            api.seal_cart(
                cart["id"], f.seal_payload(broken["version"], SEAL_SECONDARY), LM_ALICE
            ),
            ApiErrorId.ERR_INVALID_CART_STATE.value,
            409,
        )
        assert read_cart(api, cart["id"])["seal_status"] == "BROKEN"

        load_item(api, cart["id"], env.batch["id"], 180)
        reloaded = read_cart(api, cart["id"])
        assert reloaded["build_status"] == "BUILDING"
        # Two more build-axis writes with the seal axis parked on `BROKEN`.
        assert reloaded["seal_status"] == "BROKEN"
        rebuilt = sign_off_build(api, cart["id"])
        assert rebuilt["build_status"] == "BUILT"
        assert rebuilt["seal_status"] == "BROKEN"

        resealed = seal_cart(api, cart["id"], SEAL_SECONDARY, headers=LM_CAROL)
        assert resealed["seal_status"] == "RESEALED"
        assert resealed["seal_count"] == 2
        assert resealed["build_status"] == "BUILT"
        assert resealed["loaded_units"] == 180


class TestTheDepartureJoin:
    """`LOADED → DEPARTED` as a join over every run of the issued manifest."""

    def test_the_first_delivery_does_not_depart_the_flight_while_a_sibling_run_waits(
        self, sealed_env
    ):
        """Two runs on one manifest, and only the second one closes the join.

        PRD §3.7: "And when every delivery run belonging to the flight's `ISSUED` manifest has reached `DELIVERED`, `RECOVERED` or `CANCELLED`, with at least one of them in `DELIVERED`, the flight moves `LOADED → DEPARTED`, which in the same cascade drives every cart of the flight still in `BUILT` along the build axis `BUILT → LOADED`, incrementing each cart's `version`."

        Design: Difficulty/non_linear_state_machine/flight_departs_only_after_every_run_of_the_issued_manifest_is_terminal
        """
        env = sealed_env
        api = env.api
        advance_to_issued(env)
        assert read_flight(api, env.flight_id)["status"] == "LOADED"

        first = reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])
        # 08:20 is not before 08:00 advanced by the truck's twenty-minute buffer.
        second = reserve_run(
            api,
            env.manifest["id"],
            env.truck["id"],
            env.stand["id"],
            window_start_utc=SECOND_WINDOW_START,
            window_end_utc=SECOND_WINDOW_END,
        )
        assert second["status"] == "RESERVED"

        set_clock(api, "2026-09-15T07:25:00Z")
        run_event(api, first["id"], EVENT_DISPATCH)
        set_clock(api, "2026-09-15T07:50:00Z")
        run_event(api, first["id"], EVENT_ARRIVE)
        set_clock(api, "2026-09-15T07:55:00Z")
        delivered = run_event(api, first["id"], EVENT_DELIVER)
        assert delivered["status"] == "DELIVERED"
        assert delivered["lateness_minutes"] == 0
        assert delivered["penalty_cents"] == 0

        # The sibling run is still `RESERVED`, so the join has not closed.
        assert read_flight(api, env.flight_id)["status"] == "LOADED"
        assert read_cart(api, env.cart["id"])["build_status"] == "BUILT"

        set_clock(api, "2026-09-15T08:15:00Z")
        run_event(api, second["id"], EVENT_DISPATCH)
        set_clock(api, "2026-09-15T08:30:00Z")
        run_event(api, second["id"], EVENT_ARRIVE)
        set_clock(api, "2026-09-15T08:45:00Z")
        second_delivered = run_event(api, second["id"], EVENT_DELIVER)
        assert second_delivered["status"] == "DELIVERED"
        assert second_delivered["lateness_minutes"] == 0
        assert second_delivered["penalty_cents"] == 0

        assert read_flight(api, env.flight_id)["status"] == "DEPARTED"
        cart = read_cart(api, env.cart["id"])
        assert cart["build_status"] == "LOADED"
        assert cart["seal_status"] == "SEALED"
        assert cart["seal_number"] == SEAL_PRIMARY

        manifest = validate_success(
            api.get_loading_manifest(env.manifest["id"], LM_BOB), 200
        )
        assert manifest["status"] == "ISSUED"
        assert manifest["amendment_count"] == 0
        assert manifest["total_units"] == 180
        assert env.reload_airline()["open_finding_count"] == 0

    def test_a_missed_run_holds_the_join_open_until_its_recovery_delivers(
        self, sealed_env
    ):
        """`MISSED` is not one of the three terminal states, so a delivered sibling is not enough.

        PRD §3.7: "**Missing** the slot moves the run `EN_ROUTE → MISSED` (and identically `AT_AIRCRAFT → MISSED`), requires a `miss_reason` to be supplied and to be something other than `SLOT_LOST` — the permitted reasons are `SLOT_LOST`, `AIRCRAFT_NOT_READY`, `TRAFFIC` and `EQUIPMENT_FAILURE`, and `SLOT_LOST` is reserved for the delay cascade's own use — sets `penalty_cents` to a flat 750,000 cents, leaves `lateness_minutes` at 0 with no banding applied at all, raises a `LATE_DELIVERY` finding of `MAJOR` severity with `source` `SYSTEM` incrementing the airline's `open_finding_count`, and pointedly does **not** advance the flight, which stays `LOADED` until a recovery run delivers."

        PRD §3.7: "The missed run moves `MISSED → RECOVERED` with its `version` incremented, and a new run is created in `RESERVED` carrying `recovery_of_run_id` set to the recovered run and the same `loading_manifest_id`."

        Design: Difficulty/non_linear_state_machine/flight_departs_only_after_every_run_of_the_issued_manifest_is_terminal
        """
        env = sealed_env
        api = env.api
        advance_to_issued(env)
        manifest_id = env.manifest["id"]
        first = reserve_run(api, manifest_id, env.truck["id"], env.stand["id"])
        second = reserve_run(
            api,
            manifest_id,
            env.truck["id"],
            env.stand["id"],
            window_start_utc=SECOND_WINDOW_START,
            window_end_utc=SECOND_WINDOW_END,
        )

        set_clock(api, "2026-09-15T07:25:00Z")
        run_event(api, first["id"], EVENT_DISPATCH)
        set_clock(api, "2026-09-15T07:40:00Z")
        run_event(api, first["id"], EVENT_ARRIVE)
        set_clock(api, "2026-09-15T07:45:00Z")
        missed = run_event(api, first["id"], EVENT_MISS, miss_reason="TRAFFIC")
        assert missed["status"] == "MISSED"
        assert missed["penalty_cents"] == 750000
        assert missed["lateness_minutes"] == 0

        set_clock(api, "2026-09-15T08:15:00Z")
        run_event(api, second["id"], EVENT_DISPATCH)
        set_clock(api, "2026-09-15T08:30:00Z")
        run_event(api, second["id"], EVENT_ARRIVE)
        set_clock(api, "2026-09-15T08:45:00Z")
        assert run_event(api, second["id"], EVENT_DELIVER)["status"] == "DELIVERED"

        # One run is `MISSED`, which is neither `DELIVERED`, `RECOVERED` nor `CANCELLED`.
        assert read_flight(api, env.flight_id)["status"] == "LOADED"
        assert read_cart(api, env.cart["id"])["build_status"] == "BUILT"

        set_clock(api, "2026-09-15T08:50:00Z")
        recovery = get_success_data(
            api.create_recovery_run(
                first["id"],
                f.recovery_run_payload(
                    env.truck["id"],
                    env.stand["id"],
                    RECOVERY_WINDOW_START,
                    RECOVERY_WINDOW_END,
                ),
                LM_BOB,
            )
        )
        assert recovery["status"] == "RESERVED"
        assert recovery["recovery_of_run_id"] == first["id"]
        assert recovery["loading_manifest_id"] == manifest_id
        assert (
            validate_success(api.get_delivery_run(first["id"], LM_BOB), 200)["status"]
            == "RECOVERED"
        )
        # A recovered run is terminal, but no run has yet closed the join.
        assert read_flight(api, env.flight_id)["status"] == "LOADED"

        set_clock(api, RECOVERY_WINDOW_START)
        run_event(api, recovery["id"], EVENT_DISPATCH)
        set_clock(api, "2026-09-15T09:12:00Z")
        run_event(api, recovery["id"], EVENT_ARRIVE)
        set_clock(api, "2026-09-15T09:14:00Z")
        recovered_delivery = run_event(api, recovery["id"], EVENT_DELIVER)
        assert recovered_delivery["status"] == "DELIVERED"
        assert recovered_delivery["lateness_minutes"] == 0

        assert read_flight(api, env.flight_id)["status"] == "DEPARTED"
        assert read_cart(api, env.cart["id"])["build_status"] == "LOADED"
        findings, meta = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)
        assert findings[0]["finding_type"] == "LATE_DELIVERY"
        assert findings[0]["severity"] == "MAJOR"
        assert findings[0]["penalty_cents"] == 200000


class TestThePostReleaseCondemnation:
    """One `QaOfficer` call travelling batch to cart to manifest to flight."""

    def test_one_failed_re_inspection_walks_all_four_hops_in_order(self, issued_env):
        """Nothing is left half-settled: no `ISSUED` manifest pins a broken cart.

        PRD §3.5: "Here neither the failure count nor `haccp_rework_rounds` is consulted, because certified food that fails re-inspection is condemned on its first failure, and the batch moves `RELEASED → REJECTED` through a four-hop cascade."

        PRD §3.5: "The second hop voids every `ACTIVE` cart item drawn from that batch, which drives each affected cart from `BUILT` back to `BUILDING` on its build axis and from `SEALED` or `RESEALED` to `BROKEN` on its seal axis."

        PRD §3.5: "The third hop takes each cart whose `seal_number` is pinned in an `ISSUED` manifest's snapshot and drives that manifest `ISSUED → AMENDED`, incrementing its `amendment_count`."

        Design: Difficulty/transitive_cascade/post_release_haccp_fail_cascades_batch_to_cart_to_manifest_to_flight
        """
        env = issued_env
        api = env.api
        batch_id = env.batch["id"]
        assert _read_batch(api, batch_id)["production_status"] == "RELEASED"

        condemning = record_check(api, batch_id, "HOLD_TEMP", 9.5)
        assert condemning["verdict"] == "FAIL"
        # The second HOLD_TEMP reading on this batch.
        assert condemning["sequence_no"] == 2

        rejected = _read_batch(api, batch_id)
        assert rejected["production_status"] == "REJECTED"
        assert rejected["scrapped_qty"] == 180
        assert_decimal_equals(rejected["haccp_risk_score"], "40.00")

        item = validate_success(api.get_cart_item(env.item["id"], LM_ALICE), 200)
        assert item["status"] == "VOID"
        cart = read_cart(api, env.cart["id"])
        assert cart["build_status"] == "BUILDING"
        assert cart["seal_status"] == "BROKEN"
        assert cart["loaded_units"] == 0
        assert cart["seal_number"] == SEAL_PRIMARY
        assert cart["sealed_by_user_id"] is None

        manifest = validate_success(
            api.get_loading_manifest(env.manifest["id"], LM_BOB), 200
        )
        assert manifest["status"] == "AMENDED"
        assert manifest["amendment_count"] == 1

        flight = read_flight(api, env.flight_id)
        assert flight["status"] == "PLANNED"
        assert flight["units_loaded"] == 0
        assert flight["units_scrapped"] == 180
        # A rejected batch's produced units stop counting.
        assert flight["units_produced"] == 0

        findings, meta = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)
        breach = findings[0]
        assert breach["finding_type"] == "HACCP_BREACH"
        assert breach["severity"] == "CRITICAL"
        assert breach["source"] == "SYSTEM"
        assert breach["status"] == "OPEN"
        assert breach["penalty_cents"] == 2500000 == finding_penalty_cents(
            "HACCP_BREACH", "CRITICAL"
        )
        airline = env.reload_airline()
        assert airline["open_finding_count"] == 1
        assert airline["penalty_accrued_cents"] == 0
        assert airline["status"] == "ACTIVE"

    def test_the_cascade_reaches_only_as_far_as_the_state_it_finds(self, released_env):
        """An unsealed, unmanifested cart takes hops one and two and stops there.

        PRD §3.5: "The severe branch is a failure recorded against a batch that is already `RELEASED` — a post-release re-inspection of certified food."

        PRD §3.5: "The fourth hop drives each amended manifest's flight `LOADED → PLANNED`."

        Design: Difficulty/transitive_cascade/post_release_haccp_fail_cascades_batch_to_cart_to_manifest_to_flight
        """
        env = released_env
        api = env.api
        set_clock(api, CLOCK_CART)
        cart = register_cart(api, env.flight_id)
        item = load_item(api, cart["id"], env.batch["id"], 180)
        sign_off_build(api, cart["id"])
        assert read_cart(api, cart["id"])["build_status"] == "BUILT"

        set_clock(api, CLOCK_MANIFEST)
        assert record_check(api, env.batch["id"], "HOLD_TEMP", 9.5)["verdict"] == "FAIL"

        # Hop one, on a batch with no prior failure and no rework round at all.
        rejected = _read_batch(api, env.batch["id"])
        assert rejected["production_status"] == "REJECTED"
        assert rejected["haccp_rework_rounds"] == 0
        assert rejected["scrapped_qty"] == 180

        # Hop two, with the seal axis untouched because it was never sealed.
        assert (
            validate_success(api.get_cart_item(item["id"], LM_ALICE), 200)["status"]
            == "VOID"
        )
        broken = read_cart(api, cart["id"])
        assert broken["build_status"] == "BUILDING"
        assert broken["seal_status"] == "UNSEALED"
        assert broken["seal_number"] is None
        assert broken["loaded_units"] == 0

        # Hops three and four had no `ISSUED` manifest to travel through.
        _, meta = validate_paginated(
            api.list_loading_manifests(LM_BOB, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 0)
        flight = read_flight(api, env.flight_id)
        assert flight["status"] == "PLANNED"
        assert flight["units_loaded"] == 0
        assert flight["units_scrapped"] == 180
        assert flight["cost_per_pax_cents"] == 0
        assert env.reload_airline()["open_finding_count"] == 1


class TestTheSuspensionCascade:
    """The docket's lever over the kitchen, pulled and then released."""

    def test_the_third_finding_holds_every_open_flight_and_one_dispute_frees_them(
        self, api
    ):
        """The hold is written during the airline transition and read at planning time.

        PRD §3.10: "When a finding creation pushes an airline's `open_finding_count` to three or more, the airline moves `ACTIVE → SUSPENDED`, its own `version` increments, and every flight of that airline whose `status` is `SCHEDULED` or `COUNTS_LOCKED` has `production_hold` set to true with that flight's `version` incremented."

        PRD §3.10: "A held flight can still take passenger-count refreshes, retimes and special meal orders, but production planning against it is refused with `ERR_AIRLINE_SUSPENDED`."

        PRD §3.10: "When a resolution drops `open_finding_count` back below three, the airline moves `SUSPENDED → ACTIVE`, its `version` increments, and every flight of that airline carrying a `production_hold` has it cleared to false with that flight's `version` incremented — releasing the kitchen to plan again."

        Design: Difficulty/transitive_cascade/third_open_finding_suspends_the_airline_and_blocks_then_unblocks_planning
        """
        env = build_base(
            api,
            name="Sunbridge Airways",
            iata_code="SB",
            waste_regime="DOMESTIC",
            cost_cap_per_pax_cents=6000,
        )
        first_flight = ingest_flight(
            api,
            env.airline_id,
            flight_number="SB901",
            service_date="2026-09-20",
            std_utc="2026-09-20T10:00:00Z",
            tail_number="SE-CCC",
            pax_economy=100,
        )
        second_flight = ingest_flight(
            api,
            env.airline_id,
            flight_number="SB902",
            service_date="2026-09-20",
            std_utc="2026-09-20T10:00:00Z",
            tail_number="SE-DDD",
            pax_economy=50,
        )
        one = raise_finding(
            api,
            env.airline_id,
            first_flight["id"],
            "SPEC_DEVIATION",
            "MINOR",
            evidence_ref="AUD-1",
        )
        two = raise_finding(
            api,
            env.airline_id,
            second_flight["id"],
            "SPEC_DEVIATION",
            "MINOR",
            evidence_ref="AUD-2",
        )
        below = env.reload_airline()
        assert below["open_finding_count"] == 2
        assert below["status"] == "ACTIVE"

        three = raise_finding(
            api,
            env.airline_id,
            first_flight["id"],
            "LATE_DELIVERY",
            "MAJOR",
            evidence_ref="AUD-3",
        )
        assert three["penalty_cents"] == 200000 == finding_penalty_cents(
            "LATE_DELIVERY", "MAJOR"
        )
        suspended = env.reload_airline()
        assert suspended["open_finding_count"] == 3
        assert suspended["status"] == "SUSPENDED"
        assert suspended["penalty_accrued_cents"] == 0

        # A held flight still takes the count lock.
        lock_counts(api, first_flight["id"])
        assert read_flight(api, first_flight["id"])["production_hold"] is True
        assert read_flight(api, second_flight["id"])["production_hold"] is True

        validate_error(
            api.cut_production_plan(first_flight["id"], {}, SUPERVISOR),
            ApiErrorId.ERR_AIRLINE_SUSPENDED.value,
            422,
        )
        blocked = read_flight(api, first_flight["id"])
        assert blocked["status"] == "COUNTS_LOCKED"
        assert blocked["units_planned"] == 0

        disputed = resolve_finding(
            api, one["id"], ACTION_DISPUTE, note="specification supplied late"
        )
        assert disputed["status"] == "DISPUTED"
        freed = env.reload_airline()
        assert freed["open_finding_count"] == 2
        assert freed["status"] == "ACTIVE"
        assert read_flight(api, first_flight["id"])["production_hold"] is False
        assert read_flight(api, second_flight["id"])["production_hold"] is False

        batches = cut_plan(api, first_flight["id"])
        assert len(batches) == 1
        assert batches[0]["planned_qty"] == 100
        assert batches[0]["store_zone"] == "CHILL"
        assert batches[0]["is_overflow"] is False
        planned = read_flight(api, first_flight["id"])
        assert planned["status"] == "PLANNED"
        assert planned["units_planned"] == 100

        assert (
            validate_success(api.get_audit_finding(two["id"], COMPLIANCE), 200)[
                "status"
            ]
            == "OPEN"
        )
        assert (
            validate_success(api.get_audit_finding(three["id"], COMPLIANCE), 200)[
                "status"
            ]
            == "OPEN"
        )

    def test_a_flight_already_planned_is_never_held_and_an_acceptance_also_frees_the_rest(
        self, base_env
    ):
        """The hold is written only onto the two pre-production states, and it accrues on accept.

        PRD §3.10: "**Accepting** is also the `ComplianceOfficer`'s and applies to a finding in `OPEN` or in `DISPUTED`, moving it `OPEN → ACCEPTED` or `DISPUTED → ACCEPTED`, adding the finding's `penalty_cents` to the airline's `penalty_accrued_cents`, and decrementing `open_finding_count` by one only when the prior status was `OPEN` — an accepted dispute has already been decremented and is not decremented twice — which again may drive the airline `SUSPENDED → ACTIVE`."

        Design: Difficulty/transitive_cascade/third_open_finding_suspends_the_airline_and_blocks_then_unblocks_planning
        """
        env = base_env
        api = env.api
        add_flight(env)
        advance_to_locked(env)
        advance_to_planned(env)
        assert env.flight["status"] == "PLANNED"

        waiting = ingest_flight(
            api,
            env.airline_id,
            flight_number="AN419",
            std_utc="2026-09-15T16:00:00Z",
            tail_number="LN-KKK",
            pax_economy=40,
        )
        assert waiting["status"] == "SCHEDULED"
        assert waiting["production_hold"] is False

        for ordinal in (1, 2):
            raise_finding(
                env.api,
                env.airline_id,
                env.flight_id,
                "SEAL_MISMATCH",
                "MINOR",
                evidence_ref=f"AUD-{ordinal}",
            )
        third = raise_finding(
            api, env.airline_id, env.flight_id, "SPEC_DEVIATION", "MAJOR"
        )
        assert third["penalty_cents"] == 300000 == finding_penalty_cents(
            "SPEC_DEVIATION", "MAJOR"
        )
        suspended = env.reload_airline()
        assert suspended["status"] == "SUSPENDED"
        assert suspended["open_finding_count"] == 3

        # The already-planned flight is in neither held state.
        assert env.reload_flight()["production_hold"] is False
        assert read_flight(api, waiting["id"])["production_hold"] is True

        accepted = resolve_finding(api, third["id"], ACTION_ACCEPT, note="conceded")
        assert accepted["status"] == "ACCEPTED"
        restored = env.reload_airline()
        assert restored["status"] == "ACTIVE"
        assert restored["open_finding_count"] == 2
        assert restored["penalty_accrued_cents"] == 300000
        assert read_flight(api, waiting["id"])["production_hold"] is False

        lock_counts(api, waiting["id"])
        released_plan = cut_plan(api, waiting["id"])
        assert len(released_plan) == 1
        assert released_plan[0]["planned_qty"] == 40
        assert read_flight(api, waiting["id"])["status"] == "PLANNED"
