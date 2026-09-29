"""Declared transitions, initial states, terminal lockdown and preconditions.

Each check drives one entity to a state and then asks it for a transition that
either is or is not declared from there.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.api_errors import (
    ERR_INVALID_INCIDENT_STATE,
    ERR_INVALID_PROFILE_STATE,
    ERR_INVALID_SLOT_STATE,
    ERR_INVALID_TIMER_STATE,
    ERR_LOOP_NOT_MERGEABLE,
    ERR_POSTURE_FROZEN,
    ERR_PULL_FORWARD_ESCALATION_LIMIT,
)
from test_helpers.test_users import ADMIN_HEADERS, AUDITOR_HEADERS


FREEZE_REASON = "POS system outage"
WAIVER_REASON = "Guest kept the drink they were given, so no remake was needed"


class TestDaypartProfileActivation:
    """DRAFT to ACTIVE once, and only once."""

    def test_activating_the_draft_profile_changes_state_and_nothing_else(
        self, api: DriveThruApiClient
    ):
        """PRD §3.1: "Activation moves a profile `DRAFT → ACTIVE` and is the point at
        which minute-of-day geometry is enforced."
        And: "Activation recomputes `total_target_seconds` and makes the profile
        usable for timer-loop creation."

        Design: Corner/state_machines/sm_daypart_profile_draft_to_active_valid_transition
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-14",
            with_staff=False,
            with_active_lunch_profile=False,
            name="Corner Activation Store",
        )
        profile = fx.create_daypart_profile(api, ctx.restaurant_id)

        activated = validate_success(
            api.activate_daypart_profile(profile["id"], ctx.operator_headers)
        )

        assert activated["profile_state"] == "ACTIVE", activated
        assert activated["total_target_seconds"] == 235, activated
        assert activated["greet_target_seconds"] == 25, activated
        assert activated["order_target_seconds"] == 95, activated
        assert activated["pull_forward_target_seconds"] == 40, activated
        assert activated["window_target_seconds"] == 75, activated

        _rows, meta = validate_paginated(
            api.list_daypart_profiles(
                ADMIN_HEADERS,
                {"restaurant_id": ctx.restaurant_id, "profile_state": "ACTIVE"},
            )
        )
        assert meta["total_count"] == 1, meta

    def test_replaying_activate_on_an_active_profile_is_refused(
        self, api: DriveThruApiClient
    ):
        """PRD §3.1: "Activation requires the profile to be in `DRAFT` and the store
        not to be frozen, and it requires that the profile's half-open minute window
        from `start_minute` up to but excluding `end_minute` does not overlap the
        window of any other profile of the same store whose `profile_state` is
        `ACTIVE`."

        Design: Corner/state_machines/sm_daypart_profile_activate_twice_second_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-15",
            with_staff=False,
            name="Corner Replay Store",
        )
        version_after_first = ctx.profile["version"]

        validate_error(
            api.activate_daypart_profile(ctx.profile_id, ctx.operator_headers),
            ERR_INVALID_PROFILE_STATE,
        )

        stored = validate_success(
            api.get_daypart_profile(ctx.profile_id, ADMIN_HEADERS)
        )
        assert stored["profile_state"] == "ACTIVE", stored
        # A rejected replay is not a mutation.
        assert stored["version"] == version_after_first, stored


class TestTimerLoopInitialState:
    """Both dimensions start where the contract says they start."""

    def test_a_new_loop_starts_open_and_pending_with_nothing_measured(
        self, api: DriveThruApiClient
    ):
        """PRD §3.3: "A new loop begins at `timing_state` `OPEN` and `accuracy_state`
        `PENDING`, with `served_after_loop_id` null."
        And: "A segment whose endpoint has not been stamped yet contributes neither a
        duration nor a flag, so flags accumulate as the loop progresses: `GREET` at
        greet, `ORDER` at order completion, `PULL_FORWARD` at window arrival and
        `WINDOW` at departure."
        And: "While `total_seconds` is null, `adjusted_total_seconds` is null too."

        Design: Corner/state_machines/sm_timer_loop_initial_states_open_and_pending
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-16",
            staff_name="Corner Mateo",
            name="Corner Initial State Store",
        )
        fx.set_clock(api, fx.at(11, 0, 0))

        loop = validate_success(
            api.create_timer_loop(
                f.timer_loop_body(ctx.restaurant_id, ctx.profile_id, "SINGLE"),
                ctx.leader_headers,
            ),
            expected_status=201,
        )

        a.assert_loop_states(loop, timing_state="OPEN", accuracy_state="PENDING")
        assert loop["car_sequence"] == 1, loop
        assert loop["arrive_at"] == fx.at(11, 0, 0), loop
        a.assert_all_null(
            loop,
            [
                "greet_at",
                "order_complete_at",
                "merge_at",
                "window_arrive_at",
                "depart_at",
                "greet_seconds",
                "order_seconds",
                "pull_forward_seconds",
                "window_seconds",
                "total_seconds",
                "adjusted_total_seconds",
                "merge_wait_seconds",
                "order_items_count",
                "served_after_loop_id",
            ],
        )
        a.assert_breach_flags(loop, [])
        assert loop["target_total_seconds_pinned"] == 235, loop


