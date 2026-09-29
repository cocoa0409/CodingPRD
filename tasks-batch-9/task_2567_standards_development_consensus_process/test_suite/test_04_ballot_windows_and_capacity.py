"""
Ballot windows: the minimum span measured to the day, the half-open overlap test
that makes adjacency legal, the committee's overlap budget, and the precedence
between the draft's own state and that budget.
"""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx


class TestDraftStateOutranksCapacity:
    """Two rules broken at once on a one-slot committee."""

    def test_second_ballot_on_a_balloting_draft_reports_the_draft_state(self, api):
        """
        The response is `ERR_INVALID_DRAFT_STATE` (409), because the draft-state check
        at precedence 70 outranks the capacity check at precedence 106, and no ballot
        row is created.

        Design: Difficulty/priority_pair_validation_conflict/ballot_create_draft_state_error_precedes_capacity_constraint_error
        """
        scenario = fx.open_subcommittee_ballot(api, max_concurrent_ballots=1)
        assert scenario.get_draft()["status"] == "SUBCOMMITTEE_BALLOT", (
            "the draft is already out at ballot"
        )
        assert scenario.get_committee()["max_concurrent_ballots"] == 1, (
            "this committee holds exactly one overlap slot"
        )

        response = api.create_ballot(
            f.ballot_payload(
                scenario.draft_id,
                scenario.committee_id,
                opens_at="2026-08-05T00:00:00Z",
                closes_at="2026-08-19T00:00:00Z",
            ),
            scenario.chair,
        )
        validate_error(response, "ERR_INVALID_DRAFT_STATE", 409)

        _, meta = validate_paginated(api.list_ballots(scenario.staff))
        a.assert_total_count(meta, 1)
        assert scenario.get_committee()["open_ballot_count"] == 1, (
            "no ballot row was created, so the count is unmoved"
        )

    def test_overlapping_ballot_on_a_drafting_sibling_reports_capacity(self, api):
        """
        If the number of occupants is already equal to or greater than the committee's
        `max_concurrent_ballots`, the request is refused with
        `ERR_BALLOT_CAPACITY_EXCEEDED`.

        Design: Difficulty/priority_pair_validation_conflict/ballot_create_draft_state_error_precedes_capacity_constraint_error
        """
        scenario = fx.open_subcommittee_ballot(api, max_concurrent_ballots=1)
        scenario.propose_work_item("p1", title="Fastener torque spec part two")
        scenario.approve_scope(designation="STD-1401")
        sibling = scenario.add_draft(
            total_clause_count=40, changed_clause_count=0, summary="Revision 1"
        )
        assert sibling["status"] == "DRAFTING", (
            "the sibling draft is in a state that accepts a subcommittee ballot"
        )

        response = api.create_ballot(
            f.ballot_payload(
                sibling["id"],
                scenario.committee_id,
                opens_at="2026-08-05T00:00:00Z",
                closes_at="2026-08-19T00:00:00Z",
            ),
            scenario.chair,
        )
        validate_error(response, "ERR_BALLOT_CAPACITY_EXCEEDED", 409)

        _, meta = validate_paginated(api.list_ballots(scenario.staff))
        a.assert_total_count(meta, 1)
        assert scenario.get_draft(sibling["id"])["status"] == "DRAFTING", (
            "the refused ballot left the sibling draft in DRAFTING"
        )


class TestMinimumBallotWindow:
    """Fourteen whole days for a subcommittee ballot, inclusive at the boundary."""

    def test_thirteen_day_subcommittee_window_is_refused(self, api):
        """
        A window from `2026-08-01T00:00:00Z` to `2026-08-15T00:00:00Z` is 14 days and
        is acceptable for a subcommittee ballot, while a window ending
        `2026-08-14T00:00:00Z` is 13 days and is refused with
        `ERR_BALLOT_WINDOW_TOO_SHORT`.

        Design: Difficulty/boundary_precision_check/ballot_window_of_exactly_min_ballot_days_is_accepted_one_day_less_is_not
        """
        scenario = fx.work_item_with_draft(api)
        before = scenario.get_draft()

        response = api.create_ballot(
            f.ballot_payload(
                scenario.draft_id,
                scenario.committee_id,
                opens_at="2026-08-01T00:00:00Z",
                closes_at="2026-08-14T00:00:00Z",
            ),
            scenario.chair,
        )
        validate_error(response, "ERR_BALLOT_WINDOW_TOO_SHORT", 409)

        _, meta = validate_paginated(api.list_ballots(scenario.staff))
        a.assert_total_count(meta, 0)
        after = scenario.get_draft()
        assert after["status"] == "DRAFTING", (
            f"the draft never left DRAFTING, got {after['status']}"
        )
        a.assert_version_unchanged(before, after)

    def test_exactly_fourteen_day_subcommittee_window_is_accepted(self, api):
        """
        The whole-day span from `opens_at` to `closes_at` must be at least 14 days for
        a subcommittee or recirculation ballot and at least 30 days for a
        consensus-body or reaffirmation ballot, and `opens_at` must be strictly
        earlier than `closes_at`; the boundary is inclusive, so a span of exactly the
        minimum passes.

        Design: Difficulty/boundary_precision_check/ballot_window_of_exactly_min_ballot_days_is_accepted_one_day_less_is_not
        """
        scenario = fx.work_item_with_draft(api)

        ballot = scenario.open_ballot(
            opens_at="2026-08-01T00:00:00Z", closes_at="2026-08-15T00:00:00Z"
        )
        assert ballot["status"] == "OPEN", (
            f"a span of exactly the minimum passes, got {ballot['status']}"
        )
        a.assert_same_instant(ballot["opens_at"], "2026-08-01T00:00:00Z")
        a.assert_same_instant(ballot["closes_at"], "2026-08-15T00:00:00Z")
        assert ballot["eligible_voter_count"] == 3, (
            f"eligible_voter_count expected 3, got {ballot['eligible_voter_count']}"
        )

        _, meta = validate_paginated(api.list_ballots(scenario.staff))
        a.assert_total_count(meta, 1)
        assert scenario.get_committee()["open_ballot_count"] == 1, (
            "the successful creation refreshes the committee's open ballot count"
        )


