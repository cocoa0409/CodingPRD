"""Concern-report intake: roster defaults, intake guards, review triage.

PRD §3.1 covers roster registration, the enrollment gate, required fields,
related-report threading, and the SUBMITTED -> UNDER_REVIEW -> terminal
review machine.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    accept_report_and_get_case,
    create_staff,
    create_student,
    get_success_data,
    setup_case_in_intake,
    setup_staff_group,
    submit_report,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import (
    make_bit_chair_headers,
    make_reporter_headers,
    make_system_admin_headers,
)


class TestStudentCreationDefaults:
    def test_student_created_enrolled_version_one(self, api, system_admin_headers):
        """PRD §3.1: "A `SystemAdmin` registers each student with a
        campus-unique `external_ref` (the student number) and a `full_name`;
        the record's `enrollment_status` begins at `ENROLLED`."
        PRD §2.4: "`version` (integer): starts at its initial value on creation
        and increments by one on every mutation, including mutations caused by
        cascades rather than direct client writes."

        Design: Corner/entities/student_creation_applies_defaults
        """
        created = validate_success(
            api.create_student(
                {"external_ref": "S0001", "full_name": "Stu Zero"}, system_admin_headers
            ),
            expected_status=201,
        )
        assert created["enrollment_status"] == "ENROLLED"
        assert created["version"] == 1
        assert isinstance(created["id"], str) and created["id"]
        fetched = validate_success(api.get_student(created["id"], system_admin_headers))
        assert fetched["enrollment_status"] == "ENROLLED"
        assert fetched["id"] == created["id"]


class TestStaffOfficeEnum:
    def test_staff_office_outside_enum_rejected(self, api, system_admin_headers):
        """PRD §3.1: "Staff are registered the same way, with a `full_name`, a
        home `office` drawn from `FACULTY_AFFAIRS`, `RESIDENCE_LIFE`,
        `COUNSELING_CENTER`, `DEAN_OF_STUDENTS`, `BIT_OFFICE`, `CAMPUS_SAFETY`,
        or `PRIVACY_OFFICE`, and an `active` flag that defaults to true."

        Design: Corner/entities/staff_office_enum_invalid_rejected
        """
        resp = api.create_staff(
            {"full_name": "Bad Office", "office": "LIBRARY"}, system_admin_headers
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestReportRequiredFields:
    def test_missing_narrative_rejected(self, api):
        """PRD §2.10: "9. **Field and constraint checks** — rubric range,
        scoring-mode consistency, enum and required-field validity, non-empty
        `objectives`, evaluator distinct from orderer, disclosure and trend
        window sanity, non-empty re-entry `conditions`, closure eligibility,
        open-plan exclusion, and pending-petition exclusion; failures yield
        `ERR_RUBRIC_SCORE_OUT_OF_RANGE`, `ERR_SCORING_MODE_INVALID`,
        `ERR_VALIDATION`, ..."

        Design: Corner/entities/concern_report_missing_required_narrative
        """
        ctx = setup_staff_group(chair=False, case_manager=False)
        student = create_student(external_ref="S0002")
        resp = api.create_concern_report(
            {
                "student_id": student["id"],
                "category": "WELLBEING_GENERAL",
                "observed_at": "2026-08-01T09:00:00Z",
            },
            ctx["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestReportReviewMachine:
    def test_accept_from_submitted_rejected(self, api):
        """PRD §3.1: "Starting review on a report that is not `SUBMITTED` is
        rejected with `ERR_REPORT_NOT_UNDER_REVIEW` — the same code that guards
        the other two transitions, which both require `UNDER_REVIEW`."

        Design: Corner/state_machines/report_accept_from_submitted_returns_invalid_state
        """
        ctx = setup_staff_group()
        student = create_student(external_ref="S0006")
        report = submit_report(ctx, student["id"])
        resp = api.accept_concern_report(
            report["id"], {"case_manager_id": ctx["cm"]["id"]}, ctx["chair_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_REPORT_NOT_UNDER_REVIEW)
        cases, meta = validate_paginated(
            api.list_care_cases(ctx["chair_headers"], params={"student_id": student["id"]})
        )
        assert meta["total_count"] == 0

    def test_start_review_then_accept_creates_intake_case(self, api):
        """PRD §3.1: "Otherwise acceptance creates a new `CareCase` in
        `INTAKE`, copying the report's `student_id`, recording
        `opened_from_report_id` as the report being accepted, and assigning the
        referenced case manager as `assigned_case_manager_id`; the report's
        `care_case_id` then points at the new case."

        Design: Corner/consistency_model/immediate_visibility_after_accept
        """
        ctx = setup_staff_group()
        student = create_student(external_ref="S0038")
        report = submit_report(ctx, student["id"], category="ACADEMIC_DISTRESS")
        accepted, case_id = accept_report_and_get_case(ctx, report["id"])
        assert accepted["status"] == "ACCEPTED"
        assert accepted["care_case_id"] == case_id
        case = validate_success(api.get_care_case(case_id, ctx["chair_headers"]))
        assert case["status"] == "INTAKE"
        assert case["assigned_case_manager_id"] == ctx["cm"]["id"]
        assert case["opened_from_report_id"] == report["id"]
        assert case["student_id"] == student["id"]


class TestEnrollmentGate:
    def test_report_for_withdrawn_student_rejected(self, api, system_admin_headers):
        """PRD §3.1: "Two guards fire before the report exists: the subject
        student must exist (`ERR_NOT_FOUND`), and a report about a `WITHDRAWN`
        student is rejected with `ERR_STUDENT_NOT_ACTIVE` (HTTP 409) — a
        rejection that, per the §2.10 ladder, the caller sees before any
        cross-reference mismatch."

        Design: Difficulty/cross_entity_state_dependency/report_requires_student_enrolled
        """
        ctx = setup_staff_group(chair=True, case_manager=False)
        student = create_student(external_ref="S9002", full_name="Stu Out")
        validate_success(
            api.patch_student(student["id"], {"enrollment_status": "WITHDRAWN"}, system_admin_headers)
        )
        resp = api.create_concern_report(
            {
                "student_id": student["id"],
                "category": "WELLBEING_GENERAL",
                "narrative": "worried",
                "observed_at": "2026-08-01T09:00:00Z",
            },
            ctx["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_STUDENT_NOT_ACTIVE)
        reports, meta = validate_paginated(
            api.list_concern_reports(ctx["chair_headers"], params={"student_id": student["id"]})
        )
        assert meta["total_count"] == 0


class TestEnrollmentGateReopened:
    def test_report_accepted_after_student_returns_to_enrolled(self, api, system_admin_headers):
        """PRD §3.1: "Two guards fire before the report exists: the subject
        student must exist (`ERR_NOT_FOUND`), and a report about a `WITHDRAWN`
        student is rejected with `ERR_STUDENT_NOT_ACTIVE` (HTTP 409) — a
        rejection that, per the §2.10 ladder, the caller sees before any
        cross-reference mismatch."
        PRD §3.1: "Thereafter `enrollment_status` moves among three values —
        `ENROLLED`, `LEAVE_OF_ABSENCE`, and `WITHDRAWN` — but only the first
        and third are under administrative control: a `SystemAdmin` may correct
        a record between `ENROLLED` and `WITHDRAWN` in either direction, and
        each such correction increments the student's `version`."

        Design: Difficulty/cross_entity_state_dependency/report_requires_student_enrolled
        """
        ctx = setup_staff_group(chair=True, case_manager=False)
        student = create_student(external_ref="S9002B", full_name="Stu Back")
        validate_success(
            api.patch_student(student["id"], {"enrollment_status": "WITHDRAWN"}, system_admin_headers)
        )
        blocked = api.create_concern_report(
            {
                "student_id": student["id"],
                "category": "WELLBEING_GENERAL",
                "narrative": "worried",
                "observed_at": "2026-08-01T09:00:00Z",
            },
            ctx["rep_headers"],
        )
        validate_error(blocked, ApiErrorId.ERR_STUDENT_NOT_ACTIVE)
        # Administrative correction back to ENROLLED reopens intake.
        validate_success(
            api.patch_student(student["id"], {"enrollment_status": "ENROLLED"}, system_admin_headers)
        )
        created = validate_success(
            api.create_concern_report(
                {
                    "student_id": student["id"],
                    "category": "WELLBEING_GENERAL",
                    "narrative": "worried again",
                    "observed_at": "2026-08-01T10:00:00Z",
                },
                ctx["rep_headers"],
            ),
            expected_status=201,
        )
        assert created["status"] == "SUBMITTED"
        assert created["student_id"] == student["id"]


class TestRelatedReportThreading:
    def test_related_report_link_recorded_and_queryable(self, api):
        """PRD §3.1: "An optional `related_report_id` may thread the new report
        to a prior report, but only when that prior report concerns the same
        student; a cross-student link is rejected with
        `ERR_RELATED_REPORT_STUDENT_MISMATCH` (HTTP 422)."

        Design: Corner/entities/related_report_chain_link
        """
        ctx = setup_staff_group()
        student = create_student(external_ref="S0005")
        r1 = submit_report(ctx, student["id"], category="ACADEMIC_DISTRESS",
                           narrative="first", observed_at="2026-07-31T10:00:00Z")
        r2 = submit_report(ctx, student["id"], category="WELLBEING_GENERAL",
                           narrative="follow-up", observed_at="2026-08-01T08:00:00Z",
                           related_report_id=r1["id"])
        assert r2["related_report_id"] == r1["id"]
        reports, meta = validate_paginated(
            api.list_concern_reports(
                ctx["chair_headers"], params={"related_report_id": r1["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert reports[0]["id"] == r2["id"]

    def test_related_report_for_other_student_rejected(self, api):
        """PRD §3.1: "An optional `related_report_id` may thread the new report
        to a prior report, but only when that prior report concerns the same
        student; a cross-student link is rejected with
        `ERR_RELATED_REPORT_STUDENT_MISMATCH` (HTTP 422)."

        Design: Corner/errors/related_report_student_mismatch_rejected
        """
        ctx = setup_staff_group(chair=False, case_manager=False)
        s1 = create_student(external_ref="S0028", full_name="Stu One")
        s2 = create_student(external_ref="S0029", full_name="Stu Two")
        r1 = submit_report(ctx, s2["id"], category="ACADEMIC_DISTRESS",
                           narrative="about s2")
        resp = api.create_concern_report(
            {
                "student_id": s1["id"],
                "category": "WELLBEING_GENERAL",
                "narrative": "about s1",
                "observed_at": "2026-08-01T09:00:00Z",
                "related_report_id": r1["id"],
            },
            ctx["rep_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RELATED_REPORT_STUDENT_MISMATCH)


class TestAcceptLinksExistingOpenCase:
    def test_second_accept_links_to_same_case(self, api):
        """PRD §3.1: "If the student already has a care case in any status other
        than `CLOSED`, the report is simply linked: its `care_case_id` is set to
        that case's `id`, and the case itself is left entirely untouched — state
        unchanged, `version` unchanged, manager assignment unchanged."

        Design: Corner/endpoints/accept_links_existing_open_case
        """
        ctx = setup_staff_group()
        student = create_student(external_ref="S0023")
        r1 = submit_report(ctx, student["id"], category="ACADEMIC_DISTRESS",
                           narrative="first")
        _, case_a = accept_report_and_get_case(ctx, r1["id"])
        r2 = submit_report(ctx, student["id"], category="WELLBEING_GENERAL",
                           narrative="second", observed_at="2026-08-01T09:00:00Z",
                           related_report_id=r1["id"])
        get_success_data(api.start_review_concern_report(r2["id"], ctx["chair_headers"]))
        accepted2 = validate_success(
            api.accept_concern_report(
                r2["id"], {"case_manager_id": ctx["cm"]["id"]}, ctx["chair_headers"]
            )
        )
        assert accepted2["status"] == "ACCEPTED"
        assert accepted2["care_case_id"] == case_a
        cases, meta = validate_paginated(
            api.list_care_cases(ctx["chair_headers"], params={"student_id": student["id"]})
        )
        assert meta["total_count"] == 1
        assert cases[0]["id"] == case_a


class TestReporterOwnReportsOnly:
    def test_reporter_reads_own_but_not_others_reports(self, api):
        """PRD §2.8: "A `Reporter` reading a concern report may read only
        reports whose `reporter_id` matches their own `X-User-ID`; reading
        another reporter's report is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/reporter_reads_only_own_reports
        """
        ctx = setup_staff_group(chair=False, case_manager=False, reporter2=True)
        student = create_student(external_ref="S0034")
        r1 = submit_report(ctx, student["id"], narrative="rep1 report")
        denied = api.get_concern_report(r1["id"], ctx["rep2_headers"])
        validate_error(denied, ApiErrorId.ERR_FORBIDDEN)
        own = validate_success(api.get_concern_report(r1["id"], ctx["rep_headers"]))
        assert own["id"] == r1["id"]
