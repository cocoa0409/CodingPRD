"""Interval geometry: what counts as touching and what counts as overlapping.

Daypart windows are half-open, deployment intervals are closed and additionally
buffered, and applied override windows are closed with touching endpoints
counting as an intersection.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.api_errors import (
    ERR_DAYPART_WINDOW_OVERLAP,
    ERR_DEPLOYMENT_BUFFER_VIOLATION,
    ERR_OVERRIDE_AGGREGATE_CAP,
)
from test_helpers.test_users import ADMIN_HEADERS


# --------------------------------------------- half-open daypart minute windows
def _store_with_one_active_daypart_and_two_drafts(api: DriveThruApiClient):
    """LUNCH is active; an adjacent AFTERNOON and an overlapping DINNER are drafted."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-S",
        with_staff=False,
        name="Norcross Calendar Store",
    )
    afternoon = fx.create_daypart_profile(
        api,
        ctx.restaurant_id,
        daypart="AFTERNOON",
        start_minute=840,
        end_minute=1020,
        greet_target_seconds=22,
        order_target_seconds=80,
        pull_forward_target_seconds=35,
        window_target_seconds=65,
    )
    dinner = fx.create_daypart_profile(
        api,
        ctx.restaurant_id,
        daypart="DINNER",
        start_minute=830,
        end_minute=1000,
        greet_target_seconds=24,
        order_target_seconds=90,
        pull_forward_target_seconds=38,
        window_target_seconds=70,
    )
    return ctx, afternoon, dinner


class TestDaypartWindowGeometry:
    """Touching dayparts may both be active; overlapping ones may not."""

    def test_a_daypart_that_merely_touches_the_active_one_activates(self, api):
        """PRD §3.1: "The geometry is genuinely half-open: two dayparts that merely
        touch — where the earlier profile's `end_minute` equals this profile's
        `start_minute` — do not overlap and both may be active."

        Design: Difficulty/resource_temporal_overlap/daypart_half_open_adjacency_allowed_overlap_rejected
        """
        ctx, afternoon, _dinner = _store_with_one_active_daypart_and_two_drafts(api)

        activated = validate_success(
            api.activate_daypart_profile(afternoon["id"], ctx.operator_headers)
        )
        assert activated["profile_state"] == "ACTIVE", activated
        # 22 + 80 + 35 + 65, the plain unrelieved sum.
        assert activated["total_target_seconds"] == 202, activated

    def test_a_daypart_overlapping_an_active_one_is_rejected(self, api):
        """PRD §3.1: "Activation requires the profile to be in `DRAFT` and the store
        not to be frozen, and it requires that the profile's half-open minute
        window from `start_minute` up to but excluding `end_minute` does not
        overlap the window of any other profile of the same store whose
        `profile_state` is `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/daypart_half_open_adjacency_allowed_overlap_rejected
        """
        ctx, afternoon, dinner = _store_with_one_active_daypart_and_two_drafts(api)

        fx.activate_profile(api, ctx.restaurant_id, afternoon["id"])

        validate_error(
            api.activate_daypart_profile(dinner["id"], ctx.operator_headers),
            ERR_DAYPART_WINDOW_OVERLAP,
        )

        stored = validate_success(
            api.get_daypart_profile(dinner["id"], ADMIN_HEADERS)
        )
        assert stored["profile_state"] == "DRAFT", stored

    def test_exactly_the_two_non_overlapping_dayparts_end_up_active(self, api):
        """PRD §3.1: "Profiles may be listed with filters on `restaurant_id`,
        `daypart` and `profile_state`, and read individually."

        Design: Difficulty/resource_temporal_overlap/daypart_half_open_adjacency_allowed_overlap_rejected
        """
        ctx, afternoon, dinner = _store_with_one_active_daypart_and_two_drafts(api)

        fx.activate_profile(api, ctx.restaurant_id, afternoon["id"])
        validate_error(
            api.activate_daypart_profile(dinner["id"], ctx.operator_headers),
            ERR_DAYPART_WINDOW_OVERLAP,
        )

        rows, meta = validate_paginated(
            api.list_daypart_profiles(
                ADMIN_HEADERS,
                {"restaurant_id": ctx.restaurant_id, "profile_state": "ACTIVE"},
            )
        )
        assert meta["total_count"] == 2, meta
        assert {row["daypart"] for row in rows} == {"LUNCH", "AFTERNOON"}, rows