class TestTimerLoopInvalidTransition:
    """Greet is declared from OPEN only."""

    def test_greeting_a_car_that_has_already_ordered_is_refused(
        self, api: DriveThruApiClient
    ):
        """PRD §3.3: "Greeting a car moves it `OPEN → GREETED`, stamping `greet_at`
        and computing `greet_seconds` as `greet_at` minus `arrive_at` in whole
        seconds."
        PRD §2.11: "**Declared transition** — the target resource is in a state from
        which the requested transition is declared."

        Design: Corner/state_machines/sm_timer_loop_greet_from_ordered_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-17",
            staff_name="Corner Priya",
            name="Corner Greet Replay Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )

        validate_error(
            api.greet_timer_loop(loop["id"], ctx.leader_headers),
            ERR_INVALID_TIMER_STATE,
        )

        stored = validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS))
        a.assert_loop_states(stored, timing_state="ORDERED")
        # The refused greet did not re-stamp the clock.
        assert stored["greet_at"] == fx.at(11, 0, 20), stored
        a.assert_loop_segments(stored, greet_seconds=20, order_seconds=40)
        a.assert_breach_flags(stored, [])


class TestTimerLoopTerminalLockdown:
    """CLOSED is terminal, and a refused second departure counts no second car."""

    def test_a_second_departure_neither_re_measures_nor_double_counts(
        self, api: DriveThruApiClient
    ):
        """PRD §3.3: "`timing_state` tracks where the car physically is: `OPEN`,
        `GREETED`, `ORDERED`, `MERGED`, `AT_WINDOW`, `CLOSED` or `ABANDONED`, with
        `CLOSED` and `ABANDONED` terminal."
        PRD §2.4: "`cars_closed_trailing` is the number of the store's own timer loops
        whose `timing_state` is `CLOSED` and whose `depart_at` is strictly later than
        the instant ten minutes (600 seconds) before the current clock reading and no
        later than the current clock reading."

        Design: Corner/state_machines/sm_timer_loop_depart_twice_terminal_rejected
        """
        fx.setup_four_tier_bands(api)
        ctx = fx.setup_store(
            api,
            "C-2398-18",
            staff_name="Corner Tomas",
            name="Corner Terminal Store",
        )
        departed = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=fx.at(11, 2, 0),
            depart_at=fx.at(11, 4, 10),
            order_items_count=3,
        )
        assert departed["total_seconds"] == 250, departed

        fx.set_clock(api, fx.at(11, 4, 30))
        validate_error(
            api.depart_timer_loop(departed["id"], ctx.leader_headers),
            ERR_INVALID_TIMER_STATE,
        )

        stored = validate_success(api.get_timer_loop(departed["id"], ADMIN_HEADERS))
        assert stored["depart_at"] == fx.at(11, 4, 10), stored
        a.assert_loop_segments(stored, total_seconds=250)

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_closed_trailing=1,
            cars_per_hour_effective=6.0,
            volume_tier="TIER_2",
            required_oot_count=1,
            service_posture="SURGE",
        )


class TestAccuracyIncidentTerminalLockdown:
    """WAIVED is terminal, so the reversal cannot be flipped into a charge."""

    def test_closing_a_waived_incident_is_refused_and_leaves_it_reversed(
        self, api: DriveThruApiClient
    ):
        """PRD §3.6: "Both `CLOSED` and `WAIVED` are terminal for the incident."
        And: "**Closing** moves the incident `REMADE → CLOSED` and `settlement_state`
        `ACCRUED → CHARGED`; it requires the incident to be in `REMADE` and the store
        not to be frozen."

        Design: Corner/state_machines/sm_accuracy_incident_close_from_logged_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-19",
            staff_name="Corner Ines",
            name="Corner Waive Terminal Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        incident = fx.log_incident(
            api, ctx, loop["id"], incident_type="WRONG_SIZE"
        )
        assert incident["severity"] == "MINOR", incident
        assert incident["penalty_seconds"] == 20, incident
        assert incident["remake_cost_cents"] == 350, incident

        fx.waive_incident(api, incident["id"], WAIVER_REASON)

        validate_error(
            api.close_accuracy_incident(incident["id"], AUDITOR_HEADERS),
            ERR_INVALID_INCIDENT_STATE,
        )

        stored = validate_success(
            api.get_accuracy_incident(incident["id"], ADMIN_HEADERS)
        )
        assert stored["incident_state"] == "WAIVED", stored
        assert stored["settlement_state"] == "REVERSED", stored

        held = validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS))
        a.assert_loop_states(held, accuracy_state="WAIVED")
        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(store, remake_cost_accrued_cents=0)


