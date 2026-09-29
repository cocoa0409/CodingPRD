"""Recount pricing in whole cents, and the settlement that closes the deposit ledger."""

import pytest

from test_helpers import (
    api_client,
    assertions,
    fixtures,
    make_candidate_representative_headers,
    validate_success,
)

DAVIS_REP = "rep-davis"
GRANT_REP = "rep-grant"


def _withdraw(recount_id, reason, requester_user_id=DAVIS_REP):
    return validate_success(
        api_client.withdraw_recount(
            recount_id,
            {"reason": reason},
            make_candidate_representative_headers(requester_user_id),
        )
    )


def _partial_scope_recount(contest_id, batch_ids, requester_user_id, candidate_name):
    return fixtures.file_recount(
        contest_id,
        requester_user_id=requester_user_id,
        scope="PARTIAL_BATCHES",
        scope_batch_ids=list(batch_ids),
        requested_by_candidate_name=candidate_name,
    )


class TestRefundVariantsOnTwoCompletedRecounts:
    """Two ten-vote margin moves; only the one that flipped the winner is refunded whole."""

    def _setup_two_completed_recounts(self):
        scenario = fixtures.setup_canvassed_two_contest_election()
        treasurer = fixtures.setup_recount_in_progress(
            scenario["contest"]["id"],
            125000,
            requester_user_id=DAVIS_REP,
            requested_by_candidate_name="DAVIS",
        )
        assessor = fixtures.setup_recount_in_progress(
            scenario["contest_c3"]["id"],
            106250,
            requester_user_id=GRANT_REP,
            requested_by_candidate_name="GRANT",
        )
        scenario["prorated"] = fixtures.complete_recount(
            treasurer["id"], {"CHEN": 1570, "DAVIS": 1430}, 6.5
        )
        scenario["statutory"] = fixtures.complete_recount(
            assessor["id"], {"FORD": 1075, "GRANT": 1175}, 4.0
        )
        return scenario

    def test_an_unchanged_outcome_recovers_the_measured_cost_from_the_deposit(self):
        """PRD §3.8: "Otherwise `refund_variant` is `PRORATED_COST_RECOVERY`:
        `forfeited_cents` is the smaller of `deposit_paid_cents` and `actual_cost_cents`,
        `refunded_cents` is `deposit_paid_cents` minus `forfeited_cents`, and
        `deposit_status` becomes `FORFEITED` when nothing is refunded and
        `PARTIALLY_REFUNDED` when something is."

        Design: Difficulty/dual_variant_calc/dual_variant_recount_refund_statutory_vs_prorated
        """
        scenario = self._setup_two_completed_recounts()

        recount = scenario["prorated"]
        assertions.assert_recount(recount)
        assert recount["actual_cost_cents"] == 68701
        assert recount["final_margin_votes"] == 140
        assert recount["margin_change_votes"] == -10
        assert recount["outcome_changed"] is False
        assert recount["refund_variant"] == "PRORATED_COST_RECOVERY"
        assert recount["forfeited_cents"] == 68701
        assert recount["refunded_cents"] == 56299
        assert recount["deposit_status"] == "PARTIALLY_REFUNDED"
        assert recount["status"] == "COMPLETED"
        assertions.assert_deposit_ledger_conserved(recount)

    def test_a_flipped_winner_returns_the_whole_deposit_whatever_the_cost(self):
        """PRD §3.8: "When `outcome_changed` is true, **or** the absolute value of
        `margin_change_votes` is at least 100 votes, the recount was materially justified:
        `refund_variant` is `STATUTORY_REFUND`, `refunded_cents` is the whole
        `deposit_paid_cents`, `forfeited_cents` stays zero regardless of what the recount
        actually cost, and `deposit_status` becomes `REFUNDED_FULL`."

        Design: Difficulty/dual_variant_calc/dual_variant_recount_refund_statutory_vs_prorated
        """
        scenario = self._setup_two_completed_recounts()

        recount = scenario["statutory"]
        assert recount["actual_cost_cents"] == 47325
        assert recount["final_margin_votes"] == 100
        assert recount["margin_change_votes"] == -10
        assert recount["outcome_changed"] is True
        assert recount["refund_variant"] == "STATUTORY_REFUND"
        assert recount["forfeited_cents"] == 0
        assert recount["refunded_cents"] == 106250
        assert recount["deposit_status"] == "REFUNDED_FULL"
        assertions.assert_deposit_ledger_conserved(recount)

    def test_both_contests_recanvass_in_place_from_the_recounted_totals(self):
        """PRD §3.8: "The contest re-canvasses itself in place: its `reported_votes` is
        replaced by the post-recount totals, and `winner_name`, `runner_up_name`,
        `margin_votes`, `margin_pct` and `automatic_recount_required` are all re-derived from
        them by the rules of §3.1, while the contest's `status` stays `CANVASSED`."

        Design: Difficulty/dual_variant_calc/dual_variant_recount_refund_statutory_vs_prorated
        """
        scenario = self._setup_two_completed_recounts()

        treasurer = fixtures.read_contest(scenario["contest"]["id"])
        assertions.assert_contest(treasurer)
        assert treasurer["winner_name"] == "CHEN"
        assert treasurer["margin_votes"] == 140
        assert treasurer["margin_pct"] == pytest.approx(4.6667, abs=0.00005)
        assert treasurer["status"] == "CANVASSED"

        assessor = fixtures.read_contest(scenario["contest_c3"]["id"])
        assert assessor["winner_name"] == "GRANT"
        assert assessor["margin_votes"] == 100
        assert assessor["margin_pct"] == pytest.approx(4.4444, abs=0.00005)
        assert assessor["status"] == "CANVASSED"


