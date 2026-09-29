"""Lifecycles that double back on themselves or run on two axes at once.

A proposal can leave the committee and return to it, and the second visit is
capped. A show carries a programming dimension and a compliance dimension that
move on their own timetables, so a restriction can strip a show's air position
while its programming status stands still.
"""

from prd_bench_local_runner.testing import validate_paginated, validate_success
from test_helpers import (
    DIRECTOR_HEADERS,
    OFFICER_COPY_DESK,
    api_client,
    assertions,
    factories,
    fixtures,
    make_committee_member_headers,
)

SPONSOR_COPY = "Support for this hour comes from Fernwood Books on Third Street."


def _proposal_after_a_revision_round():
    """A proposal sent back for revision, re-submitted and back in committee
    with a second full slate of ballots on file."""
    base = fixtures.station()
    chain = fixtures.open_review_chain(
        base["host_id"],
        base["members"],
        title="Night Ledger",
        format_code="MUSIC",
        requested_daypart="OVERNIGHT",
        requested_duration_minutes=180,
    )
    fixtures.cast_uniform_ballots(
        chain["proposal_id"],
        base["members"],
        format_fit_score=3,
        diversity_score=4,
        quality_score=3,
        recommendation="REVISE",
    )
    first_decision = fixtures.decide_proposal(chain["proposal_id"])
    resubmitted = fixtures.submit_proposal(chain["proposal_id"], base["host_id"])
    reopened = fixtures.open_review(chain["proposal_id"])
    return {
        "host_id": base["host_id"],
        "members": base["members"],
        "proposal_id": chain["proposal_id"],
        "first_decision": first_decision,
        "resubmitted": resubmitted,
        "reopened": reopened,
    }


def _on_air_show_with_a_cleared_sponsor_spot():
    """A published grid with a music show and a news show on air, one airing
    scheduled, and a cleared underwriting spot carried by the music show."""
    base = fixtures.station()
    grid = fixtures.quota_ready_grid(base["host_id"], base["members"], publish=True)
    episode = fixtures.create_episode(
        grid["music_program_id"],
        grid["music_slot_id"],
        base["host_id"],
        scheduled_start_utc="2026-09-07T20:00:00Z",
    )
    spot = fixtures.create_reviewed_spot(
        officer=OFFICER_COPY_DESK,
        underwriter_name="Fernwood Books",
        spot_class="UNDERWRITING",
        copy_text=SPONSOR_COPY,
        flight_start="2026-09-07T00:00:00Z",
        flight_end="2026-10-07T00:00:00Z",
        assigned_program_id=grid["music_program_id"],
    )
    assert spot["spot"]["status"] == "APPROVED"
    return {
        "host_id": base["host_id"],
        "grid_id": grid["grid_id"],
        "music_program_id": grid["music_program_id"],
        "news_program_id": grid["news_program_id"],
        "music_slot_id": grid["music_slot_id"],
        "news_slot_id": grid["news_slot_id"],
        "episode_id": episode["id"],
        "spot_id": spot["spot_id"],
    }


class TestProposalRevisionCycle:
    def test_the_revision_band_sends_the_proposal_back_for_a_second_round(self):
        """Three uniform revise ballots score 3.35 and reopen the review.

        "a `composite_score` of at least `3.00` but below `4.00` moves it
        `IN_COMMITTEE → REVISION_REQUESTED` provided the current `review_round`
        is below 2". Re-submission then "moves the proposal `REVISION_REQUESTED →
        SUBMITTED`, raises `review_round` by 1, clears `composite_score` back to
        null and `decline_majority` back to false", and "The previous round's
        ballots remain stored — the minutes are not rewritten — but they are
        excluded from the next tally, so the committee must vote again."

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_re_enters_committee_then_hits_the_round_cap
        """
        setup = _proposal_after_a_revision_round()

        assert setup["first_decision"]["status"] == "REVISION_REQUESTED"
        assertions.assert_two_decimals_equal(
            setup["first_decision"]["composite_score"], 3.35, "composite_score"
        )
        assert setup["first_decision"]["decline_majority"] is False
        assert setup["first_decision"]["review_round"] == 1

        assert setup["resubmitted"]["status"] == "SUBMITTED"
        assert setup["resubmitted"]["review_round"] == 2
        assert setup["resubmitted"]["composite_score"] is None
        assert setup["resubmitted"]["decline_majority"] is False

        assert setup["reopened"]["status"] == "IN_COMMITTEE"
        assert setup["reopened"]["review_round"] == 2

        for member in setup["members"]:
            response = api_client.cast_vote(
                setup["proposal_id"],
                factories.cast_vote_payload(
                    member["id"],
                    format_fit_score=3,
                    diversity_score=4,
                    quality_score=3,
                    recommendation="REVISE",
                    rationale="Revise.",
                ),
                make_committee_member_headers(member["id"]),
            )
            ballot = validate_success(response, 201)
            assert ballot["review_round"] == 2

        rows, meta = validate_paginated(
            api_client.list_committee_votes(
                DIRECTOR_HEADERS, params={"proposal_id": setup["proposal_id"], "limit": 100}
            )
        )
        assert meta["total_count"] == 6
        assert sorted(row["review_round"] for row in rows) == [1, 1, 1, 2, 2, 2]

    def test_the_same_score_in_the_second_round_declines_on_the_round_cap(self):
        """The identical 3.35 lands on decline the second time round.

        "The station allows at most **two** review rounds, and that cap is
        expressed as a third route to decline: a proposal scoring at least `3.00`
        but below `4.00` in `review_round` 2 is `DECLINED` rather than sent back
        for a second revision." The decline is the cap's doing and not the
        committee's, so `decline_majority` stays false, and no show is written
        because "An approval creates the show."

        Design: Difficulty/non_linear_state_machine/proposal_revision_cycle_re_enters_committee_then_hits_the_round_cap
        """
        setup = _proposal_after_a_revision_round()
        fixtures.cast_uniform_ballots(
            setup["proposal_id"],
            setup["members"],
            format_fit_score=3,
            diversity_score=4,
            quality_score=3,
            recommendation="REVISE",
        )

        second_decision = fixtures.decide_proposal(setup["proposal_id"])

        assert second_decision["status"] == "DECLINED"
        assertions.assert_two_decimals_equal(
            second_decision["composite_score"], 3.35, "composite_score"
        )
        assert second_decision["decline_majority"] is False
        assert second_decision["review_round"] == 2

        _, meta = validate_paginated(
            api_client.list_programs(
                DIRECTOR_HEADERS, params={"proposal_id": setup["proposal_id"]}
            )
        )
        assert meta["total_count"] == 0


