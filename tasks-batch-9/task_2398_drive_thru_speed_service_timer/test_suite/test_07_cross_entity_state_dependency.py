"""Creations whose outcome depends on another entity's state alone.

In both scenarios a byte-for-byte identical payload is first rejected and then
accepted, with nothing changed but the state of the entity it references.
"""

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.api_errors import ERR_PROFILE_NOT_ACTIVE, ERR_REPORT_NOT_PUBLISHED
from test_helpers.test_users import ADMIN_HEADERS, COACH_HEADERS


# --------------------------------------- a loop needs its profile to be ACTIVE
def _store_whose_lunch_profile_is_still_a_draft(api: DriveThruApiClient):
    """A fully-provisioned store whose only lunch profile was never activated."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-Q",
        staff_name="Hana Silva",
        name="Kennesaw Draft Daypart",
        with_active_lunch_profile=False,
    )
    profile = fx.create_daypart_profile(api, ctx.restaurant_id)
    ctx.profile = profile
    fx.set_clock(api, fx.at(11, 0, 0))
    return ctx, profile


def _loop_payload(ctx) -> dict:
    return {
        "restaurant_id": ctx.restaurant_id,
        "daypart_profile_id": ctx.profile_id,
        "lane": "SINGLE",
    }


class TestTimerLoopNeedsAnActiveProfile:
    """The referenced profile's state alone decides the outcome."""

    def test_a_draft_profile_blocks_loop_creation(self, api):
        """PRD §3.3: "Creation requires the named profile to be in `ACTIVE`, and it
        requires the logical clock's minute-of-day to fall inside that profile's
        half-open window — at or after `start_minute` and strictly before
        `end_minute` — or the request fails with `ERR_DAYPART_WINDOW_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/timer_loop_creation_requires_active_daypart_profile
        """
        ctx, profile = _store_whose_lunch_profile_is_still_a_draft(api)

        assert profile["profile_state"] == "DRAFT", profile
        validate_error(
            api.create_timer_loop(_loop_payload(ctx), ctx.leader_headers),
            ERR_PROFILE_NOT_ACTIVE,
        )

        _rows, meta = validate_paginated(
            api.list_timer_loops(ADMIN_HEADERS, {"restaurant_id": ctx.restaurant_id})
        )
        assert meta["total_count"] == 0, meta

    def test_the_identical_payload_succeeds_once_the_profile_is_active(self, api):
        """PRD §3.1: "Activation recomputes `total_target_seconds` and makes the
        profile usable for timer-loop creation."

        Design: Difficulty/cross_entity_state_dependency/timer_loop_creation_requires_active_daypart_profile
        """
        ctx, profile = _store_whose_lunch_profile_is_still_a_draft(api)

        validate_error(
            api.create_timer_loop(_loop_payload(ctx), ctx.leader_headers),
            ERR_PROFILE_NOT_ACTIVE,
        )

        activated = fx.activate_profile(api, ctx.restaurant_id, profile["id"])
        assert activated["profile_state"] == "ACTIVE", activated

        loop = validate_success(
            api.create_timer_loop(_loop_payload(ctx), ctx.leader_headers),
            expected_status=201,
        )
        assert loop["car_sequence"] == 1, loop
        assert loop["target_total_seconds_pinned"] == 235, loop

    def test_the_accepted_loop_opens_with_the_pinned_profile_targets(self, api):
        """PRD §3.3: "The server stamps `arrive_at` from the logical clock and
        assigns `car_sequence`, a per-store monotone integer starting at 1 that
        becomes the pinned tie-break for every order-sensitive rule downstream. A
        new loop begins at `timing_state` `OPEN` and `accuracy_state` `PENDING`,
        with `served_after_loop_id` null."

        Design: Difficulty/cross_entity_state_dependency/timer_loop_creation_requires_active_daypart_profile
        """
        ctx, profile = _store_whose_lunch_profile_is_still_a_draft(api)

        validate_error(
            api.create_timer_loop(_loop_payload(ctx), ctx.leader_headers),
            ERR_PROFILE_NOT_ACTIVE,
        )
        fx.activate_profile(api, ctx.restaurant_id, profile["id"])
        loop = validate_success(
            api.create_timer_loop(_loop_payload(ctx), ctx.leader_headers),
            expected_status=201,
        )

        a.assert_loop_states(loop, timing_state="OPEN", accuracy_state="PENDING")
        a.assert_pinned_targets(loop, 25, 95, 40, 75, total=235)
        assert loop["arrive_at"] == fx.at(11, 0, 0), loop
        assert loop["served_after_loop_id"] is None, loop