class TestRecountCostRoundsEachLineBeforeSumming:
    """A 1000/995/1005 scope costs one cent more than the naive product."""

    def _setup_completed_partial_recount(self):
        scenario = fixtures.setup_canvassed_treasurer_contest()
        scenario["recount"] = _partial_scope_recount(
            scenario["contest"]["id"],
            [batch["id"] for batch in scenario["batches"]],
            DAVIS_REP,
            "DAVIS",
        )
        fixtures.post_deposit(scenario["recount"]["id"], 170000, DAVIS_REP)
        fixtures.start_recount(scenario["recount"]["id"])
        scenario["completed"] = fixtures.complete_recount(
            scenario["recount"]["id"], {"CHEN": 1570, "DAVIS": 1430}, 6.5
        )
        return scenario

    def test_a_partial_scope_is_priced_at_the_higher_per_ballot_rate(self):
        """PRD §3.8: "for a `PARTIAL_BATCHES` recount, `ballots_in_scope` is the sum of
        `ballot_count` over the batches named in `scope_batch_ids` and the rate is 40 cents
        per ballot, the higher rate reflecting the fixed overhead of mobilising for a partial
        count."

        Design: Difficulty/combinatorial_formula/combinatorial_recount_cost_per_line_rounding_precedes_summation
        """
        scenario = fixtures.setup_canvassed_treasurer_contest()

        recount = _partial_scope_recount(
            scenario["contest"]["id"],
            [batch["id"] for batch in scenario["batches"]],
            DAVIS_REP,
            "DAVIS",
        )

        assertions.assert_recount(recount)
        assert recount["ballots_in_scope"] == 3000
        assert recount["required_deposit_cents"] == 170000
        assert recount["deposit_status"] == "PENDING"

    def test_each_batch_line_is_rounded_before_the_lines_are_summed(self):
        """PRD §3.8: "For each ballot batch in scope, taken in `batch_label` ascending order,
        the line is 12.5 cents multiplied by that batch's `ballot_count`, rounded half up to
        whole cents; the ballot cost is the sum of those rounded lines, never the rounding of
        their sum, so a scope of many odd-sized batches costs measurably more than the naive
        total."

        Design: Difficulty/combinatorial_formula/combinatorial_recount_cost_per_line_rounding_precedes_summation
        """
        scenario = self._setup_completed_partial_recount()

        completed = scenario["completed"]
        assert completed["actual_cost_cents"] == 68701
        assert completed["actual_cost_cents"] != 68700
        assert completed["refund_variant"] == "PRORATED_COST_RECOVERY"
        assert completed["forfeited_cents"] == 68701
        assert completed["refunded_cents"] == 101299
        assert completed["deposit_paid_cents"] == 170000
        assert completed["deposit_status"] == "PARTIALLY_REFUNDED"
        assert completed["status"] == "COMPLETED"
        assertions.assert_deposit_ledger_conserved(completed)