class TestMergeCommitPrecondition:
    """The slot is fine; the car it was awarded to has moved on."""

    def test_committing_a_slot_whose_car_left_ordered_is_refused(
        self, api: DriveThruApiClient
    ):
        """PRD §3.4: "It requires the slot to be in `RESERVED`, the slot's
        `timer_loop_id` to name the loop being merged, that loop's `timing_state` to
        be `ORDERED`, and the store not to be frozen; a commit attempted from any
        other `slot_state` is `ERR_INVALID_SLOT_STATE`, while a commit whose awarded
        loop is no longer `ORDERED` is `ERR_LOOP_NOT_MERGEABLE`."
        PRD §3.3: "At a store whose `lane_config` is `SINGLE` there is no merge step
        at all, and window arrival moves the car directly `ORDERED → AT_WINDOW` with
        `merge_wait_seconds` left null."

        Design: Corner/state_machines/sm_merge_commit_precondition_loop_left_ordered_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-20",
            merge_slots_capacity=1,
            staff_name="Corner Rafa",
            name="Corner Single Lane Slot Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        slot = fx.award_merge_slot(api, ctx)
        assert slot["slot_state"] == "RESERVED", slot
        a.assert_merge_capacity(fx.get_restaurant(api, ctx.restaurant_id), free=0)

        fx.set_clock(api, fx.at(11, 2, 0))
        at_window = fx.arrive_at_window(api, ctx, loop["id"])
        assert at_window["timing_state"] == "AT_WINDOW", at_window

        # The slot itself is still RESERVED, so the slot-state check passes.
        error_id = validate_error_is_one_of(
            api.commit_merge_slot(slot["id"], ctx.leader_headers),
            [ERR_LOOP_NOT_MERGEABLE, ERR_INVALID_SLOT_STATE],
        )
        assert error_id == ERR_LOOP_NOT_MERGEABLE, error_id

        stored_slot = validate_success(api.get_merge_slot(slot["id"], ADMIN_HEADERS))
        assert stored_slot["slot_state"] == "RESERVED", stored_slot
        stored_loop = validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS))
        a.assert_loop_states(stored_loop, timing_state="AT_WINDOW")
        assert stored_loop["merge_at"] is None, stored_loop
        a.assert_merge_capacity(fx.get_restaurant(api, ctx.restaurant_id), free=0)


class TestPullForwardEscalationLimit:
    """The park-and-reissue cycle terminates at two escalations."""

    def test_a_third_reissue_is_refused_and_the_counter_stays_at_two(
        self, api: DriveThruApiClient
    ):
        """PRD §3.5: "Reissue requires `escalation_count` to be at most 1 beforehand,
        which caps a pull-forward at two reissues in total; a third attempt is
        rejected with `ERR_PULL_FORWARD_ESCALATION_LIMIT` (422)."
        And: "Reissuing moves it back `PARKED → ISSUED` when the items still are not
        ready; it stamps `reissued_at` from the logical clock, increments
        `escalation_count` by 1, and adds a further 15 seconds of escalation penalty
        to the loop's `adjusted_total_seconds` for each escalation accumulated."

        Design: Corner/state_machines/sm_pull_forward_reissue_escalation_limit_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-21",
            staff_name="Corner Nadia",
            name="Corner Escalation Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        order = fx.issue_pull_forward(
            api, ctx, loop["id"], reason="ITEM_LAG", lag_seconds=30
        )
        assert order["escalation_count"] == 0, order

        counts = []
        for _cycle in (1, 2):
            validate_success(
                api.park_pull_forward_order(order["id"], ctx.leader_headers)
            )
            reissued = validate_success(
                api.reissue_pull_forward_order(order["id"], ctx.leader_headers)
            )
            counts.append(reissued["escalation_count"])
        assert counts == [1, 2], counts

        parked = validate_success(
            api.park_pull_forward_order(order["id"], ctx.leader_headers)
        )
        assert parked["pf_state"] == "PARKED", parked

        validate_error(
            api.reissue_pull_forward_order(order["id"], ctx.leader_headers),
            ERR_PULL_FORWARD_ESCALATION_LIMIT,
        )

        stored = validate_success(
            api.get_pull_forward_order(order["id"], ADMIN_HEADERS)
        )
        assert stored["pf_state"] == "PARKED", stored
        assert stored["escalation_count"] == 2, stored
        assert stored["reason"] == "ITEM_LAG", stored
        assert stored["lag_seconds"] == 30, stored
        assert stored["restaurant_id"] == ctx.restaurant_id, stored

        stored_loop = validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS))
        a.assert_loop_states(stored_loop, timing_state="ORDERED")
        assert stored_loop["total_seconds"] is None, stored_loop