# ------------------------------------------- closed, buffered deployment windows
def _store_with_one_planned_deployment(api: DriveThruApiClient):
    """A member booked from 11:00 to 11:30 inclusive."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-T",
        staff_name="Kit Bello",
        name="Duluth Changeover Store",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    first = fx.plan_deployment(api, ctx, fx.at(11, 0, 0), fx.at(11, 30, 0))
    return ctx, first


def _plan_body(ctx, start: str, end: str) -> dict:
    return {
        "restaurant_id": ctx.restaurant_id,
        "staff_member_id": ctx.staff_id,
        "daypart_profile_id": ctx.profile_id,
        "position": "OOT_LANE_A",
        "planned_start_at": start,
        "planned_end_at": end,
    }


class TestDeploymentChangeoverBuffer:
    """Back-to-back is rejected; ten clear minutes is accepted."""

    def test_a_back_to_back_plan_is_rejected(self, api):
        """PRD §3.2: "Because these intervals are closed and the buffer is additive,
        back-to-back deployments that merely touch are rejected, with
        `ERR_DEPLOYMENT_BUFFER_VIOLATION`."

        Design: Difficulty/resource_temporal_overlap/deployment_closed_interval_buffer_rejects_adjacency
        """
        ctx, first = _store_with_one_planned_deployment(api)

        a.assert_deployment_charge(first, planned_minutes=30)
        validate_error(
            api.create_deployment(
                _plan_body(ctx, fx.at(11, 30, 0), fx.at(12, 0, 0)),
                ctx.operator_headers,
            ),
            ERR_DEPLOYMENT_BUFFER_VIOLATION,
        )

    def test_a_plan_exactly_ten_minutes_later_is_accepted(self, api):
        """PRD §3.2: "For every *other* deployment of the same member whose
        `deployment_state` is `PLANNED` or `ACTIVE`, the new deployment must
        satisfy one of two conditions — either its `planned_start_at` is at or
        after that other deployment's `planned_end_at` plus 600 seconds, or its
        `planned_end_at` plus 600 seconds is at or before that other
        deployment's `planned_start_at`."

        Design: Difficulty/resource_temporal_overlap/deployment_closed_interval_buffer_rejects_adjacency
        """
        ctx, _first = _store_with_one_planned_deployment(api)

        validate_error(
            api.create_deployment(
                _plan_body(ctx, fx.at(11, 30, 0), fx.at(12, 0, 0)),
                ctx.operator_headers,
            ),
            ERR_DEPLOYMENT_BUFFER_VIOLATION,
        )

        second = validate_success(
            api.create_deployment(
                _plan_body(ctx, fx.at(11, 40, 0), fx.at(12, 10, 0)),
                ctx.operator_headers,
            ),
            expected_status=201,
        )
        assert second["deployment_state"] == "PLANNED", second
        a.assert_deployment_charge(second, planned_minutes=30)

    def test_planning_twice_commits_no_labor_and_deploys_nobody(self, api):
        """PRD §3.2: "The labor ledger is a four-state accounting story, and each
        state moves money differently. Planning commits nothing."

        Design: Difficulty/resource_temporal_overlap/deployment_closed_interval_buffer_rejects_adjacency
        """
        ctx, _first = _store_with_one_planned_deployment(api)

        validate_error(
            api.create_deployment(
                _plan_body(ctx, fx.at(11, 30, 0), fx.at(12, 0, 0)),
                ctx.operator_headers,
            ),
            ERR_DEPLOYMENT_BUFFER_VIOLATION,
        )
        validate_success(
            api.create_deployment(
                _plan_body(ctx, fx.at(11, 40, 0), fx.at(12, 10, 0)),
                ctx.operator_headers,
            ),
            expected_status=201,
        )

        _rows, meta = validate_paginated(
            api.list_deployments(ADMIN_HEADERS, {"staff_member_id": ctx.staff_id})
        )
        assert meta["total_count"] == 2, meta

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_labor_ledger(store, committed=0, available=300)
        staff = validate_success(api.get_staff_member(ctx.staff_id, ADMIN_HEADERS))
        assert staff["staff_state"] == "AVAILABLE", staff
        assert staff["deployed_minutes_today"] == 0, staff


# --------------------------------------- closed override windows and the 0.50 cap
def _store_with_one_applied_override_and_two_approved(api: DriveThruApiClient):
    """A 0.30 event override in force, plus a 0.25 and a 0.20 waiting to apply."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-U",
        with_staff=False,
        name="Stone Mountain Event Store",
    )
    fx.set_clock(api, fx.at(11, 0, 0))
    first = fx.applied_override(
        api,
        ctx,
        fx.at(11, 0, 0),
        fx.at(13, 0, 0),
        projected_cars_delta_pct=0.30,
        source="LOCAL_EVENT",
    )
    second = fx.propose_override(
        api,
        ctx,
        fx.at(12, 0, 0),
        fx.at(14, 0, 0),
        projected_cars_delta_pct=0.25,
        source="WEATHER",
    )
    fx.approve_override(api, second["id"])
    third = fx.propose_override(
        api,
        ctx,
        fx.at(12, 0, 0),
        fx.at(14, 0, 0),
        projected_cars_delta_pct=0.20,
        source="SYSTEM_OUTAGE",
    )
    fx.approve_override(api, third["id"])
    return ctx, first, second, third