class TestCommitteeOverlapBudget:
    """Adjacent windows are free; overlapping ones consume slots."""

    def test_adjacent_window_opens_beyond_a_full_overlap_budget(self, api):
        """
        Two ballot windows overlap when each one's start is strictly before the other's
        end; adjacency is therefore explicitly permitted, and a ballot opening at
        exactly the instant another closes does not overlap it.

        Design: Difficulty/resource_temporal_overlap/committee_ballot_slots_allow_adjacent_windows_but_cap_overlapping_ones
        """
        scenario = fx.committee_with_four_drafted_work_items(api, max_concurrent_ballots=2)
        scenario.open_ballot(
            draft_id=scenario.draft_ids[0],
            opens_at="2026-08-01T00:00:00Z",
            closes_at="2026-08-15T00:00:00Z",
        )
        scenario.open_ballot(
            draft_id=scenario.draft_ids[1],
            opens_at="2026-08-01T00:00:00Z",
            closes_at="2026-08-15T00:00:00Z",
        )
        assert scenario.get_committee()["open_ballot_count"] == 2, (
            "the budget of two overlapping windows is fully taken"
        )

        adjacent = scenario.open_ballot(
            draft_id=scenario.draft_ids[2],
            opens_at="2026-08-15T00:00:00Z",
            closes_at="2026-08-29T00:00:00Z",
        )
        assert adjacent["status"] == "OPEN", (
            "a window opening exactly when the others close is not an occupant; got "
            f"{adjacent['status']}"
        )
        assert scenario.get_draft(scenario.draft_ids[2])["status"] == "SUBCOMMITTEE_BALLOT", (
            "the third draft went out to ballot"
        )
        assert scenario.get_committee()["open_ballot_count"] == 3, (
            "three ballots are open at once, none of them overlapping more than one "
            "other"
        )

    def test_overlapping_fourth_window_is_refused_at_the_budget(self, api):
        """
        The occupants of the candidate window are the ballot rows on this same
        committee whose `status` is `OPEN` or `CLOSED` and whose half-open window
        overlaps the candidate's — two windows overlapping exactly when each one's
        start is strictly earlier than the other's end, so a ballot opening at the
        instant another closes is not an occupant.

        Design: Difficulty/resource_temporal_overlap/committee_ballot_slots_allow_adjacent_windows_but_cap_overlapping_ones
        """
        scenario = fx.committee_with_four_drafted_work_items(api, max_concurrent_ballots=2)
        for index in (0, 1):
            scenario.open_ballot(
                draft_id=scenario.draft_ids[index],
                opens_at="2026-08-01T00:00:00Z",
                closes_at="2026-08-15T00:00:00Z",
            )
        scenario.open_ballot(
            draft_id=scenario.draft_ids[2],
            opens_at="2026-08-15T00:00:00Z",
            closes_at="2026-08-29T00:00:00Z",
        )

        response = api.create_ballot(
            f.ballot_payload(
                scenario.draft_ids[3],
                scenario.committee_id,
                opens_at="2026-08-14T00:00:00Z",
                closes_at="2026-08-28T00:00:00Z",
            ),
            scenario.chair,
        )
        validate_error(response, "ERR_BALLOT_CAPACITY_EXCEEDED", 409)

        assert scenario.get_draft(scenario.draft_ids[3])["status"] == "DRAFTING", (
            "the refused ballot left the fourth draft in DRAFTING"
        )
        _, meta = validate_paginated(api.list_ballots(scenario.staff))
        a.assert_total_count(meta, 3)
        committee = scenario.get_committee()
        assert committee["open_ballot_count"] == 3, (
            f"open_ballot_count expected 3, got {committee['open_ballot_count']}"
        )
        assert committee["max_concurrent_ballots"] == 2, (
            "the budget itself is unchanged by a refused request"
        )
