"""The two discrepancy-measure variants, and the board adjudication that re-derives them."""

import pytest

from test_helpers import assertions, constants, fixtures

BOARD_DEM = constants.TEST_DEFAULTS["BOARD_DEM_USER_ID"]
BOARD_REP = constants.TEST_DEFAULTS["BOARD_REP_USER_ID"]
BOARD_DEM_2 = constants.TEST_DEFAULTS["BOARD_DEM_2_USER_ID"]

SIX_VOTE_OVERSTATEMENT = {"ALVAREZ": 522, "BRENNAN": 478}


def _setup_one_count_measured_both_ways():
    """The same 522/478 hand count submitted under a net-shift and an overstatement audit."""
    scenario = fixtures.setup_two_audits_sharing_first_batch()
    team_id = scenario["team"]["id"]
    net_shift = fixtures.open_manual_tally(
        scenario["rla_target"]["id"],
        team_id,
        session_start_at="2026-11-05T09:00:00Z",
        session_end_at="2026-11-05T11:00:00Z",
        counted_votes=dict(SIX_VOTE_OVERSTATEMENT),
    )
    overstatement = fixtures.open_manual_tally(
        scenario["comparison_target"]["id"],
        team_id,
        session_start_at="2026-11-05T11:30:00Z",
        session_end_at="2026-11-05T13:30:00Z",
        counted_votes=dict(SIX_VOTE_OVERSTATEMENT),
    )
    scenario["net_shift_tally"] = fixtures.submit_manual_tally(net_shift["id"], team_id)
    scenario["overstatement_tally"] = fixtures.submit_manual_tally(
        overstatement["id"], team_id
    )
    return scenario


class TestMeasureVariantsOnOneHandCount:
    """Six votes of overstatement, measured two ways, with two different verdicts."""

    def test_the_variant_follows_the_methodology_not_the_numbers(self):
        """PRD §3.3: "Planning derives `measure_variant` from the methodology and never
        accepts it as input: risk-limiting and fixed-percentage audits take the variant
        `NET_MARGIN_SHIFT`, while comparison audits take `MAX_RELATIVE_OVERSTATEMENT`."

        Design: Difficulty/dual_variant_calc/dual_variant_discrepancy_measure_net_shift_vs_relative_overstatement
        """
        scenario = _setup_one_count_measured_both_ways()

        net_shift_audit = fixtures.read_audit(scenario["rla"]["audit"]["id"])
        overstatement_audit = fixtures.read_audit(scenario["comparison"]["audit"]["id"])
        assert net_shift_audit["measure_variant"] == "NET_MARGIN_SHIFT"
        assert net_shift_audit["planned_sample_size"] == 3
        assert overstatement_audit["measure_variant"] == "MAX_RELATIVE_OVERSTATEMENT"
        assert overstatement_audit["planned_sample_size"] == 2
        for tally in (scenario["net_shift_tally"], scenario["overstatement_tally"]):
            assert tally["machine_margin_votes"] == 50
            assert tally["manual_margin_votes"] == 44
            assert tally["net_error_votes"] == 6
            assert tally["relative_taint"] == pytest.approx(0.9000, abs=0.00005)

    def test_the_net_shift_variant_crosses_its_threshold_and_escalates(self):
        """PRD §3.5: "Under `NET_MARGIN_SHIFT` — the variant of risk-limiting and
        fixed-percentage audits — `round_measure` is the absolute value of
        `cumulative_net_error_votes` divided by `counted_ballots`, rounded half up to four
        decimal places. It escalates when that value is greater than or equal to 0.0050."

        Design: Difficulty/dual_variant_calc/dual_variant_discrepancy_measure_net_shift_vs_relative_overstatement
        """
        scenario = _setup_one_count_measured_both_ways()

        audit_round = fixtures.read_audit_round(scenario["rla"]["round"]["id"])
        assertions.assert_audit_round(audit_round)
        assert audit_round["round_measure"] == pytest.approx(0.0060, abs=0.00005)
        assert audit_round["status"] == "REVIEW_REQUIRED"
        audit = fixtures.read_audit(scenario["rla"]["audit"]["id"])
        assert audit["discrepancy_measure"] == pytest.approx(0.0060, abs=0.00005)
        assert audit["status"] == "DISCREPANCY_REVIEW"
        assert fixtures.read_election(scenario["election"]["id"])[
            "certification_risk_flag"
        ] is True
        finding = fixtures.only_discrepancy(scenario["net_shift_tally"]["id"])
        assert finding["discrepancy_type"] == "OVERSTATEMENT"
        assert finding["magnitude_votes"] == 6

    def test_the_relative_overstatement_variant_stays_under_its_threshold(self):
        """PRD §3.5: "Under `MAX_RELATIVE_OVERSTATEMENT` — the variant of comparison audits
        — `round_measure` is the largest `relative_taint` among those tallies, floored at
        zero so the measure is never negative, rounded half up to four decimal places. It
        escalates when that value is greater than or equal to 1.0000."

        Design: Difficulty/dual_variant_calc/dual_variant_discrepancy_measure_net_shift_vs_relative_overstatement
        """
        scenario = _setup_one_count_measured_both_ways()

        audit_round = fixtures.read_audit_round(scenario["comparison"]["round"]["id"])
        assert audit_round["round_measure"] == pytest.approx(0.9000, abs=0.00005)
        assert audit_round["status"] == "TALLYING"
        audit = fixtures.read_audit(scenario["comparison"]["audit"]["id"])
        assert audit["discrepancy_measure"] == pytest.approx(0.9000, abs=0.00005)
        assert audit["status"] == "TALLYING"
        finding = fixtures.only_discrepancy(scenario["overstatement_tally"]["id"])
        assert finding["discrepancy_type"] == "OVERSTATEMENT"
        assert finding["magnitude_votes"] == 6


