"""Graduation applications: filing guards, review preconditions, the decide
fork, conditional-clearance auto-resolution, and the terminal states
(PRD §2.5, §2.7, §3.6).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_gpa,
    create_application_payload,
    declare,
    get_application,
    get_student,
    make_course,
    make_program,
    make_requirement_group,
    make_student,
    make_student_headers,
    open_application,
    run_audit,
    set_clock,
    setup_graduation_pipeline,
    submit_application,
    begin_review,
    validate_error,
    validate_success,
)


def _final_term_scenario(program_code):
    """Student with 9 completed credits (C1 A, C2 B, C3 B) plus one IN_PROGRESS
    C4, a CURRENT FINAL audit (unsatisfied: 9 < 12), and an application walked
    to UNDER_REVIEW."""
    return setup_graduation_pipeline(
        program_overrides={
            "program_code": program_code, "name": program_code,
            "min_total_credits": 12, "min_gpa": 2.0,
            "catalog_year_start": 2024, "catalog_year_end": 2028,
        },
        groups=[
            {"group_code": "CORE", "required_credits": 9, "min_grade": "D",
             "eligible_course_codes": ["C1", "C2", "C3"]},
        ],
        student_overrides={"student_number": f"S-{program_code}", "legal_name": "Bree Branch"},
        enrollment_specs=[
            {"course_code": "C1", "term": "2024-FA", "grade": "A"},
            {"course_code": "C2", "term": "2024-FA", "grade": "B"},
            {"course_code": "C3", "term": "2025-SP", "grade": "B"},
            {"course_code": "C4", "term": "2026-SP"},  # IN_PROGRESS, 3cr
        ],
        audit_kinds=("FINAL",),
        walk_to="UNDER_REVIEW",
    )


class TestBeginReviewFinalAuditGate:
    def _submitted_application(self, program_code="BS-FR"):
        sc = setup_graduation_pipeline(
            program_overrides={"program_code": program_code, "name": program_code},
            student_overrides={"student_number": f"S-{program_code}", "legal_name": "Fran Frost"},
            audit_kinds=(),  # no audit of any kind
            walk_to="SUBMITTED",
        )
        return sc

    def test_begin_review_without_final_audit_rejected(self, api, registrar_headers):
        """PRD §3.6: "Two preconditions apply, in order: a `CURRENT` `FINAL`
        audit must exist for the declaration — beginning review without one is
        rejected with `ERR_FINAL_AUDIT_REQUIRED` — and the financial hold is
        re-examined, with a held student refused via `ERR_FINANCIAL_HOLD`."

        Design: Difficulty/cross_entity_state_dependency/begin_review_requires_current_final_audit
        """
        sc = self._submitted_application()
        res = api.begin_review(sc.application["id"], registrar_headers)
        validate_error(res, ApiErrorId.ERR_FINAL_AUDIT_REQUIRED.value, expected_status=409)
        assert get_application(sc.application["id"])["status"] == "SUBMITTED"

    def test_begin_review_succeeds_once_final_audit_exists(self, api, registrar_headers):
        """PRD §3.6: "Review begins when `RegistrarStaff` takes the application
        from `SUBMITTED` to `UNDER_REVIEW`. Two preconditions apply, in order: a
        `CURRENT` `FINAL` audit must exist for the declaration — beginning review
        without one is rejected with `ERR_FINAL_AUDIT_REQUIRED`". Creating the
        FINAL audit satisfies the gate.

        Design: Difficulty/cross_entity_state_dependency/begin_review_requires_current_final_audit
        """
        sc = self._submitted_application(program_code="BS-FR2")
        run_audit(sc.student_program["id"], "FINAL")
        reviewed = validate_success(
            api.begin_review(sc.application["id"], registrar_headers), 200)
        assert reviewed["status"] == "UNDER_REVIEW"


class TestBeginReviewStateBeforeFiscal:
    def _held_draft_application(self):
        program = make_program(program_code="BS-PF", name="BS PF")
        student = make_student(student_number="S-PF", legal_name="Penny Frost",
                               financial_hold=True)
        sp = declare(student["id"], program["id"], catalog_year=2024)
        application = open_application(sp["id"], student["id"])
        return student, application

    def test_state_check_fires_before_financial_hold(self, api, registrar_headers):
        """PRD §2.7: "A request that would fail multiple checks always surfaces
        the earliest applicable one. The order is:" ... "5. **From-state
        validity.** The target resource must be in a state that allows the
        requested transition (`ERR_PROGRAM_INVALID_STATE`,
        `ERR_ENROLLMENT_INVALID_STATE`, `ERR_STUDENT_PROGRAM_NOT_ACTIVE`,
        `ERR_WAIVER_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`,
        `ERR_DIPLOMA_INVALID_STATE`)." ... "11. **Financial standing.** The
        student's `financial_hold` must be clear where the workflow requires it
        (`ERR_FINANCIAL_HOLD`)."

        Begin-review on a DRAFT application whose student is on hold violates
        both; the from-state check surfaces.

        Design: Difficulty/priority_pair_validation_conflict/begin_review_state_before_fiscal
        """
        _student, application = self._held_draft_application()
        assert application["status"] == "DRAFT"

        res = api.begin_review(application["id"], registrar_headers)
        body = res.json()
        assert body["data"]["error_id"] == ApiErrorId.ERR_APPLICATION_INVALID_STATE.value
        assert body["data"]["error_id"] != ApiErrorId.ERR_FINANCIAL_HOLD.value

    def test_rejected_begin_review_leaves_draft_unchanged(self, api, registrar_headers):
        """PRD §2.7: "5. **From-state validity.** The target resource must be in
        a state that allows the requested transition (`ERR_PROGRAM_INVALID_STATE`,
        `ERR_ENROLLMENT_INVALID_STATE`, `ERR_STUDENT_PROGRAM_NOT_ACTIVE`,
        `ERR_WAIVER_INVALID_STATE`, `ERR_APPLICATION_INVALID_STATE`,
        `ERR_DIPLOMA_INVALID_STATE`)." PRD §5 maps `ERR_APPLICATION_INVALID_STATE`
        to 409 Conflict; a rejected transition leaves the application in its
        prior state.

        Design: Difficulty/priority_pair_validation_conflict/begin_review_state_before_fiscal
        """
        _student, application = self._held_draft_application()
        res = api.begin_review(application["id"], registrar_headers)
        validate_error(res, ApiErrorId.ERR_APPLICATION_INVALID_STATE.value, expected_status=409)
        assert get_application(application["id"])["status"] == "DRAFT"


class TestConditionalClearanceFork:
    def test_conditional_clearance_then_contingency_failed(self, api, registrar_headers):
        """PRD §3.6: "if it is false the application moves `CONDITIONALLY_CLEARED`
        → `DENIED` with `decision_reason` set to `CONTINGENCY_FAILED`."

        Design: Difficulty/non_linear_state_machine/application_conditional_clearance_fork
        """
        sc = _final_term_scenario("BS-BR")
        app_id = sc.application["id"]
        in_progress = sc.enrollments[3]
        assert in_progress["status"] == "IN_PROGRESS"

        # Fork: CONDITIONALLY_CLEARED is allowed while >=1 IN_PROGRESS enrollment exists.
        decided = validate_success(api.decide_application(
            app_id, {"decision": "CONDITIONALLY_CLEARED"}, registrar_headers), 200)
        assert decided["status"] == "CONDITIONALLY_CLEARED"

        # Posting F on the last IN_PROGRESS enrollment resolves the contingency
        # against the student: F earns no credit, so the FINAL audit stays
        # unsatisfied (9 < 12) and the application auto-denies.
        posted = validate_success(api.post_grade(
            in_progress["id"], {"grade": "F"}, registrar_headers), 200)
        assert posted["status"] == "COMPLETED"
        assert posted["credits_earned"] == 0

        after = get_application(app_id)
        assert after["status"] == "DENIED"
        assert after["decision_reason"] == "CONTINGENCY_FAILED"

    def test_f_grade_keeps_credits_in_gpa_denominator(self, api, registrar_headers):
        """PRD §3.2: "An enrollment's `credits_earned` equals the course's
        credits when the enrollment is `COMPLETED` with a grade of `A` through
        `D`, and is zero in every other case — an `F` earns nothing, and a
        withdrawal earns nothing."
        PRD §3.2: "An enrollment is **GPA-bearing** when it is `COMPLETED` with a
        grade of `A` through `F`; a `W` is excluded from GPA entirely,
        contributing neither grade points nor credits attempted to the
        denominator."

        After the F: 9 earned credits, GPA = (12+9+9+0)/12 = 30.00/12 = 2.500,
        and the divergent CLEARED branch does not fire.

        Design: Difficulty/non_linear_state_machine/application_conditional_clearance_fork
        """
        sc = _final_term_scenario("BS-BR2")
        app_id = sc.application["id"]
        in_progress = sc.enrollments[3]
        validate_success(api.decide_application(
            app_id, {"decision": "CONDITIONALLY_CLEARED"}, registrar_headers), 200)
        validate_success(api.post_grade(
            in_progress["id"], {"grade": "F"}, registrar_headers), 200)

        student = get_student(sc.student["id"])
        assert student["total_earned_credits"] == 9
        assert_gpa(student["institutional_gpa"], 2.500)

        after = get_application(app_id)
        assert after["status"] != "CLEARED"


class TestPostGradeClearanceCascade:
    def test_post_grade_updates_enrollment_and_student(self, api, registrar_headers):
        """PRD §2.11: "Grade events (an enrollment created with a grade, a grade
        posting, a grade change) and exception decisions (approval, revocation)
        fire a deterministic recompute chain: first the enrollment's own credit
        fields are recomputed, then the owning student's aggregate credits and
        GPAs, then every `CURRENT` degree audit of each `ACTIVE` declaration of
        that student, then the declaration's `latest_audit_satisfied` flag, and
        finally any conditionally cleared graduation application awaiting its
        contingency resolution."

        Hop 1–2: the B posting completes the enrollment (3 earned) and lifts the
        student to 12 earned credits, GPA 39.00/12 = 3.250.

        Design: Difficulty/transitive_cascade/post_grade_four_hop_clearance_cascade
        """
        sc = _final_term_scenario("BS-CC")
        validate_success(api.decide_application(
            sc.application["id"], {"decision": "CONDITIONALLY_CLEARED"},
            registrar_headers), 200)

        in_progress = sc.enrollments[3]
        posted = validate_success(api.post_grade(
            in_progress["id"], {"grade": "B"}, registrar_headers), 200)
        assert posted["status"] == "COMPLETED"
        assert posted["credits_earned"] == 3

        student = get_student(sc.student["id"])
        assert student["total_earned_credits"] == 12
        assert_gpa(student["institutional_gpa"], 3.250)

    def test_post_grade_recomputes_audit_and_releases_clearance(self, api, registrar_headers):
        """PRD §3.6: "When an enrollment mutation (a grade posting or a grade
        change, including a withdrawal) leaves the student with zero
        `IN_PROGRESS` enrollments, the recomputed `CURRENT` `FINAL` audit decides
        the outcome as the terminal hop of the recompute cascade: if
        `overall_satisfied` is true the application moves `CONDITIONALLY_CLEARED`
        → `CLEARED`"

        Hop 3–4: the FINAL audit recomputes to satisfied (12 applied >= 12,
        group CORE 9/9), the declaration flag flips, and the application
        auto-clears.

        Design: Difficulty/transitive_cascade/post_grade_four_hop_clearance_cascade
        """
        sc = _final_term_scenario("BS-CC2")
        app_id = sc.application["id"]
        sp_id = sc.student_program["id"]
        validate_success(api.decide_application(
            app_id, {"decision": "CONDITIONALLY_CLEARED"}, registrar_headers), 200)

        validate_success(api.post_grade(
            sc.enrollments[3]["id"], {"grade": "B"}, registrar_headers), 200)

        from test_helpers import list_audits, get_student_program
        audits, _ = list_audits(sp_id, audit_kind="FINAL", status="CURRENT")
        assert audits[0]["total_credits_applied"] == 12
        assert audits[0]["overall_satisfied"] is True
        assert get_student_program(sp_id)["latest_audit_satisfied"] is True
        assert get_application(app_id)["status"] == "CLEARED"


class TestFilingDeadline:
    def test_submit_at_deadline_passes_and_clearly_later_filing_fails(self, api, registrar_headers):
        """PRD §3.6: "The filing window must still be open: the logical clock
        must read on or before the date thirty days before the
        `expected_conferral_date`, and a later filing is rejected with
        `ERR_FILING_DEADLINE_PASSED`."
        PRD §2.5: "Before any adjustment, the logical clock reads exactly
        2026-08-01T00:00:00Z, and the server never falls back to wall-clock time
        on its own."

        Conferral date 2026-09-15 puts the deadline date at 2026-08-16: filing
        when the clock reads the start of that date is on time, while filing a
        full day later is past it.

        Design: Corner/validations/filing_deadline_inclusive_boundary
        """
        program = make_program(program_code="BS-FD", name="BS FD")
        s1 = make_student(student_number="S-F1", legal_name="Fay One")
        s2 = make_student(student_number="S-F2", legal_name="Fay Two")
        sp1 = declare(s1["id"], program["id"], catalog_year=2024)
        sp2 = declare(s2["id"], program["id"], catalog_year=2024)
        app1 = open_application(sp1["id"], s1["id"])
        app2 = open_application(sp2["id"], s2["id"])

        set_clock("2026-08-16T00:00:00Z")
        submitted = validate_success(
            api.submit_application(app1["id"], make_student_headers(s1["id"])), 200)
        assert submitted["status"] == "SUBMITTED"

        set_clock("2026-08-17T00:00:00Z")
        res = api.submit_application(app2["id"], make_student_headers(s2["id"]))
        validate_error(res, ApiErrorId.ERR_FILING_DEADLINE_PASSED.value, expected_status=422)
        assert get_application(app2["id"])["status"] == "DRAFT"


class TestFinancialHoldSubmit:
    def test_submit_with_financial_hold_rejected(self, api, registrar_headers):
        """PRD §3.6: "Finally the student's `financial_hold` must be false, else
        the filing stops with `ERR_FINANCIAL_HOLD`."

        Design: Corner/validations/financial_hold_blocks_submit_clean
        """
        program = make_program(program_code="BS-FH", name="BS FH")
        student = make_student(student_number="S-FH", legal_name="Fin Hold",
                               financial_hold=True)
        sp = declare(student["id"], program["id"], catalog_year=2024)
        application = open_application(sp["id"], student["id"])

        res = api.submit_application(application["id"], make_student_headers(student["id"]))
        validate_error(res, ApiErrorId.ERR_FINANCIAL_HOLD.value, expected_status=402)
        assert get_application(application["id"])["status"] == "DRAFT"


class TestDecideGuards:
    def test_decide_cleared_with_unsatisfied_audit_rejected(self, api, registrar_headers):
        """PRD §3.6: "`CLEARED` certifies the degree and requires the `CURRENT`
        `FINAL` audit's `overall_satisfied` to be true; an unsatisfied audit
        blocks clearance with `ERR_AUDIT_NOT_SATISFIED`."

        Design: Corner/validations/decide_cleared_requires_satisfied_final_audit
        """
        sc = setup_graduation_pipeline(
            program_overrides={"program_code": "BS-AS", "name": "BS AS"},
            student_overrides={"student_number": "S-AS", "legal_name": "Aud Sat"},
            audit_kinds=("FINAL",),  # 0 credits -> unsatisfied
            walk_to="UNDER_REVIEW",
        )
        assert sc.audits["FINAL"]["overall_satisfied"] is False

        res = api.decide_application(
            sc.application["id"], {"decision": "CLEARED"}, registrar_headers)
        validate_error(res, ApiErrorId.ERR_AUDIT_NOT_SATISFIED.value, expected_status=409)
        assert get_application(sc.application["id"])["status"] == "UNDER_REVIEW"

    def test_conditional_clearance_requires_in_progress_enrollment(self, api, registrar_headers):
        """PRD §3.6: "`CONDITIONALLY_CLEARED` is the final-term contingency path
        for students whose coursework is still in flight, and requires at least
        one `IN_PROGRESS` enrollment; without one the decision is rejected with
        `ERR_NO_IN_PROGRESS_ENROLLMENTS`."

        Design: Corner/validations/conditional_clearance_requires_in_progress_enrollment
        """
        sc = setup_graduation_pipeline(
            program_overrides={"program_code": "BS-NI", "name": "BS NI"},
            student_overrides={"student_number": "S-NI", "legal_name": "No Inp"},
            enrollment_specs=(),  # zero enrollments -> zero IN_PROGRESS
            audit_kinds=("FINAL",),
            walk_to="UNDER_REVIEW",
        )
        res = api.decide_application(
            sc.application["id"], {"decision": "CONDITIONALLY_CLEARED"}, registrar_headers)
        validate_error(res, ApiErrorId.ERR_NO_IN_PROGRESS_ENROLLMENTS.value, expected_status=409)
        assert get_application(sc.application["id"])["status"] == "UNDER_REVIEW"


class TestActiveApplicationUniqueness:
    def test_terminal_denied_application_does_not_block_new_filing(self, api, registrar_headers):
        """PRD §3.6: "There must be no other live application for the same
        declaration: a sibling in `DRAFT`, `SUBMITTED`, `UNDER_REVIEW`,
        `CLEARED`, or `CONDITIONALLY_CLEARED` blocks the filing with
        `ERR_ACTIVE_APPLICATION_EXISTS`, while terminal `DENIED` and
        `DEGREE_CONFERRED` applications do not."

        Design: Corner/validations/active_application_uniqueness
        """
        sc = setup_graduation_pipeline(
            program_overrides={"program_code": "BS-AA", "name": "BS AA"},
            student_overrides={"student_number": "S-AA", "legal_name": "Ann App"},
            audit_kinds=("FINAL",),  # 0 credits -> unsatisfied
            walk_to="DENIED",
        )
        assert sc.application["status"] == "DENIED"

        # Once the first application is terminally DENIED, a fresh application
        # can be opened and filed for a later term.
        second = validate_success(api.create_application(
            sc.student_program["id"],
            create_application_payload(expected_term="2026-FA",
                                       expected_conferral_date="2027-01-15"),
            make_student_headers(sc.student["id"])), 201)
        assert second["id"] != sc.application["id"]
        assert second["status"] == "DRAFT"

        submitted = validate_success(api.submit_application(
            second["id"], make_student_headers(sc.student["id"])), 200)
        assert submitted["status"] == "SUBMITTED"


class TestDeniedApplicationTerminal:
    def test_decide_on_denied_application_rejected(self, api, registrar_headers):
        """PRD §3.6: "`DENIED` ends the application terminally, recording the
        `decision_reason`." and "The certification decision rests with
        `RegistrarStaff`, who submits a `decision` with an optional
        `decision_reason` from the `UNDER_REVIEW` state (any other state meets
        `ERR_APPLICATION_INVALID_STATE`)."

        Design: Corner/state_machines/denied_application_is_terminal
        """
        sc = setup_graduation_pipeline(
            program_overrides={"program_code": "BS-DN", "name": "BS DN"},
            student_overrides={"student_number": "S-DN", "legal_name": "Dan Nial"},
            audit_kinds=("FINAL",),
            walk_to="UNDER_REVIEW",
        )
        app_id = sc.application["id"]

        denied = validate_success(api.decide_application(
            app_id, {"decision": "DENIED", "decision_reason": "requirements unmet"},
            registrar_headers), 200)
        assert denied["status"] == "DENIED"
        assert denied["decision_reason"] == "requirements unmet"

        res = api.decide_application(app_id, {"decision": "CLEARED"}, registrar_headers)
        validate_error(res, ApiErrorId.ERR_APPLICATION_INVALID_STATE.value, expected_status=409)