def _frozen_store_ready_for_a_car(api: DriveThruApiClient):
    """A fully provisioned store the operator has just frozen mid-shift."""
    fx.setup_single_unbounded_band(api)
    ctx = fx.setup_store(
        api,
        "C-2398-22",
        staff_name="Corner Basil",
        name="Corner Freeze Gate Store",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    frozen = fx.freeze_store(api, ctx, FREEZE_REASON)
    return ctx, frozen


class TestFreezeGateOnLoopCreation:
    """The frozen posture blocks the car, and unfreezing lets it in."""

    def test_the_frozen_store_refuses_a_new_car(self, api: DriveThruApiClient):
        """PRD §2.6: "While `service_posture` is `FROZEN`, every mutating operation is
        rejected with `ERR_POSTURE_FROZEN` (409) except these eight: `POST
        /drive-thru/restaurants`, `PATCH /drive-thru/restaurants/{restaurantId}`,
        `POST /drive-thru/restaurants/{restaurantId}/unfreeze`, `POST
        /drive-thru/volume-tier-policies`, `POST /drive-thru/forecast-overrides`,
        `POST /drive-thru/forecast-overrides/{overrideId}/approve`, `POST
        /drive-thru/forecast-overrides/{overrideId}/reject` and `POST
        /drive-thru/_clock/set_current_utc`."

        Design: Corner/state_machines/sm_restaurant_freeze_blocks_loop_create_then_unfreeze_restores
        """
        ctx, frozen = _frozen_store_ready_for_a_car(api)

        assert frozen["service_posture"] == "FROZEN", frozen
        assert frozen["posture_override"] == "FROZEN", frozen
        assert frozen["freeze_reason"] == FREEZE_REASON, frozen

        validate_error(
            api.create_timer_loop(
                f.timer_loop_body(ctx.restaurant_id, ctx.profile_id, "SINGLE"),
                ctx.leader_headers,
            ),
            ERR_POSTURE_FROZEN,
        )

        _rows, meta = validate_paginated(
            api.list_timer_loops(ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id})
        )
        assert meta["total_count"] == 0, meta

    def test_unfreezing_clears_the_flag_and_the_identical_car_is_admitted(
        self, api: DriveThruApiClient
    ):
        """PRD §2.6: "Unfreezing requires `posture_override` to currently be `FROZEN`;
        it sets `posture_override` back to `NONE`, sets `freeze_reason` back to null,
        increments `version` by 1, and then re-runs the rollup chain — so unfreezing
        does not necessarily land on `OPEN`."

        Design: Corner/state_machines/sm_restaurant_freeze_blocks_loop_create_then_unfreeze_restores
        """
        ctx, _frozen = _frozen_store_ready_for_a_car(api)

        validate_error(
            api.create_timer_loop(
                f.timer_loop_body(ctx.restaurant_id, ctx.profile_id, "SINGLE"),
                ctx.leader_headers,
            ),
            ERR_POSTURE_FROZEN,
        )

        thawed = validate_success(
            api.unfreeze_restaurant(ctx.restaurant_id, ctx.operator_headers)
        )
        # No cars closed and nobody required, so the recompute lands on OPEN.
        assert thawed["service_posture"] == "OPEN", thawed
        assert thawed["posture_override"] == "NONE", thawed
        assert thawed["freeze_reason"] is None, thawed

        loop = validate_success(
            api.create_timer_loop(
                f.timer_loop_body(ctx.restaurant_id, ctx.profile_id, "SINGLE"),
                ctx.leader_headers,
            ),
            expected_status=201,
        )
        assert loop["car_sequence"] == 1, loop
        assert loop["target_total_seconds_pinned"] == 235, loop


