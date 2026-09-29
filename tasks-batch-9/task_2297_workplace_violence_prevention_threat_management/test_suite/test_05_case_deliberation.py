"""Behavioural risk: the interim score, the per-seat rounded shares and the reassessment cycle."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ApiClient,
    ApiErrorId,
    assert_case_state,
    assert_risk_scores,
    assert_seat_ballot,
    assert_seat_ballot_cleared,
    assert_two_decimal_value,
    build_ballot,
    build_decision,
    build_reassess,
    build_separation,
    read_case,
    setup_deliberating_case,
    setup_monitoring_case,
)

#: The five round-two ballots, all MONITOR, in casting order.
SECOND_ROUND_BALLOTS = (
    ("member_ops", "Round 2: shifts were separated, contact risk dropped."),
    ("member_sec", "Round 2: badge control installed at the front desk."),
    ("threat_team_lead", "Round 2: subject engaged with the counselling referral."),
    ("member_clin", "Round 2: clinical picture unchanged and non-acute."),
    ("member_legal", "Round 2: no charges filed; order no longer sought."),
)


def _read_seat(api: ApiClient, ctx, seat_key: str):
    return get_success_data(
        api.get_team_assignment(ctx["seats"][seat_key]["id"], ctx["headers"]["threat_team_lead"])
    )


class TestInterimAndConsensusVariants:
    """The interim score looks only at the incident; the consensus score blends in the team."""

    def test_interim_score_of_forty_two_ignores_every_ballot(self, api: ApiClient) -> None:
        """Fifty severity points, no prior cases and a weapon give 42.00 with the consensus still null.

        PRD: "The score is then the sum of three terms: the report's `severity_points` multiplied by 0.60, plus 8 points for each prior case with the prior-case count capped at 4, plus 12 points when the report's `weapon_involved` is true."
        Design: Difficulty/dual_variant_calc/behavioral_risk_interim_versus_consensus_divergence
        """
        ctx = setup_deliberating_case(api)

        case = read_case(api, ctx)

        assert_case_state(case, status="DELIBERATION", assessment_round=1, ballot_count_current_round=5)
        assert_risk_scores(case, interim=42.00)
        assert case["consensus_risk_score"] is None

    def test_consensus_variant_diverges_from_the_interim_by_eighteen_point_nine_four(
        self, api: ApiClient
    ) -> None:
        """The decision blends 42.00 with the team's 71.14 into 60.94 and rebands the case HIGH.

        PRD: "Finally, `consensus_risk_score` is 0.35 multiplied by the case's `interim_risk_score` plus 0.65 multiplied by the sum of rounded shares, rounded half-up to two decimal places, and `risk_band` is refreshed from it."
        Design: Difficulty/dual_variant_calc/behavioral_risk_interim_versus_consensus_divergence
        """
        ctx = setup_deliberating_case(api)

        decided = get_success_data(
            api.decide_threat_case(
                ctx["case"]["id"],
                build_decision("ELEVATED_RISK"),
                ctx["headers"]["threat_team_lead"],
            )
        )

        assert_risk_scores(
            decided,
            interim=42.00,
            consensus=60.94,
            risk_band="HIGH",
            disposition="ELEVATED_RISK",
        )
        assert_case_state(decided, status="MONITORING")
        assert_two_decimal_value(
            decided["consensus_risk_score"] - decided["interim_risk_score"],
            18.94,
            "variant divergence",
        )


class TestPerSeatShareRounding:
    """Each seat's share is rounded before the shares are added together."""

    def test_each_seat_share_is_rounded_to_two_decimals_before_the_sum(
        self, api: ApiClient
    ) -> None:
        """The five discipline weights over a total of 5.125 give 9.83, 24.56, 12.68, 7.85 and 16.22.

        PRD: "The order is mandatory and not interchangeable: each share is rounded first and the rounded shares are summed, because summing the unrounded shares and rounding once at the end produces a different number and is wrong."
        Design: Difficulty/combinatorial_formula/consensus_ballot_shares_rounded_per_seat_then_summed
        """
        ctx = setup_deliberating_case(api)
        get_success_data(
            api.decide_threat_case(
                ctx["case"]["id"],
                build_decision("ELEVATED_RISK"),
                ctx["headers"]["threat_team_lead"],
            )
        )

        expected = (
            ("ops", 0.775, 9.83),
            ("sec", 1.325, 24.56),
            ("hr", 1.000, 12.68),
            ("clin", 1.150, 7.85),
            ("legal", 0.875, 16.22),
        )
        total = 0.0
        for seat_key, weight, share in expected:
            seat = _read_seat(api, ctx, seat_key)
            assert_seat_ballot(seat, ballot_round=1, ballot_weight=weight, ballot_share=share)
            total += seat["ballot_share"]
        assert_two_decimal_value(total, 71.14, "sum of rounded shares")

    def test_consensus_score_lands_on_sixty_point_nine_four_not_sixty_point_nine_five(
        self, api: ApiClient
    ) -> None:
        """Rounding each share at its own step, then blending, gives 60.94 rather than 60.95.

        PRD: "For each counted seat, `ballot_weight` is pinned to that seat's discipline weight, and `ballot_share` is that seat's ballot points multiplied by its `ballot_weight`, divided by the total weight, and **rounded half-up to two decimal places at that point**."
        Design: Difficulty/combinatorial_formula/consensus_ballot_shares_rounded_per_seat_then_summed
        """
        ctx = setup_deliberating_case(api)

        decided = get_success_data(
            api.decide_threat_case(
                ctx["case"]["id"],
                build_decision("ELEVATED_RISK"),
                ctx["headers"]["threat_team_lead"],
            )
        )

        assert_risk_scores(decided, consensus=60.94)
        assert decided["consensus_risk_score"] != 60.95


