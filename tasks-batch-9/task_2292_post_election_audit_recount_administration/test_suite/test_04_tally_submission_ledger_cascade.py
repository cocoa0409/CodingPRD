"""Hand-count submission, the error ledger it feeds, and the reopen that reverses it."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    fixtures,
    make_tally_team_lead_headers,
    validate_error,
    validate_success,
)


class TestSubmissionCascadesToTheElectionRiskFlag:
    """One discrepant hand count moves five entities inside one request."""

    def test_submission_computes_the_error_figures_and_counts_the_batch(self):
        """PRD §3.5: "`net_error_votes` is `machine_margin_votes` minus
        `manual_margin_votes`; a positive value means the machine overstated the winner's
        margin, and a negative value means it understated it. `relative_taint` is
        `net_error_votes` multiplied by the contest's `margin_votes`, divided by twice the
        drawn batch's `ballot_count`, rounded half up to four decimal places."

        Design: Difficulty/transitive_cascade/cascade_tally_submit_five_hops_to_election_risk_flag
        """
        scenario = fixtures.setup_draft_tally(
            counted_votes={"ALVAREZ": 520, "BRENNAN": 480}
        )

        submitted = fixtures.submit_manual_tally(
            scenario["manual_tally"]["id"], scenario["team"]["id"]
        )

        assertions.assert_manual_tally(submitted)
        assert submitted["status"] == "SUBMITTED"
        assert submitted["machine_margin_votes"] == 50
        assert submitted["manual_margin_votes"] == 40
        assert submitted["net_error_votes"] == 10
        assert submitted["relative_taint"] == pytest.approx(1.5000, abs=0.00005)
        assert fixtures.read_audit_batch(scenario["target_audit_batch"]["id"])[
            "tally_status"
        ] == "COUNTED"

    def test_submission_creates_the_open_overstatement_finding(self):
        """PRD §3.6: "Its `discrepancy_type` is derived: `OVERSTATEMENT` when the tally's
        `net_error_votes` is greater than zero, `UNDERSTATEMENT` when it is less than zero,
        and `BALLOT_COUNT_MISMATCH` when `net_error_votes` is exactly zero but the
        hand-counted valid votes differ from the machine valid votes."

        Design: Difficulty/transitive_cascade/cascade_tally_submit_five_hops_to_election_risk_flag
        """
        scenario = fixtures.setup_open_discrepancy()

        finding = scenario["discrepancy"]
        assertions.assert_discrepancy(finding)
        assert finding["status"] == "OPEN"
        assert finding["discrepancy_type"] == "OVERSTATEMENT"
        assert finding["magnitude_votes"] == 10
        assert finding["relative_taint"] == pytest.approx(1.5000, abs=0.00005)
        assert finding["manual_tally_id"] == scenario["manual_tally"]["id"]

    def test_round_audit_and_election_rollups_all_move_inside_the_request(self):
        """PRD §3.5: "When the recomputed measure reaches the applicable escalation
        threshold the round moves from `TALLYING` to `REVIEW_REQUIRED`, which drives the
        audit from `TALLYING` to `DISCREPANCY_REVIEW` and recomputes the audit's
        `discrepancy_measure` and timeline fields, which in turn sets the election's
        `certification_risk_flag` to true."

        Design: Difficulty/transitive_cascade/cascade_tally_submit_five_hops_to_election_risk_flag
        """
        scenario = fixtures.setup_open_discrepancy()

        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["discrepancy_count"] == 1
        assert audit_round["cumulative_net_error_votes"] == 10
        assert audit_round["counted_ballots"] == 1000
        assert audit_round["round_measure"] == pytest.approx(0.0100, abs=0.00005)
        assert audit_round["status"] == "REVIEW_REQUIRED"

        audit = fixtures.read_audit(scenario["audit"]["id"])
        assert audit["status"] == "DISCREPANCY_REVIEW"
        assert audit["discrepancy_measure"] == pytest.approx(0.0100, abs=0.00005)
        assert audit["cumulative_net_error_votes"] == 10
        assert audit["counted_ballots"] == 1000

        assert fixtures.read_election(scenario["election"]["id"])[
            "certification_risk_flag"
        ] is True
        untouched = [
            fixtures.read_audit_batch(drawn["id"])["tally_status"]
            for drawn in scenario["audit_batches"][1:]
        ]
        assert untouched == ["NOT_STARTED", "NOT_STARTED"]


class TestRoundMeasureAtTheNetShiftThreshold:
    """0.0050 is inside the threshold; 0.0040 is not."""

    def test_a_measure_below_the_threshold_leaves_the_round_tallying(self):
        """PRD §3.5: "It escalates when that value is greater than or equal to 0.0050: net
        error of half a vote per hundred counted ballots is the point at which the round
        stops being routine."

        Design: Difficulty/boundary_precision_check/boundary_round_measure_exactly_at_net_shift_threshold
        """
        scenario = fixtures.setup_submitted_tally(
            counted_votes={"ALVAREZ": 523, "BRENNAN": 477}
        )

        assert scenario["submitted_tally"]["net_error_votes"] == 4
        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["round_measure"] == pytest.approx(0.0040, abs=0.00005)
        assert audit_round["status"] == "TALLYING"
        assert audit_round["cumulative_net_error_votes"] == 4
        assert fixtures.read_audit(scenario["audit"]["id"])["status"] == "TALLYING"

    def test_a_measure_exactly_on_the_threshold_escalates_the_round(self):
        """PRD §2.7: "every threshold comparison against them is inclusive — a value that
        lands exactly on a threshold satisfies the threshold."

        Design: Difficulty/boundary_precision_check/boundary_round_measure_exactly_at_net_shift_threshold
        """
        scenario = fixtures.setup_submitted_tally(
            counted_votes={"ALVAREZ": 523, "BRENNAN": 477}
        )
        tally_id = scenario["manual_tally"]["id"]
        team_id = scenario["team"]["id"]
        fixtures.reopen_manual_tally(tally_id, team_id)
        validate_success(
            api_client.patch_manual_tally(
                tally_id,
                {
                    "counted_votes": {"ALVAREZ": 522, "BRENNAN": 477},
                    "ambiguous_ballot_count": 0,
                    "no_vote_count": 1,
                },
                make_tally_team_lead_headers(team_id),
            )
        )

        resubmitted = fixtures.submit_manual_tally(tally_id, team_id)

        assert resubmitted["manual_margin_votes"] == 45
        assert resubmitted["net_error_votes"] == 5
        assert resubmitted["relative_taint"] == pytest.approx(0.7500, abs=0.00005)
        assert resubmitted["reopen_count"] == 1
        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["round_measure"] == pytest.approx(0.0050, abs=0.00005)
        assert audit_round["status"] == "REVIEW_REQUIRED"
        assert audit_round["cumulative_net_error_votes"] == 5
        assert audit_round["counted_ballots"] == 1000
        assert audit_round["discrepancy_count"] == 1
        assert fixtures.read_audit(scenario["audit"]["id"])["status"] == (
            "DISCREPANCY_REVIEW"
        )
        findings = fixtures.list_discrepancies(tally_id)
        assert sorted(finding["status"] for finding in findings) == ["OPEN", "VOIDED"]
        live = [finding for finding in findings if finding["status"] == "OPEN"][0]
        assert live["magnitude_votes"] == 5


class TestReopenAllowanceIsBoundedAtTwo:
    """A tally may go round the submit/reopen loop twice and no more."""

    def test_two_reopens_are_allowed_and_the_third_is_refused(self):
        """PRD §3.5: "The tally must be `SUBMITTED`, its `reopen_count` must be below two,
        the owning audit must not be `COMPLETE` or `TERMINATED`, and no discrepancy of the
        tally may be `ESCALATED` or `RESOLVED` — once the board has acted on a finding, the
        count beneath it is no longer the team's to withdraw. A third reopen is refused
        because the reopen limit is exceeded."

        Design: Difficulty/non_linear_state_machine/nonlinear_tally_reopen_cycle_bounded_at_two
        """
        scenario = fixtures.setup_submitted_tally()
        tally_id = scenario["manual_tally"]["id"]
        team_id = scenario["team"]["id"]

        fixtures.reopen_manual_tally(tally_id, team_id)
        fixtures.submit_manual_tally(tally_id, team_id)
        fixtures.reopen_manual_tally(tally_id, team_id)
        fixtures.submit_manual_tally(tally_id, team_id)
        response = api_client.reopen_manual_tally(
            tally_id,
            {"reason": "Third stack recount requested."},
            make_tally_team_lead_headers(team_id),
        )

        validate_error(response, ApiErrorId.ERR_REOPEN_LIMIT_EXCEEDED.value, 409)
        tally = fixtures.read_manual_tally(tally_id)
        assert tally["status"] == "SUBMITTED"
        assert tally["reopen_count"] == 2

    def test_the_ledger_after_the_second_resubmission_matches_one_clean_count(self):
        """PRD §2.8: "Reopening a submitted tally must leave the round and audit error
        ledgers at exactly the values they held before that tally was submitted — the
        reversal subtracts precisely what the submission added, and a status that was
        escalated because of the submission falls back when the recomputed measure no
        longer justifies it."

        Design: Difficulty/non_linear_state_machine/nonlinear_tally_reopen_cycle_bounded_at_two
        """
        scenario = fixtures.setup_submitted_tally()
        tally_id = scenario["manual_tally"]["id"]
        team_id = scenario["team"]["id"]

        for _cycle in range(2):
            fixtures.reopen_manual_tally(tally_id, team_id)
            fixtures.submit_manual_tally(tally_id, team_id)

        tally = fixtures.read_manual_tally(tally_id)
        assert tally["net_error_votes"] == 0
        assert fixtures.read_audit_batch(scenario["target_audit_batch"]["id"])[
            "tally_status"
        ] == "COUNTED"
        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["status"] == "TALLYING"
        assert audit_round["discrepancy_count"] == 0
        assert audit_round["counted_ballots"] == 1000
        assert audit_round["round_measure"] == pytest.approx(0.0, abs=0.00005)
        assert fixtures.read_audit(scenario["audit"]["id"])["status"] == "TALLYING"


class TestReopenRestoresTheAuditErrorLedger:
    """The compensation is exact: every ledger figure returns to its pre-submit value."""

    def test_reopen_returns_the_round_ledger_to_its_pre_submission_values(self):
        """PRD §3.5: "each voided discrepancy decreases the round's `discrepancy_count` by
        one, subtracts the tally's `net_error_votes` from the round's
        `cumulative_net_error_votes`, subtracts the drawn batch's `ballot_count` from the
        round's `counted_ballots`, and re-derives `round_measure`."

        Design: Difficulty/compensating_invariant/compensating_reopen_restores_audit_error_ledger
        """
        scenario = fixtures.setup_open_discrepancy()
        before = fixtures.read_audit_round(scenario["round"]["id"])
        assert before["cumulative_net_error_votes"] == 10
        assert before["counted_ballots"] == 1000
        assert before["round_measure"] == pytest.approx(0.0100, abs=0.00005)
        assert before["discrepancy_count"] == 1

        fixtures.reopen_manual_tally(
            scenario["manual_tally"]["id"], scenario["team"]["id"]
        )

        after = fixtures.read_audit_round(scenario["round"]["id"])
        assert after["cumulative_net_error_votes"] == 0
        assert after["counted_ballots"] == 0
        assert after["round_measure"] == pytest.approx(0.0, abs=0.00005)
        assert after["discrepancy_count"] == 0
        assert after["status"] == "TALLYING"

    def test_reopen_voids_the_finding_and_walks_the_audit_and_election_back(self):
        """PRD §3.5: "When the recomputed measure drops below the applicable threshold the
        round moves from `REVIEW_REQUIRED` back to `TALLYING`, which drives the audit from
        `DISCREPANCY_REVIEW` back to `TALLYING` and re-derives the election's
        `certification_risk_flag`."

        Design: Difficulty/compensating_invariant/compensating_reopen_restores_audit_error_ledger
        """
        scenario = fixtures.setup_open_discrepancy()

        fixtures.reopen_manual_tally(
            scenario["manual_tally"]["id"], scenario["team"]["id"]
        )

        audit = fixtures.read_audit(scenario["audit"]["id"])
        assert audit["status"] == "TALLYING"
        assert audit["discrepancy_measure"] == pytest.approx(0.0, abs=0.00005)
        assert audit["cumulative_net_error_votes"] == 0
        assert audit["counted_ballots"] == 0
        assert fixtures.read_discrepancy(scenario["discrepancy"]["id"])["status"] == (
            "VOIDED"
        )
        assert fixtures.read_election(scenario["election"]["id"])[
            "certification_risk_flag"
        ] is False

    def test_reopen_preserves_the_recorded_counts_and_clears_the_error_figures(self):
        """PRD §3.5: "The tally's `status` returns to `DRAFT`, `reopen_count` increases by
        one, `net_error_votes` and `relative_taint` are reset to null, and the drawn
        batch's `tally_status` returns from `COUNTED` to `IN_PROGRESS`."

        Design: Difficulty/compensating_invariant/compensating_reopen_restores_audit_error_ledger
        """
        scenario = fixtures.setup_open_discrepancy()

        reopened = fixtures.reopen_manual_tally(
            scenario["manual_tally"]["id"], scenario["team"]["id"]
        )

        assert reopened["status"] == "DRAFT"
        assert reopened["reopen_count"] == 1
        assert reopened["net_error_votes"] is None
        assert reopened["relative_taint"] is None
        assert reopened["counted_votes"] == {"ALVAREZ": 520, "BRENNAN": 480}
        assert fixtures.read_audit_batch(scenario["target_audit_batch"]["id"])[
            "tally_status"
        ] == "IN_PROGRESS"
