"""Settlement signature tallying, execution hurdles and withdrawal."""
import pytest

from test_helpers import (
    U_LICENSEE_A,
    U_NGO,
    U_NGO_2,
    U_TRIBE,
    api_client,
    assert_ledger_matches,
    assert_postures,
    circulate_settlement,
    decide_plan,
    make_licensee_headers,
    new_measure,
    new_settlement,
    read_measure,
    read_project,
    read_settlement,
    read_signature,
    read_study_plan,
    register_party,
    setup_approved_study_plan,
    setup_circulated_settlement,
    sign_roster,
    sign_settlement,
    tally_settlement,
    validate_error,
    withdraw_settlement,
)

TRIBE_PARTY = dict(
    party_name="River Tribe",
    party_type="TRIBE",
    has_conditioning_authority=False,
    vote_weight=1,
    contact_user_id=U_TRIBE,
)
NGO_PARTY = dict(
    party_name="Watershed Alliance",
    party_type="NGO",
    has_conditioning_authority=False,
    vote_weight=1,
    contact_user_id=U_NGO,
)
SECOND_NGO_PARTY = dict(
    party_name="Paddlers Coalition",
    party_type="NGO",
    has_conditioning_authority=False,
    vote_weight=1,
    contact_user_id=U_NGO_2,
)
MINIMUM_FLOW_MEASURE = dict(
    measure_name="Minimum flow release",
    resource_category="WATER_QUALITY",
    capital_cost_usd=600000.00,
    annual_om_cost_usd=20000.00,
    construction_start_year=2026,
    implementation_months=6,
    flow_release_cfs=40,
    gross_head_ft=60,
    release_days=120,
)
RECREATION_MEASURE = dict(
    measure_name="Recreation flow release",
    resource_category="RECREATION",
    capital_cost_usd=300000.00,
    annual_om_cost_usd=10000.00,
    construction_start_year=2026,
    implementation_months=12,
    flow_release_cfs=30,
    gross_head_ft=40,
    release_days=90,
)
LICENSEE_HEADERS = make_licensee_headers(U_LICENSEE_A)


def _attempt_tally(settlement_id, intended_outcome):
    """Tally without pre-validating, so a rejection can be inspected."""
    return api_client.tally_settlement(
        settlement_id, {"intended_outcome": intended_outcome}, LICENSEE_HEADERS
    )


class TestEquallyWeightedRosterFallsShortOfThreshold:
    def test_two_of_three_equal_parties_cannot_execute_the_settlement(self):
        """Shares of 33.33 each sum to 66.66, one cent below the execution threshold.

        PRD §3.5: "The tallied `support_pct` must be at least 66.67, or the request is rejected with `ERR_SUPPORT_THRESHOLD_NOT_MET`."
        PRD §3.5: "Three parties each weighted 1, with two of them supporting, yield per-party shares of 33.33 each, a sum of 66.66, and a `support_pct` of 66.66 — below the execution threshold of 66.67, so execution is refused."

        Design: Difficulty/combinatorial_formula/support_tally_rounds_per_party_before_summing_and_blocks_execution
        """
        ctx = setup_circulated_settlement(party_specs=[TRIBE_PARTY, NGO_PARTY])
        agency, tribe, _ngo = ctx["parties"]
        settlement_id = ctx["settlement"]["id"]
        sign_roster(settlement_id, [(agency, "SUPPORT"), (tribe, "SUPPORT")])

        response = _attempt_tally(settlement_id, "EXECUTE")

        validate_error(response, "ERR_SUPPORT_THRESHOLD_NOT_MET", 422)
        after = read_settlement(settlement_id)
        assert after["status"] == "CIRCULATED"
        assert after["executed_at"] is None

    def test_each_supporting_share_is_rounded_before_the_shares_are_summed(self):
        """The same signatures close the round at 66.66 with two persisted 33.33 shares.

        PRD §3.5: "The evaluation order is pinned and it is not an accounting nicety: each share is rounded *before* summation, never after."
        PRD §3.5: "First, the denominator: `total_vote_weight` is the sum of `vote_weight` over **all** of the project's registered parties, including parties that never signed at all — non-signers dilute support because they stay in the denominator."

        Design: Difficulty/combinatorial_formula/support_tally_rounds_per_party_before_summing_and_blocks_execution
        """
        ctx = setup_circulated_settlement(party_specs=[TRIBE_PARTY, NGO_PARTY])
        agency, tribe, _ngo = ctx["parties"]
        settlement_id = ctx["settlement"]["id"]
        agency_signature, tribe_signature = sign_roster(
            settlement_id, [(agency, "SUPPORT"), (tribe, "SUPPORT")]
        )

        closed = tally_settlement(settlement_id, "CLOSE_ROUND")

        assert closed["support_pct"] == pytest.approx(66.66, abs=0.01)
        assert closed["total_vote_weight"] == 3
        assert closed["status"] == "NEGOTIATING"
        assert closed["round_number"] == 2
        assert read_signature(agency_signature["id"])["share_pct"] == pytest.approx(
            33.33, abs=0.01
        )
        assert read_signature(tribe_signature["id"])["share_pct"] == pytest.approx(
            33.33, abs=0.01
        )