class TestReassessmentCycle:
    """The DELIBERATION to ASSESSING loop wipes every ballot and can change the outcome."""

    def test_reassess_reopens_round_two_and_clears_every_seat(self, api: ApiClient) -> None:
        """Round two starts with no ballots, the interim score intact and the consensus still null.

        PRD: "Reassessment, carrying a mandatory `reassess_reason`, returns the case `DELIBERATION` → `ASSESSING` for a fresh round: `assessment_round` increments by one, and `ballot_value`, `ballot_round`, `ballot_weight`, `ballot_share`, `ballot_submitted_at` and `rationale` are cleared on **every** seat of the case, so `ballot_count_current_round` falls back to 0."
        Design: Difficulty/non_linear_state_machine/threat_case_deliberation_reassess_cycle_clears_ballots_and_changes_outcome
        """
        ctx = setup_deliberating_case(api)

        reassessed = get_success_data(
            api.reassess_threat_case(
                ctx["case"]["id"],
                build_reassess(
                    reassess_reason=(
                        "Shifts were separated and badge control was installed; "
                        "the team re-scores."
                    )
                ),
                ctx["headers"]["threat_team_lead"],
            )
        )

        assert_case_state(
            reassessed, status="ASSESSING", assessment_round=2, ballot_count_current_round=0
        )
        assert_risk_scores(reassessed, interim=42.00)
        assert reassessed["consensus_risk_score"] is None
        for seat_key in ("hr", "sec", "ops", "clin", "legal"):
            assert_seat_ballot_cleared(_read_seat(api, ctx, seat_key))

    def test_second_lap_of_monitor_ballots_yields_a_different_consensus(
        self, api: ApiClient
    ) -> None:
        """Five MONITOR ballots in round two give 37.45, band MODERATE and disposition MONITOR.

        PRD: "`risk_band` is `IMMINENT` when `consensus_risk_score` is at least 70, `HIGH` when it is at least 45 but below 70, `MODERATE` when it is at least 20 but below 45, and `LOW` below 20."
        Design: Difficulty/non_linear_state_machine/threat_case_deliberation_reassess_cycle_clears_ballots_and_changes_outcome
        """
        ctx = setup_deliberating_case(api)
        get_success_data(
            api.reassess_threat_case(
                ctx["case"]["id"],
                build_reassess(
                    reassess_reason=(
                        "Shifts were separated and badge control was installed; "
                        "the team re-scores."
                    )
                ),
                ctx["headers"]["threat_team_lead"],
            )
        )

        for header_key, rationale in SECOND_ROUND_BALLOTS:
            get_success_data(
                api.cast_ballot(
                    ctx["case"]["id"],
                    build_ballot("MONITOR", rationale),
                    ctx["headers"][header_key],
                )
            )
        assert_case_state(
            read_case(api, ctx), status="DELIBERATION", ballot_count_current_round=5
        )

        decided = get_success_data(
            api.decide_threat_case(
                ctx["case"]["id"], build_decision("MONITOR"), ctx["headers"]["threat_team_lead"]
            )
        )

        assert_risk_scores(
            decided, consensus=37.45, risk_band="MODERATE", disposition="MONITOR"
        )
        assert_case_state(decided, status="MONITORING", assessment_round=2)
        assert_seat_ballot(
            _read_seat(api, ctx, "sec"), ballot_value="MONITOR", ballot_round=2, ballot_share=9.05
        )


