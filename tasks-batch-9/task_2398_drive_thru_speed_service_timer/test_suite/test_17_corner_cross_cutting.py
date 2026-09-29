"""Cross-cutting layers: the store version token, and the two-open-remake threshold.

The concurrency anchor is exercised on both write paths that carry it, and the
accuracy-hold threshold is probed on both sides of its boundary.
"""

from prd_bench_local_runner.testing import (
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.api_errors import (
    ERR_MERGE_CAPACITY_EXHAUSTED,
    ERR_NO_MERGE_CANDIDATE,
    ERR_OVERRIDE_AGGREGATE_CAP,
    ERR_POSTURE_ACCURACY_HOLD,
    ERR_REPORT_WINDOW_EMPTY,
    ERR_REPORT_WINDOW_FUTURE,
    ERR_STALE_RESTAURANT_VERSION,
    ERR_WINDOW_BOUNDS_INVALID,
)
from test_helpers.test_users import ADMIN_HEADERS, COACH_HEADERS


def _store_whose_version_moved_under_the_client(api: DriveThruApiClient):
    """A store read once, then advanced by an unrelated adjustment."""
    fx.setup_single_unbounded_band(api)
    ctx = fx.setup_store(
        api,
        "C-2398-67",
        staff_name="Corner Vega",
        name="Corner Stale Token Store",
    )
    stale_version = fx.current_restaurant_version(api, ctx.restaurant_id)
    bumped = validate_success(
        api.patch_restaurant(
            ctx.restaurant_id,
            f.restaurant_patch_body(labor_minutes_budget=420),
            ctx.operator_headers,
        )
    )
    assert bumped["version"] == stale_version + 1, (stale_version, bumped)
    return ctx, stale_version, bumped["version"]


class TestOverrideCreateVersionToken:
    """The proposal carries a token the store has already outgrown."""

    def test_a_proposal_on_a_superseded_version_is_refused_without_advancing_anything(
        self, api: DriveThruApiClient
    ):
        """PRD §2.10: "`POST /drive-thru/forecast-overrides` must carry
        `expected_restaurant_version` matching the target store's current `version`. If
        the store's `version` has advanced since the client last read it, the proposal is
        rejected with `ERR_STALE_RESTAURANT_VERSION` (412)."
        And: "Several proposed overrides on overlapping windows are perfectly legitimate
        — the aggregate cap in §3.7 counts only overrides already in force — so nothing
        about the override itself precludes the write; the stale
        `expected_restaurant_version` is the only thing that identifies a writer whose
        view of `volume_tier`, `service_posture` and the in-force override set is out of
        date."
        PRD §2.5: "`Restaurant.version` deserves special attention because it is the
        concurrency anchor for the whole store."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_restaurant_version_rejects_override_create
        """
        ctx, stale_version, current_version = _store_whose_version_moved_under_the_client(
            api
        )

        # A well-formed window and a delta far inside the aggregate cap: only the
        # version token is wrong.
        error_id = validate_error_is_one_of(
            api.create_forecast_override(
                f.forecast_override_body(
                    ctx.restaurant_id,
                    fx.at(11, 0, 0),
                    fx.at(14, 0, 0),
                    0.20,
                    stale_version,
                    source="WEATHER",
                ),
                ctx.operator_headers,
            ),
            [
                ERR_STALE_RESTAURANT_VERSION,
                ERR_OVERRIDE_AGGREGATE_CAP,
                ERR_WINDOW_BOUNDS_INVALID,
            ],
        )
        assert error_id == ERR_STALE_RESTAURANT_VERSION

        _rows, meta = validate_paginated(
            api.list_forecast_overrides(
                ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id}
            )
        )
        assert meta["total_count"] == 0, meta
        assert (
            fx.current_restaurant_version(api, ctx.restaurant_id) == current_version
        ), current_version


