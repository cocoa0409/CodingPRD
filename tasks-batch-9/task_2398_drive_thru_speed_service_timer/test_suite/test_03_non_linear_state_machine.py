"""State machines that are not simple linear chains.

A timer loop carries two dimensions that advance independently, and a coaching
intervention's revision loop is cyclic, returning to the authoring state.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as a
from test_helpers import fixtures as fx
from test_helpers.api_client import DriveThruApiClient
from test_helpers.test_users import (
    ADMIN_HEADERS,
    COACH_HEADERS,
    SECOND_COACH_HEADERS,
    SECOND_MARKET_COACH_ID,
)


# ------------------------------------------------------ the two loop dimensions
def _loop_with_an_open_remake_at_the_window(api: DriveThruApiClient):
    """A car at the window whose order was already logged as wrong."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-F",
        staff_name="Sam Okonjo",
        name="Decatur Single Lane",
    )
    remaker = fx.add_staff_member(
        api,
        ctx.restaurant_id,
        "Tess Aldana",
        oot_certified=False,
        window_certified=True,
    )
    loop = fx.drive_loop(
        api,
        ctx,
        arrive_at=fx.at(11, 0, 0),
        greet_at=fx.at(11, 0, 20),
        order_complete_at=fx.at(11, 1, 0),
        window_arrive_at=fx.at(11, 2, 0),
        depart_at=None,
        order_items_count=3,
    )
    incident = fx.log_incident(api, ctx, loop["id"], incident_type="WRONG_ITEM")
    return ctx, loop["id"], incident["id"], remaker["id"]


class TestTimerLoopParallelDimensions:
    """Timing and accuracy move on their own tracks."""

    def test_departure_does_not_verify_a_loop_that_already_carries_a_remake(self, api):
        """PRD §3.3: "Departure also auto-advances the accuracy dimension: if
        `accuracy_state` is `PENDING` at that moment it becomes `VERIFIED`, and
        if any pull-forward order of this loop is in `ISSUED` or `PARKED` it
        becomes `CLEARED` with `cleared_at` stamped."

        Design: Difficulty/non_linear_state_machine/timer_loop_parallel_dimensions_advance_independently
        """
        ctx, loop_id, incident_id, remaker_id = _loop_with_an_open_remake_at_the_window(
            api
        )

        fx.set_clock(api, fx.at(11, 4, 10))
        departed = fx.depart_loop(api, ctx, loop_id)
        a.assert_loop_states(
            departed, timing_state="CLOSED", accuracy_state="REMAKE_OPEN"
        )
        assert departed["accuracy_state"] != "VERIFIED", departed

        fx.deliver_remake(api, ctx, incident_id, remaker_id)
        loop = validate_success(api.get_timer_loop(loop_id, ADMIN_HEADERS))
        a.assert_loop_states(loop, timing_state="CLOSED", accuracy_state="REMADE")

    def test_measured_segments_and_penalty_survive_both_dimension_moves(self, api):
        """PRD §3.3: "`breach_flags` is the subset of `[GREET, ORDER,
        PULL_FORWARD, WINDOW]` — always reported in exactly that order — whose
        measured seconds are *strictly greater* than the corresponding pinned
        target"

        Design: Difficulty/non_linear_state_machine/timer_loop_parallel_dimensions_advance_independently
        """
        ctx, loop_id, incident_id, remaker_id = _loop_with_an_open_remake_at_the_window(
            api
        )

        fx.set_clock(api, fx.at(11, 4, 10))
        fx.depart_loop(api, ctx, loop_id)
        fx.deliver_remake(api, ctx, incident_id, remaker_id)

        loop = validate_success(api.get_timer_loop(loop_id, ADMIN_HEADERS))
        a.assert_loop_segments(
            loop,
            greet_seconds=20,
            order_seconds=40,
            pull_forward_seconds=60,
            window_seconds=130,
            total_seconds=250,
            adjusted_total_seconds=295,
        )
        a.assert_breach_flags(loop, ["PULL_FORWARD", "WINDOW"])

        incident = validate_success(api.get_accuracy_incident(incident_id, ADMIN_HEADERS))
        assert incident["incident_state"] == "REMADE", incident
        assert incident["settlement_state"] == "ACCRUED", incident
        assert incident["remade_by_staff_id"] == remaker_id, incident

    def test_store_rollup_reflects_the_closed_car_and_the_open_remake_together(
        self, api
    ):
        """PRD §3.2: "An **accuracy bump** of 1 applies when `open_remake_count`
        is at least 1; otherwise it is 0."

        Design: Difficulty/non_linear_state_machine/timer_loop_parallel_dimensions_advance_independently
        """
        ctx, loop_id, incident_id, remaker_id = _loop_with_an_open_remake_at_the_window(
            api
        )

        fx.set_clock(api, fx.at(11, 4, 10))
        fx.depart_loop(api, ctx, loop_id)
        fx.deliver_remake(api, ctx, incident_id, remaker_id)

        store = fx.get_restaurant(api, ctx.restaurant_id)
        a.assert_rollup(
            store,
            cars_closed_trailing=1,
            volume_tier="TIER_2",
            open_remake_count=1,
            remake_cost_accrued_cents=750,
            required_oot_count=2,
            deployed_oot_count=0,
            service_posture="SURGE",
        )