class TestWeightedRosterExactlyAtThreshold:
    def test_shares_of_sixteen_sixty_seven_and_fifty_execute_the_settlement(self):
        """Weights 1 and 3 out of 6 give exactly 66.67, which satisfies the threshold.

        PRD §3.5: "Parties weighted 1, 3 and 2 for a total of 6, with the weight-1 and weight-3 parties supporting, yield 16.67 plus 50.00 for a `support_pct` of exactly 66.67 — precisely at the threshold, which is sufficient."

        Design: Difficulty/boundary_precision_check/support_pct_exactly_at_threshold_executes_the_settlement
        """
        ctx = setup_circulated_settlement(
            party_specs=[
                dict(TRIBE_PARTY, vote_weight=3),
                dict(NGO_PARTY, party_name="River Alliance", vote_weight=2),
            ],
            settlement_measures=[MINIMUM_FLOW_MEASURE],
        )
        agency, tribe, _ngo = ctx["parties"]
        settlement_id = ctx["settlement"]["id"]
        agency_signature, tribe_signature = sign_roster(
            settlement_id, [(agency, "SUPPORT"), (tribe, "SUPPORT")]
        )

        executed = tally_settlement(settlement_id, "EXECUTE")

        assert executed["total_vote_weight"] == 6
        assert read_signature(agency_signature["id"])["share_pct"] == pytest.approx(
            16.67, abs=0.01
        )
        assert read_signature(tribe_signature["id"])["share_pct"] == pytest.approx(
            50.00, abs=0.01
        )
        assert executed["support_pct"] == pytest.approx(66.67, abs=0.01)
        assert executed["status"] == "EXECUTED"
        assert executed["included_measure_count"] == 1

    def test_execution_includes_the_settlement_measure_and_rebuilds_the_ledger(self):
        """The executed settlement's measure turns INCLUDED and enters the burden ledger.

        PRD §3.5: "On success, the tally persists `support_pct` and `total_vote_weight`, stamps `executed_at` from the logical clock, moves every mitigation measure attached to this settlement that is still `PROPOSED` to `INCLUDED`, sets `included_measure_count` to the number of measures so moved, and increments the settlement's `version`."

        Design: Difficulty/boundary_precision_check/support_pct_exactly_at_threshold_executes_the_settlement
        """
        ctx = setup_circulated_settlement(
            party_specs=[
                dict(TRIBE_PARTY, vote_weight=3),
                dict(NGO_PARTY, party_name="River Alliance", vote_weight=2),
            ],
            settlement_measures=[MINIMUM_FLOW_MEASURE],
        )
        agency, tribe, _ngo = ctx["parties"]
        measure = ctx["measures"][0]
        assert measure["status"] == "PROPOSED"
        sign_roster(ctx["settlement"]["id"], [(agency, "SUPPORT"), (tribe, "SUPPORT")])

        tally_settlement(ctx["settlement"]["id"], "EXECUTE")

        assert read_measure(measure["id"])["status"] == "INCLUDED"
        project = read_project(ctx["project"]["id"])
        assert_ledger_matches(
            project,
            total_pme_annual_cost_usd=57500.00,
            total_generation_loss_mwh=230.4,
            administrative_annual_charge_usd=1150.00,
            total_annual_burden_usd=68326.80,
            burden_ratio_pct=0.65,
        )
        assert_postures(project, regulatory_posture="OPEN")


