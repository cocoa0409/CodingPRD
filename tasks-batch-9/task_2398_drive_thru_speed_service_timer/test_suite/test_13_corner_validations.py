"""Field-level and cross-entity validation rules, each taken to its rejection.

Every rejection is checked twice over: the error identity the PRD names, and the
stored state the refused request was not allowed to touch.
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
    ERR_ALLERGEN_WAIVER_FORBIDDEN,
    ERR_CLOCK_REGRESSION,
    ERR_COACHING_REVISION_LIMIT,
    ERR_DAYPART_WINDOW_MISMATCH,
    ERR_DAYPART_WINDOW_OVERLAP,
    ERR_DUPLICATE_DAYPART,
    ERR_DUPLICATE_STORE_NUMBER,
    ERR_DUPLICATE_TIER_POLICY,
    ERR_LOOP_HAS_NO_ORDER,
    ERR_MERGE_CAPACITY_EXHAUSTED,
    ERR_NO_MERGE_CANDIDATE,
    ERR_PROFILE_NOT_ACTIVE,
    ERR_PULL_FORWARD_ALREADY_OPEN,
    ERR_REMAKE_ALREADY_OPEN,
    ERR_STAFF_CONSECUTIVE_LIMIT,
    ERR_STAFF_NOT_OOT_CERTIFIED,
    ERR_WINDOW_BOUNDS_INVALID,
)
from test_helpers.test_users import ADMIN_HEADERS, AUDITOR_HEADERS


class TestClockMonotonicity:
    """The logical clock only ever moves forward, or stands still."""

    def test_a_backwards_set_is_refused_and_an_equal_one_is_accepted(
        self, api: DriveThruApiClient
    ):
        """PRD §2.4: "The clock is only ever set to whole seconds, and it never moves
        backwards: if `to_iso8601` is earlier than the clock's current value the request
        is rejected with `ERR_CLOCK_REGRESSION` (422). Setting the clock to exactly its
        current value is permitted."

        Design: Corner/validations/val_clock_regression_rejected
        """
        first = fx.set_clock(api, fx.at(11, 0, 0))
        assert first["current_utc"] == fx.at(11, 0, 0), first

        validate_error(
            api.set_clock(f.clock_body(fx.at(10, 0, 0)), ADMIN_HEADERS),
            ERR_CLOCK_REGRESSION,
        )

        again = fx.set_clock(api, fx.at(11, 0, 0))
        assert again["current_utc"] == fx.at(11, 0, 0), again


class TestIntervalBoundOrdering:
    """An interval whose end precedes its start is refused, never swapped."""

    def test_a_daypart_window_that_ends_before_it_starts_is_refused(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Interval bound ordering** — `end_minute` strictly greater than
        `start_minute`; `planned_end_at` strictly after `planned_start_at`;
        `window_end_at` strictly after `window_start_at`; `effective_end_at` strictly
        after `effective_start_at`."

        Design: Corner/validations/val_daypart_end_minute_not_after_start_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-33",
            with_active_lunch_profile=False,
            name="Corner Bounds Store",
        )

        validate_error(
            api.create_daypart_profile(
                f.daypart_profile_body(
                    ctx.restaurant_id, start_minute=840, end_minute=660
                ),
                ctx.operator_headers,
            ),
            ERR_WINDOW_BOUNDS_INVALID,
        )

        rows, meta = validate_paginated(
            api.list_daypart_profiles(
                ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id}
            )
        )
        assert rows == [], rows
        assert meta["total_count"] == 0, meta


class TestDaypartContainment:
    """An active profile is not enough: the clock must be inside its window."""

    def test_a_car_arriving_before_the_lunch_window_is_refused(
        self, api: DriveThruApiClient
    ):
        """PRD §3.3: "Creation requires the named profile to be in `ACTIVE`, and it
        requires the logical clock's minute-of-day to fall inside that profile's
        half-open window — at or after `start_minute` and strictly before `end_minute` —
        or the request fails with `ERR_DAYPART_WINDOW_MISMATCH`."

        Design: Corner/validations/val_loop_created_outside_daypart_window_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-35",
            with_active_lunch_profile=False,
            staff_name="Corner Rosa",
            name="Corner Containment Store",
        )
        drafted = fx.create_daypart_profile(api, ctx.restaurant_id)
        assert drafted["profile_state"] == "DRAFT", drafted
        ctx.profile = fx.activate_profile(api, ctx.restaurant_id, drafted["id"])
        assert ctx.profile["profile_state"] == "ACTIVE", ctx.profile
        assert ctx.profile["start_minute"] == 660, ctx.profile

        fx.set_clock(api, fx.at(10, 30, 0))

        # Minute-of-day 630 is the only thing wrong, so the active-profile gate
        # cannot be what fires.
        error_id = validate_error_is_one_of(
            api.create_timer_loop(
                f.timer_loop_body(ctx.restaurant_id, ctx.profile_id),
                ctx.leader_headers,
            ),
            [ERR_DAYPART_WINDOW_MISMATCH, ERR_PROFILE_NOT_ACTIVE],
        )
        assert error_id == ERR_DAYPART_WINDOW_MISMATCH

        _rows, meta = validate_paginated(
            api.list_timer_loops(ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id})
        )
        assert meta["total_count"] == 0, meta