# ------------------------------------------------------- the revision loop cycle
CONTEST_REASON = "Greet delay was caused by a POS outage, not by the coachee"


def _issued_intervention_on_a_green_report(api: DriveThruApiClient):
    """A published GREEN report with a GREET intervention already issued."""
    fx.setup_four_tier_bands(api)
    ctx = fx.setup_store(
        api,
        "S-2398-G",
        staff_name="Lena Ford",
        name="Buckhead Single Lane",
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
    fx.publish_report(api, report["id"])
    coaching = fx.create_coaching(api, report["id"], ctx.staff_id, "GREET")
    fx.issue_coaching(api, coaching["id"])
    return ctx, report["id"], coaching["id"]


class TestCoachingRevisionCycle:
    """Contesting completes a two-step cycle inside a single request."""

    def test_contest_lands_back_in_draft_with_the_revision_counted(self, api):
        """PRD §3.9: "Contesting is a **cyclic** two-step that completes inside a
        single request: the intervention passes through `ISSUED → CONTESTED` and
        then, as an automatic follow-through of that same request, `CONTESTED →
        DRAFT` with `revision_count` incremented by 1."

        Design: Difficulty/non_linear_state_machine/coaching_intervention_revision_cycle_returns_to_draft
        """
        ctx, _report_id, coaching_id = _issued_intervention_on_a_green_report(api)

        contested = fx.contest_coaching(api, ctx, coaching_id, CONTEST_REASON)
        assert contested["ci_state"] == "DRAFT", contested
        assert contested["revision_count"] == 1, contested
        assert contested["contest_reason"] == CONTEST_REASON, contested

    def test_reissue_by_a_second_coach_overwrites_the_issuing_identity(self, api):
        """PRD §3.9: "It stamps the issuing coach's opaque `X-User-ID` into
        `issued_by_user_id`, overwriting whatever was there from a previous
        issue, and recomputes `segment_gap_seconds`, `priority_score` and `tier`
        in full from the report's stored figures as they now stand — so an
        intervention that goes round the revision loop can come back with a
        different score and a different `tier`."

        Design: Difficulty/non_linear_state_machine/coaching_intervention_revision_cycle_returns_to_draft
        """
        ctx, _report_id, coaching_id = _issued_intervention_on_a_green_report(api)

        fx.contest_coaching(api, ctx, coaching_id, CONTEST_REASON)
        reissued = validate_success(
            api.issue_coaching_intervention(coaching_id, SECOND_COACH_HEADERS)
        )
        assert reissued["ci_state"] == "ISSUED", reissued
        assert reissued["revision_count"] == 1, reissued
        assert reissued["issued_by_user_id"] == SECOND_MARKET_COACH_ID, reissued
        a.assert_coaching_scoring(
            reissued, segment_gap_seconds=0, priority_score=3.00, tier="TIER_A_OBSERVE"
        )

    def test_the_score_the_cycle_recomputes_comes_from_the_green_band(self, api):
        """PRD §3.9: "The intervention's `tier` follows from the score:
        `TIER_C_RETRAIN` when `priority_score` is at least 70, otherwise
        `TIER_B_COACH` when it is at least 40, otherwise `TIER_A_OBSERVE`."

        Design: Difficulty/non_linear_state_machine/coaching_intervention_revision_cycle_returns_to_draft
        """
        _ctx, report_id, coaching_id = _issued_intervention_on_a_green_report(api)

        report = validate_success(api.get_throughput_report(report_id, COACH_HEADERS))
        a.assert_report_metrics(
            report,
            attainment_pct=100.40,
            attainment_band="GREEN",
            coaching_pool_points=6,
        )

        coaching = validate_success(
            api.get_coaching_intervention(coaching_id, COACH_HEADERS)
        )
        # 60 * 0 + 25 * 0 + 15 * 0.2, the GREEN band weight alone.
        a.assert_coaching_scoring(
            coaching, segment_gap_seconds=0, priority_score=3.00, tier="TIER_A_OBSERVE"
        )