def _store_with_a_published_report_and_a_successor(api: DriveThruApiClient):
    """One served car scored twice: report A published, report B drafted over it."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "C-2398-23",
        staff_name="Corner Wren",
        name="Corner Supersede Store",
    )
    fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 0, 0),
        greet_at=fx.at(11, 0, 20),
        order_complete_at=fx.at(11, 1, 0),
        window_arrive_at=fx.at(11, 2, 0),
        depart_at=fx.at(11, 4, 10),
        order_items_count=3,
    )
    fx.set_clock(api, fx.at(11, 5, 0))
    first = fx.create_published_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0))
    second = fx.create_report(
        api,
        ctx,
        fx.at(11, 0, 0),
        fx.at(11, 5, 0),
        supersedes_report_id=first["id"],
    )
    return ctx, first, second


class TestReportSupersedeSideEffect:
    """Publishing the successor retires the predecessor in the same operation."""

    def test_publishing_the_successor_supersedes_the_named_predecessor(
        self, api: DriveThruApiClient
    ):
        """PRD §3.8: "If the report names a `supersedes_report_id` and that
        predecessor is currently `PUBLISHED`, the predecessor moves `PUBLISHED →
        SUPERSEDED` as part of the same operation; existing coaching interventions
        keep pointing at the superseded report through their `throughput_report_id`,
        but no new intervention may be created against it."

        Design: Corner/state_machines/sm_report_publish_supersedes_named_predecessor
        """
        ctx, first, second = _store_with_a_published_report_and_a_successor(api)

        published = fx.publish_report(api, second["id"])
        assert published["report_state"] == "PUBLISHED", published
        assert published["supersedes_report_id"] == first["id"], published

        predecessor = validate_success(
            api.get_throughput_report(first["id"], ADMIN_HEADERS)
        )
        assert predecessor["report_state"] == "SUPERSEDED", predecessor

        rows, meta = validate_paginated(
            api.list_throughput_reports(
                ADMIN_HEADERS,
                {"restaurant_id": ctx.restaurant_id, "report_state": "PUBLISHED"},
            )
        )
        assert meta["total_count"] == 1, meta
        assert rows[0]["id"] == second["id"], rows

    def test_the_successor_recomputes_the_same_window_to_the_same_numbers(
        self, api: DriveThruApiClient
    ):
        """PRD §3.8: "Every metric is computed **once, at creation**, from the state
        visible at that moment; publishing never recomputes anything."
        And: "`target_total_seconds_effective` is `mean_pinned_target_seconds`
        multiplied by one plus that relief, rounded half up to a whole second."

        Design: Corner/state_machines/sm_report_publish_supersedes_named_predecessor
        """
        _ctx, first, second = _store_with_a_published_report_and_a_successor(api)

        # One car in a 300-second window is 12.0 cars per hour, which is TIER_3,
        # whose 0.07 relief lifts the 235-second mean target to 251.
        a.assert_report_metrics(
            first,
            attainment_pct=100.40,
            attainment_band="GREEN",
        )
        a.assert_report_metrics(
            second,
            metric_basis="TOTAL",
            cars_served=1,
            cars_per_hour=12.0,
            window_tier="TIER_3",
            avg_metric_seconds=250.0,
            mean_pinned_target_seconds=235,
            target_total_seconds_effective=251,
            attainment_pct=100.40,
            attainment_band="GREEN",
            coaching_pool_points=6,
        )