class TestStoreNumberUniqueness:
    """The store number identifies the store globally."""

    def test_a_second_registration_on_the_same_number_leaves_the_first_alone(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Uniqueness** — the pair of store and `daypart` is unique among
        profiles whose `profile_state` is `DRAFT` or `ACTIVE` (`ERR_DUPLICATE_DAYPART`);
        `tier` is globally unique across volume-tier bands
        (`ERR_DUPLICATE_TIER_POLICY`); `store_number` is globally unique across stores
        (`ERR_DUPLICATE_STORE_NUMBER`)."

        Design: Corner/validations/val_duplicate_store_number_rejected
        """
        fx.setup_single_unbounded_band(api)
        original = fx.register_restaurant(api, "C-2398-34")

        validate_error(
            api.register_restaurant(
                f.restaurant_body(
                    "C-2398-34",
                    name="Corner Unique Store Twin",
                    lane_config="DUAL_PARALLEL",
                    merge_slots_capacity=4,
                    labor_minutes_budget=900,
                ),
                ADMIN_HEADERS,
            ),
            ERR_DUPLICATE_STORE_NUMBER,
        )

        stored = fx.get_restaurant(api, original["id"])
        assert stored["lane_config"] == "SINGLE", stored
        assert stored["merge_slots_capacity"] == 1, stored
        assert stored["labor_minutes_budget"] == 300, stored
        a.assert_created_unmodified(stored)


class TestTierUniqueness:
    """One band per tier name, whatever its floor and ceiling say."""

    def test_a_second_band_on_the_same_tier_does_not_overwrite_the_first(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Uniqueness** — the pair of store and `daypart` is unique among
        profiles whose `profile_state` is `DRAFT` or `ACTIVE` (`ERR_DUPLICATE_DAYPART`);
        `tier` is globally unique across volume-tier bands
        (`ERR_DUPLICATE_TIER_POLICY`); `store_number` is globally unique across stores
        (`ERR_DUPLICATE_STORE_NUMBER`)."
        PRD §3.1: "It is a flat, chain-wide table (not per store) of at most four rows,
        one per `tier`, whose values are exactly `TIER_1`, `TIER_2`, `TIER_3` and
        `TIER_4`."

        Design: Corner/validations/val_duplicate_tier_policy_rejected
        """
        original = fx.create_tier_band(
            api,
            {
                "tier": "TIER_1",
                "cars_per_hour_floor": 0,
                "cars_per_hour_ceiling": 6,
                "target_relief_pct": 0.00,
                "min_oot_count": 0,
                "merge_award_bias": "ALTERNATE",
            },
        )

        validate_error(
            api.create_volume_tier_policy(
                f.tier_policy_body(
                    "TIER_1",
                    40,
                    0.1,
                    2,
                    "LONGEST_WAIT",
                    cars_per_hour_ceiling=60,
                ),
                ADMIN_HEADERS,
            ),
            ERR_DUPLICATE_TIER_POLICY,
        )

        rows, meta = validate_paginated(api.list_volume_tier_policies(ADMIN_HEADERS))
        assert meta["total_count"] == 1, meta
        assert rows[0]["id"] == original["id"], rows
        assert rows[0]["cars_per_hour_floor"] == 0, rows[0]


class TestDaypartUniqueness:
    """A draft profile already occupies its daypart."""

    def test_a_second_lunch_profile_is_refused_while_the_first_is_still_a_draft(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Uniqueness** — the pair of store and `daypart` is unique among
        profiles whose `profile_state` is `DRAFT` or `ACTIVE` (`ERR_DUPLICATE_DAYPART`);
        `tier` is globally unique across volume-tier bands
        (`ERR_DUPLICATE_TIER_POLICY`); `store_number` is globally unique across stores
        (`ERR_DUPLICATE_STORE_NUMBER`)."
        PRD §3.2: "Either way it requires the store not to be frozen, and either way it
        frees the store-and-daypart uniqueness slot so a replacement profile can be
        drafted."

        Design: Corner/validations/val_duplicate_daypart_for_store_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-36",
            with_active_lunch_profile=False,
            name="Corner Daypart Uniqueness Store",
        )
        drafted = fx.create_daypart_profile(api, ctx.restaurant_id)
        assert drafted["profile_state"] == "DRAFT", drafted

        # The overlap rule guards activation; uniqueness guards creation.
        error_id = validate_error_is_one_of(
            api.create_daypart_profile(
                f.daypart_profile_body(
                    ctx.restaurant_id,
                    start_minute=700,
                    end_minute=800,
                    greet_target_seconds=20,
                    order_target_seconds=80,
                    pull_forward_target_seconds=30,
                    window_target_seconds=60,
                ),
                ctx.operator_headers,
            ),
            [ERR_DUPLICATE_DAYPART, ERR_DAYPART_WINDOW_OVERLAP],
        )
        assert error_id == ERR_DUPLICATE_DAYPART

        rows, meta = validate_paginated(
            api.list_daypart_profiles(
                ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id}
            )
        )
        assert meta["total_count"] == 1, meta
        assert rows[0]["id"] == drafted["id"], rows


