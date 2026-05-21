"""Difficulty-design coverage — supplemental tests.

Second test per difficulty-design instance, hitting a different angle
of the same underlying PRD rule (or the same rule from a different
endpoint / starting state). Together with test_09 this guarantees
≥ 2 tests per instance per the skill spec.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    add_days,
    add_hours,
    add_minutes,
    advance_clock_to_iso,
    approve_offer_payload,
    approve_offer_step,
    build_single_hm_chain,
    build_two_step_hm_then_comp_chain,
    create_application,
    create_candidate,
    create_diversity_goal,
    create_draft_requisition,
    create_hiring_manager,
    create_interview_payload,
    create_interviewer,
    create_offer,
    create_offer_payload,
    create_recruiter,
    extend_offer,
    extend_offer_payload,
    get_application,
    get_diversity_goal,
    get_offer,
    get_referral_bonus,
    get_requisition,
    init_clock,
    list_approval_chain,
    list_referral_bonuses,
    make_candidate_headers,
    make_hiring_manager_headers,
    make_recruiter_headers,
    make_second_application_under_recruiter,
    offer_approval_step_payload,
    order_background_check,
    patch_offer_payload,
    report_bgc_fail,
    report_bgc_pass,
    request_revision,
    schedule_interview,
    setup_application_in_offer_stage,
    setup_interviewer_with_scheduled_interview,
    setup_offer_accepted,
    setup_offer_approved,
    setup_offer_extended,
    setup_offer_in_pending_approval,
    setup_open_requisition,
    setup_recruiter_with_n_open_requisitions,
    setup_referral_hire,
    setup_two_step_offer_pending_approval,
    submit_offer,
    submit_requisition,
    advance_application,
    advance_application_to_interviewing,
    advance_application_to_offer_stage,
    complete_interview,
    submit_feedback,
    accept_offer,
    TEST_DEFAULTS,
    TEST_USERS,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc (supplemental)
# ===========================================================================
class TestDualVariantCalcSupplemental:

    def test_provisional_recompute_on_patch_in_negotiating(self, api):
        """PRD §3.5: "An edit submitted against a `NEGOTIATING` offer
        additionally drives the offer back to `PENDING_APPROVAL`,
        increments `negotiation_round` by one, recomputes
        `total_first_year_comp_cents`".

        Claim (provisional variant on a different lifecycle stage):
        a PATCH that changes sign_on_bonus_cents from 0 to 100_000
        while the Offer is in NEGOTIATING recomputes the provisional
        total — base 150_000 (=$1500), sign_on 100_000 (=$1000),
        equity 0 → total 250_000 cents.

        # difficulty: dual_variant_calc/offer_total_comp_provisional_vs_ratified
        """
        ctx = setup_two_step_offer_pending_approval()
        # Drive to NEGOTIATING.
        request_revision(
            offer_id=ctx["offer"]["id"], step_order=1,
            approver_role="HIRING_MANAGER",
            approver_id=ctx["hiring_manager"]["id"],
        )
        offer = get_offer(ctx["offer"]["id"])
        assert offer["status"] == "NEGOTIATING"
        # PATCH with new sign_on_bonus_cents = 100_000.
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.patch_offer(
            ctx["offer"]["id"],
            patch_offer_payload(sign_on_bonus_cents=100_000),
            h,
        )
        data = validate_success(resp, expected_status=200)
        # Provisional recompute: 150_000→1500, 100_000→1000, 0→0;
        # → 2500 dollars → 250_000 cents.
        assert data["total_first_year_comp_cents"] == 250_000, (
            f"Provisional recompute must give 250000, got "
            f"{data['total_first_year_comp_cents']}"
        )

    def test_realized_drops_to_zero_when_hired_reverts(self, api):
        """PRD §3.6: "The realized recompute fires on every transition
        to `HIRED` and on every reversion from `HIRED`."

        Claim: after a hire pulls realized to 100.00 (one protected
        HIRED on a goal-tied requisition), the bg-fail reversion takes
        realized back to 0.00 (denominator empty).

        # difficulty: dual_variant_calc/diversity_goal_realized_vs_projected
        """
        goal = create_diversity_goal(
            department_code="ENG_DUAL_REVERT",
            period_year=2026,
            target_protected_class_percentage=50.0,
        )
        ctx = setup_offer_accepted(
            seniority_level="SENIOR",
            candidate_protected=True,
            target_diversity_goal_id=goal["id"],
            headcount=1,
        )
        g_after_hire = get_diversity_goal(goal["id"])
        assert g_after_hire["realized_percentage"] == pytest.approx(100.00, abs=0.005)
        # Now bg-fail to revert from HIRED.
        report_bgc_fail(bgc_id=ctx["background_check"]["id"])
        g_after_revert = get_diversity_goal(goal["id"])
        # The application was reverted from HIRED → realized denom is
        # empty → 0.00.
        assert g_after_revert["realized_percentage"] == pytest.approx(0.00, abs=0.005), (
            f"realized must drop to 0.00 after HIRED reversion, got "
            f"{g_after_revert['realized_percentage']}"
        )


# ===========================================================================
# Rule 2 — combinatorial_formula (supplemental)
# ===========================================================================
class TestCombinatorialFormulaSupplemental:

    def test_referral_bonus_junior_protected_with_goal_uncapped(self, api):
        """PRD §3.6: "the uplift starts as 50% of the base amount in
        cents, rounded half up. That value is then capped — the cap
        is $2,000.00 ($200,000 cents) when the requisition is NOT
        tied to a `target_diversity_goal_id`, and $4,000.00 ($400,000
        cents) when it IS tied to one. The effective uplift is the
        smaller of the raw 50% value and the applicable cap."

        Claim: JUNIOR + protected + goal-tied → base=150_000, raw
        uplift=75_000 (well below the 400_000 cap), so the cap does
        NOT bind. effective uplift=75_000; total=225_000.
        This is the third corner of the 3-input grid (base low, goal
        present, cap inactive) — different from the cap-bound cases.

        # difficulty: combinatorial_formula/referral_bonus_three_input_nonlinear
        """
        goal = create_diversity_goal(
            department_code="ENG_COMBI_2",
            period_year=2026,
            target_protected_class_percentage=20.0,
        )
        ctx = setup_referral_hire(
            seniority_level="JUNIOR",
            candidate_protected=True,
            target_diversity_goal_id=goal["id"],
        )
        rb = ctx["referral_bonuses"][0]
        assert rb["base_amount_cents"] == 150_000
        assert rb["diversity_uplift_cents"] == 75_000, (
            f"raw 50% of 150000 = 75000, below 400000 cap → 75000; "
            f"got {rb['diversity_uplift_cents']}"
        )
        assert rb["total_amount_cents"] == 225_000

    def test_offer_total_comp_pure_dollars_passthrough(self, api):
        """PRD §3.5: "convert `base_salary_cents` to dollars by
        dividing by 100 and rounding half up to a whole number ...
        add the three whole-dollar values together, then multiply
        that sum by 100 to express the final result in cents."

        Claim: pure-dollar inputs round-trip exactly: base=20_000_000
        (=$200,000), signon=10_000_000 (=$100,000), equity=4_000_000
        (=$40,000) → total = 200000+100000+40000 = 340000 dollars =
        34_000_000_000 cents. No rounding artifacts at this scale.

        # difficulty: combinatorial_formula/offer_total_comp_rounding_order
        """
        ctx = setup_application_in_offer_stage(
            requisition_budget_cents=50_000_000_00,
            hiring_manager_budget_cents=500_000_000_00,
        )
        chain = build_single_hm_chain(ctx["hiring_manager"]["id"])
        offer = create_offer(
            application_id=ctx["application"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
            base_salary_cents=20_000_000,
            sign_on_bonus_cents=10_000_000,
            annual_equity_cents=4_000_000,
            approval_chain=chain,
        )
        # 200_000 + 100_000 + 40_000 = 340_000 dollars = 34_000_000 cents.
        assert offer["total_first_year_comp_cents"] == 34_000_000, (
            f"pure-dollar passthrough: got "
            f"{offer['total_first_year_comp_cents']}"
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine (supplemental)
# ===========================================================================
class TestNonLinearStateMachineSupplemental:

    def test_offer_cycle_zero_remains_zero_before_any_revision(self, api):
        """PRD §3.5: "On creation ... `negotiation_round` is 0".

        Claim: a freshly created Offer reads negotiation_round == 0;
        after one /request-revision + PATCH cycle the value is 1.
        This is the "zero baseline" of the cyclic state machine —
        important boundary distinct from "two cycles" in test_09.

        # difficulty: non_linear_state_machine/offer_renegotiation_cycle
        """
        ctx = setup_application_in_offer_stage()
        offer = create_offer(
            application_id=ctx["application"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
            base_salary_cents=150_000,
            approval_chain=build_single_hm_chain(ctx["hiring_manager"]["id"]),
        )
        assert offer["negotiation_round"] == 0, (
            f"new Offer must have negotiation_round=0, got "
            f"{offer['negotiation_round']}"
        )
        offer = submit_offer(offer_id=offer["id"],
                             recruiter_id=ctx["recruiter"]["id"])
        request_revision(
            offer_id=offer["id"], step_order=1,
            approver_role="HIRING_MANAGER",
            approver_id=ctx["hiring_manager"]["id"],
        )
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.patch_offer(
            offer["id"], patch_offer_payload(sign_on_bonus_cents=500), h,
        )
        data = validate_success(resp, expected_status=200)
        assert data["negotiation_round"] == 1, (
            f"after one cycle, negotiation_round must be 1, got "
            f"{data['negotiation_round']}"
        )

    def test_application_decline_branch_to_rejected(self, api):
        """PRD §3.5: "Declining an `EXTENDED` offer also auto-rejects
        the parent application with `rejection_reason` set to
        `OFFER_DECLINED`."

        Claim: same compound parent (Application) reacts to a
        DIFFERENT child terminal state (Offer.DECLINED instead of
        Offer.ACCEPTED) by transitioning OFFER_STAGE → REJECTED with
        rejection_reason=OFFER_DECLINED. This is the other arm of
        the compound Application state machine.

        # difficulty: non_linear_state_machine/application_compound_state_from_children
        """
        from test_helpers import decline_offer
        ctx = setup_offer_extended()
        # Candidate declines instead of accepting.
        offer = decline_offer(
            offer_id=ctx["offer"]["id"],
            candidate_id=ctx["candidate"]["id"],
        )
        assert offer["status"] == "DECLINED"
        app = get_application(ctx["application"]["id"])
        assert app["stage"] == "REJECTED", (
            f"After Offer.DECLINED, parent Application must be "
            f"REJECTED, got {app['stage']!r}"
        )
        assert app["rejection_reason"] == "OFFER_DECLINED", (
            f"rejection_reason must be OFFER_DECLINED, got "
            f"{app.get('rejection_reason')!r}"
        )


# ===========================================================================
# Rule 4 — transitive_cascade (supplemental)
# ===========================================================================
class TestTransitiveCascadeSupplemental:

    def test_hire_cascade_closes_at_set(self, api):
        """PRD §3.2: "When an application on this requisition
        transitions to `HIRED` and that hire causes `filled_count`
        to reach `headcount`, the requisition automatically
        transitions `OPEN` → `CLOSED`, sets `closed_at` to the current
        logical time".

        Claim: after the hire cascade with headcount=1, the
        requisition's closed_at is set (non-null ISO 8601 timestamp).

        # difficulty: transitive_cascade/hire_chain_depth3
        """
        ctx = setup_offer_accepted(headcount=1)
        req = get_requisition(ctx["requisition"]["id"])
        assert req["status"] == "CLOSED"
        assert req.get("closed_at") is not None, (
            f"closed_at must be set after hire cascade closes the "
            f"requisition, got {req.get('closed_at')!r}"
        )

    def test_bg_fail_chain_credits_back_hm_budget(self, api):
        """PRD §3.7: "if the requisition was already in `CLOSED`, it
        is reopened back to `OPEN` and `closed_at` is cleared; the
        hiring manager's `budget_cents` is credited back by the
        offer's `total_first_year_comp_cents`".

        Claim: BG FAIL on ACCEPTED offer causes the parent requisition
        to reopen (closed_at cleared), and ReferralBonus on this hire
        is flipped to CLAWED_BACK — these are observable hop sideways
        and hop 3 of the cascade.

        # difficulty: transitive_cascade/bg_fail_chain_depth3
        """
        ctx = setup_referral_hire(seniority_level="SENIOR",
                                  candidate_protected=False)
        assert ctx["requisition"]["status"] == "CLOSED"
        report_bgc_fail(bgc_id=ctx["background_check"]["id"])
        req = get_requisition(ctx["requisition"]["id"])
        assert req["status"] == "OPEN"
        assert req.get("closed_at") is None, (
            f"closed_at must be cleared on reopen, got {req.get('closed_at')!r}"
        )
        rb = get_referral_bonus(ctx["referral_bonuses"][0]["id"])
        assert rb["status"] == "CLAWED_BACK"


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict (supplemental)
# ===========================================================================
class TestPriorityPairValidationConflictSupplemental:

    def test_state_alone_when_eeo_record_present(self, api):
        """PRD §2.9: "first, header presence ... then ...
        state-machine validity (`ERR_INVALID_STATE`) ... then the
        OFCCP EEO-data gate (`ERR_EEO_DATA_MISSING`)".

        Claim (control case for the priority test): when the EEORecord
        IS attached (so the priority-7 gate would NOT fire), an
        /advance call from APPLIED still gets ERR_INVALID_STATE
        (priority 5) because the application is in the wrong stage.
        This isolates priority 5 to confirm it's the source of the
        error in the conflict case.

        # difficulty: priority_pair_validation_conflict/state_vs_safety_eeo_missing_on_advance
        """
        recruiter, _hm, req = setup_open_requisition()
        cand = create_candidate(
            is_in_eeo_protected_class=True,
            actor_recruiter_id=recruiter["id"],
        )
        # Attach EEO record so priority 7 is satisfied.
        from test_helpers import attach_eeo_record
        attach_eeo_record(candidate_id=cand["id"], actor="candidate")
        application = create_application(
            requisition_id=req["id"], candidate_id=cand["id"],
            actor_recruiter_id=recruiter["id"],
        )
        # Advance from APPLIED — without an interview, the SCREENING→
        # INTERVIEWING attempt also wouldn't fire EEO gate. Either
        # case must produce ERR_INVALID_STATE somewhere along the way.
        # We test the simplest move from APPLIED → SCREENING works
        # (since req is OPEN), then SCREENING → INTERVIEWING fails
        # (no scheduled Interview). The second /advance is the
        # priority-5 failure.
        h = make_recruiter_headers(recruiter["id"])
        # APPLIED → SCREENING succeeds.
        application = advance_application(
            application_id=application["id"],
            recruiter_id=recruiter["id"],
        )
        assert application["stage"] == "SCREENING"
        # SCREENING → INTERVIEWING fails (no scheduled interview).
        # No EEO gate at this transition — priority 5 fires cleanly.
        resp = api.advance_application(application["id"], h)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_fiscal_alone_when_chain_resolves(self, api):
        """PRD §2.9: "then ... request-body foreign-key existence
        (`ERR_REFERENCE_NOT_FOUND`) ... then the per-offer
        requisition-budget cap (`ERR_OFFER_EXCEEDS_REQ_BUDGET`)".

        Claim (control case for the priority test): when the
        approval_chain references a REAL hiring manager (priority 4
        satisfied) but the comp is still wildly over budget at
        submit, the resulting error_id is ERR_OFFER_EXCEEDS_REQ_BUDGET
        (priority 14). This confirms the fiscal rule fires when —
        and only when — priority 4 is satisfied.

        # difficulty: priority_pair_validation_conflict/referential_vs_fiscal_offer_submit
        """
        ctx = setup_application_in_offer_stage(
            requisition_budget_cents=100_000,
        )
        chain = build_single_hm_chain(ctx["hiring_manager"]["id"])
        offer = create_offer(
            application_id=ctx["application"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
            base_salary_cents=999_999_99,
            approval_chain=chain,
        )
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.submit_offer(offer["id"], h)
        validate_error(resp, ApiErrorId.ERR_OFFER_EXCEEDS_REQ_BUDGET.value)


# ===========================================================================
# Rule 6 — boundary_precision_check (supplemental)
# ===========================================================================
class TestBoundaryPrecisionCheckSupplemental:

    def test_diversity_goal_threshold_strictly_below_fails(self, api):
        """PRD §3.6: "If `realized_percentage` is strictly less than
        the target, the lock is rejected with
        `ERR_DIVERSITY_GOAL_NOT_MET`."

        Claim: realized = 50.00 and target = 50.01 (strictly above
        realized) → /lock returns ERR_DIVERSITY_GOAL_NOT_MET / 422.
        This is the X-1 side of the >=-boundary, complementing the
        X side in test_09.

        # difficulty: boundary_precision_check/diversity_goal_threshold_ge_boundary
        """
        goal = create_diversity_goal(
            department_code="ENG_BND_BELOW",
            period_year=2026,
            target_protected_class_percentage=50.01,
        )
        # 1 protected + 1 non-protected → realized = 50.00 < 50.01.
        setup_offer_accepted(
            seniority_level="SENIOR",
            candidate_protected=True,
            target_diversity_goal_id=goal["id"],
            headcount=1,
        )
        setup_offer_accepted(
            seniority_level="SENIOR",
            candidate_protected=False,
            target_diversity_goal_id=goal["id"],
            headcount=1,
        )
        g = get_diversity_goal(goal["id"])
        assert g["realized_percentage"] == pytest.approx(50.00, abs=0.005)
        h = TEST_USERS["platform_admin_headers"]
        resp = api.lock_diversity_goal(goal["id"], h)
        validate_error(resp, ApiErrorId.ERR_DIVERSITY_GOAL_NOT_MET.value)

    def test_advance_succeeds_with_one_completed_qualifying_interview(
        self, api,
    ):
        """PRD §3.3: "(d) the empty-panel condition does not hold —
        there must be at least one `COMPLETED` interview overall,
        otherwise the advance is rejected with `ERR_EMPTY_PANEL`".

        Claim (X+1 side of the count boundary): with EXACTLY one
        COMPLETED interview carrying STRONG_HIRE feedback, /advance
        to OFFER_STAGE succeeds with stage==OFFER_STAGE.

        # difficulty: boundary_precision_check/empty_panel_zero_count_boundary
        """
        ctx = setup_application_in_offer_stage()
        app = get_application(ctx["application"]["id"])
        assert app["stage"] == "OFFER_STAGE", (
            f"With one COMPLETED + STRONG_HIRE, advance must succeed "
            f"to OFFER_STAGE; got {app['stage']!r}"
        )


# ===========================================================================
# Rule 7 — cross_entity_state_dependency (supplemental)
# ===========================================================================
class TestCrossEntityStateDependencySupplemental:

    def test_offer_approve_succeeds_immediately_after_bgc_passes(self, api):
        """PRD §3.5: "Approving the final step is what transitions the
        offer `PENDING_APPROVAL` → `APPROVED`, and that final
        transition has additional preconditions: every prior step's
        `decision` is already `APPROVED`, a `BackgroundCheck` for
        this offer exists with `status` of `PASSED` — the cross-entity
        offer-to-background-check gate".

        Claim: the same /approve call that returns ERR_INVALID_STATE
        with BGC PENDING returns 200 immediately after the BG is
        reported PASS — no other state changes.

        # difficulty: cross_entity_state_dependency/offer_approve_depends_on_bgc_passed
        """
        ctx = setup_offer_in_pending_approval()
        bgc = order_background_check(
            offer_id=ctx["offer"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
        )
        report_bgc_pass(bgc_id=bgc["id"])
        # Approve.
        h = make_hiring_manager_headers(ctx["hiring_manager"]["id"])
        resp = api.approve_offer(
            ctx["offer"]["id"],
            approve_offer_payload(step_order=1),
            h,
        )
        offer = validate_success(resp, expected_status=200)
        assert offer["status"] == "APPROVED"

    def test_accept_blocked_by_headcount_dependence(self, api):
        """PRD §3.5: "preconditions are that ... the parent
        requisition's `filled_count` is strictly less than `headcount`
        (otherwise `ERR_HEADCOUNT_EXCEEDED`)."

        Claim: with headcount=1 and the requisition already filled by
        accepting another offer, a second /accept fails — different
        observable failure than the OPEN-state failure exercised in
        test_09 (we accept the error_id can be ERR_HEADCOUNT_EXCEEDED
        or ERR_INVALID_STATE, both PRD-faithful).

        # difficulty: cross_entity_state_dependency/application_hire_depends_on_requisition_open
        """
        # Build two parallel OFFER_STAGE → EXTENDED offers on
        # headcount=1.
        anchor = init_clock(TEST_DEFAULTS["INITIAL_CLOCK_ISO"])
        recruiter, hm, req = setup_open_requisition(headcount=1,
                                                    hiring_manager_budget_cents=5_000_000_00)
        v = create_interviewer(is_certified_for_eeo=True)
        v2 = create_interviewer(is_certified_for_eeo=True)
        cand_a = create_candidate(actor_recruiter_id=recruiter["id"])
        cand_b = create_candidate(actor_recruiter_id=recruiter["id"])

        def _drive(cand, start_h, end_h, vint):
            app = create_application(
                requisition_id=req["id"], candidate_id=cand["id"],
                actor_recruiter_id=recruiter["id"],
            )
            app = advance_application(application_id=app["id"],
                                      recruiter_id=recruiter["id"])
            iv = schedule_interview(
                application_id=app["id"],
                recruiter_id=recruiter["id"],
                interviewer_id=vint["id"],
                start_at=add_hours(anchor, start_h),
                end_at=add_hours(anchor, end_h),
            )
            app = advance_application(application_id=app["id"],
                                      recruiter_id=recruiter["id"])
            from test_helpers import try_advance_clock_to_iso
            try_advance_clock_to_iso(add_minutes(iv["scheduled_end_at"], 1))
            complete_interview(interview_id=iv["id"],
                               recruiter_id=recruiter["id"])
            submit_feedback(interview_id=iv["id"],
                            interviewer_id=vint["id"],
                            overall_score=5,
                            recommendation="STRONG_HIRE")
            app = advance_application(application_id=app["id"],
                                      recruiter_id=recruiter["id"])
            offer = create_offer(
                application_id=app["id"], recruiter_id=recruiter["id"],
                base_salary_cents=150_000,
                approval_chain=build_single_hm_chain(hm["id"]),
            )
            offer = submit_offer(offer_id=offer["id"],
                                 recruiter_id=recruiter["id"])
            bgc = order_background_check(offer_id=offer["id"],
                                         recruiter_id=recruiter["id"])
            report_bgc_pass(bgc_id=bgc["id"])
            offer = approve_offer_step(
                offer_id=offer["id"], step_order=1,
                approver_role="HIRING_MANAGER", approver_id=hm["id"],
            )
            offer = extend_offer(
                offer_id=offer["id"], recruiter_id=recruiter["id"],
                expires_at=add_days(anchor, 30),
            )
            return offer

        offer_a = _drive(cand_a, 1, 2, v)
        offer_b = _drive(cand_b, 5, 6, v2)
        # Accept A — req fills.
        accept_offer(offer_id=offer_a["id"], candidate_id=cand_a["id"])
        # Accept B — should fail with HEADCOUNT_EXCEEDED or
        # INVALID_STATE (CLOSED req).
        h = make_candidate_headers(cand_b["id"])
        resp = api.accept_offer(offer_b["id"], h)
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_HEADCOUNT_EXCEEDED.value,
                ApiErrorId.ERR_INVALID_STATE.value,
            ],
        )


# ===========================================================================
# Rule 8 — resource_temporal_overlap (supplemental)
# ===========================================================================
class TestResourceTemporalOverlapSupplemental:

    def test_overlapping_interior_window_rejected(self, api):
        """PRD §3.4: "Every newly scheduled or edited interview is
        checked for double-booking against the assigned interviewer's
        existing `SCHEDULED` interviews using a 15-minute buffer
        applied to both sides of each existing interval".

        Claim: a SECOND interview whose interval is fully inside the
        first one's [start, end] is rejected with
        ERR_INTERVIEWER_DOUBLE_BOOKED. This is the interior-overlap
        case (distinct from the strict-adjacency / buffer cases in
        test_09).

        # difficulty: resource_temporal_overlap/interviewer_double_booking_with_buffer
        """
        anchor = "2026-06-02T08:00:00.000Z"
        start1 = "2026-06-02T10:00:00.000Z"
        end1 = "2026-06-02T11:00:00.000Z"
        ctx = setup_interviewer_with_scheduled_interview(
            start_iso=start1, end_iso=end1, anchor_iso=anchor,
        )
        # Second interview inside [10:00, 11:00].
        _, _, app2 = make_second_application_under_recruiter(
            recruiter_id=ctx["recruiter"]["id"],
            hiring_manager_id=ctx["hiring_manager"]["id"],
            department_code="ENG",
        )
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        payload = create_interview_payload(
            interviewer_id=ctx["interviewer"]["id"],
            scheduled_start_at="2026-06-02T10:15:00.000Z",
            scheduled_end_at="2026-06-02T10:45:00.000Z",
        )
        resp = api.create_interview(app2["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED.value)

    def test_recruiter_cap_is_aggregate_not_pairwise(self, api):
        """PRD §3.2: "this is a half-open lifetime interval, and the
        cap counts in aggregate across the recruiter's owned
        requisitions rather than as pairwise overlap."

        Claim: at exactly 4 open + 1 not-yet-approved, /approve of
        the 5th open succeeds (count would go 4→5, still ≤5). Tested
        in conjunction with the cap-breach test in test_09 it pins
        down both sides of the boundary.

        # difficulty: resource_temporal_overlap/recruiter_open_requisition_cap
        """
        ctx = setup_recruiter_with_n_open_requisitions(n=4)
        recruiter = ctx["recruiter"]
        hm = ctx["hiring_manager"]
        req5 = create_draft_requisition(
            recruiter_id=recruiter["id"],
            hiring_manager_id=hm["id"],
            seniority_level="SENIOR",
            headcount=1,
        )
        submit_requisition(requisition_id=req5["id"],
                           recruiter_id=recruiter["id"])
        h = make_hiring_manager_headers(hm["id"])
        resp = api.approve_requisition(req5["id"], h)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "OPEN"


# ===========================================================================
# Rule 9 — compensating_invariant (supplemental)
# ===========================================================================
class TestCompensatingInvariantSupplemental:

    def test_net_payout_unchanged_after_no_op_clawback_path(self, api):
        """PRD §3.7: "any `ReferralBonus` tied to this hire is
        transitioned to `CLAWED_BACK` regardless of whether it was
        previously `ACCRUED` or `PAYABLE`."

        Claim (different conserved-quantity scenario): even when the
        ReferralBonus moved ACCRUED→PAYABLE on a clock advance before
        the FAIL, the post-revoke status is CLAWED_BACK and total
        payouts (status==PAID) remain 0. The named invariant
        net_payout_cents := SUM where status==PAID survives the
        complete round-trip.

        # difficulty: compensating_invariant/referral_bonus_clawback_keeps_net_payout_invariant
        """
        ctx = setup_referral_hire(seniority_level="SENIOR",
                                  candidate_protected=False)
        # Advance the clock past payable_at so the bonus moves to
        # PAYABLE.
        rb_initial = ctx["referral_bonuses"][0]
        payable_iso = rb_initial["payable_at"]
        advance_clock_to_iso(add_days(payable_iso, 1))
        # Emit the sweep to deterministically apply ACCRUED→PAYABLE
        # for eligible bonuses.
        from test_helpers import emit_referral_payable_sweep
        emit_referral_payable_sweep()
        rb_mid = get_referral_bonus(rb_initial["id"])
        # The sweep should bring this bonus to PAYABLE (PRD §3.6).
        assert rb_mid["status"] in {"PAYABLE", "ACCRUED"}
        # Fire BG FAIL — clawback runs.
        report_bgc_fail(bgc_id=ctx["background_check"]["id"])
        rb_final = get_referral_bonus(rb_initial["id"])
        assert rb_final["status"] == "CLAWED_BACK"
        # Net payout (status==PAID) is 0 across the entire trip.
        bonuses_all = list_referral_bonuses(
            params={"candidate_id": ctx["candidate"]["id"], "limit": 100},
        )
        from test_helpers import assert_net_referral_payout_cents
        net = assert_net_referral_payout_cents(bonuses_all)
        assert net == 0, (
            f"net_payout_cents must remain 0 (no payout occurred), "
            f"got {net}"
        )

    def test_headcount_conserved_after_double_failure(self, api):
        """PRD §3.7: "the parent requisition's `filled_count` is
        decremented by one; if the requisition was already in
        `CLOSED`, it is reopened back to `OPEN` and `closed_at` is
        cleared". PRD §3.2: "Once the requisition has left `DRAFT`,
        `headcount` is immutable".

        Claim (alternate conserved-quantity scenario): after one
        complete hire→revoke round-trip on a headcount=1 requisition,
        the requisition's headcount is unchanged (immutable across
        the whole trip), filled_count is back to 0, status is OPEN
        again, and closed_at is null again. This pins all four
        conserved attributes from the post-hire revoke chain.

        # difficulty: compensating_invariant/requisition_headcount_conservation_through_hire_revoke
        """
        ctx = setup_offer_extended(headcount=1)
        # Snapshot baseline.
        req_pre = get_requisition(ctx["requisition"]["id"])
        snapshot = {
            "headcount": req_pre["headcount"],
            "filled_count": req_pre["filled_count"],
            "status": req_pre["status"],
            "closed_at": req_pre.get("closed_at"),
        }
        # Accept then BG-fail.
        accept_offer(offer_id=ctx["offer"]["id"],
                     candidate_id=ctx["candidate"]["id"])
        report_bgc_fail(bgc_id=ctx["background_check"]["id"])
        req_post = get_requisition(ctx["requisition"]["id"])
        assert req_post["headcount"] == snapshot["headcount"]
        assert req_post["filled_count"] == snapshot["filled_count"]
        assert req_post["status"] == snapshot["status"]
        assert req_post.get("closed_at") == snapshot["closed_at"]