class TestComplianceStandingIndependence:
    def test_watch_standing_leaves_the_air_position_untouched(self):
        """One minor sponsor-identification point puts the show on watch only.

        "`WATCH` is a warning state only: a show on `WATCH` keeps airing, keeps
        its occupations and can still be given new airings, and the standing
        dimension is entirely independent of `programming_status`." A `SPONSOR_ID`
        base "is 1, 2 and 4", so a `MINOR` complaint is priced at 1 point.

        Design: Difficulty/non_linear_state_machine/program_compliance_standing_moves_independently_of_programming_status
        """
        setup = _on_air_show_with_a_cleared_sponsor_spot()

        minor = fixtures.create_incident(
            "SPONSOR_ID",
            "MINOR",
            "2026-09-07T20:10:00Z",
            complainant_note="The sponsor was not named at the top of the hour.",
            program_id=setup["music_program_id"],
            underwriting_spot_id=setup["spot_id"],
        )
        assert minor["penalty_points"] == 1

        fixtures.adjudicate_incident(minor["id"], finding="SUBSTANTIATED")

        program = fixtures.read_program(setup["music_program_id"])
        assert program["compliance_penalty_points"] == 1
        assert program["compliance_standing"] == "WATCH"
        assert program["programming_status"] == "ON_AIR_ACTIVE"

        slot = fixtures.read_slot(setup["music_slot_id"])
        assert slot["status"] == "CONFIRMED"
        assert fixtures.read_episode(setup["episode_id"])["air_status"] == "SCHEDULED"

        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["total_assigned_minutes"] == 150
        assert grid["status"] == "PUBLISHED"

    def test_restricted_standing_strips_the_air_position_but_not_the_status(self):
        """Six points take the show off the air with its status unchanged.

        "`RESTRICTED` is different, and it fires the cascade already described:
        every occupation of that show in `TENTATIVE` or `CONFIRMED` moves to
        `PREEMPTED` — with `preempted_by_program_id` left null, because no rival
        show displaced it — each preemption recomputes the owning grid's
        `total_assigned_minutes` and `public_affairs_minutes_pct` and advances
        that grid's `version`, and every airing of that show whose `air_status`
        is `SCHEDULED` moves to `CANCELLED`." For `PUBLIC_FILE` the base "is 1, 3
        and 5", so a `CRITICAL` complaint on top of the earlier point reaches 6.

        Design: Difficulty/non_linear_state_machine/program_compliance_standing_moves_independently_of_programming_status
        """
        setup = _on_air_show_with_a_cleared_sponsor_spot()
        minor = fixtures.create_incident(
            "SPONSOR_ID",
            "MINOR",
            "2026-09-07T20:10:00Z",
            complainant_note="The sponsor was not named at the top of the hour.",
            program_id=setup["music_program_id"],
            underwriting_spot_id=setup["spot_id"],
        )
        fixtures.adjudicate_incident(minor["id"], finding="SUBSTANTIATED")

        critical = fixtures.create_incident(
            "PUBLIC_FILE",
            "CRITICAL",
            "2026-09-08T09:00:00Z",
            complainant_note="The political file entry for this spot was never filed.",
            program_id=setup["music_program_id"],
            underwriting_spot_id=setup["spot_id"],
        )
        assert critical["penalty_points"] == 5

        fixtures.adjudicate_incident(critical["id"], finding="SUBSTANTIATED")

        program = fixtures.read_program(setup["music_program_id"])
        assert program["compliance_penalty_points"] == 6
        assert program["compliance_standing"] == "RESTRICTED"
        assert program["programming_status"] == "ON_AIR_ACTIVE"

        music_slot = fixtures.read_slot(setup["music_slot_id"])
        assert music_slot["status"] == "PREEMPTED"
        assert music_slot["preempted_by_program_id"] is None
        assert fixtures.read_slot(setup["news_slot_id"])["status"] == "CONFIRMED"

        assert fixtures.read_episode(setup["episode_id"])["air_status"] == "CANCELLED"

        grid = fixtures.read_grid(setup["grid_id"])
        assert grid["total_assigned_minutes"] == 30
        assertions.assert_two_decimals_equal(
            grid["public_affairs_minutes_pct"], 100.00, "public_affairs_minutes_pct"
        )

        assert fixtures.read_spot(setup["spot_id"])["status"] == "SUSPENDED"