class TestConsecutiveMinutesCap:
    """The cap is the member's own, not a system-wide number."""

    def test_a_ninety_minute_block_for_a_sixty_minute_member_moves_no_labor(
        self, api: DriveThruApiClient
    ):
        """PRD §3.4: "Second, `planned_minutes` may not exceed the member's
        `max_consecutive_deployment_minutes`, or the plan is rejected with
        `ERR_STAFF_CONSECUTIVE_LIMIT`."
        And: "First, a deployment at `OOT_LANE_A` or `OOT_LANE_B` requires the named
        member's `oot_certified` to be true; otherwise the plan is rejected with
        `ERR_STAFF_NOT_OOT_CERTIFIED`."

        Design: Corner/validations/val_deployment_exceeding_consecutive_limit_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-37",
            with_staff=False,
            name="Corner Consecutive Cap Store",
        )
        member = fx.add_staff_member(
            api,
            ctx.restaurant_id,
            "Corner Nadia",
            oot_certified=True,
            max_consecutive_deployment_minutes=60,
        )
        assert member["max_consecutive_deployment_minutes"] == 60, member
        assert member["oot_certified"] is True, member
        fx.set_clock(api, fx.at(11, 0, 0))

        # 5400 seconds rounds up to 90 planned minutes against a cap of 60.
        error_id = validate_error_is_one_of(
            api.create_deployment(
                f.deployment_body(
                    ctx.restaurant_id,
                    member["id"],
                    ctx.profile_id,
                    fx.at(11, 0, 0),
                    fx.at(12, 30, 0),
                ),
                ctx.operator_headers,
            ),
            [ERR_STAFF_CONSECUTIVE_LIMIT, ERR_STAFF_NOT_OOT_CERTIFIED],
        )
        assert error_id == ERR_STAFF_CONSECUTIVE_LIMIT

        a.assert_labor_ledger(
            fx.get_restaurant(api, ctx.restaurant_id), committed=0, available=300
        )
        _rows, meta = validate_paginated(
            api.list_deployments(ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id})
        )
        assert meta["total_count"] == 0, meta


class TestOneLivePullForwardPerLoop:
    """A car that is already being pulled forward cannot be pulled forward again."""

    def test_a_second_order_on_the_same_car_leaves_the_first_lag_intact(
        self, api: DriveThruApiClient
    ):
        """PRD §3.7: "A loop may carry only one live pull-forward at a time: if any
        pull-forward order for that loop is already in `ISSUED` or `PARKED`, the request
        is rejected with `ERR_PULL_FORWARD_ALREADY_OPEN` (409)."

        Design: Corner/validations/val_second_pull_forward_on_same_loop_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-38",
            staff_name="Corner Tomas",
            name="Corner Pull Forward Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        first = fx.issue_pull_forward(
            api, ctx, loop["id"], reason="ITEM_LAG", lag_seconds=45
        )
        assert first["pf_state"] == "ISSUED", first
        assert first["lag_seconds"] == 45, first

        validate_error(
            api.create_pull_forward_order(
                f.pull_forward_body(loop["id"], "MERGE_CONFLICT", 120),
                ctx.leader_headers,
            ),
            ERR_PULL_FORWARD_ALREADY_OPEN,
        )

        stored = validate_success(
            api.get_pull_forward_order(first["id"], ADMIN_HEADERS)
        )
        assert stored["reason"] == "ITEM_LAG", stored
        assert stored["lag_seconds"] == 45, stored
        _rows, meta = validate_paginated(
            api.list_pull_forward_orders(
                ADMIN_HEADERS, {"timer_loop_id": loop["id"]}
            )
        )
        assert meta["total_count"] == 1, meta