class TestConveneStateBeforeQuorum:
    """The state check on convene runs ahead of the quorum check."""

    def _monitoring_case_with_a_recused_legal_seat(self, api: ApiClient):
        ctx = setup_monitoring_case(api)
        get_success_data(
            api.separate_employee(
                ctx["legal"]["id"],
                build_separation(separation_reason="Resigned; last day 2026-08-01."),
                ctx["headers"]["hr_partner"],
            )
        )
        return ctx

    def test_convene_on_a_monitoring_case_reports_the_invalid_state(
        self, api: ApiClient
    ) -> None:
        """With the legal seat recused and quorum broken, re-convening still reports the case state.

        PRD: "Convening from any state other than `OPEN` is refused with `ERR_CASE_INVALID_STATE`, and because the state check precedes the quorum check, convening an already-`ASSESSING` case with a broken roster reports the invalid state."
        Design: Difficulty/priority_pair_validation_conflict/case_state_check_outranks_quorum_constraint_on_convene
        """
        ctx = self._monitoring_case_with_a_recused_legal_seat(api)
        assert_case_state(read_case(api, ctx), status="MONITORING", quorum_met=False)

        response = api.convene_threat_case(
            ctx["case"]["id"],
            {"convene_note": "Re-convening after the legal seat vacated."},
            ctx["headers"]["threat_team_lead"],
        )

        validate_error(response, ApiErrorId.CASE_INVALID_STATE, 409)
        assert response.json()["data"]["error_id"] != ApiErrorId.QUORUM_NOT_MET

    def test_separation_recuses_the_seat_and_the_failed_convene_recomputes_nothing(
        self, api: ApiClient
    ) -> None:
        """The recusal clears the legal ballot and breaks quorum; the rejected convene changes no score.

        PRD: "Fifth, every team seat held by the departing worker whose `status` is `ASSIGNED` becomes `RECUSED` with its ballot fields cleared, and each affected case's `quorum_met` and `ballot_count_current_round` are recomputed — a recusal can therefore break a quorum that was previously met."
        Design: Difficulty/priority_pair_validation_conflict/case_state_check_outranks_quorum_constraint_on_convene
        """
        ctx = self._monitoring_case_with_a_recused_legal_seat(api)
        legal_seat = _read_seat(api, ctx, "legal")
        assert legal_seat["status"] == "RECUSED"
        assert_seat_ballot_cleared(legal_seat)

        validate_error(
            api.convene_threat_case(
                ctx["case"]["id"],
                {"convene_note": "Re-convening after the legal seat vacated."},
                ctx["headers"]["threat_team_lead"],
            ),
            ApiErrorId.CASE_INVALID_STATE,
            409,
        )

        case = read_case(api, ctx)
        assert_case_state(case, status="MONITORING", assessment_round=1, quorum_met=False)
        assert_risk_scores(case, interim=42.00, consensus=60.94, risk_band="HIGH")