class TestNegotiationRoundExhaustion:
    def test_three_closed_rounds_walk_the_settlement_into_failed(self):
        """Round 1 and 2 return to NEGOTIATING while round 3 has nowhere left to go.

        PRD §3.5: "Below round 3, closing the round moves the settlement `CIRCULATED → NEGOTIATING`: it persists the closed round's `support_pct`, increments `round_number` by 1, clears `circulated_at` back to unset, retains every prior-round signature unchanged, and increments the settlement's `version`."
        PRD §3.5: "At round 3, there is nowhere left to go: closing the round moves the settlement `CIRCULATED → FAILED`, persists `support_pct`, cascades every attached measure still in `PROPOSED` to `SUPERSEDED`, and increments the settlement's `version`."

        Design: Difficulty/non_linear_state_machine/settlement_negotiation_rounds_exhaust_into_failed_and_supersede_measures
        """
        ctx = setup_circulated_settlement(
            party_specs=[NGO_PARTY], settlement_measures=[RECREATION_MEASURE]
        )
        _agency, ngo = ctx["parties"]
        settlement_id = ctx["settlement"]["id"]
        sign_roster(settlement_id, [(ngo, "SUPPORT")])

        after_round_1 = tally_settlement(settlement_id, "CLOSE_ROUND")
        circulate_settlement(settlement_id)
        after_round_2 = tally_settlement(settlement_id, "CLOSE_ROUND")
        circulate_settlement(settlement_id)
        after_round_3 = tally_settlement(settlement_id, "CLOSE_ROUND")

        assert after_round_1["status"] == "NEGOTIATING"
        assert after_round_1["round_number"] == 2
        assert after_round_1["support_pct"] == pytest.approx(50.00, abs=0.01)
        assert after_round_2["status"] == "NEGOTIATING"
        assert after_round_2["round_number"] == 3
        assert after_round_2["support_pct"] == pytest.approx(0.00, abs=0.01)
        assert after_round_3["status"] == "FAILED"
        assert after_round_3["round_number"] == 3

    def test_failure_supersedes_the_proposed_measure_and_keeps_the_ledger_empty(self):
        """The retained round-1 signature is untouched and no ledger figure ever moves.

        PRD §3.5: "No ledger figure moves on failure either, because `PROPOSED` measures were never in the ledger."
        PRD §3.5: "Signatures from earlier rounds are retained forever as an append-only ledger."

        Design: Difficulty/non_linear_state_machine/settlement_negotiation_rounds_exhaust_into_failed_and_supersede_measures
        """
        ctx = setup_circulated_settlement(
            party_specs=[NGO_PARTY], settlement_measures=[RECREATION_MEASURE]
        )
        _agency, ngo = ctx["parties"]
        settlement_id = ctx["settlement"]["id"]
        measure = ctx["measures"][0]
        round_one_signature = sign_roster(settlement_id, [(ngo, "SUPPORT")])[0]

        tally_settlement(settlement_id, "CLOSE_ROUND")
        circulate_settlement(settlement_id)
        tally_settlement(settlement_id, "CLOSE_ROUND")
        circulate_settlement(settlement_id)
        tally_settlement(settlement_id, "CLOSE_ROUND")

        retained = read_signature(round_one_signature["id"])
        assert retained["round_number"] == 1
        assert retained["share_pct"] == pytest.approx(50.00, abs=0.01)
        assert read_measure(measure["id"])["status"] == "SUPERSEDED"
        project = read_project(ctx["project"]["id"])
        assert_ledger_matches(
            project,
            total_pme_annual_cost_usd=0.00,
            total_generation_loss_mwh=0.0,
            administrative_annual_charge_usd=0.00,
            total_annual_burden_usd=0.00,
            burden_ratio_pct=0.00,
        )