class TestMergeCandidateAvailability:
    """Free capacity does not manufacture a candidate."""

    def test_a_store_whose_only_car_is_merely_greeted_has_nothing_to_award(
        self, api: DriveThruApiClient
    ):
        """PRD §3.4: "Eligibility comes first: a candidate is a loop of this store
        whose `timing_state` is `ORDERED`, whose `accuracy_state` is either `PENDING` or
        `VERIFIED`, for which no merge slot is currently in `RESERVED` or `COMMITTED`,
        and for which no pull-forward order is currently in `ISSUED` or `PARKED`. If
        that candidate set is empty the award fails with `ERR_NO_MERGE_CANDIDATE` (409);
        if `merge_slots_free` is below 1 it fails with `ERR_MERGE_CAPACITY_EXHAUSTED`
        (409)."

        Design: Corner/validations/val_merge_award_with_no_eligible_loop_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-39",
            lane_config="DUAL_PARALLEL",
            merge_slots_capacity=2,
            staff_name="Corner Ivy",
            name="Corner No Candidate Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            lane="LANE_A",
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=None,
        )
        a.assert_loop_states(loop, timing_state="GREETED")
        a.assert_merge_capacity(fx.get_restaurant(api, ctx.restaurant_id), free=2)

        error_id = validate_error_is_one_of(
            api.award_merge_slot(ctx.restaurant_id, ctx.leader_headers),
            [ERR_NO_MERGE_CANDIDATE, ERR_MERGE_CAPACITY_EXHAUSTED],
        )
        assert error_id == ERR_NO_MERGE_CANDIDATE

        _rows, meta = validate_paginated(
            api.list_merge_slots(ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id})
        )
        assert meta["total_count"] == 0, meta
        a.assert_merge_capacity(fx.get_restaurant(api, ctx.restaurant_id), free=2)


class TestMergeCapacity:
    """A non-empty candidate pool still needs a free slot."""

    def test_a_second_award_against_a_single_spent_slot_is_refused(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Merge capacity** — `merge_slots_free` is at least 1. Applies to
        `POST /drive-thru/restaurants/{restaurantId}/merge-award`. Rejection:
        `ERR_MERGE_CAPACITY_EXHAUSTED` (409)."

        Design: Corner/validations/val_merge_award_with_zero_free_slots_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-40",
            lane_config="DUAL_PARALLEL",
            merge_slots_capacity=1,
            staff_name="Corner Reza",
            name="Corner Capacity Store",
        )
        fx.set_clock(api, fx.at(11, 0, 0))
        first = fx.open_loop(api, ctx, lane="LANE_A")
        fx.set_clock(api, fx.at(11, 0, 5))
        second = fx.open_loop(api, ctx, lane="LANE_B")
        fx.set_clock(api, fx.at(11, 0, 20))
        fx.greet_loop(api, ctx, first["id"])
        fx.set_clock(api, fx.at(11, 0, 30))
        fx.greet_loop(api, ctx, second["id"])
        fx.set_clock(api, fx.at(11, 1, 0))
        fx.complete_order(api, ctx, first["id"], order_items_count=3)
        fx.set_clock(api, fx.at(11, 2, 0))
        fx.complete_order(api, ctx, second["id"], order_items_count=3)

        slot = fx.award_merge_slot(api, ctx)
        assert slot["timer_loop_id"] == first["id"], slot
        a.assert_merge_capacity(fx.get_restaurant(api, ctx.restaurant_id), free=0)

        # The second car is a perfectly good candidate; the shelf is what is full.
        error_id = validate_error_is_one_of(
            api.award_merge_slot(ctx.restaurant_id, ctx.leader_headers),
            [ERR_MERGE_CAPACITY_EXHAUSTED, ERR_NO_MERGE_CANDIDATE],
        )
        assert error_id == ERR_MERGE_CAPACITY_EXHAUSTED

        rows, meta = validate_paginated(
            api.list_merge_slots(ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id})
        )
        assert meta["total_count"] == 1, meta
        assert rows[0]["slot_state"] == "RESERVED", rows[0]
        waiting = validate_success(api.get_timer_loop(second["id"], ADMIN_HEADERS))
        a.assert_loop_states(waiting, timing_state="ORDERED")


class TestAllergenWaiverBan:
    """A critical defect is never forgiven."""

    def test_the_auditor_cannot_waive_an_allergen_incident(
        self, api: DriveThruApiClient
    ):
        """PRD §3.6: "It requires the incident to be in `LOGGED`, the store not to be
        frozen, and the incident's `severity` not to be `CRITICAL` — an `ALLERGEN`
        defect can never be waived, and the attempt is rejected with
        `ERR_ALLERGEN_WAIVER_FORBIDDEN` (422)."

        Design: Corner/validations/val_waive_of_allergen_incident_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-41",
            staff_name="Corner Priya",
            name="Corner Allergen Waiver Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        incident = fx.log_incident(api, ctx, loop["id"], incident_type="ALLERGEN")
        assert incident["severity"] == "CRITICAL", incident

        validate_error(
            api.waive_accuracy_incident(
                incident["id"],
                f.waive_body("Guest said the reaction was mild"),
                AUDITOR_HEADERS,
            ),
            ERR_ALLERGEN_WAIVER_FORBIDDEN,
        )

        stored = validate_success(
            api.get_accuracy_incident(incident["id"], ADMIN_HEADERS)
        )
        assert stored["incident_state"] == "LOGGED", stored
        assert stored["settlement_state"] == "ACCRUED", stored
        assert stored["waiver_reason"] is None, stored

        held = validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS))
        a.assert_loop_states(held, accuracy_state="REMAKE_OPEN")
        a.assert_rollup(
            fx.get_restaurant(api, ctx.restaurant_id),
            remake_cost_accrued_cents=1200,
        )


