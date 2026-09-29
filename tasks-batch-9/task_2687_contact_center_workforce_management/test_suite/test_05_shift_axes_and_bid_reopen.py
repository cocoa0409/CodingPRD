"""Two non-linear state machines: the shift's parallel axes and the cyclic bid round."""

from prd_bench_local_runner.testing import validate_error

from test_helpers import factories as f
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_agent_coaching,
    assert_cycle_ledgers,
    assert_ratio,
    assert_shift_adherence,
    assert_shift_axes,
)
from test_helpers.constants import (
    ADHERENCE_OUT_OF_ADHERENCE,
    BID_STATUS_SUBMITTED,
    COACHING_ACTIVE,
    COACHING_CLEARED,
    PUBLICATION_CANCELLED,
    PUBLICATION_PUBLISHED,
    ROUND_STATUS_AWARDED,
    ROUND_STATUS_OPEN,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    award_round,
    build_published_week,
    cancel_shift,
    make_agent,
    make_bid_round,
    make_labor_agreement,
    make_planning_cycle,
    make_shift_bid,
    make_shift_template,
    open_round,
    read_agent,
    read_bid,
    read_cycle,
    read_round,
    read_shift,
    read_template,
    record_observation,
    score_round,
    set_clock,
    set_round_status,
)
from test_helpers.test_users import INTRADAY_USER_ID, SCHEDULER_HEADERS


class TestShiftParallelAxes:
    """One row, two state dimensions that never overwrite one another."""

    def test_an_observation_moves_only_the_adherence_axis(self, api):
        """Recording 5400 non-adherent seconds scores 0.8000 while publication stays PUBLISHED.

        "Movement on the publication axis never reads or writes the adherence
        axis, and movement on the adherence axis never reads or writes the
        publication axis."

        Design: Difficulty/non_linear_state_machine/schedule_shift_parallel_publication_and_adherence_axes
        """
        world = build_published_week(api)

        observed = record_observation(api, world["shift"]["id"], 5400)

        assert_shift_axes(
            observed,
            publication_status=PUBLICATION_PUBLISHED,
            adherence_status=ADHERENCE_OUT_OF_ADHERENCE,
        )
        assert_shift_adherence(observed, adherence_pct=0.8000)
        assert observed["scheduled_seconds"] == 27000

    def test_the_flagging_controller_is_stamped_on_the_shift(self, api):
        """The observation records the acting controller as the flagging identifier.

        "Every transition into `OUT_OF_ADHERENCE` stamps `flagged_by_user_id` with
        the acting controller's `X-User-ID`, and that stored identifier is the
        value the segregation-of-duties check consumes when a coach later
        adjudicates."

        Design: Difficulty/non_linear_state_machine/schedule_shift_parallel_publication_and_adherence_axes
        """
        world = build_published_week(api)

        observed = record_observation(api, world["shift"]["id"], 5400)

        assert_shift_adherence(observed, flagged_by_user_id=INTRADAY_USER_ID)

    def test_cancelling_the_publication_leaves_the_adherence_axis_frozen(self, api):
        """After cancellation the shift is CANCELLED yet still reports its 0.8000 flag.

        "Movement on the publication axis never reads or writes the adherence
        axis, and movement on the adherence axis never reads or writes the
        publication axis."

        Design: Difficulty/non_linear_state_machine/schedule_shift_parallel_publication_and_adherence_axes
        """
        world = build_published_week(api)
        record_observation(api, world["shift"]["id"], 5400)

        cancel_shift(api, world["shift"]["id"])

        final = read_shift(api, world["shift"]["id"])
        assert_shift_axes(
            final,
            publication_status=PUBLICATION_CANCELLED,
            adherence_status=ADHERENCE_OUT_OF_ADHERENCE,
        )
        assert_shift_adherence(
            final, adherence_pct=0.8000, flagged_by_user_id=INTRADAY_USER_ID
        )

    def test_cancellation_drops_the_shift_out_of_the_agent_scored_set(self, api):
        """Losing its publication takes the shift out of the rollup, so the agent snaps to 1.0000.

        "The scored set is the agent's shifts whose `publication_status` is
        `PUBLISHED` and whose `adherence_status` is anything other than `PENDING`;
        draft shifts, cancelled shifts and never-observed shifts are all excluded,
        which is why cancelling a published shift shifts the agent's score."

        Design: Difficulty/non_linear_state_machine/schedule_shift_parallel_publication_and_adherence_axes
        """
        world = build_published_week(api)
        record_observation(api, world["shift"]["id"], 5400)
        assert_agent_coaching(
            read_agent(api, world["agent"]["id"]),
            coaching_flag_count=1,
            coaching_status=COACHING_ACTIVE,
        )

        cancel_shift(api, world["shift"]["id"])

        assert_agent_coaching(
            read_agent(api, world["agent"]["id"]),
            adherence_pct=1.0000,
            coaching_flag_count=0,
            coaching_status=COACHING_CLEARED,
        )

    def test_cancellation_also_releases_the_scheduled_hours(self, api):
        """The cancelled shift stops contributing to the cycle's scheduled-hours ledger.

        "On success it recomputes the agent's `scheduled_hours_committed` and the
        cycle's `total_scheduled_hours`, recomputes coverage on every interval the
        shift previously covered and re-evaluates the posture edges, and recomputes
        the agent's `coaching_flag_count` and `adherence_pct`, since a cancelled
        shift leaves the agent's scored set entirely."

        Design: Difficulty/non_linear_state_machine/schedule_shift_parallel_publication_and_adherence_axes
        """
        world = build_published_week(api)
        record_observation(api, world["shift"]["id"], 5400)

        cancel_shift(api, world["shift"]["id"])

        assert_cycle_ledgers(
            read_cycle(api, world["cycle"]["id"]), total_scheduled_hours=0.00
        )


