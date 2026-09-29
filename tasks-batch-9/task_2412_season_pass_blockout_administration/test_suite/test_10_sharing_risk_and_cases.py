"""Sharing risk scoring, the investigation workflow, revocation and appeal."""

from test_helpers import (
    BRONZE,
    GOLD,
    ApiErrorId,
    BillingStatus,
    CaseDecision,
    CaseStatus,
    GateCode,
    InstallmentStatus,
    PassStatus,
    PassholderStatus,
    PaymentMode,
    PhotoMatch,
    PlanStatus,
    ProgramStatus,
    SYSTEM_OPENED_BY_USER_ID,
    appeal_case,
    appeal_payload,
    assert_installment_statuses,
    assert_ledger,
    assert_pass_dimensions,
    assert_revenue_summary,
    build_active_pass,
    build_plan,
    build_program,
    compliance_officer_headers,
    create_park_day,
    decide_case,
    get_pass,
    get_passholder,
    get_plan,
    make_passholder_headers,
    open_case,
    plan_installments,
    record_visit,
    review_case,
    revenue_summary,
    set_clock,
    settle_installment,
    validate_error,
    validate_paginated,
)


def _cases_of(api, season_pass_id):
    """Every sharing case filed against one pass, with the listing counters."""
    response = api.list_sharing_cases(
        headers=compliance_officer_headers(), params={"season_pass_id": season_pass_id}
    )
    return validate_paginated(response)