class TestExecutionDependsOnTheStudyPlanState:
    def test_ample_support_cannot_execute_while_the_plan_awaits_determination(self):
        """A 75.00 percent roster is refused because the study plan is not yet APPROVED.

        PRD §3.5: "The project must already have a study plan in `APPROVED` status, or the request is rejected with `ERR_STUDY_PLAN_NOT_APPROVED` — settlements cannot be locked in before the study programme is settled."

        Design: Difficulty/cross_entity_state_dependency/settlement_execution_blocked_by_unapproved_study_plan_state
        """
        ctx = setup_circulated_settlement(
            approve_plan=False,
            party_specs=[TRIBE_PARTY, NGO_PARTY, SECOND_NGO_PARTY],
        )
        agency, tribe, ngo, _ngo2 = ctx["parties"]
        settlement_id = ctx["settlement"]["id"]
        sign_roster(
            settlement_id,
            [(agency, "SUPPORT"), (tribe, "SUPPORT"), (ngo, "SUPPORT")],
        )
        assert read_study_plan(ctx["plan"]["id"])["status"] == "UNDER_AGENCY_REVIEW"

        response = _attempt_tally(settlement_id, "EXECUTE")

        validate_error(response, "ERR_STUDY_PLAN_NOT_APPROVED", 409)
        after = read_settlement(settlement_id)
        assert after["status"] == "CIRCULATED"
        assert after["round_number"] == 1
        assert after["executed_at"] is None

    def test_approving_the_plan_lets_the_identical_signature_set_execute(self):
        """Nothing about the settlement changes; only the sibling plan reaches APPROVED.

        PRD §3.5: "Four parties each weighted 1 with three supporting yield 25.00 three times over, a `support_pct` of 75.00, and comfortable execution."

        Design: Difficulty/cross_entity_state_dependency/settlement_execution_blocked_by_unapproved_study_plan_state
        """
        ctx = setup_circulated_settlement(
            approve_plan=False,
            party_specs=[TRIBE_PARTY, NGO_PARTY, SECOND_NGO_PARTY],
        )
        agency, tribe, ngo, _ngo2 = ctx["parties"]
        settlement_id = ctx["settlement"]["id"]
        sign_roster(
            settlement_id,
            [(agency, "SUPPORT"), (tribe, "SUPPORT"), (ngo, "SUPPORT")],
        )
        validate_error(
            _attempt_tally(settlement_id, "EXECUTE"), "ERR_STUDY_PLAN_NOT_APPROVED", 409
        )

        approved = decide_plan(ctx["plan"]["id"], "APPROVE")
        executed = tally_settlement(settlement_id, "EXECUTE")

        assert approved["status"] == "APPROVED"
        assert executed["support_pct"] == pytest.approx(75.00, abs=0.01)
        assert executed["status"] == "EXECUTED"
        project = read_project(ctx["project"]["id"])
        assert project["total_pme_annual_cost_usd"] == pytest.approx(0.00, abs=0.01)