def _scoring_round(api):
    """Two templates, two ranked bidders and a round closed for scoring."""
    set_clock(api, CANONICAL_CLOCK)
    agreement = make_labor_agreement(api, preference_honor_floor_pct=0.5000)
    cycle = make_planning_cycle(api, name="W37-BID")
    template_a = make_shift_template(
        api, cycle["id"], code="T-A", start_time_local="08:00", duration_minutes=480
    )
    template_b = make_shift_template(
        api, cycle["id"], code="T-B", start_time_local="14:00", duration_minutes=300
    )
    senior = make_agent(
        api, agreement["id"], employee_code="E-001", seniority_rank=1
    )
    junior = make_agent(
        api, agreement["id"], employee_code="E-002", seniority_rank=2
    )
    bid_round = make_bid_round(api, cycle["id"], code="BR-1", max_reopen_count=1)
    open_round(api, bid_round["id"])
    preferences = [template_a["id"], template_b["id"]]
    senior_bid = make_shift_bid(api, bid_round["id"], senior["id"], preferences)
    junior_bid = make_shift_bid(api, bid_round["id"], junior["id"], preferences)
    score_round(api, bid_round["id"])
    return {
        "cycle": cycle,
        "template_a": template_a,
        "template_b": template_b,
        "senior": senior,
        "junior": junior,
        "round": bid_round,
        "senior_bid": senior_bid,
        "junior_bid": junior_bid,
    }


