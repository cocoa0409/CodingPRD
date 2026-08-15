"""Senior audits, graduation gating, outcomes, and drift.

PRD §3.7 (audit machine, certify gates, auto-flag, graduation cascade),
§3.8 (outcome records).
"""
import pytest

from test_helpers import (
    TEST_USERS, ApiErrorId, add_completed_enrollment, add_enrollment,
    assert_outcome_record, assert_senior_audit, complete_placement,
    confirm_placement, create_active_plan, create_advisor,
    create_application, create_certification, create_pathway,
    create_placement, create_rec_request, create_senior_audit, create_site,
    create_student, create_teacher, get_senior_audit, get_student,
    get_teacher, list_milestones, make_advisor_headers, make_student_headers,
    schedule_certification, setup_audit_in_review, setup_certified_audit,
    setup_graduated_student, setup_student_with_active_plan,
    transition_audit, transition_enrollment, validate_error,
    validate_success,
)

ADMIN = TEST_USERS["district_admin_headers"]
WBL = TEST_USERS["wbl_coordinator_headers"]


class TestAuditMachineBasics:
    def test_audit_flag_requires_reason_returns_400(self, api):
        """PRD §3.7: "from `IN_REVIEW` to `FLAGGED`, which requires a
        non-empty `flag_reason` in the payload (else `ERR_VALIDATION`)".

        Design: Corner/state_machines/audit_flag_requires_reason_returns_400
        """
        assigned = create_advisor(max_caseload=10)
        auditor = create_advisor(max_caseload=10)
        student = create_student(student_ref="FR1", advisor_id=assigned["id"])
        audit = create_senior_audit(student["id"], auditor["id"])
        transition_audit(audit["id"], auditor["id"], "IN_REVIEW")

        resp = api.transition_senior_audit(
            audit["id"], {"to_status": "FLAGGED"},
            make_advisor_headers(auditor["id"]))
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        after = get_senior_audit(audit["id"])
        assert after["status"] == "IN_REVIEW"

    def test_audit_transition_by_non_auditor_returns_403(self, api):
        """PRD §3.7: "Reviewing the audit belongs to the named auditor and no
        one else: any transition attempted by an advisor other than
        `auditor_advisor_id` is rejected with `ERR_NOT_AUDITOR`."

        Design: Corner/validations/audit_transition_by_non_auditor_returns_403
        """
        assigned = create_advisor(max_caseload=10)
        auditor = create_advisor(max_caseload=10)
        bystander = create_advisor(max_caseload=10)
        student = create_student(student_ref="NA1", advisor_id=assigned["id"])
        audit = create_senior_audit(student["id"], auditor["id"])

        resp = api.transition_senior_audit(
            audit["id"], {"to_status": "IN_REVIEW"},
            make_advisor_headers(bystander["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_AUDITOR)
        assert get_senior_audit(audit["id"])["status"] == "DRAFT"

    def test_senior_audit_requires_grade_12_returns_409(self, api):
        """PRD §3.7: "The senior audit is the district's graduation gate, and
        it opens when a `DistrictAdmin` names an `auditor_advisor_id` for a
        student whose `grade_level` is exactly 12 — opening one for a
        non-senior is `ERR_NOT_SENIOR`."

        Design: Corner/validations/senior_audit_requires_grade_12_returns_409
        """
        assigned = create_advisor(max_caseload=10)
        auditor = create_advisor(max_caseload=10)
        student = create_student(student_ref="NS1", grade_level=11,
                                 advisor_id=assigned["id"])
        resp = api.create_senior_audit(student["id"],
                                       {"auditor_advisor_id": auditor["id"]},
                                       ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_SENIOR)
        audits = validate_success(
            api.list_student_senior_audits(student["id"], ADMIN))
        assert audits == [], "no audit row may be created for a non-senior"


class TestCertifyGates:
    def test_sod_auditor_is_assigned_advisor_returns_409(self, api):
        """PRD §3.7: "The auditor identity check comes first, then segregation
        of duties: the `auditor_advisor_id` must differ from the student's
        current `assigned_advisor_id`, and a violation is
        `ERR_AUDITOR_IS_ASSIGNED_ADVISOR`."

        Design: Corner/validations/sod_auditor_is_assigned_advisor_returns_409
        """
        assigned = create_advisor(max_caseload=10)
        pathway = create_pathway(pathway_code="CRS")
        student = create_student(student_ref="SD1", advisor_id=assigned["id"])
        plan = create_active_plan(student, pathway["id"], assigned["id"])
        add_completed_enrollment(student["id"], plan["id"], assigned["id"],
                                 "CR24", 24)
        audit = create_senior_audit(student["id"], assigned["id"])
        transition_audit(audit["id"], assigned["id"], "IN_REVIEW")

        resp = api.transition_senior_audit(
            audit["id"], {"to_status": "CERTIFIED"},
            make_advisor_headers(assigned["id"]))
        validate_error(resp, ApiErrorId.ERR_AUDITOR_IS_ASSIGNED_ADVISOR)
        assert get_senior_audit(audit["id"])["status"] == "IN_REVIEW"

    def test_certify_blocked_pathway_incomplete_returns_409(self, api):
        """PRD §3.7: "pathway_requirements_met` must hold (else
        `ERR_PATHWAY_INCOMPLETE`)". PRD §3.7: "The `pathway_requirements_met`
        flag is true exactly when every course code in the student's `ACTIVE`
        plan's pathway's `required_course_codes` has a `COMPLETED` enrollment
        behind it."

        Design: Corner/validations/certify_blocked_pathway_incomplete_returns_409
        """
        ctx = setup_audit_in_review(
            pathway_overrides={"pathway_code": "PBIO",
                               "required_course_codes": ["BIO201"]})
        resp = api.transition_senior_audit(
            ctx["audit"]["id"], {"to_status": "CERTIFIED"},
            make_advisor_headers(ctx["auditor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_PATHWAY_INCOMPLETE)
        assert get_senior_audit(ctx["audit"]["id"])["status"] == "IN_REVIEW"

    def test_certify_blocked_certification_missing_returns_409(self, api):
        """PRD §3.7: "certification_requirement_met` must hold (else
        `ERR_CERTIFICATION_MISSING`)". PRD §3.7: "The
        `certification_requirement_met` flag is true when the pathway's
        required certification stands `PASSED` — and trivially true when the
        pathway requires none."

        Design: Corner/validations/certify_blocked_certification_missing_returns_409
        """
        ctx = setup_audit_in_review(
            pathway_overrides={"pathway_code": "CERTP",
                               "required_certification_code": "CNA",
                               "required_work_hours": 0})
        resp = api.transition_senior_audit(
            ctx["audit"]["id"], {"to_status": "CERTIFIED"},
            make_advisor_headers(ctx["auditor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_MISSING)

    def test_certify_blocked_work_hours_returns_409(self, api):
        """PRD §3.7: "work_hours_met` must hold (else
        `ERR_WORK_HOURS_SHORTFALL`)". PRD §3.7: "The `work_hours_met` flag is
        true when the summed `hours_logged` of the student's `COMPLETED`
        placements is at least the pathway's `required_work_hours`."

        Design: Corner/validations/certify_blocked_work_hours_returns_409
        """
        ctx = setup_audit_in_review(
            pathway_overrides={"pathway_code": "WH40",
                               "required_work_hours": 40})
        site = create_site(site_code="WHX", max_concurrent_placements=5)
        placement = create_placement(ctx["student"]["id"], site["id"],
                                     "2026-04-01T00:00:00Z",
                                     "2026-05-01T00:00:00Z", 10)
        confirm_placement(placement["id"])
        complete_placement(placement["id"], 30)

        resp = api.transition_senior_audit(
            ctx["audit"]["id"], {"to_status": "CERTIFIED"},
            make_advisor_headers(ctx["auditor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_WORK_HOURS_SHORTFALL)


class TestCreditsThreshold:
    """Difficulty instance: credits_earned == 24 passes, 23.5 fails."""

    def test_exact_24_credits_certifies(self, api):
        """PRD §3.7: "the clearance comparison is exact: `credits_earned` must
        be at least `required_credits`, and equality passes." PRD §3.7: "The
        audit snapshots `required_credits` at 24, the district's graduation
        requirement".

        Design: Difficulty/boundary_precision_check/audit_credits_exact_threshold
        """
        ctx = setup_audit_in_review(credits=24)
        certified = transition_audit(ctx["audit"]["id"],
                                     ctx["auditor"]["id"], "CERTIFIED")
        assert_senior_audit(certified)
        assert certified["status"] == "CERTIFIED"
        assert certified["credits_earned"] == 24
        assert certified["certified_at"] is not None

    def test_23_5_credits_shortfall(self, api):
        """PRD §3.7: "`credits_earned` must meet or exceed the 24-credit
        snapshot (else `ERR_CREDITS_SHORTFALL`)".

        Design: Difficulty/boundary_precision_check/audit_credits_exact_threshold
        """
        ctx = setup_audit_in_review(credits=23.5, grade="B")
        resp = api.transition_senior_audit(
            ctx["audit"]["id"], {"to_status": "CERTIFIED"},
            make_advisor_headers(ctx["auditor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_CREDITS_SHORTFALL)
        assert get_senior_audit(ctx["audit"]["id"])["status"] == "IN_REVIEW"


class TestOpenEnrollmentsGate:
    """Difficulty instance: SeniorAudit x CourseEnrollment gate."""

    def _setup_open_enrollment(self):
        ctx = setup_audit_in_review()
        enr = add_enrollment(ctx["student"]["id"], ctx["plan"]["id"],
                             ctx["assigned"]["id"], "OPEN1", 2)
        transition_enrollment(enr["id"], ctx["assigned"]["id"], "ENROLLED")
        return ctx, enr

    def test_certify_blocked_by_open_enrollment(self, api):
        """PRD §3.7: "no enrollment of the student may remain in `PLANNED` or
        `ENROLLED` (else `ERR_OPEN_ENROLLMENTS`)".

        Design: Difficulty/cross_entity_state_dependency/audit_certify_blocked_by_open_enrollment
        """
        ctx, enr = self._setup_open_enrollment()
        resp = api.transition_senior_audit(
            ctx["audit"]["id"], {"to_status": "CERTIFIED"},
            make_advisor_headers(ctx["auditor"]["id"]))
        validate_error(resp, ApiErrorId.ERR_OPEN_ENROLLMENTS)

    def test_audit_stays_in_review_after_open_enrollment_rejection(self, api):
        """PRD §3.7: "no enrollment of the student may remain in `PLANNED` or
        `ENROLLED` (else `ERR_OPEN_ENROLLMENTS`)". PRD §2.4: "The `version` is
        an integer that starts at 1 when the resource is created and
        increments by exactly 1 on every mutation of that resource."

        Design: Difficulty/cross_entity_state_dependency/audit_certify_blocked_by_open_enrollment
        """
        ctx, enr = self._setup_open_enrollment()
        before = get_senior_audit(ctx["audit"]["id"])
        api.transition_senior_audit(
            ctx["audit"]["id"], {"to_status": "CERTIFIED"},
            make_advisor_headers(ctx["auditor"]["id"]))
        after = get_senior_audit(ctx["audit"]["id"])
        assert after["status"] == "IN_REVIEW"
        assert after["version"] == before["version"]


class TestCertifiedAuditAutoFlag:
    """Difficulty instance: post-certification drift flips CERTIFIED ->
    FLAGGED with AUTO_DRIFT."""

    def _setup_certified_then_new_completion(self):
        ctx = setup_certified_audit()
        enr2 = add_enrollment(ctx["student"]["id"], ctx["plan"]["id"],
                              ctx["assigned"]["id"], "ELECT6", 4)
        transition_enrollment(enr2["id"], ctx["assigned"]["id"], "ENROLLED")
        return ctx, enr2

    def test_completion_flags_certified_audit(self, api):
        """PRD §3.7: "When a later cascade — an enrollment completion,
        failure, or drop, a certification pass, a placement completion or
        termination — changes any audited input, the `CERTIFIED` audit
        auto-flags: it moves to `FLAGGED` with `flag_reason` set to
        `AUTO_DRIFT`, its `certified_at` is cleared to null, and its `version`
        increments."

        Design: Difficulty/transitive_cascade/enrollment_completion_flags_certified_audit
        """
        ctx, enr2 = self._setup_certified_then_new_completion()
        transition_enrollment(enr2["id"], ctx["assigned"]["id"], "COMPLETED",
                              grade="A")
        audit = get_senior_audit(ctx["audit"]["id"])
        assert audit["status"] == "FLAGGED"
        assert audit["flag_reason"] == "AUTO_DRIFT"
        assert audit["certified_at"] is None

    def test_flagged_audit_refreshes_credits(self, api):
        """PRD §3.7: "Four computed flags carry the audit's verdict, and all
        four refresh continuously while the audit is anything but
        `CERTIFIED`." PRD §3.7: "The `credits_earned` figure sums `credits`
        over the student's `COMPLETED` enrollments".

        Design: Difficulty/transitive_cascade/enrollment_completion_flags_certified_audit
        """
        ctx, enr2 = self._setup_certified_then_new_completion()
        transition_enrollment(enr2["id"], ctx["assigned"]["id"], "COMPLETED",
                              grade="A")
        audit = get_senior_audit(ctx["audit"]["id"])
        assert audit["status"] == "FLAGGED"
        assert audit["credits_earned"] == 28, (
            "refresh resumes once the audit leaves CERTIFIED (24 + 4)"
        )


class TestGraduation:
    def test_graduate_without_certified_audit_returns_409(self, api):
        """PRD §3.7: "Graduation itself is a `DistrictAdmin` act with a single
        hard precondition: a senior audit for the student must stand
        `CERTIFIED`, or the attempt is `ERR_NO_CERTIFIED_AUDIT`."

        Design: Corner/validations/graduate_without_certified_audit_returns_409
        """
        advisor = create_advisor(max_caseload=10)
        student = create_student(student_ref="GA1", advisor_id=advisor["id"])
        resp = api.graduate_student(student["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_CERTIFIED_AUDIT)
        assert get_student(student["id"])["status"] == "ENROLLED"

    def test_graduate_cascade_closes_open_work(self, api):
        """PRD §3.7: "Graduation stamps `graduated_at`, increments the
        student's `version`, and fires the closing cascade — every application
        still in `DRAFT`, `READY`, or `SUBMITTED` moves to `WITHDRAWN` with
        its own withdrawal side effects firing (milestone waiver included),
        every recommendation request in `REQUESTED` or `ACCEPTED` moves to
        `WITHDRAWN`, and every certification in `REGISTERED` or
        `EXAM_SCHEDULED` moves to `CANCELLED`."

        Design: Corner/cross_cutting_complexity_layers/graduate_cascade_closes_open_work
        """
        ctx = setup_certified_audit()
        student = ctx["student"]
        teacher = create_teacher(full_name="GC Tee")
        app = create_application(student)
        seeded = list_milestones(app["id"])
        rr = create_rec_request(student, teacher["id"])
        cert = create_certification(student["id"], "OSHA")
        schedule_certification(cert["id"], "2026-05-20T09:00:00Z")
        assert get_teacher(teacher["id"])["open_request_count"] == 1

        graduated = validate_success(api.graduate_student(student["id"],
                                                          ADMIN))
        assert graduated["status"] == "GRADUATED"
        assert graduated["graduated_at"] is not None

        app_after = validate_success(api.get_application(app["id"], ADMIN))
        assert app_after["submission_status"] == "WITHDRAWN"
        milestones_after = list_milestones(app["id"])
        assert all(m["status"] == "WAIVED" for m in milestones_after), (
            "application withdrawal waives milestones still PENDING or READY"
        )

        rr_after = validate_success(
            api.get_recommendation_request(rr["id"], ADMIN))
        assert rr_after["status"] == "WITHDRAWN"
        assert get_teacher(teacher["id"])["open_request_count"] == 0

        cert_after = validate_success(api.get_certification(cert["id"], WBL))
        assert cert_after["status"] == "CANCELLED"


class TestOutcomes:
    def test_pre_graduation_outcome_rejected(self, api):
        """PRD §3.8: "Recording an outcome for a student who has not graduated
        is `ERR_STUDENT_NOT_GRADUATED`".

        Design: Difficulty/cross_entity_state_dependency/outcome_requires_graduated_student
        """
        ctx = setup_audit_in_review()
        resp = api.create_outcome_record(
            ctx["student"]["id"],
            {"outcome_type": "ENROLLED_4YR",
             "reported_at": "2026-05-02T00:00:00Z",
             "institution_name": "State U"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_GRADUATED)

    def test_post_graduation_outcome_recorded_unverified(self, api):
        """PRD §3.8: "The record's `verification_status` starts `UNVERIFIED`".
        PRD §3.7: "Graduation stamps `graduated_at`, increments the student's
        `version`".

        Design: Difficulty/cross_entity_state_dependency/outcome_requires_graduated_student
        """
        ctx = setup_graduated_student()
        assert ctx["student"]["status"] == "GRADUATED"
        assert ctx["student"]["graduated_at"] is not None

        created = validate_success(
            api.create_outcome_record(
                ctx["student"]["id"],
                {"outcome_type": "ENROLLED_4YR",
                 "reported_at": "2026-05-02T00:00:00Z",
                 "institution_name": "State U"},
                ADMIN,
            ),
            expected_status=201,
        )
        assert_outcome_record(created)
        assert created["verification_status"] == "UNVERIFIED"

    def test_second_outcome_record_returns_409(self, api):
        """PRD §3.8: "a second record for the same student is
        `ERR_OUTCOME_EXISTS` — the record is one per student."

        Design: Corner/validations/second_outcome_record_returns_409
        """
        ctx = setup_graduated_student()
        validate_success(api.create_outcome_record(
            ctx["student"]["id"],
            {"outcome_type": "EMPLOYED",
             "reported_at": "2026-05-02T00:00:00Z"},
            ADMIN), expected_status=201)

        resp = api.create_outcome_record(
            ctx["student"]["id"],
            {"outcome_type": "APPRENTICESHIP",
             "reported_at": "2026-05-03T00:00:00Z"},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_OUTCOME_EXISTS)

    def test_outcome_verified_terminal_lockdown_returns_409(self, api):
        """PRD §3.8: "the district may then verify it, stamping `verified_at`,
        or dispute it, and a `DISPUTED` record may later be verified after
        all. `VERIFIED` is terminal". PRD §2.6: "The entity sits in a
        from-state for the requested transition, and terminal lockdown holds.
        Failures yield `ERR_INVALID_STATE`".

        Design: Corner/state_machines/outcome_verified_terminal_lockdown_returns_409
        """
        ctx = setup_graduated_student()
        outcome = validate_success(api.create_outcome_record(
            ctx["student"]["id"],
            {"outcome_type": "EMPLOYED",
             "reported_at": "2026-05-02T00:00:00Z"},
            ADMIN), expected_status=201)
        verified = validate_success(
            api.transition_outcome_record(outcome["id"],
                                          {"to_status": "VERIFIED"}, ADMIN))
        assert verified["verification_status"] == "VERIFIED"

        resp = api.transition_outcome_record(outcome["id"],
                                             {"to_status": "DISPUTED"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api.get_outcome_record(outcome["id"], ADMIN))
        assert after["verification_status"] == "VERIFIED"