class TestIncidentNeedsAnOrder:
    """Nothing can be wrong with an order that has not been taken."""

    def test_a_greeted_car_cannot_carry_a_missing_item_defect(
        self, api: DriveThruApiClient
    ):
        """PRD §3.6: "Logging is only possible once the car has actually ordered: the
        loop's `timing_state` must be `ORDERED`, `MERGED`, `AT_WINDOW` or `CLOSED`, and
        a loop still in `OPEN` or `GREETED` is rejected with `ERR_LOOP_HAS_NO_ORDER`."

        Design: Corner/validations/val_incident_on_greeted_loop_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-42",
            staff_name="Corner Blaise",
            name="Corner No Order Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=None,
        )
        a.assert_loop_states(loop, timing_state="GREETED", accuracy_state="PENDING")

        validate_error(
            api.create_accuracy_incident(
                f.accuracy_incident_body(loop["id"], ctx.staff_id, "MISSING_ITEM"),
                ctx.leader_headers,
            ),
            ERR_LOOP_HAS_NO_ORDER,
        )

        untouched = validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS))
        a.assert_loop_states(untouched, accuracy_state="PENDING")
        a.assert_rollup(
            fx.get_restaurant(api, ctx.restaurant_id), open_remake_count=0
        )
        _rows, meta = validate_paginated(
            api.list_accuracy_incidents(
                ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id}
            )
        )
        assert meta["total_count"] == 0, meta


class TestOneOpenRemakePerLoop:
    """A car with an unresolved remake cannot accrue a second one."""

    def test_a_second_defect_on_the_same_car_adds_nothing_to_the_ledger(
        self, api: DriveThruApiClient
    ):
        """PRD §3.6: "The loop's `accuracy_state` must be `PENDING` or `VERIFIED`; a
        loop already carrying an unresolved remake — `accuracy_state` of `REMAKE_OPEN`
        or `REMADE` — is rejected with `ERR_REMAKE_ALREADY_OPEN`."

        Design: Corner/validations/val_second_incident_while_remake_open_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-43",
            staff_name="Corner Gita",
            name="Corner Second Defect Store",
        )
        loop = fx.drive_loop(
            api,
            ctx,
            arrive_at=fx.at(11, 0, 0),
            greet_at=fx.at(11, 0, 20),
            order_complete_at=fx.at(11, 1, 0),
            window_arrive_at=None,
        )
        first = fx.log_incident(api, ctx, loop["id"], incident_type="WRONG_SIZE")
        assert first["remake_cost_cents"] == 350, first

        validate_error(
            api.create_accuracy_incident(
                f.accuracy_incident_body(loop["id"], ctx.staff_id, "ALLERGEN"),
                ctx.leader_headers,
            ),
            ERR_REMAKE_ALREADY_OPEN,
        )

        rows, meta = validate_paginated(
            api.list_accuracy_incidents(ADMIN_HEADERS, {"timer_loop_id": loop["id"]})
        )
        assert meta["total_count"] == 1, meta
        assert rows[0]["id"] == first["id"], rows
        # The refused critical defect did not add its 1200 cents.
        a.assert_rollup(
            fx.get_restaurant(api, ctx.restaurant_id),
            open_remake_count=1,
            remake_cost_accrued_cents=350,
        )


