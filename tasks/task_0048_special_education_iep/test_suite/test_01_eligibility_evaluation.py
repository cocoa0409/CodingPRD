"""Eligibility evaluation: composite scoring, the dual INITIAL/TRIENNIAL model,
the eligibility threshold boundary, the triennial reevaluation window, and the
guards on finalize (segregation of duties, role, consent).

Every test drives an evaluation through the PRD §3.2 lifecycle and asserts on the
finalize-time computation (PRD §3.3) or the student reconciliation it triggers
(PRD §3.1, §3.2).
"""

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    make_case_manager_headers,
    make_evaluator_headers,
    create_evaluation_payload,
    set_clock,
    create_student,
    make_finalized_evaluation,
    make_evaluation_in_progress,
    get_student,
)

CM = make_case_manager_headers("cm_1")
EV = make_evaluator_headers("ev_1")


def _drive_to_in_progress(student_id, eval_overrides):
    """Open eval, request consent, grant, begin — return eval id (IN_PROGRESS)."""
    ev = make_evaluation_in_progress(student_id, eval_overrides=eval_overrides)
    return ev["id"]


class TestCompositeScore:
    def test_initial_composite_nonlinear_three_inputs(self, api):
        """PRD §3.3: "The raw composite is the sum of three terms: the gap weight multiplied by the discrepancy, plus 0.30 multiplied by the adaptive deficit, plus 0.20 multiplied by the academic deficit. That raw value is rounded half-up to two decimal places to produce the `composite_eligibility_score`."
        PRD §3.3: "The outcome is then `ELIGIBLE` when the composite score is at least 15.0, and `INELIGIBLE` when it is below 15.0."

        Scores 110/70/75 INITIAL: discrepancy 40 * 0.5 = 20.0; adaptive deficit
        (100-75)=25 * 0.30 = 7.5; academic deficit (100-70)=30 * 0.20 = 6.0;
        raw = 33.50 → ELIGIBLE.

        Design: Difficulty/combinatorial_formula/eligibility_composite_nonlinear_three_inputs
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Mara Vox",
                                 date_of_birth="2015-05-05", grade_level=5)
        eval_id = _drive_to_in_progress(
            student["id"],
            {"eval_type": "INITIAL", "cognitive_score": 110, "academic_score": 70,
             "adaptive_score": 75, "proposed_category": "SLD"},
        )
        data = validate_success(api.finalize_evaluation(eval_id, EV), 200)
        assert data["composite_eligibility_score"] == 33.50, data["composite_eligibility_score"]
        assert data["outcome"] == "ELIGIBLE", data["outcome"]

    def test_initial_vs_triennial_gap_weight_diverges(self, api):
        """PRD §3.3: "for an `INITIAL` evaluation the gap weight is 0.5, and for a `TRIENNIAL` evaluation it is 0.6, the higher factor reflecting the continuity of a student who already carries an identification history."
        PRD §3.3: "The two variants of this model — the initial model with its 0.5 gap weight and the triennial model with its 0.6 gap weight — differ only in that single factor; every other term and the threshold are identical."

        Identical scores 110/70/75: INITIAL composite 33.50 vs TRIENNIAL 37.50.

        Design: Difficulty/dual_variant_calc/eligibility_composite_initial_vs_triennial_diverge
        """
        set_clock("2026-01-10T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Lee Ng",
                                 date_of_birth="2016-02-01", grade_level=4)
        ev1 = make_finalized_evaluation(
            student["id"],
            eval_overrides={"eval_type": "INITIAL", "cognitive_score": 110,
                            "academic_score": 70, "adaptive_score": 75,
                            "proposed_category": "SLD"},
        )
        assert ev1["composite_eligibility_score"] == 33.50, ev1["composite_eligibility_score"]

        set_clock("2029-02-01T09:00:00Z")
        ev2 = make_finalized_evaluation(
            student["id"],
            eval_overrides={"eval_type": "TRIENNIAL", "cognitive_score": 110,
                            "academic_score": 70, "adaptive_score": 75,
                            "proposed_category": "SLD"},
        )
        assert ev2["composite_eligibility_score"] == 37.50, ev2["composite_eligibility_score"]

    def test_triennial_composite_uses_higher_gap_weight(self, api):
        """PRD §3.3: "for an `INITIAL` evaluation the gap weight is 0.5, and for a `TRIENNIAL` evaluation it is 0.6, the higher factor reflecting the continuity of a student who already carries an identification history."

        A TRIENNIAL evaluation with 110/70/75 yields composite 37.50 (gap 40*0.6=24.0
        + 7.5 + 6.0), distinct from the 33.50 the INITIAL model would produce.

        Design: Difficulty/dual_variant_calc/eligibility_composite_initial_vs_triennial_diverge
        """
        set_clock("2026-01-10T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Lee Ng2",
                                 date_of_birth="2016-02-01", grade_level=4)
        make_finalized_evaluation(
            student["id"],
            eval_overrides={"eval_type": "INITIAL", "cognitive_score": 110,
                            "academic_score": 70, "adaptive_score": 75,
                            "proposed_category": "SLD"},
        )
        set_clock("2029-02-01T09:00:00Z")
        ev2 = make_finalized_evaluation(
            student["id"],
            eval_overrides={"eval_type": "TRIENNIAL", "cognitive_score": 110,
                            "academic_score": 70, "adaptive_score": 75,
                            "proposed_category": "SLD"},
        )
        assert ev2["composite_eligibility_score"] == 37.50, ev2["composite_eligibility_score"]
        assert ev2["outcome"] == "ELIGIBLE", ev2["outcome"]

    def test_initial_combinatorial_outcome_eligible(self, api):
        """PRD §3.3: "First, an ability-achievement discrepancy is formed by subtracting the `academic_score` from the `cognitive_score`; if that difference is negative it is treated as zero, so a negative gap never contributes."
        PRD §3.3: "An adaptive deficit is then formed as 100 minus the `adaptive_score`, taking zero whenever that would be negative; likewise an academic deficit is formed as 100 minus the `academic_score`, again floored at zero."

        110/70/75 INITIAL combines a clamped discrepancy and two below-100 deficits
        into composite 33.50 (>= 15.0) → ELIGIBLE.

        Design: Difficulty/combinatorial_formula/eligibility_composite_nonlinear_three_inputs
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Mara Vox2",
                                 date_of_birth="2015-05-05", grade_level=5)
        ev = make_finalized_evaluation(
            student["id"],
            eval_overrides={"eval_type": "INITIAL", "cognitive_score": 110,
                            "academic_score": 70, "adaptive_score": 75,
                            "proposed_category": "SLD"},
        )
        assert ev["composite_eligibility_score"] == 33.50, ev["composite_eligibility_score"]
        assert ev["outcome"] == "ELIGIBLE", ev["outcome"]