class TestBallotAccountingSurvivesAdjudication:
    """One ambiguous ballot moves into the counts without breaking the identity."""

    def _adjudicate_to_accept(self, scenario):
        interpretation_id = scenario["interpretation"]["id"]
        fixtures.cast_board_vote(interpretation_id, BOARD_DEM, "DEM", "ACCEPT")
        fixtures.cast_board_vote(interpretation_id, BOARD_REP, "REP", "ACCEPT")
        return fixtures.cast_board_vote(
            interpretation_id, BOARD_DEM_2, "DEM", "REJECT"
        )

    def test_three_votes_across_both_parties_reach_quorum_and_adjudicate(self):
        """PRD §3.7: "`quorum_met` becomes true when `votes_cast` is at least three **and**
        the recorded parties include at least one `DEM` and at least one `REP` — abstentions
        count towards quorum but towards neither side of the decision."

        Design: Difficulty/compensating_invariant/compensating_ballot_accounting_conserved_through_adjudication
        """
        scenario = fixtures.setup_pending_adjudication()
        assert scenario["interpretation"]["status"] == "PENDING"
        assert scenario["submitted_tally"]["net_error_votes"] == 11
        assert scenario["submitted_tally"]["relative_taint"] == pytest.approx(
            1.6500, abs=0.00005
        )

        adjudicated = self._adjudicate_to_accept(scenario)

        assertions.assert_ballot_interpretation(adjudicated)
        assert adjudicated["votes_cast"] == 3
        assert adjudicated["accept_count"] == 2
        assert adjudicated["reject_count"] == 1
        assert adjudicated["quorum_met"] is True
        assert adjudicated["status"] == "ADJUDICATED"
        assert adjudicated["final_determination"] == "ALVAREZ"

    def test_the_determination_moves_the_ballot_out_of_the_ambiguous_pile(self):
        """PRD §3.7: "the tally's `ambiguous_ballot_count` is decreased by one, and either
        its `no_vote_count` is increased by one when `final_determination` is `NO_VOTE`, or
        its `counted_votes` entry for the determined candidate is increased by one. The
        ballot accounting invariant — the sum of `counted_votes`, plus
        `ambiguous_ballot_count`, plus `no_vote_count`, equal to the drawn batch's
        `ballot_count` — therefore holds across every adjudication."

        Design: Difficulty/compensating_invariant/compensating_ballot_accounting_conserved_through_adjudication
        """
        scenario = fixtures.setup_pending_adjudication()
        ballot_count = scenario["target_audit_batch"]["ballot_count"]
        assert scenario["submitted_tally"]["ambiguous_ballot_count"] == 1
        assertions.assert_ballot_accounting_identity(
            scenario["submitted_tally"], ballot_count
        )

        self._adjudicate_to_accept(scenario)

        tally = fixtures.read_manual_tally(scenario["manual_tally"]["id"])
        assert tally["counted_votes"] == {"ALVAREZ": 520, "BRENNAN": 480}
        assert tally["ambiguous_ballot_count"] == 0
        assert tally["no_vote_count"] == 0
        assertions.assert_ballot_accounting_identity(tally, ballot_count)
        assert tally["status"] == "SUBMITTED"

    def test_every_error_figure_is_rederived_from_the_adjudicated_counts(self):
        """PRD §3.7: "The tally then recomputes `manual_margin_votes`, `net_error_votes` and
        `relative_taint` from the adjudicated counts, and its discrepancy is created,
        updated or voided to match the recomputed `net_error_votes`, which re-derives the
        round counters and the audit measure exactly as a submission would."

        Design: Difficulty/compensating_invariant/compensating_ballot_accounting_conserved_through_adjudication
        """
        scenario = fixtures.setup_pending_adjudication()
        finding_before = fixtures.only_discrepancy(scenario["manual_tally"]["id"])
        assert finding_before["magnitude_votes"] == 11

        self._adjudicate_to_accept(scenario)

        tally = fixtures.read_manual_tally(scenario["manual_tally"]["id"])
        assert tally["manual_margin_votes"] == 40
        assert tally["net_error_votes"] == 10
        assert tally["relative_taint"] == pytest.approx(1.5000, abs=0.00005)
        finding = fixtures.read_discrepancy(finding_before["id"])
        assert finding["magnitude_votes"] == 10
        assert finding["status"] == "OPEN"
        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["cumulative_net_error_votes"] == 10
        assert audit_round["round_measure"] == pytest.approx(0.0100, abs=0.00005)
        audit = fixtures.read_audit(scenario["audit"]["id"])
        assert audit["status"] == "DISCREPANCY_REVIEW"
        assert audit["discrepancy_measure"] == pytest.approx(0.0100, abs=0.00005)
