"""Entity surfaces: declared inputs, defaults, computed fields and rejections.

These checks pin the shape of a stored row — what the server seeds at creation,
what it derives, what it defaults and what it refuses — one entity at a time.
"""

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
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
    ERR_INVALID_REQUEST,
    ERR_RESTAURANT_NOT_FOUND,
    ERR_STAFF_NOT_FOUND,
    ERR_WINDOW_BOUNDS_INVALID,
)
from test_helpers.constants import ABSENT_UUID
from test_helpers.test_users import ADMIN_HEADERS, AUDITOR_HEADERS


class TestRestaurantCreation:
    """What registration puts in the row, and what it leaves alone."""

    def test_registration_seeds_every_derived_store_field(self, api: DriveThruApiClient):
        """PRD §3.1: "Registration initialises the store's derived state without
        running the full recompute chain: `merge_slots_free` is set equal to
        `merge_slots_capacity`, `labor_minutes_available` is set equal to
        `labor_minutes_budget` with `labor_minutes_committed` at 0,
        `cars_per_hour_observed` and `cars_per_hour_effective` are both 0.0,
        `volume_tier` is read off the band containing a car rate of 0.0,
        `posture_override` is `NONE`, and `service_posture` is `OPEN`."
        And: "`cars_closed_trailing`, `required_oot_count`, `deployed_oot_count`,
        `open_remake_count` and `remake_cost_accrued_cents` all start at 0, and
        `freeze_reason` starts null."

        Design: Corner/entities/entity_restaurant_creation_returns_declared_fields
        """
        fx.setup_single_unbounded_band(api)

        store = validate_success(
            api.register_restaurant(
                f.restaurant_body(
                    "C-2398-01",
                    name="Corner Creation Store",
                    lane_config="DUAL_TANDEM",
                    merge_slots_capacity=4,
                    labor_minutes_budget=480,
                    staffing_basis="OBSERVED",
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert store["name"] == "Corner Creation Store", store
        assert store["store_number"] == "C-2398-01", store
        assert store["lane_config"] == "DUAL_TANDEM", store
        assert store["merge_slots_capacity"] == 4, store
        a.assert_merge_capacity(store, free=4)
        assert store["labor_minutes_budget"] == 480, store
        a.assert_labor_ledger(store, committed=0, available=480)
        a.assert_rollup(
            store,
            cars_closed_trailing=0,
            cars_per_hour_observed=0.0,
            cars_per_hour_effective=0.0,
            volume_tier="TIER_1",
            required_oot_count=0,
            deployed_oot_count=0,
            open_remake_count=0,
            remake_cost_accrued_cents=0,
            service_posture="OPEN",
        )
        assert store["posture_override"] == "NONE", store
        assert store["freeze_reason"] is None, store
        a.assert_common_fields(store, expected_version=1)

    def test_the_optional_staffing_basis_defaults_to_the_observed_variant(
        self, api: DriveThruApiClient
    ):
        """PRD §3.1: "`staffing_basis` is optional at registration and defaults to
        `OBSERVED`."
        PRD §3.2: "Under `OBSERVED`, `cars_per_hour_effective` equals
        `cars_per_hour_observed`, so the tier, the lane bump and therefore
        `required_oot_count` are read off the trailing ten-minute closed-car count
        alone and forecast overrides in force are ignored entirely."

        Design: Corner/entities/entity_restaurant_staffing_basis_defaults_to_observed
        """
        fx.setup_single_unbounded_band(api)

        store = validate_success(
            api.register_restaurant(
                f.restaurant_body(
                    "C-2398-06",
                    name="Corner Default Basis Store",
                    lane_config="SINGLE",
                    merge_slots_capacity=1,
                    labor_minutes_budget=300,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert store["staffing_basis"] == "OBSERVED", store
        assert store["cars_per_hour_effective"] == 0.0, store

        stored = fx.get_restaurant(api, store["id"])
        assert stored["staffing_basis"] == "OBSERVED", stored
        assert stored["cars_per_hour_effective"] == 0.0, stored

    def test_the_system_fields_come_from_the_server_and_the_logical_clock(
        self, api: DriveThruApiClient
    ):
        """PRD §2.5: "`id` (string): a server-minted UUID. It carries no type prefix
        and is never supplied by the client."
        And: "`version` (integer): a monotonically increasing integer that starts at
        1 on creation and increments by exactly 1 on every mutation of that
        resource."
        PRD §2.4: "Nothing in this system reads wall-clock time."

        Design: Corner/entities/entity_restaurant_system_fields_input_ignored
        """
        fx.setup_single_unbounded_band(api)
        fx.set_clock(api, fx.at(9, 15, 0))

        store = validate_success(
            api.register_restaurant(
                f.restaurant_body(
                    "C-2398-10",
                    name="Corner System Fields Store",
                    lane_config="SINGLE",
                    merge_slots_capacity=1,
                    labor_minutes_budget=300,
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        assert is_valid_uuid(store["id"]), store
        assert is_iso8601_timestamp(store["created_at"]), store
        # The clock stood at 09:15:00 on the operating day when the row was written.
        assert store["created_at"].startswith("2026-08-01T09:15:00"), store
        a.assert_created_unmodified(store)


class TestRestaurantRetrieval:
    """Reading a store hands back the stored row and mutates nothing."""

    def test_a_read_returns_the_stored_row_to_a_role_that_did_not_create_it(
        self, api: DriveThruApiClient
    ):
        """PRD §2.5: "`version` (integer): a monotonically increasing integer that
        starts at 1 on creation and increments by exactly 1 on every mutation of
        that resource."

        Design: Corner/entities/entity_restaurant_retrieval_returns_stored_row
        """
        fx.setup_single_unbounded_band(api)
        created = fx.register_restaurant(
            api, "C-2398-02", name="Corner Retrieval Store", lane_config="SINGLE"
        )

        read = validate_success(api.get_restaurant(created["id"], AUDITOR_HEADERS))

        assert read["id"] == created["id"], read
        assert read["store_number"] == "C-2398-02", read
        assert read["volume_tier"] == "TIER_1", read
        assert read["service_posture"] == "OPEN", read
        # A read is not a mutation.
        assert read["version"] == 1, read

    def test_an_identifier_no_create_call_minted_is_a_not_found(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Path-resource existence** — every path-templated resource
        exists, validated strictly left to right. Applies to every endpoint with a
        path parameter. Rejection is the 404 code matching the first path segment
        that fails to resolve: `ERR_RESTAURANT_NOT_FOUND`, `ERR_PROFILE_NOT_FOUND`,
        `ERR_STAFF_NOT_FOUND`, `ERR_DEPLOYMENT_NOT_FOUND`, `ERR_LOOP_NOT_FOUND`,
        `ERR_SLOT_NOT_FOUND`, `ERR_PULL_FORWARD_NOT_FOUND`,
        `ERR_INCIDENT_NOT_FOUND`, `ERR_REPORT_NOT_FOUND`, `ERR_COACHING_NOT_FOUND`
        or `ERR_OVERRIDE_NOT_FOUND` (all 404)."

        Design: Corner/entities/entity_restaurant_not_found_on_absent_identifier
        """
        fx.setup_single_unbounded_band(api)
        unrelated = fx.register_restaurant(
            api, "C-2398-04", name="Corner Unrelated Store"
        )

        # validate_error also proves the body is an error envelope with a message.
        error = validate_error(
            api.get_restaurant(ABSENT_UUID, ADMIN_HEADERS), ERR_RESTAURANT_NOT_FOUND
        )
        assert error["message"].strip(), error

        untouched = fx.get_restaurant(api, unrelated["id"])
        assert untouched["version"] == 1, untouched


class TestTimerLoopListing:
    """Two stored loops, read one page at a time."""

    def test_a_one_row_page_reports_the_full_total_and_the_earlier_loop_first(
        self, api: DriveThruApiClient
    ):
        """PRD §2.3: "List responses carry four pagination fields inside the
        envelope's `meta` object: `limit`, `offset`, `total_count` and `has_more`."
        And: "Unless a specific endpoint states otherwise, every list endpoint
        returns its rows sorted by `created_at` in ascending order."

        Design: Corner/entities/entity_timer_loop_listing_paginates_with_total_count
        """
        ctx, first, second = _store_with_two_open_loops(api)

        page1, meta1 = validate_paginated(
            api.list_timer_loops(
                ADMIN_HEADERS,
                {"restaurant_id": ctx.restaurant_id, "limit": 1, "offset": 0},
            )
        )
        assert len(page1) == 1, page1
        a.assert_pagination_meta(meta1, total_count=2, has_more=True, limit=1, offset=0)
        assert page1[0]["id"] == first["id"], page1
        assert page1[0]["car_sequence"] == 1, page1

        page2, meta2 = validate_paginated(
            api.list_timer_loops(
                ADMIN_HEADERS,
                {"restaurant_id": ctx.restaurant_id, "limit": 1, "offset": 1},
            )
        )
        assert len(page2) == 1, page2
        a.assert_pagination_meta(meta2, total_count=2, has_more=False, limit=1, offset=1)
        assert page2[0]["id"] == second["id"], page2
        assert page2[0]["car_sequence"] == 2, page2

    def test_a_state_filter_that_matches_nothing_reports_a_zero_total(
        self, api: DriveThruApiClient
    ):
        """PRD §3.3: "A new loop begins at `timing_state` `OPEN` and
        `accuracy_state` `PENDING`, with `served_after_loop_id` null."

        Design: Corner/entities/entity_timer_loop_listing_paginates_with_total_count
        """
        ctx, first, second = _store_with_two_open_loops(api)

        assert first["timing_state"] == "OPEN", first
        assert second["timing_state"] == "OPEN", second

        rows, meta = validate_paginated(
            api.list_timer_loops(
                ADMIN_HEADERS,
                {"restaurant_id": ctx.restaurant_id, "timing_state": "CLOSED"},
            )
        )
        assert rows == [], rows
        assert meta["total_count"] == 0, meta


def _store_with_two_open_loops(api: DriveThruApiClient):
    """Two cars in the lane five seconds apart, neither greeted yet."""
    fx.setup_single_unbounded_band(api)
    ctx = fx.setup_store(
        api,
        "C-2398-03",
        staff_name="Paige Ortiz",
        name="Corner Listing Store",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    first = fx.open_loop(api, ctx)
    fx.set_clock(api, fx.at(11, 0, 5))
    second = fx.open_loop(api, ctx)
    return ctx, first, second


class TestDaypartProfileInputs:
    """The drafted profile's required inputs, computed sum and numeric ranges."""

    def test_omitting_a_target_with_no_default_is_rejected(
        self, api: DriveThruApiClient
    ):
        """PRD §2.11: "**Request schema** — required fields present, enum members
        recognized, numbers inside their declared ranges, datetimes ISO 8601 UTC
        with whole seconds, and `limit` inside 1 through 100. Applies to every
        endpoint with a body or query parameters. Rejection: `ERR_INVALID_REQUEST`
        (400)."

        Design: Corner/entities/entity_daypart_profile_missing_required_field_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-05",
            with_staff=False,
            with_active_lunch_profile=False,
            name="Corner Required Field Store",
        )

        validate_error(
            api.create_daypart_profile(
                f.drop(
                    f.daypart_profile_body(ctx.restaurant_id),
                    "window_target_seconds",
                ),
                ctx.operator_headers,
            ),
            ERR_INVALID_REQUEST,
        )

        _rows, meta = validate_paginated(
            api.list_daypart_profiles(
                ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id}
            )
        )
        assert meta["total_count"] == 0, meta

        store = fx.get_restaurant(api, ctx.restaurant_id)
        assert store["version"] == 1, store

    def test_the_total_target_is_the_server_s_sum_of_the_four_segments(
        self, api: DriveThruApiClient
    ):
        """PRD §3.1: "The server derives `total_target_seconds` as the plain,
        unrelieved sum of those four values."
        And: "A newly drafted profile has `profile_state` of `DRAFT`, and a store
        may hold only one profile per `daypart` whose `profile_state` is `DRAFT` or
        `ACTIVE`."

        Design: Corner/entities/entity_daypart_profile_total_target_seconds_computed
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-08",
            with_staff=False,
            with_active_lunch_profile=False,
            name="Corner Computed Total Store",
        )

        profile = validate_success(
            api.create_daypart_profile(
                f.daypart_profile_body(
                    ctx.restaurant_id,
                    daypart="BREAKFAST",
                    start_minute=360,
                    end_minute=660,
                    greet_target_seconds=20,
                    order_target_seconds=70,
                    pull_forward_target_seconds=30,
                    window_target_seconds=60,
                ),
                ctx.operator_headers,
            ),
            expected_status=201,
        )

        # 20 + 70 + 30 + 60.
        assert profile["total_target_seconds"] == 180, profile
        assert profile["profile_state"] == "DRAFT", profile
        assert profile["start_minute"] == 360, profile
        assert profile["end_minute"] == 660, profile

    def test_a_start_minute_past_the_last_minute_of_the_day_is_rejected(
        self, api: DriveThruApiClient
    ):
        """PRD §3.1: "`start_minute` is the inclusive start, expressed in minutes
        since UTC midnight, between 0 and 1439 inclusive."
        PRD §2.11: "The first violated rule in this list wins, and its error is the
        one returned."

        Design: Corner/entities/entity_daypart_profile_out_of_range_number_rejected
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-12",
            with_staff=False,
            with_active_lunch_profile=False,
            name="Corner Range Check Store",
        )

        # The body also fails the interval-ordering rule, which sits far lower.
        error_id = validate_error_is_one_of(
            api.create_daypart_profile(
                f.daypart_profile_body(
                    ctx.restaurant_id,
                    daypart="LATE",
                    start_minute=1440,
                    end_minute=1440,
                ),
                ctx.operator_headers,
            ),
            [ERR_INVALID_REQUEST, ERR_WINDOW_BOUNDS_INVALID],
        )
        assert error_id == ERR_INVALID_REQUEST, error_id

        _rows, meta = validate_paginated(
            api.list_daypart_profiles(
                ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id}
            )
        )
        assert meta["total_count"] == 0, meta


class TestStaffMemberDefaults:
    """A member added with nothing but a name and a home store."""

    def test_the_three_optional_attributes_take_their_declared_defaults(
        self, api: DriveThruApiClient
    ):
        """PRD §3.2: "Three optional attributes shape what they may be asked to do:
        `oot_certified`, which defaults to false and marks them cleared to take
        orders outside the building; `window_certified`, which also defaults to
        false and marks them cleared to hand off at the window; and
        `max_consecutive_deployment_minutes`, which defaults to 90 and must be
        between 15 and 240 inclusive — the longest single stretch this member may be
        planned for."
        And: "The server also tracks `deployed_minutes_today`, which starts at 0 and
        accumulates the labor actually charged across the member's released
        deployments."

        Design: Corner/entities/entity_staff_member_optional_inputs_take_declared_defaults
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-07",
            with_staff=False,
            with_active_lunch_profile=False,
            name="Corner Roster Defaults Store",
        )

        staff = validate_success(
            api.create_staff_member(
                {"restaurant_id": ctx.restaurant_id, "full_name": "Default Dana"},
                ctx.operator_headers,
            ),
            expected_status=201,
        )

        assert staff["oot_certified"] is False, staff
        assert staff["window_certified"] is False, staff
        assert staff["max_consecutive_deployment_minutes"] == 90, staff
        assert staff["staff_state"] == "AVAILABLE", staff
        assert staff["deployed_minutes_today"] == 0, staff
        assert staff["restaurant_id"] == ctx.restaurant_id, staff


class TestDeploymentPlannedMinutes:
    """A part-minute plan costs the whole minute."""

    def test_a_1810_second_plan_stores_31_minutes(self, api: DriveThruApiClient):
        """PRD §3.2: "From those the server derives `planned_minutes` as the
        interval's length in seconds divided by 60 and rounded **up** to the next
        whole minute — a 61-second plan therefore costs two minutes, not one."
        And: "A freshly planned deployment has `deployment_state` of `PLANNED`, its
        `activated_at` and `released_at` are null, its `labor_minutes_charged` is 0,
        and — importantly — no labor has been committed against the store yet."

        Design: Corner/entities/entity_deployment_planned_minutes_computed_with_ceiling
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-09",
            labor_minutes_budget=300,
            staff_name="Corner Casey",
            name="Corner Ceiling Store",
        )
        fx.set_clock(api, fx.at(11, 0, 0))

        # 11:00:00 to 11:30:10 is 1810 seconds, i.e. 30.1666... minutes.
        deployment = validate_success(
            api.create_deployment(
                f.deployment_body(
                    ctx.restaurant_id,
                    ctx.staff_id,
                    ctx.profile_id,
                    fx.at(11, 0, 0),
                    fx.at(11, 30, 10),
                    position="OOT_LANE_A",
                ),
                ctx.operator_headers,
            ),
            expected_status=201,
        )

        assert deployment["planned_minutes"] == 31, deployment
        assert deployment["deployment_state"] == "PLANNED", deployment
        a.assert_deployment_charge(deployment, labor_minutes_charged=0)
        a.assert_all_null(deployment, ["activated_at", "released_at"])

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(store, committed=0, available=300)


class TestVolumeTierPolicyEnum:
    """The band's merge bias accepts only the three declared ranking modes."""

    def test_an_unrecognized_merge_bias_is_rejected(self, api: DriveThruApiClient):
        """PRD §3.1: "A `ProgramAdmin` declares each band with its `tier`, its
        `cars_per_hour_floor` (which must be at least 0), an optional
        `cars_per_hour_ceiling` (omitted or null for the topmost band; otherwise
        strictly greater than the floor), its `target_relief_pct` (between 0.00 and
        0.25 inclusive — the fraction by which daypart segment targets are relaxed
        at this volume), its `min_oot_count` (between 0 and 4 inclusive — the
        outside order-takers the staffing model requires at this tier) and its
        `merge_award_bias`, which selects the ranking mode the merge selector uses
        at this volume from `ALTERNATE`, `LONGEST_WAIT` and `ACCURACY_FIRST`."

        Design: Corner/entities/entity_volume_tier_policy_unknown_enum_rejected
        """
        validate_error(
            api.create_volume_tier_policy(
                f.tier_policy_body(
                    "TIER_1",
                    cars_per_hour_floor=0,
                    cars_per_hour_ceiling=6,
                    target_relief_pct=0.0,
                    min_oot_count=0,
                    merge_award_bias="SHORTEST_LINE",
                ),
                ADMIN_HEADERS,
            ),
            ERR_INVALID_REQUEST,
        )

        _rows, meta = validate_paginated(api.list_volume_tier_policies(ADMIN_HEADERS))
        assert meta["total_count"] == 0, meta


class TestFlatTopologyBodyForeignKeys:
    """Relationships travel in the body, and the body's ids must resolve."""

    def test_an_absent_reporter_id_is_a_not_found_before_any_business_rule(
        self, api: DriveThruApiClient
    ):
        """PRD §2.12: "Existence therefore always precedes ownership, and ownership
        always precedes business rules."
        PRD §2.11: "**Body foreign-key existence** — every foreign key named in the
        body resolves to a row."

        Design: Corner/entities/entity_flat_topology_body_fk_not_found
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-13",
            staff_name="Corner Della",
            name="Corner Body FK Store",
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
            api.create_accuracy_incident(
                f.accuracy_incident_body(
                    loop["id"], ABSENT_UUID, incident_type="WRONG_SIZE"
                ),
                ctx.leader_headers,
            ),
            ERR_STAFF_NOT_FOUND,
        )

        _rows, meta = validate_paginated(
            api.list_accuracy_incidents(ADMIN_HEADERS, {"timer_loop_id": loop["id"]})
        )
        assert meta["total_count"] == 0, meta

        stored = validate_success(api.get_timer_loop(loop["id"], ADMIN_HEADERS))
        a.assert_loop_states(stored, timing_state="ORDERED", accuracy_state="PENDING")

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(store, open_remake_count=0, remake_cost_accrued_cents=0)