class TestEligibilityThreshold:
    def test_composite_exactly_15_is_eligible(self, api):
        """PRD §3.3: "The outcome is then `ELIGIBLE` when the composite score is at least 15.0, and `INELIGIBLE` when it is below 15.0."

        130/100/100 INITIAL: discrepancy 30 * 0.5 = 15.0; adaptive deficit 0;
        academic deficit 0; composite exactly 15.00, landing on the >= boundary →
        ELIGIBLE.

        Design: Difficulty/boundary_precision_check/eligibility_threshold_exact_15_is_eligible
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Beth Lin",
                                 date_of_birth="2015-01-01", grade_level=5)
        ev = make_finalized_evaluation(
            student["id"],
            eval_overrides={"eval_type": "INITIAL", "cognitive_score": 130,
                            "academic_score": 100, "adaptive_score": 100,
                            "proposed_category": "SLD"},
        )
        assert ev["composite_eligibility_score"] == 15.00, ev["composite_eligibility_score"]
        assert ev["outcome"] == "ELIGIBLE", ev["outcome"]

    def test_threshold_boundary_outcome_eligible_at_15(self, api):
        """PRD §3.3: "The outcome is then `ELIGIBLE` when the composite score is at least 15.0, and `INELIGIBLE` when it is below 15.0."

        Confirms the inclusive lower edge: a composite that lands exactly at the
        threshold 15.00 (scores 130/100/100 INITIAL) is decided ELIGIBLE.

        Design: Difficulty/boundary_precision_check/eligibility_threshold_exact_15_is_eligible
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Beth Lin2",
                                 date_of_birth="2015-01-01", grade_level=5)
        eval_id = _drive_to_in_progress(
            student["id"],
            {"eval_type": "INITIAL", "cognitive_score": 130, "academic_score": 100,
             "adaptive_score": 100, "proposed_category": "SLD"},
        )
        data = validate_success(api.finalize_evaluation(eval_id, EV), 200)
        assert data["composite_eligibility_score"] == 15.00
        assert data["outcome"] == "ELIGIBLE"

    def test_below_threshold_is_ineligible_and_student_reconciled(self, api):
        """PRD §3.3: "The outcome is then `ELIGIBLE` when the composite score is at least 15.0, and `INELIGIBLE` when it is below 15.0."
        PRD §3.2: "the student's `eligibility_status` is recomputed from this newly finalized evaluation; if the outcome is `ELIGIBLE` the student's `disability_category` is set to this evaluation's `proposed_category`, and otherwise the category is left null"

        100/100/100 INITIAL: discrepancy 0, both deficits 0 → composite 0.00 (< 15.0)
        → INELIGIBLE; student.eligibility_status becomes INELIGIBLE.

        Design: Corner/calculations/eligibility_below_threshold_is_ineligible
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Fay Long",
                                 date_of_birth="2014-03-03", grade_level=6)
        ev = make_finalized_evaluation(
            student["id"],
            eval_overrides={"eval_type": "INITIAL", "cognitive_score": 100,
                            "academic_score": 100, "adaptive_score": 100,
                            "proposed_category": "SLD"},
        )
        assert ev["composite_eligibility_score"] == 0.0, ev["composite_eligibility_score"]
        assert ev["outcome"] == "INELIGIBLE", ev["outcome"]
        stu = get_student(student["id"])
        assert stu["eligibility_status"] == "INELIGIBLE", stu["eligibility_status"]


class TestTriennialReevalWindow:
    def test_reeval_due_date_is_finalized_at_plus_1095_days(self, api):
        """PRD §3.1: "The `next_reeval_due_date` is the triennial reevaluation deadline, computed as the finalization timestamp of the latest finalized evaluation plus three years, expressed as 1095 days, and is null while the student is `NOT_EVALUATED`."

        Finalizing at 2026-03-01T09:00:00Z sets next_reeval_due_date to
        2029-02-28T09:00:00.000Z (1095 days later; 2028 is a leap year).

        Design: Difficulty/resource_temporal_overlap/triennial_reeval_due_window_three_years
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Hugo Pratt",
                                 date_of_birth="2015-03-03", grade_level=5)
        make_finalized_evaluation(
            student["id"],
            eval_overrides={"eval_type": "INITIAL", "cognitive_score": 110,
                            "academic_score": 70, "adaptive_score": 75,
                            "proposed_category": "SLD"},
        )
        stu = get_student(student["id"])
        assert stu["next_reeval_due_date"] == "2029-02-28T09:00:00.000Z", stu["next_reeval_due_date"]

    def test_reeval_due_date_anchored_at_finalization_instant(self, api):
        """PRD §3.1: "The `next_reeval_due_date` is the triennial reevaluation deadline, computed as the finalization timestamp of the latest finalized evaluation plus three years, expressed as 1095 days, and is null while the student is `NOT_EVALUATED`."

        A finalization pinned to a different instant (2026-01-10T09:00:00Z) anchors
        the 1095-day forward window at exactly 2029-01-09T09:00:00.000Z.

        Design: Difficulty/resource_temporal_overlap/triennial_reeval_due_window_three_years
        """
        set_clock("2026-01-10T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Hugo Pratt2",
                                 date_of_birth="2015-03-03", grade_level=5)
        make_finalized_evaluation(
            student["id"],
            eval_overrides={"eval_type": "INITIAL", "cognitive_score": 110,
                            "academic_score": 70, "adaptive_score": 75,
                            "proposed_category": "SLD"},
        )
        stu = get_student(student["id"])
        # 2026-01-10 + 1095 days = 2029-01-09 (2028 leap year).
        assert stu["next_reeval_due_date"] == "2029-01-09T09:00:00.000Z", stu["next_reeval_due_date"]


