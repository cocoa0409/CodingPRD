"""Difficulty-design coverage — primary tests for each instance.

Every instance declared in the difficulty-design index gets at least
two tests (this file and test_10_difficulty_coverage_supplemental.py).
Each test cites a verbatim PRD sentence for its underlying rule.

Tag format: each test docstring carries `# difficulty: <rule_id>/<name>`.
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
    approve_offer_step,
    assert_net_referral_payout_cents,
    build_single_hm_chain,
    build_two_step_hm_then_comp_chain,
    create_application,
    create_candidate,
    create_diversity_goal,
    create_offer,
    create_offer_payload,
    create_recruiter,
    create_hiring_manager,
    create_interviewer,
    extend_offer,
    get_application,
    get_background_check,
    get_diversity_goal,
    get_offer,
    get_referral_bonus,
    get_requisition,
    hold_requisition,
    init_clock,
    list_approval_chain,
    list_referral_bonuses,
    make_recruiter_headers,
    make_hiring_manager_headers,
    make_second_application_under_recruiter,
    offer_approval_step_payload,
    order_background_check,
    patch_offer_payload,
    report_bgc_fail,
    report_bgc_pass,
    request_revision,
    resume_requisition,
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
    approve_requisition,
    create_draft_requisition,
    TEST_DEFAULTS,
    TEST_USERS,
    advance_application,
    advance_application_to_interviewing,
    advance_application_to_offer_stage,
    schedule_interview,
    complete_interview,
    submit_feedback,
    accept_offer,
    create_interview_payload,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rule 1 — dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:

    def test_offer_total_comp_provisional_vs_ratified(self, api):
        """PRD §3.5: "While the offer is in `DRAFT`,
        `PENDING_APPROVAL`, or `NEGOTIATING`, the recompute is
        provisional — it reads the live component fields and is not
        budget-pinned. Once the offer transitions to `APPROVED`, the
        value freezes at that moment, and subsequent attempts to edit
        `base_salary_cents`, `sign_on_bonus_cents`, or
        `annual_equity_cents` are rejected with
        `ERR_OFFER_FIELDS_IMMUTABLE` (those fields are editable only
        while the offer is in `DRAFT` or `NEGOTIATING`)."

        Claim: with components (150_000, 150_050, 150_050), the
        provisional total at submit and the ratified total after
        APPROVED both equal 450_200 (per-component round_half_up:
        1500 + 1501 + 1501 = 4502 dollars). A PATCH attempt on
        sign_on_bonus_cents after APPROVED returns
        ERR_OFFER_FIELDS_IMMUTABLE and the ratified total remains 450_200.

        # difficulty: dual_variant_calc/offer_total_comp_provisional_vs_ratified
        """
        ctx = setup_application_in_offer_stage(
            requisition_budget_cents=10_000_000,
            hiring_manager_budget_cents=50_000_000,
        )
        chain = build_single_hm_chain(ctx["hiring_manager"]["id"])
        offer = create_offer(
            application_id=ctx["application"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
            base_salary_cents=150_000,
            sign_on_bonus_cents=150_050,
            annual_equity_cents=150_050,
            approval_chain=chain,
        )
        offer = submit_offer(offer_id=offer["id"],
                             recruiter_id=ctx["recruiter"]["id"])
        # Provisional total observable via GET /offers/{id}.
        provisional = get_offer(offer["id"])
        assert provisional["total_first_year_comp_cents"] == 450_200, (
            f"Provisional total: 1500 + 1501 + 1501 = 4502 → "
            f"450200 cents; got {provisional['total_first_year_comp_cents']}"
        )
        # PASS the BG and approve the only step.
        bgc = order_background_check(offer_id=offer["id"],
                                     recruiter_id=ctx["recruiter"]["id"])
        report_bgc_pass(bgc_id=bgc["id"])
        offer = approve_offer_step(
            offer_id=offer["id"], step_order=1,
            approver_role="HIRING_MANAGER",
            approver_id=ctx["hiring_manager"]["id"],
        )
        assert offer["status"] == "APPROVED"
        assert offer["total_first_year_comp_cents"] == 450_200
        # PATCH on APPROVED must be rejected, ratified total unchanged.
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.patch_offer(
            offer["id"],
            patch_offer_payload(sign_on_bonus_cents=999_999),
            h,
        )
        validate_error(resp, ApiErrorId.ERR_OFFER_FIELDS_IMMUTABLE.value)
        after = get_offer(offer["id"])
        assert after["total_first_year_comp_cents"] == 450_200, (
            f"Ratified total must survive failed PATCH, got "
            f"{after['total_first_year_comp_cents']}"
        )

    def test_diversity_goal_realized_vs_projected(self, api):
        """PRD §3.6: "The realized variant looks only at applications
        that are currently in `HIRED` ... The projected variant uses
        a wider denominator: the set of applications whose `stage` is
        any of `APPLIED`, `SCREENING`, `INTERVIEWING`, `OFFER_STAGE`,
        or `HIRED`".

        Claim: with one A_HIRED (protected) and one A_APPLIED (not
        protected) both tied to goal G:
            realized_percentage == 100.00  (denominator = {A_HIRED})
            projected_percentage == 50.00  (denominator = {A_HIRED, A_APPLIED})

        # difficulty: dual_variant_calc/diversity_goal_realized_vs_projected
        """
        goal = create_diversity_goal(
            department_code="ENG_DUAL_DG",
            period_year=2026,
            target_protected_class_percentage=50.0,
        )
        # A_HIRED — protected, goal-tied, headcount=1, will accept.
        ctx_hire = setup_offer_accepted(
            seniority_level="SENIOR",
            candidate_protected=True,
            target_diversity_goal_id=goal["id"],
            headcount=1,
        )
        # A_APPLIED — non-protected, goal-tied, separate requisition.
        anchor = init_clock(TEST_DEFAULTS["INITIAL_CLOCK_ISO"])
        recruiter2, hm2, req2 = setup_open_requisition(
            seniority_level="SENIOR",
            target_diversity_goal_id=goal["id"],
            headcount=1,
        )
        cand2 = create_candidate(actor_recruiter_id=recruiter2["id"])
        application2 = create_application(
            requisition_id=req2["id"],
            candidate_id=cand2["id"],
            actor_recruiter_id=recruiter2["id"],
        )
        assert application2["stage"] == "APPLIED"
        # Now read goal.
        g = get_diversity_goal(goal["id"])
        assert g["realized_percentage"] == pytest.approx(100.00, abs=0.005), (
            f"realized must be 100.00 (1 HIRED protected of 1 HIRED), got "
            f"{g['realized_percentage']}"
        )
        assert g["projected_percentage"] == pytest.approx(50.00, abs=0.005), (
            f"projected must be 50.00 (1 of 2 in {{HIRED, APPLIED}} "
            f"protected), got {g['projected_percentage']}"
        )
        assert g["realized_percentage"] != g["projected_percentage"]


# ===========================================================================
# Rule 2 — combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:

    def test_referral_bonus_three_input_nonlinear(self, api):
        """PRD §3.6: "Its `base_amount_cents` is computed by looking
        up the requisition's `seniority_level` in a fixed schedule:
        `JUNIOR` yields $1,500.00 ($150,000 cents), `MID` yields
        $2,500.00 ($250,000 cents), `SENIOR` yields $5,000.00
        ($500,000 cents), `STAFF` yields $7,500.00 ($750,000 cents),
        and `PRINCIPAL` yields $10,000.00 ($1,000,000 cents). If the
        candidate is flagged `is_in_eeo_protected_class`, a diversity
        uplift is applied: the uplift starts as 50% of the base amount
        in cents, rounded half up. That value is then capped — the
        cap is $2,000.00 ($200,000 cents) when the requisition is NOT
        tied to a `target_diversity_goal_id`, and $4,000.00 ($400,000
        cents) when it IS tied to one. The effective uplift is the
        smaller of the raw 50% value and the applicable cap."

        Claim: 3 inputs (seniority, protected, goal-tied) interact
        non-linearly:
          SENIOR + protected + no goal → base=500_000, uplift=200_000
            (capped from raw 250_000), total=700_000
          PRINCIPAL + protected + goal-tied → base=1_000_000,
            uplift=400_000 (capped from raw 500_000), total=1_400_000

        # difficulty: combinatorial_formula/referral_bonus_three_input_nonlinear
        """
        # First leg: SENIOR + protected + no goal.
        ctx_no_goal = setup_referral_hire(
            seniority_level="SENIOR",
            candidate_protected=True,
            target_diversity_goal_id=None,
        )
        rb_no_goal = ctx_no_goal["referral_bonuses"][0]
        assert rb_no_goal["base_amount_cents"] == 500_000
        assert rb_no_goal["diversity_uplift_cents"] == 200_000, (
            f"no-goal cap is 200000; got {rb_no_goal['diversity_uplift_cents']}"
        )
        assert rb_no_goal["total_amount_cents"] == 700_000

        # Second leg: PRINCIPAL + protected + goal tied.
        goal = create_diversity_goal(
            department_code="ENG_COMBI",
            period_year=2026,
            target_protected_class_percentage=30.0,
        )
        ctx_with_goal = setup_referral_hire(
            seniority_level="PRINCIPAL",
            candidate_protected=True,
            target_diversity_goal_id=goal["id"],
        )
        rb_with_goal = ctx_with_goal["referral_bonuses"][0]
        assert rb_with_goal["base_amount_cents"] == 1_000_000
        assert rb_with_goal["diversity_uplift_cents"] == 400_000, (
            f"goal-tied cap is 400000; got "
            f"{rb_with_goal['diversity_uplift_cents']}"
        )
        assert rb_with_goal["total_amount_cents"] == 1_400_000

    def test_offer_total_comp_rounding_order(self, api):
        """PRD §3.5: "Offer total compensation
        (`total_first_year_comp_cents`) is computed by rounding each
        component to whole dollars first and then summing —
        specifically: convert `base_salary_cents` to dollars by
        dividing by 100 and rounding half up to a whole number,
        convert `sign_on_bonus_cents` to dollars by dividing by 100
        and rounding half up to a whole number, convert
        `annual_equity_cents` to dollars by dividing by 100 and
        rounding half up to a whole number, add the three whole-dollar
        values together, then multiply that sum by 100 to express the
        final result in cents. Summing the original cents and rounding
        once at the end is not the same answer and is not what the
        system computes."

        Claim: inputs (150_000, 150_050, 150_050) → 450_200 (the
        per-component answer), NOT 450_100 (the sum-then-round
        answer).

        # difficulty: combinatorial_formula/offer_total_comp_rounding_order
        """
        ctx = setup_application_in_offer_stage()
        chain = build_single_hm_chain(ctx["hiring_manager"]["id"])
        offer = create_offer(
            application_id=ctx["application"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
            base_salary_cents=150_000,
            sign_on_bonus_cents=150_050,
            annual_equity_cents=150_050,
            approval_chain=chain,
        )
        assert offer["total_first_year_comp_cents"] == 450_200, (
            f"Per-component round_half_up: 150000→1500, 150050→1501, "
            f"150050→1501 → 4502 → 450200; got "
            f"{offer['total_first_year_comp_cents']}"
        )
        assert offer["total_first_year_comp_cents"] != 450_100, (
            "450100 would be the sum-then-round answer (incorrect)"
        )


# ===========================================================================
# Rule 3 — non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:

    def test_offer_renegotiation_cycle(self, api):
        """PRD §3.5: "The acting step's `decision` is recorded as
        `REJECTED`, `decided_at` is stamped, and the offer transitions
        `PENDING_APPROVAL` → `NEGOTIATING`. The recruiter then edits
        the offer ... An edit submitted against a `NEGOTIATING` offer
        additionally drives the offer back to `PENDING_APPROVAL`,
        increments `negotiation_round` by one, recomputes
        `total_first_year_comp_cents`, resets every
        `OfferApprovalStep` back to `PENDING` with `decided_at` set
        to null".

        Claim: two cycles of PENDING_APPROVAL → NEGOTIATING →
        PENDING_APPROVAL drive negotiation_round to 2; every
        OfferApprovalStep.decision returns to PENDING with
        decided_at == null.

        # difficulty: non_linear_state_machine/offer_renegotiation_cycle
        """
        ctx = setup_two_step_offer_pending_approval()
        # First cycle.
        request_revision(
            offer_id=ctx["offer"]["id"], step_order=1,
            approver_role="HIRING_MANAGER",
            approver_id=ctx["hiring_manager"]["id"],
        )
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.patch_offer(
            ctx["offer"]["id"],
            patch_offer_payload(sign_on_bonus_cents=0),
            h,
        )
        offer = validate_success(resp, expected_status=200)
        assert offer["status"] == "PENDING_APPROVAL"
        assert offer["negotiation_round"] == 1
        # Second cycle.
        request_revision(
            offer_id=ctx["offer"]["id"], step_order=1,
            approver_role="HIRING_MANAGER",
            approver_id=ctx["hiring_manager"]["id"],
        )
        resp = api.patch_offer(
            ctx["offer"]["id"],
            patch_offer_payload(sign_on_bonus_cents=100),
            h,
        )
        offer = validate_success(resp, expected_status=200)
        assert offer["status"] == "PENDING_APPROVAL"
        assert offer["negotiation_round"] == 2
        # Steps must all be PENDING with decided_at null.
        chain = list_approval_chain(ctx["offer"]["id"])
        assert len(chain) == 2
        for step in chain:
            assert step["decision"] == "PENDING", (
                f"step {step['step_order']} decision must be PENDING "
                f"after second cycle, got {step['decision']!r}"
            )
            assert step.get("decided_at") is None, (
                f"step {step['step_order']} decided_at must be null, "
                f"got {step.get('decided_at')!r}"
            )

    def test_application_compound_state_from_children(self, api):
        """PRD §3.3: "Advancing from `INTERVIEWING` to `OFFER_STAGE`
        is the most heavily gated transition in the system. It
        requires ... at least one `Interview` under the application
        has reached `COMPLETED` and carries at least one
        `InterviewFeedback` whose `recommendation` is `HIRE` or
        `STRONG_HIRE`".

        PRD §3.6: "When an offer reaches `ACCEPTED`, a three-hop
        cascade fires. Hop one: the parent application transitions
        from `OFFER_STAGE` to `HIRED`."

        Claim: the parent Application reacts to its children's states
        — INTERVIEWING→OFFER_STAGE on COMPLETED interview + qualifying
        feedback, then OFFER_STAGE→HIRED on Offer→ACCEPTED.

        # difficulty: non_linear_state_machine/application_compound_state_from_children
        """
        # OFFER_STAGE entry path is exactly what
        # setup_application_in_offer_stage does — verify it.
        ctx = setup_application_in_offer_stage()
        app = get_application(ctx["application"]["id"])
        assert app["stage"] == "OFFER_STAGE", (
            f"After completed interview + qualifying feedback + advance, "
            f"stage must be OFFER_STAGE, got {app['stage']!r}"
        )
        # Now drive through approve + extend + accept.
        chain = build_single_hm_chain(ctx["hiring_manager"]["id"])
        offer = create_offer(
            application_id=ctx["application"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
            base_salary_cents=150_000,
            approval_chain=chain,
        )
        offer = submit_offer(offer_id=offer["id"],
                             recruiter_id=ctx["recruiter"]["id"])
        bgc = order_background_check(offer_id=offer["id"],
                                     recruiter_id=ctx["recruiter"]["id"])
        report_bgc_pass(bgc_id=bgc["id"])
        offer = approve_offer_step(
            offer_id=offer["id"], step_order=1,
            approver_role="HIRING_MANAGER",
            approver_id=ctx["hiring_manager"]["id"],
        )
        expires_at = add_days(ctx["anchor_iso"], 7)
        offer = extend_offer(
            offer_id=offer["id"],
            recruiter_id=ctx["recruiter"]["id"],
            expires_at=expires_at,
        )
        # After extend, application is still OFFER_STAGE (parent waits
        # on the child offer).
        app = get_application(ctx["application"]["id"])
        assert app["stage"] == "OFFER_STAGE"
        # Accept → parent transitions to HIRED.
        offer = accept_offer(offer_id=offer["id"],
                             candidate_id=ctx["candidate"]["id"])
        assert offer["status"] == "ACCEPTED"
        app = get_application(ctx["application"]["id"])
        assert app["stage"] == "HIRED", (
            f"After Offer→ACCEPTED, parent Application must be HIRED, "
            f"got {app['stage']!r}"
        )


# ===========================================================================
# Rule 4 — transitive_cascade
# ===========================================================================
class TestTransitiveCascade:

    def test_hire_chain_depth3(self, api):
        """PRD §3.6: "When an offer reaches `ACCEPTED`, a three-hop
        cascade fires. Hop one: the parent application transitions
        from `OFFER_STAGE` to `HIRED`. Hop two: the parent
        requisition's `filled_count` is incremented by one ... Hop
        three: if this hire just brought `filled_count` to equal
        `headcount`, the requisition transitions `OPEN` → `CLOSED`,
        `closed_at` is set to the current logical time, and every
        remaining non-terminal application on the requisition is
        auto-rejected with `rejection_reason` set to `OTHER`."

        Claim: with headcount=1 and a second non-terminal Application
        in INTERVIEWING, /accept on the EXTENDED offer for A_hire
        triggers depth-3 cascade:
            A_hire → HIRED  (hop 1)
            filled_count == 1 and Requisition → CLOSED  (hop 2)
            A_other → REJECTED rejection_reason=OTHER  (hop 3)

        # difficulty: transitive_cascade/hire_chain_depth3
        """
        # Build OFFER_STAGE A_hire and INTERVIEWING A_other under same Req.
        anchor = init_clock(TEST_DEFAULTS["INITIAL_CLOCK_ISO"])
        recruiter, hm, req = setup_open_requisition(headcount=1)
        v = create_interviewer(is_certified_for_eeo=True)
        # A_hire: protected gear unnecessary; non-protected for speed.
        cand_h = create_candidate(actor_recruiter_id=recruiter["id"])
        a_hire = create_application(
            requisition_id=req["id"], candidate_id=cand_h["id"],
            actor_recruiter_id=recruiter["id"],
        )
        a_hire, iv_hire = advance_application_to_interviewing(
            application=a_hire, recruiter_id=recruiter["id"],
            interviewer_id=v["id"], anchor_iso=anchor,
        )
        a_hire = advance_application_to_offer_stage(
            application=a_hire, interview=iv_hire,
            recruiter_id=recruiter["id"], interviewer_id=v["id"],
        )
        # A_other: stay in INTERVIEWING. Schedule an interview *after*
        # iv_hire's window (which is anchor+1h to anchor+2h) plus
        # buffer to avoid double-booking. We use a different
        # interviewer to be safe.
        v2 = create_interviewer(is_certified_for_eeo=True)
        cand_o = create_candidate(actor_recruiter_id=recruiter["id"])
        a_other = create_application(
            requisition_id=req["id"], candidate_id=cand_o["id"],
            actor_recruiter_id=recruiter["id"],
        )
        a_other = advance_application(
            application_id=a_other["id"], recruiter_id=recruiter["id"],
        )
        schedule_interview(
            application_id=a_other["id"], recruiter_id=recruiter["id"],
            interviewer_id=v2["id"],
            start_at=add_hours(anchor, 24),
            end_at=add_hours(anchor, 25),
        )
        a_other = advance_application(
            application_id=a_other["id"], recruiter_id=recruiter["id"],
        )
        assert a_other["stage"] == "INTERVIEWING"
        # Offer chain for A_hire.
        offer = create_offer(
            application_id=a_hire["id"], recruiter_id=recruiter["id"],
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
        offer = extend_offer(offer_id=offer["id"],
                             recruiter_id=recruiter["id"],
                             expires_at=add_days(anchor, 30))
        offer = accept_offer(offer_id=offer["id"],
                             candidate_id=cand_h["id"])
        # Hops 1-3 observable.
        assert offer["status"] == "ACCEPTED"
        a_hire = get_application(a_hire["id"])
        assert a_hire["stage"] == "HIRED"
        req = get_requisition(req["id"])
        assert req["filled_count"] == 1
        assert req["status"] == "CLOSED", (
            f"Requisition must reach CLOSED on full headcount, got "
            f"{req['status']!r}"
        )
        a_other = get_application(a_other["id"])
        assert a_other["stage"] == "REJECTED"
        assert a_other["rejection_reason"] == "OTHER", (
            f"Auto-rejected sibling must carry rejection_reason=OTHER, "
            f"got {a_other.get('rejection_reason')!r}"
        )

    def test_bg_fail_chain_depth3(self, api):
        """PRD §3.7: "If instead the linked offer has already been
        `ACCEPTED` — that is, the hire has been recorded — the
        cascade is broader (this is the post-hire revoke chain): the
        offer transitions `ACCEPTED` → `RESCINDED`; the parent
        application transitions `HIRED` → `REJECTED` with
        `rejection_reason` set to `FAILED_BACKGROUND_CHECK`; the
        parent requisition's `filled_count` is decremented by one;
        if the requisition was already in `CLOSED`, it is reopened
        back to `OPEN` and `closed_at` is cleared ... and any
        `ReferralBonus` tied to this hire is transitioned to
        `CLAWED_BACK` regardless of whether it was previously
        `ACCRUED` or `PAYABLE`."

        Claim: BG FAIL on an ACCEPTED referral hire triggers depth-3+
        cascade — Offer.status==RESCINDED, Application.stage==REJECTED
        with FAILED_BACKGROUND_CHECK, Requisition.filled_count==0 and
        reopened to OPEN, ReferralBonus.status==CLAWED_BACK.

        # difficulty: transitive_cascade/bg_fail_chain_depth3
        """
        ctx = setup_referral_hire(
            seniority_level="SENIOR",
            candidate_protected=True,
        )
        assert ctx["requisition"]["status"] == "CLOSED"
        assert ctx["requisition"]["filled_count"] == 1
        assert len(ctx["referral_bonuses"]) >= 1
        rb_id = ctx["referral_bonuses"][0]["id"]
        # Fire BG FAIL.
        report_bgc_fail(bgc_id=ctx["background_check"]["id"])
        offer = get_offer(ctx["offer"]["id"])
        app = get_application(ctx["application"]["id"])
        req = get_requisition(ctx["requisition"]["id"])
        rb = get_referral_bonus(rb_id)
        assert offer["status"] == "RESCINDED"
        assert app["stage"] == "REJECTED"
        assert app["rejection_reason"] == "FAILED_BACKGROUND_CHECK"
        assert req["filled_count"] == 0
        assert req["status"] == "OPEN"
        assert rb["status"] == "CLAWED_BACK"


# ===========================================================================
# Rule 5 — priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:

    def test_referential_vs_fiscal_offer_creation(self, api):
        """PRD §2.9: "first, header presence ... then ...
        request-body foreign-key existence (`ERR_REFERENCE_NOT_FOUND`)
        ... then the per-offer requisition-budget cap
        (`ERR_OFFER_EXCEEDS_REQ_BUDGET`)".

        Claim: an offer-creation request whose approval_chain step
        references a NON-EXISTENT hiring manager id AND has a comp
        total wildly over the requisition's budget triggers both
        rules; the priority-4 foreign-key existence wins over the
        priority-14 fiscal cap. Observed error_id ==
        ERR_REFERENCE_NOT_FOUND.

        # difficulty: priority_pair_validation_conflict/referential_vs_fiscal_offer_submit

        Note: we use validate_error_is_one_of because PRD names the
        priority order but the offer-creation endpoint's exact firing
        moment for the FK check (creation vs submit) is implementation-
        derivable. PRD §2.6 explicitly says foreign-key checks fire
        before state checks; we assert that ERR_REFERENCE_NOT_FOUND
        is the resulting error_id when both would fire.
        """
        from test_helpers import validate_error_is_one_of
        ctx = setup_application_in_offer_stage(
            requisition_budget_cents=100_000,
        )
        chain = [
            offer_approval_step_payload(
                step_order=1,
                approver_role="HIRING_MANAGER",
                required_approver_id=NON_EXISTENT_UUID,
            ),
        ]
        from test_helpers import create_offer_payload, make_recruiter_headers
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        # Choose base_salary_cents wildly larger than budget so the
        # fiscal cap would fire too on /submit.
        payload = create_offer_payload(
            base_salary_cents=99_999_999,
            approval_chain=chain,
        )
        resp = api.create_offer(ctx["application"]["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_REFERENCE_NOT_FOUND.value)


# ===========================================================================
# Rule 6 — boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:

    def test_diversity_goal_threshold_ge_boundary_eq(self, api):
        """PRD §3.6: "The lock succeeds only when
        `realized_percentage` is greater than or equal to
        `target_protected_class_percentage` — note that the threshold
        is met when exactly equal; it is a non-strict comparison."

        Claim: realized == target (50.00 == 50.00) → /lock returns 200.

        # difficulty: boundary_precision_check/diversity_goal_threshold_ge_boundary
        """
        goal = create_diversity_goal(
            department_code="ENG_BND_EQ",
            period_year=2026,
            target_protected_class_percentage=50.0,
        )
        # Build TWO HIREs tied to goal: 1 protected, 1 non-protected →
        # realized = 50.00.
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
        validate_success(resp, expected_status=200)

    def test_empty_panel_zero_count_boundary(self, api):
        """PRD §3.3: "(d) the empty-panel condition does not hold —
        there must be at least one `COMPLETED` interview overall,
        otherwise the advance is rejected with `ERR_EMPTY_PANEL`".

        Claim: Application in INTERVIEWING with ZERO COMPLETED
        interviews (one SCHEDULED but never advanced past
        scheduled_end_at) → /advance returns ERR_EMPTY_PANEL / 409,
        and the application's stage remains INTERVIEWING.

        # difficulty: boundary_precision_check/empty_panel_zero_count_boundary
        """
        ctx = setup_interviewer_with_scheduled_interview(
            start_iso=add_hours(TEST_DEFAULTS["INITIAL_CLOCK_ISO"], 10),
            end_iso=add_hours(TEST_DEFAULTS["INITIAL_CLOCK_ISO"], 11),
            anchor_iso=TEST_DEFAULTS["INITIAL_CLOCK_ISO"],
        )
        # The setup leaves application_a in SCREENING with one scheduled
        # interview. Advance to INTERVIEWING.
        application = advance_application(
            application_id=ctx["application_a"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
        )
        assert application["stage"] == "INTERVIEWING"
        # Now /advance again — no COMPLETED interview yet.
        h = make_recruiter_headers(ctx["recruiter"]["id"])
        resp = api.advance_application(application["id"], h)
        validate_error(resp, ApiErrorId.ERR_EMPTY_PANEL.value)
        # Stage unchanged.
        app = get_application(application["id"])
        assert app["stage"] == "INTERVIEWING"


# ===========================================================================
# Rule 7 — cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_offer_approve_requires_bgc_passed(self, api):
        """PRD §3.5: "Approving the final step is what transitions the
        offer `PENDING_APPROVAL` → `APPROVED`, and that final
        transition has additional preconditions: every prior step's
        `decision` is already `APPROVED`, a `BackgroundCheck` for this
        offer exists with `status` of `PASSED` — the cross-entity
        offer-to-background-check gate".

        Claim: /approve while BGC is PENDING → ERR_INVALID_STATE;
        after BGC → PASSED, /approve succeeds.

        # difficulty: cross_entity_state_dependency/offer_approve_depends_on_bgc_passed
        """
        ctx = setup_offer_in_pending_approval()
        bgc = order_background_check(
            offer_id=ctx["offer"]["id"],
            recruiter_id=ctx["recruiter"]["id"],
        )
        h = make_hiring_manager_headers(ctx["hiring_manager"]["id"])
        # Attempt 1: BGC is PENDING — must fail.
        from test_helpers import approve_offer_payload
        resp = api.approve_offer(
            ctx["offer"]["id"], approve_offer_payload(step_order=1), h,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)
        offer = get_offer(ctx["offer"]["id"])
        assert offer["status"] == "PENDING_APPROVAL"
        # Now PASS.
        report_bgc_pass(bgc_id=bgc["id"])
        # Attempt 2: BGC PASSED → must succeed.
        resp = api.approve_offer(
            ctx["offer"]["id"], approve_offer_payload(step_order=1), h,
        )
        offer = validate_success(resp, expected_status=200)
        assert offer["status"] == "APPROVED"

    def test_application_hire_requires_requisition_open(self, api):
        """PRD §3.5: "Accepting transitions the offer `EXTENDED` →
        `ACCEPTED`; preconditions are that the acting candidate
        matches the parent application's `candidate_id`, the current
        logical time is strictly before `expires_at`, the parent
        requisition is still `OPEN`, and the parent requisition's
        `filled_count` is strictly less than `headcount`".

        Claim: /accept fails with ERR_INVALID_STATE when parent
        requisition is not OPEN. We construct this by accepting on
        a different requisition that has reached CLOSED (or here,
        directly — the test recipe suggests holding ON_HOLD, but
        holding a requisition that has an OFFER_STAGE application is
        disallowed by PRD §3.2; so we use the close-via-headcount
        path: independently fill the requisition then attempt a
        second /accept on a sibling offer). For simplicity we observe
        the requisition.OPEN precondition by accepting the only
        EXTENDED offer (the happy path) and asserting the post-state
        matches the PRD claim.

        # difficulty: cross_entity_state_dependency/application_hire_depends_on_requisition_open
        """
        # Single-headcount happy path — accept succeeds, requisition
        # CLOSED. A subsequent /accept attempt on a sibling EXTENDED
        # offer (if any) would have ERR_HEADCOUNT_EXCEEDED or
        # ERR_INVALID_STATE. To exercise the OPEN dependency, build
        # second extended offer on a sibling application then close
        # the req via the first hire, and assert the second /accept
        # fails.
        anchor = init_clock(TEST_DEFAULTS["INITIAL_CLOCK_ISO"])
        recruiter, hm, req = setup_open_requisition(headcount=1,
                                                    hiring_manager_budget_cents=5_000_000_00)
        v = create_interviewer(is_certified_for_eeo=True)
        # Build two parallel Applications through OFFER_STAGE.
        cand_a = create_candidate(actor_recruiter_id=recruiter["id"])
        cand_b = create_candidate(actor_recruiter_id=recruiter["id"])

        def _drive_to_offer_stage(cand, start_h, end_h, vint):
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
            # Complete interview + feedback, advance to OFFER_STAGE.
            from test_helpers import try_advance_clock_to_iso
            try_advance_clock_to_iso(
                add_minutes(iv["scheduled_end_at"], 1),
            )
            complete_interview(interview_id=iv["id"],
                               recruiter_id=recruiter["id"])
            submit_feedback(interview_id=iv["id"],
                            interviewer_id=vint["id"],
                            overall_score=5,
                            recommendation="STRONG_HIRE")
            app = advance_application(application_id=app["id"],
                                      recruiter_id=recruiter["id"])
            return app

        v2 = create_interviewer(is_certified_for_eeo=True)
        app_a = _drive_to_offer_stage(cand_a, 1, 2, v)
        # Use a separate interviewer + a comfortably-separated window
        # to avoid double-booking buffer (interview ends anchor+2h,
        # +15min buffer; we use anchor+5h-6h on v2 to be safe).
        app_b = _drive_to_offer_stage(cand_b, 5, 6, v2)

        def _build_extended_offer(app, expires_offset_days):
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
                expires_at=add_days(anchor, expires_offset_days),
            )
            return offer

        offer_a = _build_extended_offer(app_a, 30)
        offer_b = _build_extended_offer(app_b, 30)
        # Accept A — drives hire, req → CLOSED (headcount 1).
        accept_offer(offer_id=offer_a["id"], candidate_id=cand_a["id"])
        req_after = get_requisition(req["id"])
        assert req_after["status"] == "CLOSED"
        # Now accept B — requisition no longer OPEN. PRD §3.5 names
        # this as a precondition; failure surfaces as
        # ERR_INVALID_STATE or ERR_HEADCOUNT_EXCEEDED depending on
        # implementation precedence (both are PRD-faithful).
        from test_helpers import (
            make_candidate_headers, validate_error_is_one_of,
        )
        h = make_candidate_headers(cand_b["id"])
        resp = api.accept_offer(offer_b["id"], h)
        validate_error_is_one_of(
            resp,
            [
                ApiErrorId.ERR_INVALID_STATE.value,
                ApiErrorId.ERR_HEADCOUNT_EXCEEDED.value,
            ],
        )


# ===========================================================================
# Rule 8 — resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_interviewer_double_booking_with_buffer(self, api):
        """PRD §3.4: "Every newly scheduled or edited interview is
        checked for double-booking against the assigned interviewer's
        existing `SCHEDULED` interviews using a 15-minute buffer
        applied to both sides of each existing interval — that is, an
        existing scheduled interview from 10:00 to 11:00 effectively
        occupies 09:45 to 11:15 for collision-detection purposes.
        Adjacency where one interview's end equals another's start is
        therefore a conflict."

        Claim: three cases on the same interviewer V:
          - strictly adjacent (end1 == start2)              → ERR_INTERVIEWER_DOUBLE_BOOKED
          - exactly-buffer away (end1 + 15min == start2)    → ERR_INTERVIEWER_DOUBLE_BOOKED
          - just-past-buffer (end1 + 16min == start2)       → 201 SCHEDULED

        # difficulty: resource_temporal_overlap/interviewer_double_booking_with_buffer
        """
        # Use a fixed anchor in the future.
        anchor = "2026-06-01T08:00:00.000Z"
        start1 = "2026-06-01T10:00:00.000Z"
        end1 = "2026-06-01T11:00:00.000Z"
        ctx = setup_interviewer_with_scheduled_interview(
            start_iso=start1, end_iso=end1, anchor_iso=anchor,
        )
        h = make_recruiter_headers(ctx["recruiter"]["id"])

        # Case 1: strictly adjacent.
        _, _, app2 = make_second_application_under_recruiter(
            recruiter_id=ctx["recruiter"]["id"],
            hiring_manager_id=ctx["hiring_manager"]["id"],
            department_code="ENG",
        )
        payload = create_interview_payload(
            interviewer_id=ctx["interviewer"]["id"],
            scheduled_start_at="2026-06-01T11:00:00.000Z",
            scheduled_end_at="2026-06-01T12:00:00.000Z",
        )
        resp = api.create_interview(app2["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED.value)

        # Case 2: exactly buffer away.
        _, _, app3 = make_second_application_under_recruiter(
            recruiter_id=ctx["recruiter"]["id"],
            hiring_manager_id=ctx["hiring_manager"]["id"],
            department_code="ENG",
        )
        payload = create_interview_payload(
            interviewer_id=ctx["interviewer"]["id"],
            scheduled_start_at="2026-06-01T11:15:00.000Z",
            scheduled_end_at="2026-06-01T12:15:00.000Z",
        )
        resp = api.create_interview(app3["id"], payload, h)
        validate_error(resp, ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED.value)

        # Case 3: just past buffer — succeeds.
        _, _, app4 = make_second_application_under_recruiter(
            recruiter_id=ctx["recruiter"]["id"],
            hiring_manager_id=ctx["hiring_manager"]["id"],
            department_code="ENG",
        )
        payload = create_interview_payload(
            interviewer_id=ctx["interviewer"]["id"],
            scheduled_start_at="2026-06-01T11:16:00.000Z",
            scheduled_end_at="2026-06-01T12:16:00.000Z",
        )
        resp = api.create_interview(app4["id"], payload, h)
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_recruiter_open_requisition_cap(self, api):
        """PRD §3.2: "a `Recruiter` may own at most 5 requisitions for
        which `posted_at` is non-null and `closed_at` is null at any
        one time — this is a half-open lifetime interval, and the cap
        counts in aggregate across the recruiter's owned requisitions
        rather than as pairwise overlap. Breaching the cap rejects
        the approval with `ERR_RECRUITER_REQUISITION_CAP`."

        Claim: 6th /approve under the same recruiter (with five
        previously approved still open) returns
        ERR_RECRUITER_REQUISITION_CAP / 409. After cancelling one of
        the five, a sixth /approve (after a fresh submit) succeeds.

        # difficulty: resource_temporal_overlap/recruiter_open_requisition_cap
        """
        ctx = setup_recruiter_with_n_open_requisitions(n=5)
        recruiter = ctx["recruiter"]
        hm = ctx["hiring_manager"]
        # Sixth requisition.
        req6 = create_draft_requisition(
            recruiter_id=recruiter["id"],
            hiring_manager_id=hm["id"],
            seniority_level="SENIOR",
            headcount=1,
        )
        submit_requisition(requisition_id=req6["id"],
                           recruiter_id=recruiter["id"])
        h = make_hiring_manager_headers(hm["id"])
        # First attempt: cap breached.
        resp = api.approve_requisition(req6["id"], h)
        validate_error(resp, ApiErrorId.ERR_RECRUITER_REQUISITION_CAP.value)
        # Cancel one of the first five — count drops to 4 + req6 in
        # PENDING_APPROVAL (count is on posted_at non-null AND
        # closed_at null, so PENDING_APPROVAL does not count).
        from test_helpers import cancel_requisition
        cancelled = cancel_requisition(
            requisition_id=ctx["requisitions"][0]["id"],
            recruiter_id=recruiter["id"],
        )
        assert cancelled["status"] == "CANCELLED"
        # Now approve req6 — count goes from 4 to 5 (within cap).
        resp = api.approve_requisition(req6["id"], h)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "OPEN"


# ===========================================================================
# Rule 9 — compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:

    def test_referral_bonus_clawback_keeps_net_payout_invariant(self, api):
        """PRD §3.7: "any `ReferralBonus` tied to this hire is
        transitioned to `CLAWED_BACK` regardless of whether it was
        previously `ACCRUED` or `PAYABLE`."

        Claim: pre-cascade SUM(rb.total_amount_cents | rb.status=PAID)
        equals post-cascade SUM (both 0 — no payout occurred before
        the clawback), AND the cascade observably ran (ReferralBonus
        flipped to CLAWED_BACK, Application REJECTED with
        FAILED_BACKGROUND_CHECK).

        # difficulty: compensating_invariant/referral_bonus_clawback_keeps_net_payout_invariant
        """
        # Before any hire — net payout is 0 (read against current bonus
        # listing). Build a fresh hire chain.
        ctx = setup_referral_hire(seniority_level="SENIOR",
                                  candidate_protected=False)
        bonuses_before = list_referral_bonuses(
            params={"candidate_id": ctx["candidate"]["id"], "limit": 100},
        )
        net_before = assert_net_referral_payout_cents(bonuses_before)
        # No payout yet (status is ACCRUED).
        assert net_before == 0
        report_bgc_fail(bgc_id=ctx["background_check"]["id"])
        bonuses_after = list_referral_bonuses(
            params={"candidate_id": ctx["candidate"]["id"], "limit": 100},
        )
        net_after = assert_net_referral_payout_cents(bonuses_after)
        assert net_after == net_before == 0, (
            f"net_payout must remain 0 across clawback (no payout "
            f"occurred), got before={net_before} after={net_after}"
        )
        # Observable cascade.
        rb = get_referral_bonus(ctx["referral_bonuses"][0]["id"])
        assert rb["status"] == "CLAWED_BACK"
        app = get_application(ctx["application"]["id"])
        assert app["stage"] == "REJECTED"
        assert app["rejection_reason"] == "FAILED_BACKGROUND_CHECK"

    def test_requisition_headcount_conservation_through_hire_revoke(self, api):
        """PRD §3.7: "the parent requisition's `filled_count` is
        decremented by one; if the requisition was already in
        `CLOSED`, it is reopened back to `OPEN` and `closed_at` is
        cleared".

        Claim: snapshot (filled_count_before=0, status_before=OPEN,
        closed_at_before=null); after /accept → /report-result FAIL
        round trip, (filled_count, status, closed_at) returns to the
        pre-accept values; headcount itself is immutable since DRAFT
        exit.

        # difficulty: compensating_invariant/requisition_headcount_conservation_through_hire_revoke
        """
        ctx = setup_offer_extended()
        req_before = get_requisition(ctx["requisition"]["id"])
        # Capture pre-accept tuple.
        filled_before = req_before["filled_count"]
        status_before = req_before["status"]
        closed_at_before = req_before.get("closed_at")
        assert filled_before == 0
        assert status_before == "OPEN"
        assert closed_at_before is None
        # Accept → hire cascade → req CLOSED.
        from test_helpers import accept_offer
        accept_offer(offer_id=ctx["offer"]["id"],
                     candidate_id=ctx["candidate"]["id"])
        req_mid = get_requisition(ctx["requisition"]["id"])
        assert req_mid["filled_count"] == 1
        assert req_mid["status"] == "CLOSED"
        # Compensating action.
        report_bgc_fail(bgc_id=ctx["background_check"]["id"])
        req_after = get_requisition(ctx["requisition"]["id"])
        assert req_after["filled_count"] == filled_before, (
            f"filled_count must return to {filled_before}, got "
            f"{req_after['filled_count']}"
        )
        assert req_after["status"] == status_before, (
            f"status must return to {status_before}, got "
            f"{req_after['status']!r}"
        )
        assert req_after.get("closed_at") == closed_at_before, (
            f"closed_at must return to {closed_at_before!r}, got "
            f"{req_after.get('closed_at')!r}"
        )
        # Headcount immutable since DRAFT exit.
        assert req_after["headcount"] == 1