class TestSharingRiskVariantsDiverge:
    """The entered day's class selects the scoring model, and the models disagree."""

    def test_gate_cluster_variant_on_a_peak_day_scores_sixty_five_and_auto_opens_a_case(
        self, api
    ):
        """Two banks on one date plus one mismatch is 40 + 25 under the cluster model.

        PRD: "The score is 40 points for each distinct gate beyond the first — that is,
        40 multiplied by the distinct-gate figure less one, treated as zero if the
        subtraction would go negative — plus 25 points for each mismatch."

        Design: Difficulty/dual_variant_calc/sharing_risk_gate_cluster_vs_rolling_window_diverge
        """
        set_clock(api, "2026-08-20T23:00:00Z")
        program = build_program(api, tiers=(GOLD,), status=ProgramStatus.SEASON_ACTIVE.value)
        standard_day = create_park_day(api, program.id, "2026-08-18")
        peak_day = create_park_day(
            api, program.id, "2026-08-20", capacity_total=1000, forecast_attendance=850
        )
        holder_pass = build_active_pass(
            api,
            program,
            tier_name="GOLD",
            holder_overrides={"full_name": "Ada Cluster", "email": "cluster@example.com"},
        )
        record_visit(
            api, holder_pass.id, standard_day["id"], "2026-08-18T09:00:00Z", GateCode.NORTH.value
        )
        record_visit(
            api,
            holder_pass.id,
            standard_day["id"],
            "2026-08-18T11:00:00Z",
            GateCode.SOUTH.value,
            PhotoMatch.MISMATCH.value,
        )

        record_visit(
            api, holder_pass.id, peak_day["id"], "2026-08-20T10:00:00Z", GateCode.EAST.value
        )

        holder = get_passholder(api, holder_pass.holder_id)
        assert holder["sharing_risk_score"] == 65, (
            "the gate-cluster score is 40 for the second distinct gate plus 25 for the "
            f"single mismatch, got {holder['sharing_risk_score']!r}"
        )
        cases, meta = _cases_of(api, holder_pass.id)
        assert meta["total_count"] == 1, (
            f"a score of 65 should auto-open exactly one case, got {meta['total_count']!r}"
        )
        case = cases[0]
        assert case["case_status"] == CaseStatus.OPEN.value, (
            f"the auto-opened case should be OPEN, got {case['case_status']!r}"
        )
        assert case["opened_by_user_id"] == SYSTEM_OPENED_BY_USER_ID, (
            f"a system-opened case should record SYSTEM as the opener, got {case['opened_by_user_id']!r}"
        )
        assert case["opened_by_role"] == "SYSTEM", (
            f"a system-opened case should record an opened_by_role of SYSTEM, got {case['opened_by_role']!r}"
        )
        assert case["risk_score_at_open"] == 65, (
            f"risk_score_at_open should capture the score just computed, got {case['risk_score_at_open']!r}"
        )

    def test_rolling_window_variant_on_a_standard_day_scores_thirty_five_and_stays_silent(
        self, api
    ):
        """Three entries are exactly the free allowance, so only the mismatch scores.

        PRD: "the score is 15 points for each window entry beyond the third — 15
        multiplied by the window entry count less three, treated as zero if the
        subtraction would go negative — plus 35 points for each window mismatch."

        Design: Difficulty/dual_variant_calc/sharing_risk_gate_cluster_vs_rolling_window_diverge
        """
        set_clock(api, "2026-08-20T23:00:00Z")
        program = build_program(api, tiers=(GOLD,), status=ProgramStatus.SEASON_ACTIVE.value)
        first_day = create_park_day(api, program.id, "2026-08-18")
        second_day = create_park_day(api, program.id, "2026-08-19")
        holder_pass = build_active_pass(
            api,
            program,
            tier_name="GOLD",
            holder_overrides={"full_name": "Bee Window", "email": "window@example.com"},
        )
        record_visit(
            api, holder_pass.id, first_day["id"], "2026-08-18T09:00:00Z", GateCode.NORTH.value
        )
        record_visit(
            api,
            holder_pass.id,
            first_day["id"],
            "2026-08-18T11:00:00Z",
            GateCode.SOUTH.value,
            PhotoMatch.MISMATCH.value,
        )

        record_visit(
            api, holder_pass.id, second_day["id"], "2026-08-19T10:00:00Z", GateCode.EAST.value
        )

        holder = get_passholder(api, holder_pass.holder_id)
        assert holder["sharing_risk_score"] == 35, (
            "three entries in the trailing week score nothing for frequency, leaving 35 "
            f"for the single mismatch, got {holder['sharing_risk_score']!r}"
        )
        _, meta = _cases_of(api, holder_pass.id)
        assert meta["total_count"] == 0, (
            f"a score of 35 is below the auto-open threshold, got {meta['total_count']!r} cases"
        )

    def test_the_same_visit_history_scores_differently_on_the_two_day_classes(self, api):
        """The selector is the entered day's class, and the two models diverge by 30.

        PRD: "Identical visit history, two very different numbers — and under the
        default auto-open threshold of 65 the first fires an investigation while the
        second stays silent."

        Design: Difficulty/dual_variant_calc/sharing_risk_gate_cluster_vs_rolling_window_diverge
        """
        set_clock(api, "2026-08-20T23:00:00Z")
        program = build_program(api, tiers=(GOLD,), status=ProgramStatus.SEASON_ACTIVE.value)
        first_day = create_park_day(api, program.id, "2026-08-18")
        second_day = create_park_day(api, program.id, "2026-08-19")
        peak_day = create_park_day(
            api, program.id, "2026-08-20", capacity_total=1000, forecast_attendance=850
        )
        cluster_pass = build_active_pass(
            api,
            program,
            tier_name="GOLD",
            holder_overrides={"full_name": "Ada Cluster", "email": "cluster@example.com"},
        )
        window_pass = build_active_pass(
            api,
            program,
            tier_name="GOLD",
            holder_overrides={"full_name": "Bee Window", "email": "window@example.com"},
        )
        for pass_ctx in (cluster_pass, window_pass):
            record_visit(
                api, pass_ctx.id, first_day["id"], "2026-08-18T09:00:00Z", GateCode.NORTH.value
            )
            record_visit(
                api,
                pass_ctx.id,
                first_day["id"],
                "2026-08-18T11:00:00Z",
                GateCode.SOUTH.value,
                PhotoMatch.MISMATCH.value,
            )
        record_visit(
            api, window_pass.id, second_day["id"], "2026-08-19T10:00:00Z", GateCode.EAST.value
        )
        record_visit(
            api, cluster_pass.id, peak_day["id"], "2026-08-20T10:00:00Z", GateCode.EAST.value
        )

        cluster_holder = get_passholder(api, cluster_pass.holder_id)
        window_holder = get_passholder(api, window_pass.holder_id)

        assert cluster_holder["sharing_risk_score"] == 65, (
            f"the crowded-day entry should score 65, got {cluster_holder['sharing_risk_score']!r}"
        )
        assert window_holder["sharing_risk_score"] == 35, (
            f"the ordinary-day entry should score 35, got {window_holder['sharing_risk_score']!r}"
        )
        _, cluster_meta = _cases_of(api, cluster_pass.id)
        _, window_meta = _cases_of(api, window_pass.id)
        assert (cluster_meta["total_count"], window_meta["total_count"]) == (1, 0), (
            "only the gate-cluster score should have fired an investigation, got "
            f"{cluster_meta['total_count']} and {window_meta['total_count']} cases"
        )