class TestFinalizeGuards:
    def test_finalize_by_requesting_casemanager_blocked_by_segregation(self, api):
        """PRD §2.1: "When an evaluator finalizes an evaluation, the finalizing `Evaluator`'s `X-User-ID` must not equal the `X-User-ID` of the `CaseManager` recorded as having requested that evaluation. A violation of either rule is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        The requesting CaseManager is recorded as cm_1; finalizing while carrying
        X-User-ID cm_1 (as an Evaluator) trips the guard.

        Design: Corner/validations/segregation_of_duties_evaluator_finalize_blocked_for_requesting_casemanager
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Cy Wren",
                                 date_of_birth="2014-08-08", grade_level=6)
        eval_id = _drive_to_in_progress(
            student["id"],
            {"eval_type": "INITIAL", "cognitive_score": 110, "academic_score": 70,
             "adaptive_score": 75, "proposed_category": "SLD"},
        )
        finalizer = make_evaluator_headers("cm_1")  # same X-User-ID as the requester
        validate_error(
            api.finalize_evaluation(eval_id, finalizer),
            ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
        )

    def test_finalize_by_casemanager_role_forbidden(self, api):
        """PRD §2.1: "When a request carries a recognized role but that role is not permitted to perform the requested operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."

        Finalize is an Evaluator-exclusive operation (PRD §4); a CaseManager calling
        it (with a non-requester id) is rejected with ERR_FORBIDDEN.

        Design: Corner/rbac/casemanager_cannot_finalize_evaluation
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Gil Tam",
                                 date_of_birth="2014-04-04", grade_level=6)
        eval_id = _drive_to_in_progress(
            student["id"],
            {"eval_type": "INITIAL", "cognitive_score": 110, "academic_score": 70,
             "adaptive_score": 75, "proposed_category": "SLD"},
        )
        validate_error(
            api.finalize_evaluation(eval_id, make_case_manager_headers("cm_2")),
            ApiErrorId.ERR_FORBIDDEN.value,
        )

    def test_begin_without_granted_consent_rejected(self, api):
        """PRD §3.2: "From `CONSENT_PENDING`, the `Evaluator` begins testing, moving the evaluation `CONSENT_PENDING → IN_PROGRESS`; this requires the evaluation to be in `CONSENT_PENDING` and additionally requires that the `EVALUATION` consent request for this evaluation's student be in `GRANTED` status — if it is not, the begin is rejected with `ERR_CONSENT_NOT_GRANTED` (HTTP 409)."

        Design: Corner/state_machines/begin_evaluation_without_granted_consent_returns_consent_not_granted
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Eli Frost",
                                 date_of_birth="2014-05-05", grade_level=6)
        ev = validate_success(
            api.create_evaluation(create_evaluation_payload(student["id"]), CM), 201
        )
        validate_success(api.request_consent(ev["id"], CM), 200)
        # Consent is left PENDING (never granted).
        validate_error(
            api.begin_evaluation(ev["id"], EV),
            ApiErrorId.ERR_CONSENT_NOT_GRANTED.value,
        )


class TestEvaluationCreateValidation:
    def test_create_evaluation_with_unknown_student_fk(self, api):
        """PRD §2.6: "Separately, several create operations carry foreign-key references in the request body — a `student_id`, an `iep_id`, or a `goal_id`. When such a body field names a resource that does not exist, the request is rejected with `ERR_FK_NOT_FOUND` (HTTP 404)."

        Design: Corner/validations/create_evaluation_fk_student_not_found
        """
        validate_error(
            api.create_evaluation(
                create_evaluation_payload("00000000-0000-4000-8000-000000000000"), CM
            ),
            ApiErrorId.ERR_FK_NOT_FOUND.value,
        )

    def test_create_evaluation_invalid_eval_type_enum(self, api):
        """PRD §2.8: "required fields must be present and well-typed and any enum value must be drawn from its allowed set (`ERR_INVALID_REQUEST`)"
        PRD §3.2: "The `eval_type` is either `INITIAL`, for a student's first eligibility determination, or `TRIENNIAL`, for the three-year reevaluation."

        Design: Corner/validations/create_evaluation_invalid_enum_eval_type
        """
        set_clock("2026-03-01T09:00:00Z")
        student = create_student(set_clock_first=False, full_name="Ada Moss",
                                 date_of_birth="2014-06-06", grade_level=6)
        validate_error(
            api.create_evaluation(
                create_evaluation_payload(student["id"], eval_type="ANNUAL"), CM
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )
