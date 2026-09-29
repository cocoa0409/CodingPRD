"""Escrow arithmetic on the transfer-application lifecycle.

PRD §3.4: "Submission is where volume actually moves, and it is the clearest
illustration of the priority ladder at work."
"""
import pytest
from test_helpers import ApiErrorId, api_client, get_success_data, validate_error
from test_helpers.fixtures import (
    ADJUDICATOR,
    ANALYST,
    add_injury_analysis,
    draft_application,
    read_application,
    read_claimant,
    read_right,
    right_version,
    setup_certified_right,
    submit_application,
)


class TestSubmitWithdrawRestoresTheLedger:
    """PRD §3.4 — the escrow taken on submission and given back on withdrawal.

    PRD §2.9: "`certified_hcu_af` equals `transferable_af` plus `encumbered_af`
    plus `transferred_away_af`" — every step below is checked against it.
    """

    def _drafted(self):
        bundle = setup_certified_right()
        bundle["application"] = draft_application(
            bundle["right"]["id"], bundle["study"]["id"], 70.00
        )
        bundle["analysis"] = add_injury_analysis(bundle["application"]["id"])
        bundle["right"] = read_right(bundle["right"]["id"])
        return bundle

    def test_submission_moves_the_requested_volume_into_escrow(self):
        """PRD §3.4: "On the right, `encumbered_af` increases by that same amount
        and `transferable_af` decreases by it, conserving the ledger identity;
        the right's status is re-derived, which is what carries an otherwise idle
        right `ACTIVE → ENCUMBERED`".

        The certified 195.00 AF sits entirely in `transferable_af` while the
        application is `DRAFT` — PRD §3.4: "No volume is escrowed, `escrowed_af`
        reads 0.00, and no bucket on the right has moved." Submitting 70.00 AF
        splits it 125.00 / 70.00 without changing `certified_hcu_af`.

        Design: Difficulty/compensating_invariant/right_volume_ledger_submit_withdraw
        """
        bundle = self._drafted()

        before = bundle["right"]
        assert before["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert before["transferable_af"] == pytest.approx(195.00, abs=0.01)
        assert before["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert before["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert before["status"] == "ACTIVE"
        assert before["pending_review_count"] == 1
        assert bundle["application"]["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        assert read_claimant(bundle["claimant"]["id"])["open_application_count"] == 1

        application = submit_application(
            bundle["application"]["id"], bundle["right"]["id"]
        )

        assert application["status"] == "SUBMITTED"
        assert application["escrowed_af"] == pytest.approx(70.00, abs=0.01)
        after = read_right(bundle["right"]["id"])
        assert after["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert after["transferable_af"] == pytest.approx(125.00, abs=0.01)
        assert after["encumbered_af"] == pytest.approx(70.00, abs=0.01)
        assert after["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert after["status"] == "ENCUMBERED"
        assert read_claimant(bundle["claimant"]["id"])["open_application_count"] == 1

    def test_withdrawal_restores_the_pre_submission_ledger_exactly(self):
        """PRD §3.4: "`escrowed_af` is released to 0.00 and the released volume
        moves from the right's `encumbered_af` back into its `transferable_af`,
        conserving the ledger, with the right's status re-derived and its
        `version` bumped."

        The round trip is a compensating pair: after withdrawal the four buckets
        read exactly what they read before submission, the `DRAFT` analysis is
        `VOIDED` so `pending_review_count` falls back to 0, and the terminal
        application no longer counts as open.

        Design: Difficulty/compensating_invariant/right_volume_ledger_submit_withdraw
        """
        bundle = self._drafted()
        submit_application(bundle["application"]["id"], bundle["right"]["id"])

        application = get_success_data(
            api_client.withdraw_transfer_application(
                bundle["application"]["id"], "Applicant re-scoping off the record.", ANALYST
            )
        )

        assert application["status"] == "WITHDRAWN"
        assert application["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["certified_hcu_af"] == pytest.approx(195.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(195.00, abs=0.01)
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["status"] == "ACTIVE"
        assert right["pending_review_count"] == 0
        analysis = get_success_data(
            api_client.get_injury_analysis(bundle["analysis"]["id"], ANALYST)
        )
        assert analysis["status"] == "VOIDED"
        assert read_claimant(bundle["claimant"]["id"])["open_application_count"] == 0


class TestStandingSanctionOutranksTheVolumeBudget:
    """PRD §3.4 — the fourth submit gate reports before the fifth.

    The application asks for 500.00 AF against a right holding only 195.00, so
    the volume budget is violated throughout; the claimant's standing is
    sanctioned on top of that for the first attempt only.
    """

    def _drafted_over_budget(self):
        bundle = setup_certified_right()
        bundle["application"] = draft_application(
            bundle["right"]["id"],
            bundle["study"]["id"],
            500.00,
            proposed_purpose_of_use="INDUSTRIAL",
        )
        return bundle

    def test_delinquent_standing_is_reported_instead_of_the_volume_excess(self):
        """PRD §3.4: "the acting claimant's `standing_status` must be
        `IN_GOOD_STANDING`, with `DELINQUENT` or `BARRED` yielding
        `ERR_CLAIMANT_NOT_IN_GOOD_STANDING` (HTTP 403); and only then is the
        volume budget consulted".

        PRD §3.4: "A delinquent claimant asking for more water than the right
        holds therefore learns about the standing problem, not the volume
        problem." Nothing is escrowed by the refusal.

        Design: Difficulty/priority_pair_validation_conflict/standing_sanction_beats_volume_budget
        """
        bundle = self._drafted_over_budget()
        get_success_data(
            api_client.set_claimant_standing(
                bundle["claimant"]["id"], "DELINQUENT", ADJUDICATOR
            )
        )

        response = api_client.submit_transfer_application(
            bundle["application"]["id"], right_version(bundle["right"]["id"]), ANALYST
        )

        validate_error(
            response,
            ApiErrorId.ERR_CLAIMANT_NOT_IN_GOOD_STANDING.value,
            expected_status=403,
        )
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "DRAFT"
        assert application["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(195.00, abs=0.01)
        assert right["status"] == "ACTIVE"

    def test_volume_budget_surfaces_only_after_standing_is_restored(self):
        """PRD §3.4: "requiring `requested_af` to be no greater than the right's
        `transferable_af`, with equality accepted and any excess rejected as
        `ERR_TRANSFERABLE_VOLUME_EXCEEDED` (HTTP 422)."

        The identical request that drew a 403 while the claimant was
        `DELINQUENT` draws a 422 once standing is `IN_GOOD_STANDING` again: the
        two gates are ordered, not alternative, and the volume defect was there
        all along. The application stays `DRAFT` and still counts as open.

        Design: Difficulty/priority_pair_validation_conflict/standing_sanction_beats_volume_budget
        """
        bundle = self._drafted_over_budget()
        get_success_data(
            api_client.set_claimant_standing(
                bundle["claimant"]["id"], "DELINQUENT", ADJUDICATOR
            )
        )
        api_client.submit_transfer_application(
            bundle["application"]["id"], right_version(bundle["right"]["id"]), ANALYST
        )
        get_success_data(
            api_client.set_claimant_standing(
                bundle["claimant"]["id"], "IN_GOOD_STANDING", ADJUDICATOR
            )
        )

        response = api_client.submit_transfer_application(
            bundle["application"]["id"], right_version(bundle["right"]["id"]), ANALYST
        )

        validate_error(
            response,
            ApiErrorId.ERR_TRANSFERABLE_VOLUME_EXCEEDED.value,
            expected_status=422,
        )
        application = read_application(bundle["application"]["id"])
        assert application["status"] == "DRAFT"
        assert application["escrowed_af"] == pytest.approx(0.00, abs=0.01)
        right = read_right(bundle["right"]["id"])
        assert right["encumbered_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferred_away_af"] == pytest.approx(0.00, abs=0.01)
        assert right["transferable_af"] == pytest.approx(195.00, abs=0.01)
        assert right["status"] == "ACTIVE"
        assert read_claimant(bundle["claimant"]["id"])["open_application_count"] == 1