class TestAppealCycleReturnsToUnderReview:
    """A substantiated case may be appealed once and re-reviewed at round two."""

    def _substantiated_case(self, api):
        set_clock(api, "2026-08-05T08:00:00Z")
        program = build_program(api, tiers=(GOLD,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-08-05")
        pass_ctx = build_active_pass(
            api, program, tier_name="GOLD", payment_mode=PaymentMode.PAY_IN_FULL.value
        )
        visit = record_visit(
            api,
            pass_ctx.id,
            day["id"],
            "2026-08-05T09:00:00Z",
            GateCode.NORTH.value,
            PhotoMatch.MISMATCH.value,
        )
        case = open_case(api, pass_ctx.id, [visit["id"]], agent_user_id="agent-77")
        review_case(api, case["id"], officer_user_id="officer-9")
        decided = decide_case(
            api, case["id"], CaseDecision.SUBSTANTIATED.value, officer_user_id="officer-9"
        )
        return program, pass_ctx, decided

    def test_appeal_then_review_walks_the_case_back_to_under_review_at_round_two(self, api):
        """The cycle SUBSTANTIATED to APPEAL_PENDING to UNDER_REVIEW runs once.

        PRD: "The same action serves a case returning from appeal, driving
        `APPEAL_PENDING → UNDER_REVIEW` and raising `review_round` from 1 to 2."

        Design: Difficulty/non_linear_state_machine/sharing_case_appeal_cycle_returns_to_under_review
        """
        _, pass_ctx, case = self._substantiated_case(api)

        appealed = appeal_case(api, case["id"], pass_ctx.holder_id)
        assert appealed["case_status"] == CaseStatus.APPEAL_PENDING.value, (
            f"the appeal should drive the case to APPEAL_PENDING, got {appealed['case_status']!r}"
        )
        assert appealed["review_round"] == 1, (
            f"the appeal itself does not advance review_round, got {appealed['review_round']!r}"
        )
        assert get_pass(api, pass_ctx.id)["pass_status"] == PassStatus.REVOKED.value, (
            "the pass should stay REVOKED throughout the appeal"
        )

        second_review = review_case(api, case["id"], officer_user_id="officer-9")
        assert second_review["case_status"] == CaseStatus.UNDER_REVIEW.value, (
            f"the case should return to UNDER_REVIEW, got {second_review['case_status']!r}"
        )
        assert second_review["review_round"] == 2, (
            f"the second review should raise review_round to 2, got {second_review['review_round']!r}"
        )

    def test_dismissal_at_round_two_compensates_the_whole_revocation_cascade(self, api):
        """A round-two dismissal walks the revocation backwards in three levels.

        PRD: "When `review_round` is 2 or more, the case had been substantiated and
        then appealed, so the dismissal is a full compensation of the revocation
        cascade, walked backwards in three levels."

        Design: Difficulty/non_linear_state_machine/sharing_case_appeal_cycle_returns_to_under_review
        """
        program, pass_ctx, case = self._substantiated_case(api)
        appeal_case(api, case["id"], pass_ctx.holder_id)
        review_case(api, case["id"], officer_user_id="officer-9")

        dismissed = decide_case(
            api, case["id"], CaseDecision.DISMISSED.value, officer_user_id="officer-9"
        )

        assert dismissed["case_status"] == CaseStatus.DISMISSED.value, (
            f"the case should end DISMISSED, got {dismissed['case_status']!r}"
        )
        assert dismissed["review_round"] == 2, (
            f"the dismissal happens at review_round 2, got {dismissed['review_round']!r}"
        )
        assert dismissed["revocation_forfeit_cents"] == 30000, (
            "the case keeps the snapshot it took at substantiation, got "
            f"{dismissed['revocation_forfeit_cents']!r}"
        )
        pass_row = get_pass(api, pass_ctx.id)
        assert_pass_dimensions(
            pass_row,
            pass_status=PassStatus.ACTIVE.value,
            billing_status=BillingStatus.PAID_IN_FULL.value,
        )
        assert_ledger(pass_row, paid=30000, credited=0, outstanding=0)
        assert_revenue_summary(
            revenue_summary(api, program.id),
            base=30000,
            recognized=30000,
            deferred=0,
            forfeited=0,
            active_passes=1,
        )
        assert get_passholder(api, pass_ctx.holder_id)["status"] == PassholderStatus.ACTIVE.value, (
            "a single substantiated case does not ban the holder"
        )

    def test_a_dismissed_case_cannot_be_appealed_again(self, api):
        """Appeal requires the case to sit in SUBSTANTIATED.

        PRD: "a case whose `review_round` has already reached 2 is refused with
        `ERR_APPEAL_LIMIT_REACHED` (HTTP 409), and that check follows the
        `ERR_INVALID_CASE_STATE` check that requires the case to be in `SUBSTANTIATED`."

        Design: Difficulty/non_linear_state_machine/sharing_case_appeal_cycle_returns_to_under_review
        """
        _, pass_ctx, case = self._substantiated_case(api)
        appeal_case(api, case["id"], pass_ctx.holder_id)
        review_case(api, case["id"], officer_user_id="officer-9")
        decide_case(api, case["id"], CaseDecision.DISMISSED.value, officer_user_id="officer-9")

        response = api.appeal_sharing_case(
            case["id"],
            appeal_payload("Please look again"),
            headers=make_passholder_headers(pass_ctx.holder_id),
        )

        validate_error(response, ApiErrorId.ERR_INVALID_CASE_STATE.value, 409)


class TestSubstantiationCascade:
    """Substantiation revokes the pass, terminates its plan and forfeits the money."""

    def _pass_with_one_settled_installment(self, api):
        set_clock(api, "2026-08-05T08:00:00Z")
        program = build_program(api, tiers=(BRONZE,), status=ProgramStatus.SEASON_ACTIVE.value)
        day = create_park_day(api, program.id, "2026-08-05")
        pass_ctx = build_active_pass(
            api, program, tier_name="BRONZE", payment_mode=PaymentMode.PAYMENT_PLAN.value
        )
        plan_ctx = build_plan(api, pass_ctx.id, 3000, 4, "2026-09-01")
        settle_installment(api, plan_ctx.installment(1)["id"], 2625)
        visit = record_visit(
            api,
            pass_ctx.id,
            day["id"],
            "2026-08-05T09:00:00Z",
            GateCode.NORTH.value,
            PhotoMatch.MISMATCH.value,
        )
        case = open_case(api, pass_ctx.id, [visit["id"]], agent_user_id="agent-77")
        review_case(api, case["id"], officer_user_id="officer-9")
        return program, pass_ctx, plan_ctx, case

    def test_revocation_terminates_the_plan_and_voids_its_scheduled_installments(self, api):
        """Levels one and two of the cascade, with the billing dimension untouched.

        PRD: "At level two, because the pass was revoked, its payment plan whose
        `plan_status` is `ACTIVE` moves `ACTIVE → TERMINATED_ON_REVOCATION`, and every
        installment of that plan whose `status` is `SCHEDULED` becomes `VOIDED`"

        Design: Difficulty/transitive_cascade/substantiated_sharing_case_revokes_pass_terminates_plan_forfeits_revenue
        """
        _, pass_ctx, plan_ctx, case = self._pass_with_one_settled_installment(api)

        decided = decide_case(
            api, case["id"], CaseDecision.SUBSTANTIATED.value, officer_user_id="officer-9"
        )

        assert decided["revocation_forfeit_cents"] == 5625, (
            "the forfeit snapshot is the pass's paid-to-date figure at that instant, got "
            f"{decided['revocation_forfeit_cents']!r}"
        )
        pass_row = get_pass(api, pass_ctx.id)
        assert_pass_dimensions(
            pass_row,
            pass_status=PassStatus.REVOKED.value,
            billing_status=BillingStatus.PLAN_CURRENT.value,
        )
        plan = get_plan(api, plan_ctx.id)
        assert plan["plan_status"] == PlanStatus.TERMINATED_ON_REVOCATION.value, (
            f"the plan should be TERMINATED_ON_REVOCATION, got {plan['plan_status']!r}"
        )
        assert_installment_statuses(
            plan_installments(api, plan_ctx.id),
            [
                InstallmentStatus.SETTLED.value,
                InstallmentStatus.VOIDED.value,
                InstallmentStatus.VOIDED.value,
                InstallmentStatus.VOIDED.value,
            ],
        )

    def test_revocation_moves_the_money_from_recognised_revenue_to_forfeited(self, api):
        """Level three reclassifies the pass out of the revenue set.

        PRD: "A revoked pass leaves the base, recognised and deferred figures entirely
        and reappears inside `forfeited_revenue_cents`; a dismissed appeal moves it
        back the other way."

        Design: Difficulty/transitive_cascade/substantiated_sharing_case_revokes_pass_terminates_plan_forfeits_revenue
        """
        program, _, _, case = self._pass_with_one_settled_installment(api)

        decide_case(api, case["id"], CaseDecision.SUBSTANTIATED.value, officer_user_id="officer-9")

        assert_revenue_summary(
            revenue_summary(api, program.id),
            base=0,
            recognized=0,
            deferred=0,
            forfeited=5625,
            active_passes=0,
            visits=0,
            visits_per_active_pass=0.00,
            spend_per_visit=0,
        )
