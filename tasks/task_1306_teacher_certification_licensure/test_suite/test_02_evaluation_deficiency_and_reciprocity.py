"""Evaluation gates, deficiency computation, deficiency plans, GPA and test
score scaling, and reciprocity mapping."""
import pytest

from test_helpers import (
    EVALUATOR,
    INTAKE,
    NON_EXISTENT_UUID,
    PAO,
    ApiErrorId,
    add_and_verify_transcript,
    add_transcript,
    advance_application,
    api_client,
    create_and_finalize_reciprocity,
    create_application,
    create_approved_program,
    create_deficiency_plan,
    create_program_payload,
    issue_emergency_permit,
    num,
    open_and_submit_background_check,
    pay_application_fee,
    post_plan_evidence,
    register_applicant,
    report_and_verify_score,
    report_test_score,
    setup_deficiency_pending_application,
    setup_paid_application_in_intake,
    setup_reciprocity_full_in_evaluation,
    transition_plan,
    validate_error,
    validate_success,
    verify_test_score,
    verify_transcript,
    withdraw_application,
)


class TestProgramAndReciprocityGates:

    def test_unapproved_program_blocks_evaluation(self):
        """PRD section 3.1: "For a `TRADITIONAL` application this second gate
        re-verifies that `program_id` is present (else
        `ERR_PATHWAY_PROGRAM_REQUIRED`), that the named program's
        `approval_status` is `APPROVED`, and that the application's
        `subject_area` appears in the program's `approved_subject_areas` — a
        failure of either program condition yields `ERR_PROGRAM_NOT_APPROVED`."

        Design: Corner/validations/unapproved_program_blocks_evaluation
        """
        resp = api_client.create_program(
            create_program_payload(institution_name="New College",
                                   program_code="NC-MATH",
                                   approved_subject_areas=["MATHEMATICS"]),
            PAO)
        program = validate_success(resp, expected_status=201)
        resp = api_client.transition_program(
            program["id"], {"to_status": "UNDER_REVIEW"}, PAO)
        validate_success(resp)
        applicant = register_applicant(full_name="Tom To", email="tom@x.com")
        app = create_application(applicant["id"], pathway="TRADITIONAL",
                                 subject_area="MATHEMATICS", grade_band="G7_12",
                                 program_id=program["id"])
        pay_application_fee(app["id"], applicant["id"])
        advance_application(app["id"], "INTAKE_REVIEW", INTAKE)
        resp = api_client.transition_application(
            app["id"], {"to_status": "EVALUATION"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_PROGRAM_NOT_APPROVED)

    def test_unfinalized_reciprocity_blocks_evaluation(self):
        """PRD section 3.1: "For a `RECIPROCITY` application the gate instead
        requires a finalized reciprocity evaluation whose `outcome` is not
        `DENIED` (else `ERR_RECIPROCITY_NOT_FINALIZED`)."

        Design: Corner/validations/unfinalized_reciprocity_blocks_evaluation
        """
        applicant = register_applicant(full_name="Urs Ur", email="urs@x.com")
        app = setup_paid_application_in_intake(applicant, pathway="RECIPROCITY",
                                               subject_area="MATHEMATICS")
        resp = api_client.transition_application(
            app["id"], {"to_status": "EVALUATION"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_RECIPROCITY_NOT_FINALIZED)


class TestEvaluationAdvanceGates:

    def test_evaluation_advance_without_transcripts_rejected(self):
        """PRD section 3.7: "Four preconditions guard the move, evaluated in
        the fixed inner order of §2.5: at least one transcript exists for the
        application and every transcript's `verification_status` is `VERIFIED`
        (else `ERR_TRANSCRIPTS_UNVERIFIED`)"
        PRD section 3.3: "A `RECIPROCITY` application requires nothing when
        its finalized outcome is `FULL`, and requires a verified passing
        `PRAXIS_SUBJECT` score otherwise."

        Design: Corner/validations/evaluation_advance_without_transcripts_rejected
        """
        applicant = register_applicant(full_name="Yan Ya", email="yan@x.com")
        app = setup_paid_application_in_intake(applicant, pathway="RECIPROCITY",
                                               subject_area="MATHEMATICS")
        create_and_finalize_reciprocity(app["id"])
        advance_application(app["id"], "EVALUATION", INTAKE)
        resp = api_client.transition_application(
            app["id"], {"to_status": "BACKGROUND_REVIEW"}, EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_TRANSCRIPTS_UNVERIFIED)

    def test_evaluation_advance_without_exams_rejected(self):
        """PRD section 3.7: "every exam the pathway requires — per the rules
        of §3.3 — has a `VERIFIED` test score with `passing` true (else
        `ERR_EXAM_REQUIREMENT_UNMET`)"
        PRD section 3.3: "`TRADITIONAL` and `ALTERNATIVE` applications each
        require a verified passing score on both `PRAXIS_SUBJECT` and
        `PEDAGOGY`."

        Design: Corner/validations/evaluation_advance_without_exams_rejected
        """
        program = create_approved_program(
            approved_subject_areas=["MATHEMATICS"],
            institution_name="State Teachers College", program_code="STC-MATH")
        applicant = register_applicant(full_name="Zeb Ze", email="zeb@x.com")
        app = create_application(applicant["id"], pathway="TRADITIONAL",
                                 subject_area="MATHEMATICS", grade_band="G7_12",
                                 program_id=program["id"])
        pay_application_fee(app["id"], applicant["id"])
        advance_application(app["id"], "INTAKE_REVIEW", INTAKE)
        add_and_verify_transcript(app["id"], applicant["id"],
                                  subject_relevant_hours=18,
                                  institution_name="STC")
        advance_application(app["id"], "EVALUATION", INTAKE)
        resp = api_client.transition_application(
            app["id"], {"to_status": "BACKGROUND_REVIEW"}, EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_EXAM_REQUIREMENT_UNMET)

    def test_evaluation_advance_with_deficiency_rejected(self):
        """PRD section 3.7: "`deficiency_hours_required` is zero (else
        `ERR_DEFICIENCY_OUTSTANDING`)"
        PRD section 2.5: "Within this final stage, ties break in a fixed inner
        order: transcripts verified first (`ERR_TRANSCRIPTS_UNVERIFIED`), then
        required exams passed (`ERR_EXAM_REQUIREMENT_UNMET`), then deficiency
        cleared (`ERR_DEFICIENCY_OUTSTANDING`), then background cleared
        (`ERR_BACKGROUND_NOT_CLEARED`)"

        Design: Corner/validations/evaluation_advance_with_deficiency_rejected
        """
        applicant = register_applicant(full_name="Xio Xi", email="xio@x.com")
        app = create_application(applicant["id"], pathway="ALTERNATIVE",
                                 subject_area="SCIENCE", grade_band="G5_8")
        pay_application_fee(app["id"], applicant["id"])
        advance_application(app["id"], "INTAKE_REVIEW", INTAKE)
        advance_application(app["id"], "EVALUATION", INTAKE)
        add_and_verify_transcript(app["id"], applicant["id"],
                                  subject_relevant_hours=18,
                                  institution_name="Night School",
                                  total_semester_hours=90,
                                  courses=[{"course_code": "BIO101",
                                            "credit_hours": 4,
                                            "letter_grade": "B"}])
        report_and_verify_score(app["id"], applicant["id"], "PRAXIS_SUBJECT",
                                60, tested_on="2026-07-01T00:00:00Z")
        report_and_verify_score(app["id"], applicant["id"], "PEDAGOGY", 30,
                                tested_on="2026-07-02T00:00:00Z")
        resp = api_client.transition_application(
            app["id"], {"to_status": "BACKGROUND_REVIEW"}, EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_DEFICIENCY_OUTSTANDING)
        fetched = validate_success(api_client.get_application(app["id"], EVALUATOR))
        # recognized min(18,18)=18; gap 30-18=12; exams passing so no penalty;
        # ALTERNATIVE addon 6 -> 18.
        assert fetched["deficiency_hours_required"] == 18


class TestDeficiencyComputation:

    def test_deficiency_combines_cap_penalty_addon_with_clamp(self):
        """PRD section 3.4: "First, recognized subject hours are the sum of
        `subject_relevant_hours` across the application's `VERIFIED`
        transcripts, capped at 18 — the recognized figure is the lesser of
        that sum and 18."
        PRD section 3.4: "Third, a test-gap penalty of 6 hours applies
        whenever any required exam lacks a verified passing score, and a
        pathway addon of 6 hours applies when the pathway is `ALTERNATIVE`."
        PRD section 3.4: "The resulting `deficiency_hours_required` is the
        lesser of 30 and the sum of subject gap, test-gap penalty, and pathway
        addon."

        Design: Difficulty/combinatorial_formula/deficiency_computation_multi_input_clamp
        """
        applicant = register_applicant(full_name="Dee Di", email="dee@x.com")
        app = create_application(applicant["id"], pathway="ALTERNATIVE",
                                 subject_area="SCIENCE", grade_band="G5_8")
        pay_application_fee(app["id"], applicant["id"])
        advance_application(app["id"], "INTAKE_REVIEW", INTAKE)
        add_and_verify_transcript(app["id"], applicant["id"],
                                  subject_relevant_hours=20,
                                  institution_name="City College",
                                  total_semester_hours=100,
                                  courses=[{"course_code": "BIO101",
                                            "credit_hours": 4,
                                            "letter_grade": "B"}])
        updated = advance_application(app["id"], "EVALUATION", INTAKE)
        # min(20, 18) = 18 recognized; gap 30-18 = 12; test-gap 6; addon 6;
        # min(30, 24) = 24.
        assert updated["deficiency_hours_required"] == 24

    def test_deficiency_recomputed_at_transcript_verification(self):
        """PRD section 3.4: "The deficiency computation runs at three moments:
        when an application crosses from `INTAKE_REVIEW` to `EVALUATION`,
        whenever a transcript is verified, and whenever a test score is
        verified."

        Design: Difficulty/combinatorial_formula/deficiency_computation_multi_input_clamp
        """
        applicant = register_applicant(full_name="Dee Dj", email="deej@x.com")
        app = create_application(applicant["id"], pathway="ALTERNATIVE",
                                 subject_area="SCIENCE", grade_band="G5_8")
        pay_application_fee(app["id"], applicant["id"])
        advance_application(app["id"], "INTAKE_REVIEW", INTAKE)
        add_and_verify_transcript(app["id"], applicant["id"],
                                  subject_relevant_hours=20)
        fetched = validate_success(api_client.get_application(app["id"], EVALUATOR))
        assert fetched["deficiency_hours_required"] == 24, (
            "transcript verification must recompute deficiency hours in place")


class TestCourseworkGpaRounding:

    def test_gpa_rounds_per_course_before_summing(self):
        """PRD section 3.3: "Verifying it runs the coursework GPA scaling,
        whose rounding order is pinned: each course is rounded first, then the
        results are summed."
        PRD section 3.3: "The transcript's `scaled_gpa` is then the sum of
        those per-course quality points divided by the sum of all
        `credit_hours`, the quotient rounded half-up to two decimal places."

        Design: Difficulty/combinatorial_formula/gpa_per_course_rounding_order
        """
        applicant = register_applicant(full_name="Eli El", email="eli@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="MATHEMATICS", grade_band="G7_12")
        transcript = add_transcript(
            app["id"], applicant["id"], institution_name="State U",
            degree_level="MASTERS", total_semester_hours=30,
            courses=[
                {"course_code": "MATH510", "credit_hours": 0.75,
                 "letter_grade": "A_MINUS"},
                {"course_code": "MATH511", "credit_hours": 0.75,
                 "letter_grade": "A_MINUS"},
            ])
        verified = verify_transcript(transcript["id"], 1.5)
        # per course round_half_up(0.75 * 3.7, 2) = 2.78; sum 5.56;
        # gpa = round_half_up(5.56 / 1.5, 2) = 3.71 (sum-then-round gives 3.70).
        assert num(verified["scaled_gpa"]) == pytest.approx(3.71, abs=1e-9)

    def test_gpa_single_fractional_course_pins_rounding_order(self):
        """PRD section 3.3: "For every course, the quality points are the
        course's `credit_hours` multiplied by the grade points of its
        `letter_grade` — 4.0 for `A`, 3.7 for `A_MINUS`, 3.0 for `B`, 2.0 for
        `C`, 1.0 for `D`, and 0.0 for `F` — with each course's product rounded
        half-up to two decimal places."
        PRD section 3.3: "(Summing unrounded products and rounding once at
        the end yields different results and is expressly not the algorithm.)"

        Design: Difficulty/combinatorial_formula/gpa_per_course_rounding_order
        """
        applicant = register_applicant(full_name="Eli Em", email="elim@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="MATHEMATICS", grade_band="G7_12")
        transcript = add_transcript(
            app["id"], applicant["id"], institution_name="State U",
            degree_level="MASTERS", total_semester_hours=30,
            courses=[{"course_code": "MATH520", "credit_hours": 0.75,
                      "letter_grade": "A_MINUS"}])
        verified = verify_transcript(transcript["id"], 0.75)
        # per course: round_half_up(2.775, 2) = 2.78; gpa = 2.78/0.75 = 3.71.
        # Forbidden order: 2.775/0.75 -> 3.70.
        assert num(verified["scaled_gpa"]) == pytest.approx(3.71, abs=1e-9)


class TestTestScoreScaling:

    def test_scaled_score_exactly_at_threshold_passes(self):
        """PRD section 3.3: "for `PRAXIS_SUBJECT` it is 100 plus the raw score
        times 1, with at least 157 passing"
        PRD section 3.3: "The comparison is inclusive — a scaled score exactly
        equal to the threshold passes — and the boolean outcome is stored in
        `passing`."

        Design: Difficulty/boundary_precision_check/scaled_score_exactly_at_threshold_passes
        """
        applicant = register_applicant(full_name="Lee Le", email="lee@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="MATHEMATICS", grade_band="G7_12")
        score = report_test_score(app["id"], applicant["id"], "PRAXIS_SUBJECT",
                                  57)
        verified = verify_test_score(score["id"])
        assert verified["scaled_score"] == 157
        assert verified["passing"] is True

    def test_scaled_score_one_below_threshold_fails(self):
        """PRD section 3.3: "for `PRAXIS_SUBJECT` it is 100 plus the raw score
        times 1, with at least 157 passing"
        PRD section 3.3: "The comparison is inclusive — a scaled score exactly
        equal to the threshold passes — and the boolean outcome is stored in
        `passing`."

        Design: Difficulty/boundary_precision_check/scaled_score_exactly_at_threshold_passes
        """
        applicant = register_applicant(full_name="Lee Li", email="leeli@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="MATHEMATICS", grade_band="G7_12")
        score = report_test_score(app["id"], applicant["id"], "PRAXIS_SUBJECT",
                                  56)
        verified = verify_test_score(score["id"])
        assert verified["scaled_score"] == 156
        assert verified["passing"] is False

    def test_double_verify_test_score_rejected(self):
        """PRD section 2.5: "The target entity must be in a state from which
        the requested transition exists, and terminal states reject every
        transition, else `ERR_INVALID_STATE`."
        PRD section 3.3: "the report lands with `verification_status` of
        `REPORTED`."

        Design: Corner/state_machines/double_verify_test_score_rejected
        """
        applicant = register_applicant(full_name="Amy Am", email="amy@x.com")
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="MATHEMATICS", grade_band="G7_12")
        score = report_test_score(app["id"], applicant["id"], "PRAXIS_SUBJECT",
                                  60)
        verified = verify_test_score(score["id"])
        assert verified["scaled_score"] == 160
        resp = api_client.verify_test_score(
            score["id"], {"verification_status": "VERIFIED"}, EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        fetched = validate_success(api_client.get_test_score(score["id"], EVALUATOR))
        assert fetched["scaled_score"] == 160


class TestReciprocityMappingVariants:

    def _open_fl_professional_evaluation(self, full_name, email):
        applicant = register_applicant(full_name=full_name, email=email)
        app = create_application(applicant["id"], pathway="RECIPROCITY",
                                 subject_area="SCIENCE", grade_band="G7_12")
        resp = api_client.create_reciprocity_evaluation(
            app["id"],
            {"source_state": "FL", "source_license_type": "PROFESSIONAL",
             "years_teaching": 5},
            EVALUATOR)
        return validate_success(resp, expected_status=201)

    def test_deterministic_mapping_keeps_table_result(self):
        """PRD section 3.5: "a `PROFESSIONAL` license from Florida maps to
        `PARTIAL` with 6 deficiency hours"
        PRD section 3.5: "Under `DETERMINISTIC`, the table result stands and
        `years_teaching` is ignored."

        Design: Difficulty/dual_variant_calc/reciprocity_deterministic_vs_committee_mapping
        """
        evaluation = self._open_fl_professional_evaluation("Boa Bo", "boa@x.com")
        resp = api_client.finalize_reciprocity_evaluation(
            evaluation["id"], {"mapping_mode": "DETERMINISTIC"}, EVALUATOR)
        finalized = validate_success(resp)
        assert finalized["outcome"] == "PARTIAL"
        assert finalized["deficiency_subject_hours"] == 6
        assert finalized["finalized"] is True

    def test_committee_mapping_applies_experience_upgrade(self):
        """PRD section 3.5: "Under `COMMITTEE`, an applicant with at least 3
        years of teaching earns a one-level upgrade applied to the table
        result: a table `DENIED` becomes `PARTIAL` with 12 deficiency hours;
        a table `PARTIAL` becomes `FULL` with its deficiency hours reduced by
        6, never below zero; and a table `FULL` is unchanged."

        Design: Difficulty/dual_variant_calc/reciprocity_deterministic_vs_committee_mapping
        """
        evaluation = self._open_fl_professional_evaluation("Cal Co", "cal@x.com")
        resp = api_client.finalize_reciprocity_evaluation(
            evaluation["id"], {"mapping_mode": "COMMITTEE"}, EVALUATOR)
        finalized = validate_success(resp)
        assert finalized["outcome"] == "FULL"
        assert finalized["deficiency_subject_hours"] == 0


class TestDeficiencyCycle:

    def test_deficiency_cycle_reentry_clears_hours(self):
        """PRD section 3.4: "The moment `completed_hours` reaches or exceeds
        `required_hours`, the plan completes automatically to `COMPLETED`, and
        the linked application becomes eligible to return from
        `DEFICIENCY_PENDING` to `EVALUATION`."
        PRD section 3.4: "That return, executed by the evaluator, requires a
        `COMPLETED` plan for the application (else
        `ERR_DEFICIENCY_OUTSTANDING`); it zeroes `deficiency_hours_required` —
        the plan is satisfied — and increments the application's `version`."

        Design: Difficulty/non_linear_state_machine/application_deficiency_cycle_reentry
        """
        ctx = setup_deficiency_pending_application(
            full_name="Fay Fa", email="fay@x.com")
        app = ctx["application"]
        assert app["deficiency_hours_required"] == 30
        plan = create_deficiency_plan(app["id"], app["version"])
        assert plan["required_hours"] == 30
        transition_plan(plan["id"], "ACCEPTED")
        completed = post_plan_evidence(plan["id"], 30)
        assert completed["status"] == "COMPLETED"
        returned = advance_application(app["id"], "EVALUATION", EVALUATOR)
        assert returned["status"] == "EVALUATION"
        assert returned["deficiency_hours_required"] == 0

    def test_deficiency_cycle_completes_at_exact_required_hours_in_steps(self):
        """PRD section 3.4: "The moment `completed_hours` reaches or exceeds
        `required_hours`, the plan completes automatically to `COMPLETED`, and
        the linked application becomes eligible to return from
        `DEFICIENCY_PENDING` to `EVALUATION`."
        PRD section 3.4: "The first posting against an `ACCEPTED` plan moves
        it to `IN_PROGRESS`, and each posting — against an `IN_PROGRESS` plan
        or an `EXTENDED` one — adds its `hours` to `completed_hours`."

        Design: Difficulty/non_linear_state_machine/application_deficiency_cycle_reentry
        """
        ctx = setup_deficiency_pending_application(
            full_name="Fay Fb", email="fayfb@x.com")
        app = ctx["application"]
        plan = create_deficiency_plan(app["id"], app["version"])
        transition_plan(plan["id"], "ACCEPTED")
        in_progress = post_plan_evidence(plan["id"], 29)
        assert in_progress["status"] == "IN_PROGRESS"
        assert in_progress["completed_hours"] == 29
        completed = post_plan_evidence(plan["id"], 1)
        assert completed["status"] == "COMPLETED"
        returned = advance_application(app["id"], "EVALUATION", EVALUATOR)
        assert returned["status"] == "EVALUATION"
        assert returned["deficiency_hours_required"] == 0


class TestZeroDeficiencyBoundary:

    def test_zero_deficiency_full_reciprocity_skips_plan(self):
        """PRD section 3.5: "a `STANDARD` license from Texas maps to `FULL`
        with zero deficiency hours"
        PRD section 3.7: "`deficiency_hours_required` is zero (else
        `ERR_DEFICIENCY_OUTSTANDING`); and a background check exists for the
        application whose status is not `DENIED` (else
        `ERR_BACKGROUND_NOT_CLEARED`)."

        Design: Difficulty/boundary_precision_check/zero_deficiency_full_reciprocity_skips_plan
        """
        applicant = register_applicant(full_name="Meg Me", email="meg@x.com")
        app = setup_reciprocity_full_in_evaluation(
            applicant, years_teaching=2)
        assert app["deficiency_hours_required"] == 0
        open_and_submit_background_check(app["id"], adverse_findings=[])
        advanced = advance_application(app["id"], "BACKGROUND_REVIEW", EVALUATOR)
        assert advanced["status"] == "BACKGROUND_REVIEW"
        assert advanced["deficiency_hours_required"] == 0

    def test_zero_deficiency_blocks_deficiency_pending_entry(self):
        """PRD section 3.4: "When `deficiency_hours_required` is greater than
        zero, a `CredentialEvaluator` may move the application from
        `EVALUATION` to `DEFICIENCY_PENDING` — attempting that move when no
        deficiency exists is rejected with `ERR_DEFICIENCY_NOT_PRESENT`."

        Design: Difficulty/boundary_precision_check/zero_deficiency_full_reciprocity_skips_plan
        """
        applicant = register_applicant(full_name="Meg Mf", email="megf@x.com")
        app = setup_reciprocity_full_in_evaluation(
            applicant, years_teaching=2)
        assert app["deficiency_hours_required"] == 0
        resp = api_client.transition_application(
            app["id"], {"to_status": "DEFICIENCY_PENDING"}, EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_DEFICIENCY_NOT_PRESENT)


class TestProgramWithdrawalCascade:

    def test_program_withdrawal_forces_application_into_deficiency(self):
        """PRD section 3.2: "When a program moves `PROBATION` →
        `APPROVAL_WITHDRAWN`, every credential application that names the
        program via `program_id`, follows the `TRADITIONAL` pathway, and
        currently sits in `EVALUATION` is forced back into
        `DEFICIENCY_PENDING`, with its `deficiency_hours_required` raised by
        12 hours but capped at 30 — the increment is the lesser of 30 and the
        current value plus 12 — and each affected application's `version`
        increments by 1."

        Design: Corner/state_machines/program_withdrawal_forces_application_into_deficiency
        """
        program = create_approved_program(
            approved_subject_areas=["MATHEMATICS"],
            institution_name="State Teachers College", program_code="STC-MATH")
        applicant = register_applicant(full_name="Dot Do", email="dot@x.com")
        app = create_application(applicant["id"], pathway="TRADITIONAL",
                                 subject_area="MATHEMATICS", grade_band="G7_12",
                                 program_id=program["id"])
        pay_application_fee(app["id"], applicant["id"])
        advance_application(app["id"], "INTAKE_REVIEW", INTAKE)
        add_and_verify_transcript(app["id"], applicant["id"],
                                  subject_relevant_hours=18,
                                  institution_name="STC")
        in_eval = advance_application(app["id"], "EVALUATION", INTAKE)
        # gap 30-18 = 12, test-gap 6, no addon -> 18.
        assert in_eval["deficiency_hours_required"] == 18
        resp = api_client.transition_program(
            program["id"], {"to_status": "PROBATION"}, PAO)
        validate_success(resp)
        resp = api_client.transition_program(
            program["id"], {"to_status": "APPROVAL_WITHDRAWN"}, PAO)
        withdrawn_program = validate_success(resp)
        assert withdrawn_program["approval_status"] == "APPROVAL_WITHDRAWN"
        fetched = validate_success(api_client.get_application(app["id"], EVALUATOR))
        assert fetched["status"] == "DEFICIENCY_PENDING"
        assert fetched["deficiency_hours_required"] == 30


class TestWithdrawalTeardown:

    def test_withdrawal_supersedes_plan_and_revokes_permit(self):
        """PRD section 3.1: "Withdrawal from `EVALUATION` or
        `DEFICIENCY_PENDING` additionally tears down in-flight artifacts:
        every emergency permit of the application in `ISSUED` or `ACTIVE`
        status moves to `REVOKED`, and every deficiency plan of the
        application in `PROPOSED`, `ACCEPTED`, `IN_PROGRESS`, or `EXTENDED`
        status moves to `SUPERSEDED`."

        Design: Corner/state_machines/withdrawal_supersedes_plan_and_revokes_permit
        """
        ctx = setup_deficiency_pending_application(
            accept_plan=True, full_name="Fio Fi", email="fio@x.com")
        app, plan = ctx["application"], ctx["plan"]
        permit = issue_emergency_permit(app["id"], district_code="D09")
        withdrawn = withdraw_application(app["id"], ctx["applicant"]["id"])
        assert withdrawn["status"] == "WITHDRAWN"
        assert withdrawn["fee_status"] == "REFUNDED"
        fetched_plan = validate_success(
            api_client.get_deficiency_plan(plan["id"], EVALUATOR))
        assert fetched_plan["status"] == "SUPERSEDED"
        fetched_permit = validate_success(
            api_client.get_emergency_permit(permit["id"], EVALUATOR))
        assert fetched_permit["status"] == "REVOKED"


class TestPathValidationOrder:

    def test_state_call_on_unknown_application_is_not_found(self):
        """PRD section 2.5: "Incoming requests are validated against an
        ordered pipeline; a failure at an earlier stage masks all later
        checks, and the error returned is always the first one that fires."
        PRD section 2.9: "the first missing identifier short-circuits the
        request with `ERR_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/priority_existence_before_state
        """
        resp = api_client.transition_application(
            NON_EXISTENT_UUID, {"to_status": "INTAKE_REVIEW"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestPlanCreateOcc:

    def test_stale_application_version_rejected_on_plan_create(self):
        """PRD section 2.7: "Creating a deficiency plan against an application
        requires `expected_application_version`, carrying the `version` of the
        application as the client last observed it. If the application's
        current `version` has advanced since that read — for example because
        another evaluator has just created a plan that superseded the prior
        `PROPOSED` plan — the create is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_stale_application_version_rejected
        """
        ctx = setup_deficiency_pending_application(
            full_name="Len Le", email="len@x.com")
        app = ctx["application"]
        plan1 = create_deficiency_plan(app["id"], app["version"])
        resp = api_client.create_deficiency_plan(
            app["id"], {"expected_application_version": app["version"]},
            EVALUATOR)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        assert resp.status_code == 412
        fetched_plan = validate_success(
            api_client.get_deficiency_plan(plan1["id"], EVALUATOR))
        assert fetched_plan["status"] == "PROPOSED"