class TestWithdrawalRestoresTheLedger:
    def _executed_settlement_over_a_priced_project(self):
        """An INCLUDED prescription measure plus an executed settlement measure."""
        ctx = setup_approved_study_plan(
            study_overrides=dict(
                resource_category="WATER_QUALITY", study_title="Temperature study"
            ),
            site_overrides=dict(river_mile=5.0),
            project_name="Restore Falls",
            installed_capacity_mw=24.0,
            base_annual_generation_mwh=250000,
            license_expiration_date="2033-12-31",
        )
        project_id = ctx["project"]["id"]
        tribe = register_party(project_id, **TRIBE_PARTY)
        base_measure = new_measure(
            project_id, source="AGENCY_PRESCRIPTION", **MINIMUM_FLOW_MEASURE
        )
        ctx["before"] = read_project(project_id)
        settlement = new_settlement(project_id)
        settlement_measure = new_measure(
            project_id,
            source="SETTLEMENT",
            settlement_id=settlement["id"],
            measure_name="Upstream fish ladder",
            resource_category="FISH_PASSAGE",
            capital_cost_usd=1200000.00,
            annual_om_cost_usd=45000.00,
            construction_start_year=2029,
            implementation_months=18,
            flow_release_cfs=120,
            gross_head_ft=85,
            release_days=180,
        )
        circulate_settlement(settlement["id"])
        sign_settlement(settlement["id"], ctx["agency_party"], position="SUPPORT")
        sign_settlement(settlement["id"], tribe, position="SUPPORT")
        ctx.update(
            {
                "settlement": settlement,
                "base_measure": base_measure,
                "settlement_measure": settlement_measure,
            }
        )
        return ctx

    def test_execution_lifts_the_ledger_onto_the_settlement_measure(self):
        """Unanimous support adds the fish ladder and moves every ledger figure upward.

        PRD §3.7: "`total_annual_burden_usd` is then `total_pme_annual_cost_usd` plus `administrative_annual_charge_usd` plus that energy value."

        Design: Difficulty/compensating_invariant/settlement_withdrawal_restores_the_burden_ledger_exactly
        """
        ctx = self._executed_settlement_over_a_priced_project()
        assert_ledger_matches(
            ctx["before"],
            total_pme_annual_cost_usd=57500.00,
            total_generation_loss_mwh=230.4,
            administrative_annual_charge_usd=1150.00,
            total_annual_burden_usd=68326.80,
            burden_ratio_pct=0.65,
        )

        executed = tally_settlement(ctx["settlement"]["id"], "EXECUTE")

        assert executed["support_pct"] == pytest.approx(100.00, abs=0.01)
        assert executed["status"] == "EXECUTED"
        during = read_project(ctx["project"]["id"])
        assert_ledger_matches(
            during,
            total_pme_annual_cost_usd=157136.35,
            total_generation_loss_mwh=1267.2,
            administrative_annual_charge_usd=3142.73,
            total_annual_burden_usd=213501.48,
            burden_ratio_pct=2.03,
        )

    def test_withdrawal_returns_every_ledger_figure_to_its_pre_execution_value(self):
        """The tiered administrative charge and all five figures come back bit-for-bit.

        PRD §3.5: "Because the burden ledger is always rebuilt from the current measure set rather than adjusted incrementally, the withdrawal restores every ledger figure to exactly its pre-execution value, and `regulatory_posture` is then recomputed from those restored figures."
        PRD §3.5: "On success it stamps `withdrawn_at` from the logical clock, resets `included_measure_count` to 0, moves every measure attached to this settlement whose `source` is `SETTLEMENT` and whose status is `INCLUDED` to `WITHDRAWN`, and moves every compliance obligation pointing at one of those measures whose status is `PENDING`, `SCHEDULED` or `OVERDUE` to `WAIVED`."

        Design: Difficulty/compensating_invariant/settlement_withdrawal_restores_the_burden_ledger_exactly
        """
        ctx = self._executed_settlement_over_a_priced_project()
        tally_settlement(ctx["settlement"]["id"], "EXECUTE")

        withdrawn = withdraw_settlement(
            ctx["settlement"]["id"], withdrawal_reason="Party withdrew consent"
        )

        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["included_measure_count"] == 0
        assert read_measure(ctx["settlement_measure"]["id"])["status"] == "WITHDRAWN"
        assert read_measure(ctx["base_measure"]["id"])["status"] == "INCLUDED"
        after = read_project(ctx["project"]["id"])
        assert_ledger_matches(
            after,
            total_pme_annual_cost_usd=57500.00,
            total_generation_loss_mwh=230.4,
            administrative_annual_charge_usd=1150.00,
            total_annual_burden_usd=68326.80,
            burden_ratio_pct=0.65,
        )
        assert_postures(after, regulatory_posture="OPEN")
        assert after["economically_infeasible"] is False