class TestBidRoundAwardReopenCycle:
    """DRAFT to OPEN to SCORING to AWARDED and back to OPEN, bounded by the ceiling."""

    def test_the_first_award_places_both_bidders_by_seniority(self, api):
        """The senior bidder takes their first choice and the junior falls to the second.

        "For each bidder, the system walks `preference_template_ids` from index 0
        forward and stops at the first template that both carries a `skill_code`
        the bidder holds in `skills` and still has a remaining slot count greater
        than zero; that bid moves `SUBMITTED → AWARDED`, its
        `awarded_shift_template_id` is set to that template, its
        `awarded_preference_index` is set to the zero-based position at which the
        match occurred, and the template's remaining slot count is reduced by one."

        Design: Difficulty/non_linear_state_machine/bid_round_award_reopen_cycle
        """
        world = _scoring_round(api)

        awarded = award_round(api, world["round"]["id"])

        assert awarded["status"] == ROUND_STATUS_AWARDED
        assert awarded["awarded_bid_count"] == 2
        assert_ratio(
            awarded["preference_honor_rate"], 0.5000, "preference_honor_rate"
        )
        senior_bid = read_bid(api, world["senior_bid"]["id"])
        assert senior_bid["awarded_shift_template_id"] == world["template_a"]["id"]
        assert senior_bid["awarded_preference_index"] == 0

    def test_the_reopen_clears_the_award_and_releases_the_slots(self, api):
        """Reopening resets the honour rate to null, the bids to SUBMITTED and the slots to zero.

        "Its effects are to increment `reopen_count` by 1, reset every `AWARDED`
        and every `UNFILLED` bid of the round back to `SUBMITTED` with
        `awarded_shift_template_id` and `awarded_preference_index` cleared to null,
        cancel every shift the round minted that is still in `DRAFT` by moving it
        `DRAFT → CANCELLED` on its publication axis, reset `preference_honor_rate`
        to null and both `awarded_bid_count` and `unfilled_bid_count` to zero, and
        recompute `slots_awarded` on every affected template."

        Design: Difficulty/non_linear_state_machine/bid_round_award_reopen_cycle
        """
        world = _scoring_round(api)
        award_round(api, world["round"]["id"])

        reopened = set_round_status(api, world["round"]["id"], ROUND_STATUS_OPEN)

        assert reopened["preference_honor_rate"] is None
        assert reopened["reopen_count"] == 1
        assert reopened["awarded_bid_count"] == 0
        assert read_bid(api, world["junior_bid"]["id"])["status"] == BID_STATUS_SUBMITTED
        assert read_template(api, world["template_a"]["id"])["slots_awarded"] == 0

    def test_the_round_can_be_awarded_a_second_time_after_the_reopen(self, api):
        """The released slots let the second award reproduce the same honour rate.

        "`SCORING → OPEN` reopens intake and requires that `reopen_count` is
        strictly less than `max_reopen_count`; it increments `reopen_count` by 1."

        Design: Difficulty/non_linear_state_machine/bid_round_award_reopen_cycle
        """
        world = _scoring_round(api)
        award_round(api, world["round"]["id"])
        set_round_status(api, world["round"]["id"], ROUND_STATUS_OPEN)
        score_round(api, world["round"]["id"])

        second = award_round(api, world["round"]["id"])

        assert_ratio(second["preference_honor_rate"], 0.5000, "preference_honor_rate")
        junior_bid = read_bid(api, world["junior_bid"]["id"])
        assert junior_bid["awarded_shift_template_id"] == world["template_b"]["id"]
        assert junior_bid["awarded_preference_index"] == 1

    def test_a_reopen_past_the_ceiling_is_refused_and_the_round_stays_awarded(self, api):
        """A second reopen would exceed the round's ceiling of one, so it is refused.

        "Whenever either reopen edge would push `reopen_count` past
        `max_reopen_count`, the request is refused with
        `ERR_REOPEN_LIMIT_REACHED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/bid_round_award_reopen_cycle
        """
        world = _scoring_round(api)
        award_round(api, world["round"]["id"])
        set_round_status(api, world["round"]["id"], ROUND_STATUS_OPEN)
        score_round(api, world["round"]["id"])
        award_round(api, world["round"]["id"])

        response = api.set_bid_round_status(
            world["round"]["id"],
            f.bid_round_status_payload(ROUND_STATUS_OPEN),
            SCHEDULER_HEADERS,
        )

        validate_error(response, ApiErrorId.REOPEN_LIMIT_REACHED.value)
        final = read_round(api, world["round"]["id"])
        assert final["status"] == ROUND_STATUS_AWARDED
        assert final["reopen_count"] == 1