class TestCoachingRevisionLimit:
    """The authoring loop is allowed exactly two trips."""

    def test_a_third_contest_is_refused_and_keeps_the_second_reason(
        self, api: DriveThruApiClient
    ):
        """PRD §3.9: "Contesting also starts from `ISSUED` under the same ownership and
        posture conditions, requires `revision_count` to be at most 1 beforehand, and
        stores the supplied `contest_reason`."
        And: "Because `revision_count` must be at most 1 to contest, an intervention
        can go round that loop at most twice; a third contest is rejected with
        `ERR_COACHING_REVISION_LIMIT`."

        Design: Corner/validations/val_third_contest_over_revision_limit_rejected
        """
        second_reason = "Second lane was closed for maintenance that daypart"
        fx.setup_four_tier_bands(api)
        ctx = fx.setup_store(
            api,
            "C-2398-44",
            staff_name="Corner Emmet",
            name="Corner Revision Limit Store",
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
        report = fx.create_published_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0))
        a.assert_report_metrics(report, attainment_band="GREEN", cars_served=1)

        coaching = fx.create_coaching(api, report["id"], ctx.staff_id, "GREET")
        assert coaching["revision_count"] == 0, coaching
        # A greet of 20 seconds against a 25-second target leaves no gap, so only
        # the GREEN band component scores.
        a.assert_coaching_scoring(
            coaching, segment_gap_seconds=0, priority_score=3.00, tier="TIER_A_OBSERVE"
        )

        fx.issue_coaching(api, coaching["id"])
        first_cycle = fx.contest_coaching(
            api, ctx, coaching["id"], "First lane sensor was miscalibrated that hour"
        )
        assert first_cycle["ci_state"] == "DRAFT", first_cycle
        assert first_cycle["revision_count"] == 1, first_cycle

        fx.issue_coaching(api, coaching["id"])
        second_cycle = fx.contest_coaching(api, ctx, coaching["id"], second_reason)
        assert second_cycle["ci_state"] == "DRAFT", second_cycle
        assert second_cycle["revision_count"] == 2, second_cycle

        reissued = fx.issue_coaching(api, coaching["id"])
        assert reissued["ci_state"] == "ISSUED", reissued

        validate_error(
            api.contest_coaching_intervention(
                coaching["id"],
                f.contest_body("Third attempt at the same argument"),
                ctx.leader_headers,
            ),
            ERR_COACHING_REVISION_LIMIT,
        )

        stored = validate_success(
            api.get_coaching_intervention(coaching["id"], ADMIN_HEADERS)
        )
        assert stored["ci_state"] == "ISSUED", stored
        assert stored["revision_count"] == 2, stored
        assert stored["contest_reason"] == second_reason, stored