class TestDepositFloorIsAppliedBeforeTheCap:
    """Ninety thousand is lifted to the floor; a hundred thousand exactly is not."""

    def test_a_price_below_the_floor_is_lifted_and_one_on_the_floor_is_not(self):
        """PRD §3.8: "A `CANDIDATE_REQUESTED` recount is priced as the filing fee of 50000
        cents plus the applicable rate multiplied by `ballots_in_scope`, then clamped — the
        floor of 100000 cents applied first, the cap of 2000000 cents applied second."

        Design: Difficulty/boundary_precision_check/boundary_required_deposit_exactly_at_statutory_floor
        """
        scenario = fixtures.setup_canvassed_two_contest_election()
        assessor_id = scenario["contest_c3"]["id"]
        smaller = fixtures.batch_by_label(scenario["batches_c3"], "C3-B02")
        larger = fixtures.batch_by_label(scenario["batches_c3"], "C3-B01")

        below_floor = _partial_scope_recount(
            assessor_id, [smaller["id"]], GRANT_REP, "GRANT"
        )
        _withdraw(
            below_floor["id"], "Refiling with the larger batch.", GRANT_REP
        )
        on_floor = _partial_scope_recount(
            assessor_id, [larger["id"]], GRANT_REP, "GRANT"
        )

        assert below_floor["ballots_in_scope"] == 1000
        assert below_floor["required_deposit_cents"] == 100000
        assert on_floor["ballots_in_scope"] == 1250
        assert on_floor["required_deposit_cents"] == 100000

    def test_a_withdrawal_before_funding_charges_nothing(self):
        """PRD §3.8: "When `deposit_status` is still `PENDING` nothing is charged and it
        stays `PENDING`. Either way `status` becomes `WITHDRAWN` and the contest's
        `open_recount_count` is decreased by one."

        Design: Difficulty/boundary_precision_check/boundary_required_deposit_exactly_at_statutory_floor
        """
        scenario = fixtures.setup_canvassed_two_contest_election()
        assessor_id = scenario["contest_c3"]["id"]
        smaller = fixtures.batch_by_label(scenario["batches_c3"], "C3-B02")
        larger = fixtures.batch_by_label(scenario["batches_c3"], "C3-B01")
        below_floor = _partial_scope_recount(
            assessor_id, [smaller["id"]], GRANT_REP, "GRANT"
        )
        _withdraw(below_floor["id"], "Refiling with the larger batch.", GRANT_REP)
        on_floor = _partial_scope_recount(
            assessor_id, [larger["id"]], GRANT_REP, "GRANT"
        )
        _withdraw(on_floor["id"], "Refiling for the whole contest.", GRANT_REP)

        full_contest = fixtures.file_recount(
            assessor_id,
            requester_user_id=GRANT_REP,
            requested_by_candidate_name="GRANT",
        )

        assert full_contest["ballots_in_scope"] == 2250
        assert full_contest["required_deposit_cents"] == 106250
        assert full_contest["status"] == "REQUESTED"
        assert full_contest["deposit_status"] == "PENDING"
        withdrawn = fixtures.read_recount(below_floor["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["deposit_status"] == "PENDING"
        assert withdrawn["refund_variant"] == "NONE"
        assert withdrawn["admin_retained_cents"] == 0
        assert withdrawn["refunded_cents"] == 0
        assessor = fixtures.read_contest(assessor_id)
        assert assessor["margin_pct"] == pytest.approx(4.8889, abs=0.00005)
        assert assessor["open_recount_count"] == 1


class TestWithdrawalRetentionConservesTheDepositLedger:
    """A held deposit splits into retention and refund with no cent invented or lost."""

    def test_withdrawal_from_a_held_deposit_retains_a_quarter_and_refunds_the_rest(self):
        """PRD §3.8: "`admin_retained_cents` becomes `deposit_paid_cents` multiplied by 0.25
        and rounded half up to whole cents, `refunded_cents` becomes `deposit_paid_cents`
        minus `admin_retained_cents`, `forfeited_cents` stays zero, `deposit_status` becomes
        `PARTIALLY_REFUNDED` and `refund_variant` becomes `WITHDRAWAL_RETENTION`."

        Design: Difficulty/compensating_invariant/compensating_deposit_ledger_conservation_on_withdrawal
        """
        scenario = fixtures.setup_canvassed_treasurer_contest()
        recount = _partial_scope_recount(
            scenario["contest"]["id"],
            [batch["id"] for batch in scenario["batches"]],
            DAVIS_REP,
            "DAVIS",
        )
        held = fixtures.post_deposit(recount["id"], 170000, DAVIS_REP)
        assert held["deposit_paid_cents"] == 170000
        assert held["deposit_status"] == "HELD"

        withdrawn = _withdraw(recount["id"], "Candidate accepts the canvassed result.")

        assert withdrawn["admin_retained_cents"] == 42500
        assert withdrawn["refunded_cents"] == 127500
        assert withdrawn["forfeited_cents"] == 0
        assert withdrawn["deposit_paid_cents"] == 170000
        assert withdrawn["refund_variant"] == "WITHDRAWAL_RETENTION"
        assert withdrawn["deposit_status"] == "PARTIALLY_REFUNDED"
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["actual_cost_cents"] == 0
        assertions.assert_deposit_ledger_conserved(withdrawn)

    def test_a_withdrawn_recount_never_folds_votes_back_into_the_contest(self):
        """PRD §3.8: "When the deposit is `HELD`, the withdrawal keeps a flat administrative
        retention instead of any measured cost: no ballots were counted and `team_hours` is
        null, so the per-line cost step is skipped entirely and `actual_cost_cents` stays
        zero."

        Design: Difficulty/compensating_invariant/compensating_deposit_ledger_conservation_on_withdrawal
        """
        scenario = fixtures.setup_canvassed_treasurer_contest()
        recount = _partial_scope_recount(
            scenario["contest"]["id"],
            [batch["id"] for batch in scenario["batches"]],
            DAVIS_REP,
            "DAVIS",
        )
        fixtures.post_deposit(recount["id"], 170000, DAVIS_REP)

        withdrawn = _withdraw(recount["id"], "Candidate accepts the canvassed result.")

        assert withdrawn["team_hours"] is None
        contest = fixtures.read_contest(scenario["contest"]["id"])
        assert contest["open_recount_count"] == 0
        assert contest["margin_votes"] == 150
        assert contest["reported_votes"] == {"CHEN": 1575, "DAVIS": 1425}