class TestReportCreateVersionToken:
    """The same anchor guards the other write that carries it."""

    def test_a_report_computed_from_a_stale_view_is_refused_before_its_window_is_scored(
        self, api: DriveThruApiClient
    ):
        """PRD §2.10: "`POST /drive-thru/throughput-reports` must likewise carry
        `expected_restaurant_version` matching the target store's current `version`, and
        a mismatch is rejected with `ERR_STALE_RESTAURANT_VERSION` (412)."
        And: "No other endpoint accepts a version field, and no other endpoint performs a
        version check. Both of these operations, on success, increment the store's
        `version` by 1."
        PRD §2.11: "**Non-empty report** — the report being published has a `cars_served`
        of at least 1. Applies to `POST /drive-thru/throughput-reports/{reportId}/publish`.
        Rejection: `ERR_REPORT_WINDOW_EMPTY` (422)."

        Design: Corner/cross_cutting_complexity_layers/occ_stale_restaurant_version_rejects_report_create
        """
        ctx, stale_version, current_version = _store_whose_version_moved_under_the_client(
            api
        )
        # The window closes exactly on the clock, so it is not a future window.
        fx.set_clock(api, fx.at(11, 5, 0))

        error_id = validate_error_is_one_of(
            api.create_throughput_report(
                f.throughput_report_body(
                    ctx.restaurant_id,
                    fx.at(11, 0, 0),
                    fx.at(11, 5, 0),
                    stale_version,
                    variant="PROVISIONAL",
                ),
                COACH_HEADERS,
            ),
            [
                ERR_STALE_RESTAURANT_VERSION,
                ERR_REPORT_WINDOW_FUTURE,
                ERR_REPORT_WINDOW_EMPTY,
            ],
        )
        assert error_id == ERR_STALE_RESTAURANT_VERSION

        _rows, meta = validate_paginated(
            api.list_throughput_reports(
                ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id}
            )
        )
        assert meta["total_count"] == 0, meta
        assert (
            fx.current_restaurant_version(api, ctx.restaurant_id) == current_version
        ), current_version