class TestCompliantDeploymentActivation:
    """Every gate satisfied: the happy path commits exactly what it planned."""

    def test_a_sixty_minute_block_clears_every_gate_and_commits_sixty_minutes(
        self, api: DriveThruApiClient
    ):
        """PRD §3.4: "Activation — moving `PLANNED → ACTIVE`, available to both an
        `Operator` and a `ShiftLeader` — requires the deployment to be in `PLANNED`, the
        store not to be frozen, the member's `staff_state` to be `AVAILABLE`, and the
        store's `labor_minutes_available` to be at least this deployment's
        `planned_minutes`; a shortfall is `ERR_LABOR_BUDGET_EXCEEDED` (402)."
        And: "On success `activated_at` is stamped from the logical clock, the member
        moves to `DEPLOYED`, the deployment's full `planned_minutes` join
        `labor_minutes_committed`, `labor_minutes_available` is re-derived, and the
        rollup chain runs — recomputing `deployed_oot_count` and then `service_posture`,
        which is how putting an outside order-taker on position can clear a `SURGE`."

        Design: Corner/validations/val_compliant_deployment_activation_passes_every_gate
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-45",
            staff_name="Corner Wren",
            name="Corner Compliant Deployment Store",
        )
        a.assert_labor_ledger(
            fx.get_restaurant(api, ctx.restaurant_id), committed=0, available=300
        )
        assert ctx.staff["max_consecutive_deployment_minutes"] == 90, ctx.staff
        assert ctx.staff["staff_state"] == "AVAILABLE", ctx.staff
        fx.set_clock(api, fx.at(11, 0, 0))

        planned = fx.plan_deployment(api, ctx, fx.at(11, 0, 0), fx.at(12, 0, 0))
        assert planned["deployment_state"] == "PLANNED", planned
        a.assert_deployment_charge(planned, planned_minutes=60)

        activated = fx.activate_deployment(api, ctx, planned["id"])

        assert activated["deployment_state"] == "ACTIVE", activated
        assert activated["activated_at"] == fx.at(11, 0, 0), activated
        a.assert_deployment_charge(activated, labor_minutes_charged=0)

        member = validate_success(api.get_staff_member(ctx.staff_id, ADMIN_HEADERS))
        assert member["staff_state"] == "DEPLOYED", member

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(store, committed=60, available=240)
        a.assert_rollup(
            store,
            deployed_oot_count=1,
            required_oot_count=0,
            service_posture="OPEN",
        )
