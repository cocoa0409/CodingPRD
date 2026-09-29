"""Derived arithmetic: ranking, thresholds, rounding, the draw, the projection and settlement."""

import pytest

from test_helpers import (
    api_client,
    assertions,
    constants,
    fixtures,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["elections_director_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
CUSTODY_OFFICER = TEST_USERS["custody_officer_headers"]

CANVASS_DAY = constants.TEST_DEFAULTS["CLOCK_CANVASS_DAY"]
CANDIDATE_REP = "u-cand-1"


class TestCanvassRanking:
    """A tie for second is broken by name, and the margin is measured against second."""

    def test_the_runner_up_of_two_tied_losers_is_the_alphabetically_smaller(self):
        """PRD §3.1: "The candidate names are ranked by their vote count in descending order,
        and where two candidates hold the same count, by candidate name in ascending order.
        `winner_name` becomes the first name in that ranking and `runner_up_name` the second".

        Design: Corner/calculations/canvass_ranking_breaks_a_runner_up_tie_by_name_ascending
        """
        fixtures.set_clock(CANVASS_DAY)
        election = fixtures.create_election(jurisdiction_code="ST-04")
        contest = fixtures.create_contest(
            election["id"], candidate_names=["ALVAREZ", "BRENNAN", "CHEN"]
        )

        canvassed = validate_success(
            api_client.submit_canvass_results(
                contest["id"],
                {"reported_votes": {"ALVAREZ": 2000, "BRENNAN": 1500, "CHEN": 1500}},
                DIRECTOR,
            )
        )

        assertions.assert_contest(canvassed)
        assert canvassed["winner_name"] == "ALVAREZ"
        assert canvassed["runner_up_name"] == "BRENNAN"
        assert canvassed["margin_votes"] == 500
        assert canvassed["margin_pct"] == pytest.approx(8.3333, abs=0.00005)
        assert canvassed["automatic_recount_required"] is False
        assert canvassed["status"] == "CANVASSED"
        assertions.assert_same_instant(
            canvassed["recount_request_deadline_at"],
            "2026-11-10T09:00:00Z",
            "recount_request_deadline_at",
        )
        assert fixtures.read_election(election["id"])["status"] == "CANVASSED"


class TestRoundLedgerInputSet:
    """A draft sheet contributes neither ballots nor error to the round."""

    def test_an_open_draft_count_is_excluded_from_the_round_roll_up(self):
        """PRD §3.5: "The round's ledger is maintained over its tallies in `SUBMITTED` or
        `CERTIFIED`: `cumulative_net_error_votes` is the sum of their `net_error_votes` and
        `counted_ballots` is the sum of their drawn batches' ballot counts."

        Design: Corner/calculations/round_counters_count_only_submitted_tallies
        """
        scenario = fixtures.setup_round_one_with_checked_out_batch()
        team_id = scenario["team"]["id"]
        second_drawn = scenario["audit_batches"][1]
        second_physical = fixtures.read_batch(second_drawn["ballot_batch_id"])
        fixtures.retrieve_batch(
            second_drawn["id"],
            second_physical["id"],
            second_physical["current_seal_number"],
        )
        first_tally = fixtures.open_manual_tally(
            scenario["target_audit_batch"]["id"],
            team_id,
            session_start_at=CANVASS_DAY,
            session_end_at="2026-11-05T11:00:00Z",
            counted_votes={"ALVAREZ": 522, "BRENNAN": 478},
        )
        submitted = fixtures.submit_manual_tally(first_tally["id"], team_id)

        draft = fixtures.open_manual_tally(
            second_drawn["id"],
            team_id,
            session_start_at="2026-11-05T11:00:00Z",
            session_end_at="2026-11-05T13:00:00Z",
            counted_votes={"ALVAREZ": 525, "BRENNAN": 475},
        )

        assert draft["status"] == "DRAFT"
        assert draft["net_error_votes"] is None
        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["counted_ballots"] == 1000
        assert audit_round["cumulative_net_error_votes"] == 6
        assert audit_round["discrepancy_count"] == 1
        assert audit_round["round_measure"] == pytest.approx(0.0060, abs=0.00005)
        assert audit_round["status"] == "REVIEW_REQUIRED"
        audit = fixtures.read_audit(scenario["audit"]["id"])
        assert audit["counted_ballots"] == 1000
        assert audit["cumulative_net_error_votes"] == 6
        assert audit["discrepancy_measure"] == pytest.approx(0.0060, abs=0.00005)
        assert audit["cumulative_sampled_batches"] == 3
        assert audit["status"] == "DISCREPANCY_REVIEW"
        assert submitted["net_error_votes"] == 6
        assert submitted["relative_taint"] == pytest.approx(0.9000, abs=0.00005)


class TestAutomaticRecountThresholdByContestType:
    """0.3000 percent is inside the candidate ceiling and outside the measure ceiling."""

    def test_the_same_margin_triggers_a_candidate_recount_but_not_a_measure_one(self):
        """PRD §3.1: "The automatic recount threshold depends on the contest type: it is
        0.5000 percent for a `CANDIDATE` contest and 0.2500 percent for a `MEASURE`.
        `automatic_recount_required` becomes true when `margin_pct` is less than or equal to
        the applicable threshold, and false otherwise; the comparison is made at four decimal
        places and the boundary counts as inside the threshold."

        Design: Corner/calculations/automatic_recount_threshold_is_selected_by_contest_type
        """
        fixtures.set_clock(CANVASS_DAY)
        election = fixtures.create_election(jurisdiction_code="ST-05")
        on_the_measure_ceiling = fixtures.create_contest(
            election["id"],
            contest_label="M1",
            office_name="Bond Measure One",
            contest_type="MEASURE",
            candidate_names=["YES", "NO"],
            ballots_cast=4000,
        )
        above_the_measure_ceiling = fixtures.create_contest(
            election["id"],
            contest_label="M2",
            office_name="Bond Measure Two",
            contest_type="MEASURE",
            candidate_names=["YES", "NO"],
            ballots_cast=4000,
        )
        candidate_contest = fixtures.create_contest(
            election["id"],
            contest_label="K1",
            office_name="County Clerk",
            candidate_names=["PATEL", "QUINN"],
            ballots_cast=4000,
        )

        first = fixtures.canvass_contest(
            on_the_measure_ceiling["id"], reported_votes={"YES": 2005, "NO": 1995}
        )
        second = fixtures.canvass_contest(
            above_the_measure_ceiling["id"], reported_votes={"YES": 2006, "NO": 1994}
        )
        third = fixtures.canvass_contest(
            candidate_contest["id"], reported_votes={"PATEL": 2006, "QUINN": 1994}
        )

        assert first["margin_votes"] == 10
        assert first["margin_pct"] == pytest.approx(0.2500, abs=0.00005)
        assert first["automatic_recount_required"] is True
        assert second["margin_votes"] == 12
        assert second["margin_pct"] == pytest.approx(0.3000, abs=0.00005)
        assert second["automatic_recount_required"] is False
        assert third["margin_votes"] == 12
        assert third["margin_pct"] == pytest.approx(0.3000, abs=0.00005)
        assert third["automatic_recount_required"] is True
        for contest in (first, second, third):
            assertions.assert_same_instant(
                contest["recount_request_deadline_at"],
                "2026-11-10T09:00:00Z",
                "recount_request_deadline_at",
            )
        assert fixtures.read_election(election["id"])["status"] == "CANVASSED"


class TestMarginPercentRounding:
    """Half up at the fourth decimal, never truncated and never half to even."""

    def test_a_trailing_five_rounds_up_and_a_repeating_third_rounds_to_seven(self):
        """PRD §3.1: "`margin_pct` becomes `margin_votes` divided by `ballots_cast`,
        multiplied by one hundred, and rounded half up to four decimal places." §2.7: "A
        contest's `margin_pct` ... and an audit's `discrepancy_measure` are all rounded half up
        to exactly four decimal places".

        Design: Corner/calculations/margin_pct_rounds_half_up_at_the_fourth_decimal
        """
        fixtures.set_clock(CANVASS_DAY)
        election = fixtures.create_election(jurisdiction_code="ST-06")
        wide = fixtures.create_contest(
            election["id"],
            contest_label="P1",
            office_name="State Senate",
            candidate_names=["KING", "LOWE"],
            ballots_cast=16000,
        )
        narrow = fixtures.create_contest(
            election["id"],
            contest_label="P2",
            office_name="State Assembly",
            candidate_names=["MOORE", "NASH"],
            ballots_cast=6000,
        )

        half_up = fixtures.canvass_contest(
            wide["id"], reported_votes={"KING": 8011, "LOWE": 7988}
        )
        repeating = fixtures.canvass_contest(
            narrow["id"], reported_votes={"MOORE": 3050, "NASH": 2950}
        )

        assert half_up["margin_votes"] == 23
        assert half_up["margin_pct"] == pytest.approx(0.1438, abs=0.00005)
        assert half_up["automatic_recount_required"] is True
        assert repeating["margin_votes"] == 100
        assert repeating["margin_pct"] == pytest.approx(1.6667, abs=0.00005)
        assert repeating["automatic_recount_required"] is False
        assert half_up["winner_name"] == "KING"
        assert repeating["winner_name"] == "MOORE"
        assertions.assert_four_decimal_places(half_up["margin_pct"], "margin_pct")
        assertions.assert_four_decimal_places(repeating["margin_pct"], "margin_pct")


class TestReproducibleDraw:
    """One seed, two audits, the same ordered prefix."""

    def test_the_comparison_audit_reproduces_the_risk_limiting_prefix(self):
        """PRD §3.4: "The draw is deterministic, and this is the property that makes the audit
        publicly checkable: the same seed, the same round number and the same eligible pool
        always produce the same ordered selection." §3.4: "The round's `selection_sequence` is
        the list of `batch_label` values in that draw order, and each drawn-batch row records
        its zero-based position in that order as `selection_index` together with a
        `ballot_count` copied from the physical batch at selection time".

        Design: Corner/calculations/identical_seed_and_pool_produce_the_same_draw_prefix
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]
        risk_limiting = fixtures.setup_seeded_audit(contest_id)
        comparison = fixtures.setup_seeded_audit(contest_id, audit_type="COMPARISON")
        first_round = fixtures.open_round(risk_limiting["id"])

        second_round = fixtures.open_round(comparison["id"])

        assert first_round["sample_size_batches"] == 3
        assert first_round["selection_sequence"] == ["B-003", "B-004", "B-005"]
        assert second_round["sample_size_batches"] == 2
        assert second_round["selection_sequence"] == ["B-003", "B-004"]
        assert second_round["round_number"] == 1
        assert second_round["previous_round_id"] is None
        assert second_round["is_full_hand_count"] is False
        drawn_rows, meta = validate_paginated(
            api_client.list_audit_batches(
                CUSTODY_OFFICER,
                params={"audit_round_id": second_round["id"], "limit": 100},
            )
        )
        assert meta["total_count"] == 2
        assert [row["selection_index"] for row in drawn_rows] == [0, 1]
        for row in drawn_rows:
            assertions.assert_audit_batch(row)
            assert row["ballot_count"] == 1000
            assert row["retrieval_status"] == "PENDING_RETRIEVAL"
            assert row["tally_status"] == "NOT_STARTED"
        for label in ("B-003", "B-004", "B-005"):
            batch = fixtures.batch_by_label(fixtures.list_batches(contest_id), label)
            assertions.assert_same_instant(
                batch["retrieval_authorized_at"],
                CANVASS_DAY,
                f"{label} retrieval_authorized_at",
            )
        never_drawn = fixtures.batch_by_label(
            fixtures.list_batches(contest_id), "B-006"
        )
        assert never_drawn["retrieval_authorized_at"] is None
        assert fixtures.read_audit(risk_limiting["id"])[
            "cumulative_sampled_batches"
        ] == 3
        second_audit = fixtures.read_audit(comparison["id"])
        assert second_audit["cumulative_sampled_batches"] == 2
        assertions.assert_same_instant(
            second_audit["seed_published_at"], CANVASS_DAY, "seed_published_at"
        )
        assert second_audit["status"] == "SAMPLING"


class TestTimelineProjection:
    """Forty-eight hours per pending round, and nothing else while nothing is hand counted."""

    def test_one_pending_round_costs_forty_eight_hours_and_slack_narrows_with_the_clock(self):
        """PRD §3.9: "The round hours are 48 multiplied by the number of pending rounds — two
        days of fixed overhead per open round." §3.9: "`timeline_status` is `BREACHED` when
        `effective_slack_hours` is negative, `AT_RISK` when it is zero or greater but no
        greater than 72, and `ON_TRACK` otherwise."

        Design: Corner/calculations/timeline_projection_charges_forty_eight_hours_per_pending_round
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        audit_id = scenario["audit"]["id"]
        first_review = validate_success(
            api_client.review_audit_timeline(audit_id, AUDIT_MANAGER)
        )

        fixtures.set_clock("2026-11-22T09:00:00Z")
        second_review = validate_success(
            api_client.review_audit_timeline(audit_id, AUDIT_MANAGER)
        )

        assertions.assert_same_instant(
            first_review["projected_completion_at"],
            "2026-11-07T09:00:00Z",
            "projected_completion_at",
        )
        assert first_review["slack_hours"] == pytest.approx(416.00, abs=0.005)
        assert first_review["extension_days_granted"] == 0
        assert first_review["timeline_status"] == "ON_TRACK"
        assert first_review["effective_slack_hours"] == pytest.approx(416.00, abs=0.005)
        assertions.assert_same_instant(
            second_review["projected_completion_at"],
            "2026-11-24T09:00:00Z",
            "projected_completion_at",
        )
        assert second_review["slack_hours"] == pytest.approx(8.00, abs=0.005)
        assert second_review["extension_days_granted"] == 0
        assert second_review["timeline_status"] == "AT_RISK"
        assert second_review["effective_slack_hours"] == pytest.approx(8.00, abs=0.005)
        assertions.assert_same_instant(
            second_review["effective_certification_deadline_at"],
            "2026-11-24T17:00:00Z",
            "effective_certification_deadline_at",
        )
        election = fixtures.read_election(scenario["election"]["id"])
        assert election["timeline_status"] == "AT_RISK"
        assertions.assert_same_instant(
            election["effective_certification_deadline_at"],
            "2026-11-24T17:00:00Z",
            "effective_certification_deadline_at",
        )
        assertions.assert_same_instant(
            election["contest_window_ends_at"],
            "2026-12-04T17:00:00Z",
            "contest_window_ends_at",
        )


class TestRecountCompletionReconciliation:
    """One request settles the money and rebases the contest."""

    def test_a_hundred_vote_move_refunds_the_whole_deposit_and_recanvasses(self):
        """PRD §3.8: "When `outcome_changed` is true, **or** the absolute value of
        `margin_change_votes` is at least 100 votes, the recount was materially justified:
        `refund_variant` is `STATUTORY_REFUND`, `refunded_cents` is the whole
        `deposit_paid_cents`, `forfeited_cents` stays zero regardless of what the recount
        actually cost". §3.8: "The contest re-canvasses itself in place: its `reported_votes`
        is replaced by the post-recount totals, and `winner_name`, `runner_up_name`,
        `margin_votes`, `margin_pct` and `automatic_recount_required` are all re-derived from
        them by the rules of §3.1".

        Design: Corner/calculations/recount_completion_rebases_the_contest_and_refunds_the_deposit
        """
        scenario = fixtures.setup_canvassed_contest()
        started = fixtures.setup_recount_in_progress(
            scenario["contest"]["id"],
            200000,
            requester_user_id=CANDIDATE_REP,
            requested_by_candidate_name="BRENNAN",
        )
        assert started["required_deposit_cents"] == 200000
        assert started["deposit_status"] == "HELD"
        assert started["status"] == "IN_PROGRESS"

        completed = fixtures.complete_recount(
            started["id"], {"ALVAREZ": 3100, "BRENNAN": 2900}, 10
        )

        assertions.assert_recount(completed)
        assert completed["actual_cost_cents"] == 123000
        assert completed["refund_variant"] == "STATUTORY_REFUND"
        assert completed["refunded_cents"] == 200000
        assert completed["forfeited_cents"] == 0
        assert completed["admin_retained_cents"] == 0
        assert completed["deposit_status"] == "REFUNDED_FULL"
        assert completed["status"] == "COMPLETED"
        assert completed["final_margin_votes"] == 200
        assert completed["margin_change_votes"] == -100
        assert completed["outcome_changed"] is False
        assertions.assert_deposit_ledger_conserved(completed)
        contest = fixtures.read_contest(scenario["contest"]["id"])
        assert contest["reported_votes"] == {"ALVAREZ": 3100, "BRENNAN": 2900}
        assert contest["margin_votes"] == 200
        assert contest["margin_pct"] == pytest.approx(3.3333, abs=0.00005)
        assert contest["winner_name"] == "ALVAREZ"
        assert contest["automatic_recount_required"] is False
        assert contest["open_recount_count"] == 0
        election = fixtures.read_election(scenario["election"]["id"])
        assert election["open_recount_count"] == 0
        assert election["status"] == "CANVASSED"