class TestTokenIsSpentByItsOwnSuccess:
    """The winning write is itself the write that invalidates the token."""

    def test_replaying_the_token_that_just_worked_is_refused_on_freshness_alone(
        self, api: DriveThruApiClient
    ):
        """PRD §2.10: "No other endpoint accepts a version field, and no other endpoint
        performs a version check. Both of these operations, on success, increment the
        store's `version` by 1."
        PRD §3.7: "A proposed override starts at `fo_state` `PROPOSED`, with
        `approved_by_user_id` and `rejection_reason` null, and it has **no effect
        whatsoever** on any store rollup — proposing changes no target and no tier."
        PRD §2.5: "`version` (integer): a monotonically increasing integer that starts at
        1 on creation and increments by exactly 1 on every mutation of that resource."

        Design: Corner/cross_cutting_complexity_layers/occ_fresh_version_succeeds_then_the_same_token_is_stale
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-68",
            with_staff=False,
            with_active_lunch_profile=False,
            name="Corner Spent Token Store",
        )
        fx.set_clock(api, fx.at(11, 0, 0))
        first_token = fx.current_restaurant_version(api, ctx.restaurant_id)
        body = f.forecast_override_body(
            ctx.restaurant_id,
            fx.at(11, 0, 0),
            fx.at(13, 0, 0),
            0.15,
            first_token,
            source="LOCAL_EVENT",
        )

        proposed = validate_success(
            api.create_forecast_override(body, ctx.operator_headers),
            expected_status=201,
        )
        assert proposed["fo_state"] == "PROPOSED", proposed

        after_first = fx.get_restaurant(api, ctx.restaurant_id)
        second_token = after_first["version"]
        assert second_token == first_token + 1, (first_token, second_token)
        # Nothing about the store's derived numbers moved; only its version did.
        a.assert_rollup(
            after_first, cars_per_hour_effective=0.0, volume_tier="TIER_1"
        )
        assert after_first["staffing_basis"] == "OBSERVED", after_first

        error_id = validate_error_is_one_of(
            api.create_forecast_override(body, ctx.operator_headers),
            [ERR_STALE_RESTAURANT_VERSION, ERR_OVERRIDE_AGGREGATE_CAP],
        )
        assert error_id == ERR_STALE_RESTAURANT_VERSION

        _rows, meta = validate_paginated(
            api.list_forecast_overrides(
                ADMIN_HEADERS,
                {"restaurant_id": ctx.restaurant_id, "fo_state": "PROPOSED"},
            )
        )
        assert meta["total_count"] == 1, meta

        # Two proposals over the very same window are legitimate — only the token
        # had gone stale.
        replayed = validate_success(
            api.create_forecast_override(
                f.forecast_override_body(
                    ctx.restaurant_id,
                    fx.at(11, 0, 0),
                    fx.at(13, 0, 0),
                    0.15,
                    second_token,
                    source="LOCAL_EVENT",
                ),
                ctx.operator_headers,
            ),
            expected_status=201,
        )
        assert replayed["fo_state"] == "PROPOSED", replayed
        assert replayed["id"] != proposed["id"], replayed


class TestAccuracyHoldThreshold:
    """One open remake is a staffing signal; two are a stop order."""

    def test_the_second_open_remake_is_what_closes_the_merge_lane(
        self, api: DriveThruApiClient
    ):
        """PRD §2.6: "`ACCURACY_HOLD` is narrower. It blocks exactly one operation,
        `POST /drive-thru/restaurants/{restaurantId}/merge-award`, with
        `ERR_POSTURE_ACCURACY_HOLD` (409), and it does so for as long as the store carries
        two or more open remakes. `SURGE` blocks nothing; it is a staffing signal that the
        store is short of outside order-takers."
        PRD §3.2: "An **accuracy bump** of 1 applies when `open_remake_count` is at least
        1; otherwise it is 0."
        PRD §2.11: "Note the consequences of the ladder's shape for the merge award, which
        is guarded four times: the accuracy-hold posture (11) outranks tier coverage (25),
        which outranks candidate availability (30), which outranks free capacity (32). A
        store in `ACCURACY_HOLD` with an exhausted merge lane reports the posture error,
        not the capacity error."
        PRD §3.4: "Eligibility comes first: a candidate is a loop of this store whose
        `timing_state` is `ORDERED`, whose `accuracy_state` is either `PENDING` or
        `VERIFIED`, for which no merge slot is currently in `RESERVED` or `COMMITTED`, and
        for which no pull-forward order is currently in `ISSUED` or `PARKED`."

        Design: Corner/cross_cutting_complexity_layers/rate_threshold_second_open_remake_flips_store_to_accuracy_hold
        """
        fx.setup_single_unbounded_band(api)
        ctx = fx.setup_store(
            api,
            "C-2398-69",
            lane_config="DUAL_PARALLEL",
            merge_slots_capacity=2,
            staff_name="Corner Wren",
            name="Corner Accuracy Threshold Store",
        )
        a.assert_rollup(ctx.restaurant, service_posture="OPEN", open_remake_count=0)

        pad = {}
        for label, lane, arrive_second in (
            ("X", "LANE_A", 0),
            ("Y", "LANE_A", 5),
            ("Z", "LANE_B", 10),
            ("W", "LANE_B", 15),
        ):
            fx.set_clock(api, fx.at(11, 0, arrive_second))
            pad[label] = fx.open_loop(api, ctx, lane=lane)
        for label, greet_second in (("X", 20), ("Y", 25), ("Z", 30), ("W", 35)):
            fx.set_clock(api, fx.at(11, 0, greet_second))
            fx.greet_loop(api, ctx, pad[label]["id"])
        for label, order_second in (("X", 0), ("Y", 10), ("Z", 20), ("W", 30)):
            fx.set_clock(api, fx.at(11, 1, order_second))
            fx.complete_order(api, ctx, pad[label]["id"], order_items_count=3)

        fx.set_clock(api, fx.at(11, 1, 40))
        fx.log_incident(api, ctx, pad["X"]["id"], incident_type="WRONG_SIZE")
        at_one = fx.get_restaurant(api, ctx.restaurant_id)
        # min_oot 0, no lane bump at a 0.0 car rate, plus the accuracy bump of 1.
        a.assert_rollup(
            at_one,
            open_remake_count=1,
            required_oot_count=1,
            deployed_oot_count=0,
            service_posture="SURGE",
        )

        # SURGE never blocks the award: X is out for its open remake, and Y holds
        # the earliest order completion among the rest.
        slot = fx.award_merge_slot(api, ctx)
        assert slot["timer_loop_id"] == pad["Y"]["id"], slot
        assert slot["award_reason"] == "ALTERNATE", slot
        assert slot["slot_state"] == "RESERVED", slot

        fx.set_clock(api, fx.at(11, 1, 50))
        fx.log_incident(api, ctx, pad["Z"]["id"], incident_type="MISSING_ITEM")
        at_two = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            at_two,
            open_remake_count=2,
            service_posture="ACCURACY_HOLD",
            remake_cost_accrued_cents=1100,
        )
        # One slot of two is taken, so capacity is not exhausted.
        a.assert_merge_capacity(at_two, free=1)

        error_id = validate_error_is_one_of(
            api.award_merge_slot(ctx.restaurant_id, ctx.leader_headers),
            [
                ERR_POSTURE_ACCURACY_HOLD,
                ERR_NO_MERGE_CANDIDATE,
                ERR_MERGE_CAPACITY_EXHAUSTED,
            ],
        )
        assert error_id == ERR_POSTURE_ACCURACY_HOLD

        _rows, meta = validate_paginated(
            api.list_merge_slots(ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id})
        )
        assert meta["total_count"] == 1, meta
        # W was and remains an eligible candidate that simply never got a slot.
        stranded = validate_success(
            api.get_timer_loop(pad["W"]["id"], ADMIN_HEADERS)
        )
        a.assert_loop_states(
            stranded, timing_state="ORDERED", accuracy_state="PENDING"
        )
        assert stranded["merge_at"] is None, stranded