# ------------------------------- coaching needs its report to be PUBLISHED
def _store_with_a_scored_but_unpublished_report(api: DriveThruApiClient):
    """One clean car and a DRAFT report whose metrics are already complete."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-R",
        staff_name="Bo Trammell",
        name="Tucker Draft Report",
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
    report = fx.create_report(api, ctx, fx.at(11, 0, 0), fx.at(11, 5, 0))
    return ctx, report


def _coaching_payload(ctx, report_id: str) -> dict:
    return {
        "throughput_report_id": report_id,
        "staff_member_id": ctx.staff_id,
        "focus_segment": "GREET",
    }


class TestCoachingNeedsAPublishedReport:
    """A complete but unpublished number cannot justify coaching."""

    def test_a_draft_report_blocks_the_intervention(self, api):
        """PRD §3.9: "The referenced report must be in `PUBLISHED`, or the draft is
        rejected with `ERR_REPORT_NOT_PUBLISHED`, and the report's store must
        match the coachee's store."

        Design: Difficulty/cross_entity_state_dependency/coaching_creation_requires_published_report
        """
        ctx, report = _store_with_a_scored_but_unpublished_report(api)

        # Only the state blocks coaching; the metrics are already complete.
        assert report["report_state"] == "DRAFT", report
        a.assert_report_metrics(
            report, attainment_band="GREEN", coaching_pool_points=6
        )

        validate_error(
            api.create_coaching_intervention(
                _coaching_payload(ctx, report["id"]), COACH_HEADERS
            ),
            ERR_REPORT_NOT_PUBLISHED,
        )

        _rows, meta = validate_paginated(
            api.list_coaching_interventions(
                COACH_HEADERS, {"throughput_report_id": report["id"]}
            )
        )
        assert meta["total_count"] == 0, meta

    def test_the_identical_payload_succeeds_once_the_report_is_published(self, api):
        """PRD §3.8: "Publishing is what makes coaching possible at all."

        Design: Difficulty/cross_entity_state_dependency/coaching_creation_requires_published_report
        """
        ctx, report = _store_with_a_scored_but_unpublished_report(api)

        validate_error(
            api.create_coaching_intervention(
                _coaching_payload(ctx, report["id"]), COACH_HEADERS
            ),
            ERR_REPORT_NOT_PUBLISHED,
        )

        published = fx.publish_report(api, report["id"])
        assert published["report_state"] == "PUBLISHED", published

        coaching = validate_success(
            api.create_coaching_intervention(
                _coaching_payload(ctx, report["id"]), COACH_HEADERS
            ),
            expected_status=201,
        )
        # greet_seconds 20 beat the pinned 25, so the gap floors at 0.
        a.assert_coaching_scoring(
            coaching, segment_gap_seconds=0, priority_score=3.00, tier="TIER_A_OBSERVE"
        )

    def test_the_accepted_intervention_starts_unissued(self, api):
        """PRD §3.9: "The server copies the report's `restaurant_id` onto the
        intervention, sets `ci_state` to `DRAFT`, sets `revision_count` to 0, and
        leaves `issued_by_user_id`, `contest_reason` and `closure_note` null."

        Design: Difficulty/cross_entity_state_dependency/coaching_creation_requires_published_report
        """
        ctx, report = _store_with_a_scored_but_unpublished_report(api)

        validate_error(
            api.create_coaching_intervention(
                _coaching_payload(ctx, report["id"]), COACH_HEADERS
            ),
            ERR_REPORT_NOT_PUBLISHED,
        )
        fx.publish_report(api, report["id"])
        coaching = validate_success(
            api.create_coaching_intervention(
                _coaching_payload(ctx, report["id"]), COACH_HEADERS
            ),
            expected_status=201,
        )

        assert coaching["ci_state"] == "DRAFT", coaching
        assert coaching["revision_count"] == 0, coaching
        assert coaching["restaurant_id"] == ctx.restaurant_id, coaching
        a.assert_all_null(
            coaching, ["issued_by_user_id", "contest_reason", "closure_note"]
        )
        assert is_valid_uuid(coaching["id"]), coaching