class TestOverrideAggregateCap:
    """Intersecting applied deltas may total 0.50 but no more."""

    def test_a_total_above_the_cap_is_rejected(self, api):
        """PRD §3.7: "take every override of this store whose `fo_state` is
        `APPLIED` and whose closed interval intersects this one — touching
        endpoints count as intersecting — sum the absolute values of their
        `projected_cars_delta_pct`, add the absolute value of this override's own
        `projected_cars_delta_pct`, and the total must not exceed 0.50."

        Design: Difficulty/resource_temporal_overlap/override_aggregate_cap_on_intersecting_windows
        """
        ctx, first, second, _third = _store_with_one_applied_override_and_two_approved(
            api
        )

        assert first["fo_state"] == "APPLIED", first
        # 0.30 already in force plus 0.25 would be 0.55.
        validate_error(
            api.apply_forecast_override(second["id"], ctx.operator_headers),
            ERR_OVERRIDE_AGGREGATE_CAP,
        )

        stored = validate_success(
            api.get_forecast_override(second["id"], ADMIN_HEADERS)
        )
        assert stored["fo_state"] == "APPROVED", stored

    def test_a_total_exactly_at_the_cap_is_accepted(self, api):
        """PRD §3.7: "Putting an approved override into force is the `Operator`'s
        act, moving it `APPROVED → APPLIED`."

        Design: Difficulty/resource_temporal_overlap/override_aggregate_cap_on_intersecting_windows
        """
        ctx, _first, second, third = _store_with_one_applied_override_and_two_approved(
            api
        )

        validate_error(
            api.apply_forecast_override(second["id"], ctx.operator_headers),
            ERR_OVERRIDE_AGGREGATE_CAP,
        )

        # 0.30 already in force plus 0.20 is exactly 0.50.
        applied = validate_success(
            api.apply_forecast_override(third["id"], ctx.operator_headers)
        )
        assert applied["fo_state"] == "APPLIED", applied

    def test_only_the_two_admitted_overrides_are_in_force(self, api):
        """PRD §3.7: "Note that the cap counts only overrides already in force,
        which is exactly why several `PROPOSED` overrides on overlapping windows
        are legitimate."

        Design: Difficulty/resource_temporal_overlap/override_aggregate_cap_on_intersecting_windows
        """
        ctx, first, second, third = _store_with_one_applied_override_and_two_approved(
            api
        )

        validate_error(
            api.apply_forecast_override(second["id"], ctx.operator_headers),
            ERR_OVERRIDE_AGGREGATE_CAP,
        )
        fx.apply_override(api, ctx, third["id"])

        rows, meta = validate_paginated(
            api.list_forecast_overrides(
                ADMIN_HEADERS,
                {"restaurant_id": ctx.restaurant_id, "fo_state": "APPLIED"},
            )
        )
        assert meta["total_count"] == 2, meta
        assert {row["id"] for row in rows} == {first["id"], third["id"]}, rows

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_per_hour_observed=0.0,
            volume_tier="TIER_1",
            service_posture="OPEN",
        )
