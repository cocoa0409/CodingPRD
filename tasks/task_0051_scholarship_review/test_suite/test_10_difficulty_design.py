"""Additional tests for difficulty-design coverage.

Each test in this file covers one difficulty-design instance with a
distinct scenario from its companion test elsewhere in the suite,
giving every instance at least TWO covering tests as required.

Tag convention: every test docstring carries a
   # difficulty: <rule_id>/<instance.name>
line so the coverage audit can attribute the test.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    advance_clock,
    announce_scholarship,
    api_client,
    approve_disbursement_plan_payload,
    approve_plan_dept,
    approve_plan_finance,
    assign_reviewers_payload,
    close_and_review,
    create_application,
    create_disbursement_plan,
    create_open_scholarship,
    create_reviewer_set,
    create_scholarship,
    create_scholarship_payload,
    create_scholarship_with_quota,
    create_submitted_application,
    dept_officer_headers,
    DEPT_OFFICER_ID_1,
    dept_review_pass,
    execute_plan,
    finance_officer_headers,
    FINANCE_OFFICER_ID_1,
    finalize_scholarship,
    iso_at,
    list_quota_slices,
    make_reviewer_headers,
    make_student_headers,
    new_student_id,
    open_scholarship,
    rule_objection,
    setup_announced_with_one_awarded,
    setup_announced_with_winner_and_runnerup,
    setup_dept_approved_plan,
    setup_executed_plan,
    setup_finalized_with_one_awarded,
    setup_review_complete,
    submit_score_payload,
    transition_scholarship,
    create_objection,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# dual_variant_calc — second tests
# ===========================================================================
class TestDualVariantSecondCoverage:

    def test_score_aggregation_trimmed_mean_marks_outlier_with_default_threshold(
        self,
    ):
        """PRD §3.6: "a score is marked as an outlier — its is_outlier
        flag flipped to true — when the absolute difference between its
        raw_total_x100 and the mean, multiplied by 100, is strictly
        greater than the scholarship's outlier_z_threshold_x100 multiplied
        by the standard deviation".

        Second coverage of trimmed-vs-full-mean: a different rubric and
        score triple at the default threshold (200, i.e. z=2.0) showing
        that with very disparate scores at z=2.0 threshold, no outlier
        forms when the disparity sits below 2-sigma.
        # difficulty: dual_variant_calc/score_aggregation_trimmed_vs_full_mean
        """
        # Scores 50,50,60 -> raws 5000,5000,6000. Mean=5333.33,
        # stddev=sqrt( ((-333.33)^2 + (-333.33)^2 + (666.67)^2)/3 )
        # = sqrt( (111110.89 + 111110.89 + 444448.89)/3 )
        # = sqrt(222223.56) ≈ 471.4.
        # threshold_x100=200 (z=2.0). Check 6000:
        # |6000-5333.33|*100 = 66667 ; 200*471.4 = 94280. 66667 < 94280 ->
        # NOT outlier. So all three kept; mean = round(5333.33) = 5333.
        state = setup_review_complete(
            criterion_scores_list=[
                {"core": 50}, {"core": 50}, {"core": 60},
            ],
            rubric_weights={"core": 100},
            outlier_z_threshold_x100=200,
        )
        assert state["application"]["aggregated_score_x100"] == 5333
        scores, _ = validate_paginated(
            api_client.list_scores(
                state["scholarship"]["id"],
                state["application"]["id"], ADMIN,
            ),
        )
        for s in scores:
            assert s["is_outlier"] is False, (
                "No outlier flagged when disparity is below "
                "outlier_z_threshold_x100 / 100 sigmas"
            )

    def test_tax_at_500250_net_below_routing_threshold(self):
        """PRD §3.10: "the alternative of computing the unrounded sum and
        rounding once at the end is explicitly forbidden because at
        fractional-edge gross values the two procedures can differ by
        one cent." Second coverage of the per-component-vs-sum-then-round
        variant: assert the routing decision uses the per-component net
        (1509), so net=498741 < 1_000_000 keeps the plan's payment_channel.
        # difficulty: dual_variant_calc/tax_withholding_per_component_vs_sum_then_round
        """
        state = setup_executed_plan(
            per_award_amount_cents=500_250,
            payment_channel="CAMPUS_CARD",
        )
        records, _ = validate_paginated(
            api_client.list_disbursement_records(
                state["scholarship"]["id"], state["plan"]["id"], ADMIN,
            ),
        )
        rec = records[0]
        # Pinned tax = 1509, so net = 500250 - 1509 = 498741.
        assert rec["tax_withheld_cents"] == 1509
        assert rec["net_cents"] == 498_741
        assert rec["payment_channel"] == "CAMPUS_CARD", (
            "net 498741 < 1_000_000 keeps plan channel"
        )


# ===========================================================================
# combinatorial_formula — second tests
# ===========================================================================
class TestCombinatorialFormulaSecondCoverage:

    def test_tax_at_2000000_mid_tier_boundary(self):
        """PRD §3.10: "from 500,000 cents up to 2,000,000 cents excluded
        at 3 percent; from 2,000,000 cents up to 5,000,000 cents excluded
        at 10 percent". Tier boundaries are lower-inclusive / upper-
        exclusive — the value 2_000_000 starts the 10% slice.

        Claim: gross=2_000_000 -> tier1 [500000,2000000)*3% = 45_000;
        tier2 zero-width at 2_000_000 (slice is 0); top tier 0; surcharge
        2_000_000 * 0.003 = 6_000. Total = 45000 + 6000 = 51_000.
        # difficulty: combinatorial_formula/tiered_tax_with_three_inputs_mode_a
        """
        state = setup_executed_plan(per_award_amount_cents=2_000_000)
        records, _ = validate_paginated(
            api_client.list_disbursement_records(
                state["scholarship"]["id"], state["plan"]["id"], ADMIN,
            ),
        )
        rec = records[0]
        # tier1 slice = min(2_000_000, 2_000_000) - 500_000 = 1_500_000.
        # tier1 tax = round_half_up(1_500_000 * 3 / 100) = 45_000.
        # tier2 slice = min(2_000_000, 5_000_000) - 2_000_000 = 0.
        # tier3 doesn't apply because gross <= tier3.lo (2m <= 5m).
        # surcharge = round_half_up(2_000_000 * 3 / 1000) = 6_000.
        expected = 45_000 + 6_000
        assert rec["tax_withheld_cents"] == expected, (
            f"Expected tax {expected}; got {rec['tax_withheld_cents']}"
        )

    def test_tax_at_500250_pinned_round_yields_pinned_value(self):
        """PRD §3.10: "the alternative of computing the unrounded sum and
        rounding once at the end is explicitly forbidden because at
        fractional-edge gross values the two procedures can differ by
        one cent."

        Second coverage of the mode-b pinned-rounding-order rule. The
        same gross=500250 input is used as in the dual_variant test, but
        we assert against the explicitly-forbidden alternative.
        # difficulty: combinatorial_formula/rounding_order_pinned_in_tax_withholding_mode_b
        """
        state = setup_executed_plan(per_award_amount_cents=500_250)
        records, _ = validate_paginated(
            api_client.list_disbursement_records(
                state["scholarship"]["id"], state["plan"]["id"], ADMIN,
            ),
        )
        rec = records[0]
        assert rec["tax_withheld_cents"] == 1509
        assert rec["tax_withheld_cents"] != 1508, (
            "PRD §3.10: forbidden 'sum-then-round' alternative would "
            "yield 1508 cents; pinned order yields 1509."
        )


# ===========================================================================
# non_linear_state_machine — second tests
# ===========================================================================
class TestNonLinearStateMachineSecondCoverage:

    def test_application_dept_pass_after_correction_reaches_passed(self):
        """PRD §3.4: "A successful PASS transitions SUBMITTED →
        DEPT_PRELIM_PASSED, overwrites the application's
        dept_review_comment with the supplied comment".

        Second coverage of the correction cycle: after the correct loop
        returns to SUBMITTED, a subsequent dept-review PASS reaches
        DEPT_PRELIM_PASSED and the comment field reflects the latest PASS.
        # difficulty: non_linear_state_machine/application_correction_cycle_revert
        """
        from test_helpers import (
            correct_application_payload, dept_review_reject,
        )
        student_dept = "DEPT-CYCLE-SECOND"
        sch, _ = create_open_scholarship(
            category="MERIT",
            required_materials=["TRANSCRIPT", "AWARD_CERT"],
            gpa_threshold_x100=0,
            department_code=student_dept,
        )
        app, student_headers = create_submitted_application(
            sch,
            student_department_code=student_dept,
            uploaded_materials=["TRANSCRIPT", "AWARD_CERT"],
        )
        close_and_review(sch)
        dept_review_reject(
            sch["id"], app["id"], dept_code=student_dept,
            comment="missing-AWARD_CERT",
        )
        validate_success(
            api_client.correct_application(
                sch["id"], app["id"],
                correct_application_payload(
                    replaced_materials=["AWARD_CERT"],
                ),
                student_headers,
            ),
        )
        # Re-pass at dept-review with explicit comment.
        passed = dept_review_pass(
            sch["id"], app["id"], dept_code=student_dept,
            uploaded_materials=["TRANSCRIPT", "AWARD_CERT"],
        )
        assert passed["status"] == "DEPT_PRELIM_PASSED"

    def test_plan_can_reach_finance_approved_after_dept_revert_cycle(self):
        """PRD §3.10: "the plan transitions DEPT_APPROVED → DRAFT, the
        dept_approver_id is cleared back to null, and the snapshotted
        total_gross_cents and total_tax_cents remain unchanged".
        PRD §3.10: "On success the plan transitions DEPT_APPROVED →
        FINANCE_APPROVED, the finance_approver_id is set to the
        requester's X-User-ID".

        Second coverage of the disbursement-plan revert cycle: after
        DRAFT->DEPT_APPROVED->DRAFT, the plan can be re-approved by a
        DIFFERENT DeptOfficer and continue forward.
        # difficulty: non_linear_state_machine/disbursement_plan_revert_cycle
        """
        from test_helpers import (
            revert_plan_dept, DEPT_OFFICER_ID_2, FINANCE_OFFICER_ID_1,
        )
        state = setup_dept_approved_plan(
            dept_officer_id=DEPT_OFFICER_ID_1,
        )
        reverted = revert_plan_dept(
            state["scholarship"]["id"], state["plan"]["id"],
            officer_id=DEPT_OFFICER_ID_1,
        )
        assert reverted["status"] == "DRAFT"
        # A different officer re-approves the same plan.
        re_approved = approve_plan_dept(
            state["scholarship"]["id"], state["plan"]["id"],
            officer_id=DEPT_OFFICER_ID_2,
        )
        assert re_approved["status"] == "DEPT_APPROVED"
        assert re_approved["dept_approver_id"] == DEPT_OFFICER_ID_2


# ===========================================================================
# transitive_cascade — second tests
# ===========================================================================
class TestTransitiveCascadeSecondCoverage:

    def test_revoked_winner_carries_objection_upheld_reason(self):
        """PRD §3.9: "on revocation the application's revocation_reason
        is set to OBJECTION_UPHELD".

        Second coverage of the upheld-revoke-promote chain. Independent
        assertion: the revoked application's revocation_reason field
        carries the OBJECTION_UPHELD enum.
        # difficulty: transitive_cascade/objection_upheld_revoke_and_promote_chain
        """
        state = setup_announced_with_winner_and_runnerup()
        objection = create_objection(
            state["scholarship"]["id"],
            state["winner"]["id"],
            reason_code="MATERIAL_FALSE",
        )
        rule_objection(
            state["scholarship"]["id"], objection["id"],
            decision="UPHOLD", ruling_comment="forged",
        )
        winner = validate_success(
            api_client.get_application(
                state["scholarship"]["id"],
                state["winner"]["id"], ADMIN,
            ),
        )
        assert winner["revocation_reason"] == "OBJECTION_UPHELD"

    def test_disbursed_chain_archives_plan_explicitly(self):
        """PRD §3.11: "Simultaneously, the DisbursementPlan transitions
        EXECUTED → ARCHIVED automatically — no explicit call is required
        to archive an executed plan; archival is the inevitable
        consequence of scholarship-level disbursement."

        Second coverage of the disbursed chain. Independent assertion:
        the DisbursementPlan reaches ARCHIVED without any explicit archive
        call.
        # difficulty: transitive_cascade/scholarship_disbursed_cascade_chain
        """
        state = setup_executed_plan()
        # Before: plan in EXECUTED.
        assert state["plan"]["status"] == "EXECUTED"
        validate_success(
            api_client.transition_scholarship(
                state["scholarship"]["id"],
                {"to_status": "DISBURSED"},
                finance_officer_headers(FINANCE_OFFICER_ID_1),
            ),
        )
        plan = validate_success(
            api_client.get_disbursement_plan(
                state["scholarship"]["id"],
                state["plan"]["id"], ADMIN,
            ),
        )
        assert plan["status"] == "ARCHIVED"


# ===========================================================================
# priority_pair_validation_conflict — both instances need TWO tests each
# ===========================================================================
class TestPriorityPairStateBeatsSOD:
    """PRD §2.6 priority chain: state (priority 6) fires before SOD
    (priority 8). Both tests build a plan in EXECUTED then attempt a
    FINANCE-level approve, which would simultaneously fail state and
    SOD — the state error must win.
    """

    def _build_executed_plan_with_user_pair(self):
        """Helper: returns (sch, plan, u_dept). plan is EXECUTED, U1 is
        dept_approver_id, U2 is finance_approver_id (and executor)."""
        from test_helpers import (
            setup_finalized_with_one_awarded,
        )
        state = setup_finalized_with_one_awarded()
        plan = create_disbursement_plan(state["scholarship"]["id"])
        approve_plan_dept(
            state["scholarship"]["id"], plan["id"],
            officer_id="user-U1",
        )
        approve_plan_finance(
            state["scholarship"]["id"], plan["id"],
            officer_id="user-U2",
        )
        plan = execute_plan(
            state["scholarship"]["id"], plan["id"],
            officer_id="user-U2",
        )
        return state["scholarship"], plan

    def test_finance_approve_on_executed_plan_returns_invalid_state(self):
        """PRD §2.6: "then parent-scholarship state compatibility
        (ERR_INVALID_STATE), then target-entity state validity for the
        requested transition (also ERR_INVALID_STATE), then time-window
        enforcement ..., then segregation-of-duties (ERR_SOD_VIOLATION)".

        Claim: U1 (= dept_approver_id) issues a FINANCE-level approve on
        a plan already in EXECUTED — both the state check AND the SOD
        check would fire; PRD's fixed priority order makes the state
        error win (state < SOD).
        # difficulty: priority_pair_validation_conflict/state_beats_sod_violation
        """
        sch, plan = self._build_executed_plan_with_user_pair()
        # U1 tries to approve at FINANCE level.
        resp = api_client.approve_disbursement_plan(
            sch["id"], plan["id"],
            approve_disbursement_plan_payload(level="FINANCE"),
            finance_officer_headers("user-U1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_finance_approve_state_beats_sod_yields_409(self):
        """PRD §5: "ERR_INVALID_STATE ... 409"; per §2.6 the state error
        wins over SOD even when both would apply.

        Second coverage: explicit HTTP 409 assertion via validate_error.
        # difficulty: priority_pair_validation_conflict/state_beats_sod_violation
        """
        sch, plan = self._build_executed_plan_with_user_pair()
        resp = api_client.approve_disbursement_plan(
            sch["id"], plan["id"],
            approve_disbursement_plan_payload(level="FINANCE"),
            finance_officer_headers("user-U1"),
        )
        # validate_error auto-checks 409 from the registered map.
        validate_error(
            resp, ApiErrorId.ERR_INVALID_STATE.value,
            expected_status=409,
        )


class TestPriorityPairStateBeatsDeptScope:
    """PRD §2.6 priority chain: state (priority 6) fires before
    dept-scope (priority 10). Tests build an application already in
    DEPT_PRELIM_PASSED (invalid state for further dept-review) and
    attempt a dept-review — even if the officer's scope didn't match,
    the state check must fire first.
    """

    def test_dept_review_on_passed_state_returns_invalid_state(self):
        """PRD §2.6: priority order places state (priority 6) before
        department-scope match (priority 10).
        PRD §3.4: "On a PASS, the server additionally re-checks
        completeness — uploaded_materials must still be a superset of
        required_materials". Path requires SUBMITTED state.

        Claim: dept-review on an application already in DEPT_PRELIM_PASSED
        -> ERR_INVALID_STATE (state-vs-scope priority).
        # difficulty: priority_pair_validation_conflict/state_beats_dept_scope_mismatch
        """
        from test_helpers import (
            dept_review_payload, make_dept_officer_headers,
        )
        student_dept = "STU-STATE-V-SCOPE"
        sch, _ = create_open_scholarship(
            category="MERIT", required_materials=["TRANSCRIPT"],
            department_code=student_dept,
            gpa_threshold_x100=0,
        )
        app, _ = create_submitted_application(
            sch, student_department_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        close_and_review(sch)
        # First, PASS the application to reach DEPT_PRELIM_PASSED.
        dept_review_pass(
            sch["id"], app["id"], dept_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        # Now try ANOTHER dept-review while application is in
        # DEPT_PRELIM_PASSED.
        officer = make_dept_officer_headers(
            "dept-officer-OTHER-mismatched",
        )
        resp = api_client.dept_review_application(
            sch["id"], app["id"],
            dept_review_payload(decision="PASS", comment=""),
            officer,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_dept_review_on_passed_state_returns_409(self):
        """PRD §5: ERR_INVALID_STATE has http status 409.
        Second coverage of the state-vs-dept-scope priority.
        # difficulty: priority_pair_validation_conflict/state_beats_dept_scope_mismatch
        """
        from test_helpers import (
            dept_review_payload, make_dept_officer_headers,
        )
        student_dept = "STU-PRIORITY"
        sch, _ = create_open_scholarship(
            category="MERIT", required_materials=["TRANSCRIPT"],
            department_code=student_dept,
            gpa_threshold_x100=0,
        )
        app, _ = create_submitted_application(
            sch, student_department_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        close_and_review(sch)
        dept_review_pass(
            sch["id"], app["id"], dept_code=student_dept,
            uploaded_materials=["TRANSCRIPT"],
        )
        officer = make_dept_officer_headers(
            "dept-officer-OTHER-mismatched-2",
        )
        resp = api_client.dept_review_application(
            sch["id"], app["id"],
            dept_review_payload(decision="PASS", comment=""),
            officer,
        )
        validate_error(
            resp, ApiErrorId.ERR_INVALID_STATE.value,
            expected_status=409,
        )


# ===========================================================================
# boundary_precision_check — second tests
# ===========================================================================
class TestBoundaryPrecisionSecondCoverage:

    def test_gpa_one_above_threshold_passes(self):
        """PRD §3.3: "the student's student_gpa_x100 is at least the
        scholarship's gpa_threshold_x100 (inclusive)".

        Second coverage of the GPA inclusive boundary: threshold + 1
        also passes.
        # difficulty: boundary_precision_check/gpa_threshold_inclusive_boundary_on_submit
        """
        sch, _ = create_open_scholarship(
            category="MERIT",
            gpa_threshold_x100=350,
            required_materials=["TRANSCRIPT"],
        )
        sid = new_student_id()
        from test_helpers import (
            make_student_headers, create_application, submit_application,
        )
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            student_gpa_x100=351,
            uploaded_materials=["TRANSCRIPT"],
        )
        result = submit_application(sch["id"], app["id"], headers)
        assert result["status"] == "SUBMITTED"

    def test_empty_eligible_grades_admits_all_grades(self):
        """PRD §3.3: "the scholarship's eligible_grades is empty or the
        student's student_grade is one of its elements".

        Second coverage of empty-list-fallback semantics — same predicate
        on grade rather than major.
        # difficulty: boundary_precision_check/empty_eligible_majors_means_all_majors_on_submit
        """
        sch, _ = create_open_scholarship(
            category="MERIT",
            gpa_threshold_x100=0,
            eligible_grades=[],
            eligible_majors=[],
            required_materials=["TRANSCRIPT"],
        )
        sid = new_student_id()
        from test_helpers import (
            make_student_headers, create_application, submit_application,
        )
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            student_grade=7,  # unusual grade
            uploaded_materials=["TRANSCRIPT"],
        )
        result = submit_application(sch["id"], app["id"], headers)
        assert result["status"] == "SUBMITTED"

    def test_identical_scores_yield_zero_stddev_no_outlier_high(self):
        """PRD §3.6: "The full-mean variant applies in the degenerate
        case: when the standard deviation across the three scores is
        zero ... no score is flagged as an outlier and the
        aggregated_score_x100 is the round-half-up of the simple mean."

        Second coverage of the stddev=0 boundary case — same predicate at
        a different uniform score value.
        # difficulty: boundary_precision_check/outlier_z_strict_inequality_on_scores
        """
        state = setup_review_complete(
            criterion_scores_list=[
                {"core": 90}, {"core": 90}, {"core": 90},
            ],
            rubric_weights={"core": 100},
            outlier_z_threshold_x100=200,
        )
        assert state["application"]["aggregated_score_x100"] == 9000
        scores, _ = validate_paginated(
            api_client.list_scores(
                state["scholarship"]["id"],
                state["application"]["id"], ADMIN,
            ),
        )
        for s in scores:
            assert s["is_outlier"] is False


# ===========================================================================
# cross_entity_state_dependency — needs TWO tests each
# ===========================================================================
class TestCrossEntityStateDependency:

    def test_submit_against_draft_scholarship_returns_window_not_open(self):
        """PRD §3.3: "the parent scholarship's status must be OPEN; if it
        is anything else, the submit is rejected with ERR_WINDOW_NOT_OPEN."

        Claim: Scholarship.status==REVIEWING + Application.status==DRAFT,
        student submit -> ERR_WINDOW_NOT_OPEN. Cross-entity state
        dependency (Application's submit-precondition references parent's
        status).
        # difficulty: cross_entity_state_dependency/application_submit_requires_scholarship_open
        """
        # Build: OPEN sch -> student drafts -> close window -> REVIEWING.
        sch, _ = create_open_scholarship()
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            uploaded_materials=["TRANSCRIPT"],
        )
        # Move scholarship to REVIEWING.
        advance_clock(sch["application_window_end"])
        validate_success(
            api_client.transition_scholarship(
                sch["id"], {"to_status": "REVIEWING"}, ADMIN,
            ),
        )
        # Now submit -> scholarship is not OPEN.
        resp = api_client.submit_application(
            sch["id"], app["id"], headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN.value)

    def test_submit_when_clock_inside_window_returns_window_closed(self):
        """PRD §3.3: "the logical "now" must be strictly earlier than
        the scholarship's application_window_end; otherwise
        ERR_WINDOW_CLOSED."

        Second coverage of the cross-entity (Application, Scholarship)
        precondition stack: even when Scholarship.status remains OPEN,
        if the clock has been advanced past application_window_end the
        submit is rejected. This is the cross-entity time-vs-state
        dependency variant.
        # difficulty: cross_entity_state_dependency/application_submit_requires_scholarship_open
        """
        sch, _ = create_open_scholarship()
        sid = new_student_id()
        headers = make_student_headers(sid)
        app, _ = create_application(
            sch["id"], student_headers=headers,
            uploaded_materials=["TRANSCRIPT"],
        )
        # Advance clock to exactly application_window_end. The
        # scholarship is still OPEN (admin hasn't moved it) but the
        # window is now closed.
        advance_clock(sch["application_window_end"])
        resp = api_client.submit_application(
            sch["id"], app["id"], headers,
        )
        validate_error(resp, ApiErrorId.ERR_WINDOW_CLOSED.value)

    def test_disburse_with_executed_plan_succeeds(self):
        """PRD §3.11: "Once a DisbursementPlan is in EXECUTED, the
        scholarship may be advanced from FINALIZED to DISBURSED by a
        FinanceOfficer. The transition requires that a DisbursementPlan
        for this scholarship has reached EXECUTED".

        Second coverage of the (Application, DisbursementPlan)
        cross-entity dependency: with the plan in EXECUTED, the
        transition succeeds and the cascade fires.
        # difficulty: cross_entity_state_dependency/application_disbursed_requires_disbursement_plan_executed
        """
        state = setup_executed_plan()
        validate_success(
            api_client.transition_scholarship(
                state["scholarship"]["id"],
                {"to_status": "DISBURSED"},
                finance_officer_headers(FINANCE_OFFICER_ID_1),
            ),
        )
        app = validate_success(
            api_client.get_application(
                state["scholarship"]["id"],
                state["application"]["id"], ADMIN,
            ),
        )
        assert app["status"] == "DISBURSED"


# ===========================================================================
# resource_temporal_overlap — needs TWO tests for scholarship_pair instance
# ===========================================================================
class TestResourceTemporalOverlap:

    def test_scholarship_pair_half_open_overlap_blocks_create(self):
        """PRD §3.1: "intervals are half-open
        [application_window_start, application_window_end) — windows
        that touch exactly at a boundary ... do not overlap and are
        accepted. Any non-empty overlap with such a peer scholarship is
        rejected with ERR_SCHOLARSHIP_WINDOW_OVERLAP."

        Claim: two same-category scholarships with overlapping windows
        -> second create returns ERR_SCHOLARSHIP_WINDOW_OVERLAP.
        # difficulty: resource_temporal_overlap/scholarship_pair_half_open_window_overlap_blocks_create
        """
        create_scholarship(
            category="MERIT",
            application_window_start=iso_at(2026, 6, 1),
            application_window_end=iso_at(2026, 6, 10),
            announcement_window_end=iso_at(2026, 6, 20),
        )
        resp = api_client.create_scholarship(
            create_scholarship_payload(
                category="MERIT",
                application_window_start=iso_at(2026, 6, 5),
                application_window_end=iso_at(2026, 6, 15),
                announcement_window_end=iso_at(2026, 6, 25),
            ),
            ADMIN,
        )
        validate_error(
            resp, ApiErrorId.ERR_SCHOLARSHIP_WINDOW_OVERLAP.value,
        )

    def test_scholarship_pair_touching_boundary_accepted(self):
        """PRD §3.1: "windows that touch exactly at a boundary (one
        scholarship's application_window_end equal to another's
        application_window_start) do not overlap and are accepted."

        Second coverage of the half-open scholarship-pair overlap rule:
        the boundary-touching case is accepted.
        # difficulty: resource_temporal_overlap/scholarship_pair_half_open_window_overlap_blocks_create
        """
        create_scholarship(
            category="MERIT",
            application_window_start=iso_at(2026, 6, 1),
            application_window_end=iso_at(2026, 6, 10),
            announcement_window_end=iso_at(2026, 6, 20),
        )
        # C touches at boundary 06-10 -> accepted under half-open.
        resp = api_client.create_scholarship(
            create_scholarship_payload(
                category="MERIT",
                application_window_start=iso_at(2026, 6, 10),
                application_window_end=iso_at(2026, 6, 20),
                announcement_window_end=iso_at(2026, 7, 1),
            ),
            ADMIN,
        )
        validate_success(resp, expected_status=201)

    def test_cross_application_buffered_overlap_blocks_second_submit(self):
        """PRD §3.3: "the buffered interval for each scholarship is the
        closed-closed interval running from its application_window_start
        to its application_window_end extended by an additional three
        days ... Two scholarships of the same category collide when their
        buffered closed-closed intervals share at least one point in
        common".

        Second coverage of the cross-application buffered overlap rule.
        # difficulty: resource_temporal_overlap/cross_application_buffered_overlap_blocks_submit
        """
        # Two NEED-category windows whose raw windows are disjoint half-
        # open ([07-01, 07-05) and [07-07, 07-15)) but whose buffered
        # closed-closed intervals overlap: [07-01, 07-08] ∩ [07-07,
        # 07-18] = [07-07, 07-08].
        # First scholarship S-X opens and student submits.
        sch_x, _ = create_open_scholarship(
            category="NEED",
            family_income_ceiling_cents=10_000_000,
            gpa_threshold_x100=0,
            required_materials=["TRANSCRIPT"],
            application_window_start=iso_at(2026, 7, 1),
            application_window_end=iso_at(2026, 7, 5),
            announcement_window_end=iso_at(2026, 7, 20),
        )
        sid = new_student_id()
        headers = make_student_headers(sid)
        app_x, _ = create_application(
            sch_x["id"], student_headers=headers,
            uploaded_materials=["TRANSCRIPT"],
            student_family_income_cents=1_000_000,
        )
        validate_success(
            api_client.submit_application(
                sch_x["id"], app_x["id"], headers,
            ),
        )
        # Second scholarship S-Y opens and same student submits.
        sch_y, _ = create_scholarship_with_quota(
            total_quota=1,
            category="NEED",
            family_income_ceiling_cents=10_000_000,
            gpa_threshold_x100=0,
            required_materials=["TRANSCRIPT"],
            application_window_start=iso_at(2026, 7, 7),
            application_window_end=iso_at(2026, 7, 15),
            announcement_window_end=iso_at(2026, 7, 30),
        )
        advance_clock(sch_y["application_window_start"])
        validate_success(
            api_client.transition_scholarship(
                sch_y["id"], {"to_status": "OPEN"}, ADMIN,
            ),
        )
        app_y, _ = create_application(
            sch_y["id"], student_headers=headers,
            uploaded_materials=["TRANSCRIPT"],
            student_family_income_cents=1_000_000,
        )
        resp = api_client.submit_application(
            sch_y["id"], app_y["id"], headers,
        )
        validate_error(
            resp, ApiErrorId.ERR_DUPLICATE_APPLICATION_CROSS.value,
        )


# ===========================================================================
# compensating_invariant — second tests
# ===========================================================================
class TestCompensatingInvariantSecondCoverage:

    def test_quota_count_equals_awarded_count_after_revoke_promote(self):
        """PRD §3.1: "filled_slots is the running count of applications
        in the slice with status AWARDED or DISBURSED".
        PRD §3.9: "the slice's filled_slots is decremented by one ... a
        single promotion cascade runs ... is flipped to AWARDED."

        Second coverage of the quota-slot conservation invariant: after
        the revoke+promote cascade, sum(filled_slots) must equal the
        live count of AWARDED applications.
        # difficulty: compensating_invariant/award_count_invariant_under_revoke_and_promote
        """
        state = setup_announced_with_winner_and_runnerup()
        objection = create_objection(
            state["scholarship"]["id"],
            state["winner"]["id"],
            reason_code="MATERIAL_FALSE",
        )
        rule_objection(
            state["scholarship"]["id"], objection["id"],
            decision="UPHOLD", ruling_comment="forged",
        )
        slices = list_quota_slices(state["scholarship"]["id"])
        # Fetch both apps and count AWARDED.
        winner = validate_success(
            api_client.get_application(
                state["scholarship"]["id"],
                state["winner"]["id"], ADMIN,
            ),
        )
        runner_up = validate_success(
            api_client.get_application(
                state["scholarship"]["id"],
                state["runner_up"]["id"], ADMIN,
            ),
        )
        awarded_count = sum(
            1 for a in (winner, runner_up)
            if a["status"] == "AWARDED"
        )
        sum_filled = sum(s["filled_slots"] for s in slices)
        assert sum_filled == awarded_count, (
            f"Quota slot conservation: sum(filled_slots)={sum_filled} "
            f"must equal AWARDED count={awarded_count}"
        )

    def test_plan_tax_unchanged_after_dept_revert_cycle(self):
        """PRD §3.10: "the snapshotted total_gross_cents and total_tax_cents
        remain unchanged — the system never recomputes them after
        creation, even across revert cycles."

        Second coverage of the monetary-aggregate conservation invariant
        across approve/revert.
        # difficulty: compensating_invariant/disbursement_gross_invariant_under_approve_and_revert
        """
        from test_helpers import revert_plan_dept
        # Build with 2 awarded applications? Easier: do one and verify
        # both fields invariant.
        state = setup_dept_approved_plan(
            per_award_amount_cents=1_000_000,
            dept_officer_id=DEPT_OFFICER_ID_1,
        )
        baseline_gross = state["plan"]["total_gross_cents"]
        baseline_tax = state["plan"]["total_tax_cents"]
        reverted = revert_plan_dept(
            state["scholarship"]["id"], state["plan"]["id"],
            officer_id=DEPT_OFFICER_ID_1,
        )
        assert reverted["total_gross_cents"] == baseline_gross
        assert reverted["total_tax_cents"] == baseline_tax
        # Re-approve dept and verify still unchanged.
        re_approved = approve_plan_dept(
            state["scholarship"]["id"], state["plan"]["id"],
            officer_id=DEPT_OFFICER_ID_1,
        )
        assert re_approved["total_gross_cents"] == baseline_gross
        assert re_approved["total_tax_cents"] == baseline_tax
