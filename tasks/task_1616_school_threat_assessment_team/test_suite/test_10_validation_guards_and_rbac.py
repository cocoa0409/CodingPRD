"""Domain error guards, validation ordering, and role-based access control."""
from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    append_document,
    build_user_headers,
    complete_interview_payload,
    create_assessment_payload,
    create_case,
    create_case_payload,
    create_checkin_payload,
    create_interview_payload,
    create_plan_payload,
    create_reentry_plan_payload,
    create_referral_payload,
    create_school,
    get_case,
    list_case_assessments,
    make_team_lead_headers,
    make_threat_assessor_headers,
    propose_reentry_plan,
    schedule_interview,
    screening_payload,
    setup_case_plan_active,
    setup_case_removed,
    setup_case_under_assessment,
    triage_case,
    triage_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

IC = TEST_USERS["intake_coordinator_headers"]
TA = TEST_USERS["threat_assessor_headers"]
TL = TEST_USERS["team_lead_headers"]
DA = TEST_USERS["district_admin_headers"]
TA1 = make_threat_assessor_headers("ta_1")
TL2 = make_team_lead_headers("tl_2")


class TestAuthenticationHeader:
    def test_unknown_role_returns_unauthenticated_header_error(self, api):
        """PRD: "A request missing either header, or carrying a role outside
        these four, is rejected with
        `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

        Design: Corner/validations/unknown_role_returns_unauthenticated_header_error
        """
        resp = api.list_cases(build_user_headers("sup_1", "Superintendent"))
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestRequestSchemaValidation:
    def test_triage_missing_priority_returns_invalid_request(self, api):
        """PRD: "Third, the request body's schema is validated — required
        fields present, types correct, enum values among their declared sets,
        and non-empty constraints on required strings and arrays such as
        `conditions`, `decline_reason`, `denial_reason`, and `summary`; any
        failure here is `ERR_INVALID_REQUEST`."
        PRD: "The coordinator supplies a `triage_priority` of `ROUTINE`,
        `URGENT`, or `EMERGENT` — any other value is `ERR_INVALID_REQUEST` —
        together with free-text `triage_notes`."

        Design: Corner/validations/triage_missing_priority_returns_invalid_request
        """
        school = create_school(name="Format HS", school_code="FMT")
        case = create_case(school["id"], subject_alias="STU-F",
                           summary="format")
        resp = api.triage_case(case["id"],
                               {"triage_notes": "missing priority field"}, IC)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestBodyReferenceExistence:
    def test_body_school_fk_not_found_returns_404(self, api):
        """PRD: "Fourth, path identifiers are resolved left to right, and the
        first identifier that does not correspond to an existing resource
        produces a 404: `ERR_CASE_NOT_FOUND` when the missing resource is a
        threat case (whether referenced in the path or through a body
        `case_id`), `ERR_SCHOOL_NOT_FOUND` when a body `school_id` references
        a school that does not exist, `ERR_CONDITION_NOT_FOUND` when a
        `conditionIndex` path segment falls outside the referenced plan's
        `conditions` array, and `ERR_NOT_FOUND` for any other missing path
        resource."

        Design: Corner/validations/body_school_fk_not_found_returns_404
        """
        resp = api.create_case(
            create_case_payload(NON_EXISTENT_UUID, subject_alias="STU-NF",
                                summary="bad school"),
            IC,
        )
        validate_error(resp, ApiErrorId.ERR_SCHOOL_NOT_FOUND)


class TestCaseStateGuards:
    def test_case_state_guards_on_child_creation(self, api):
        """PRD: "While a case is `UNDER_ASSESSMENT`, a `ThreatAssessor`
        schedules interviews against it; a case in any other state rejects
        scheduling with `ERR_CASE_NOT_UNDER_ASSESSMENT`."
        PRD: "A `ThreatAssessor` drafts a risk assessment for a case that is
        `UNDER_ASSESSMENT` or `PLAN_ACTIVE` (any other state is
        `ERR_CASE_NOT_ASSESSABLE`), provided the case does not already have an
        open assessment — one in `DRAFT` or `SUBMITTED` — in which case the
        create is rejected with `ERR_OPEN_ASSESSMENT_EXISTS`."
        PRD: "Drafting requires the case to be `UNDER_ASSESSMENT` or
        `PLAN_ACTIVE` (`ERR_CASE_NOT_PLANNABLE` otherwise) and requires that
        some assessment for the case has actually been finalized
        (`ERR_NO_FINALIZED_ASSESSMENT` otherwise)."
        PRD: "The case must still be open — referral creation is permitted
        while the case is `TRIAGED`, `UNDER_ASSESSMENT`, `PLAN_ACTIVE`, or
        `REMOVED`, and anything else is rejected with `ERR_CASE_NOT_OPEN`."

        Design: Corner/errors/case_state_guards_return_domain_errors
        """
        school = create_school(name="Guards HS", school_code="GRD")
        case_x = create_case(school["id"], subject_alias="STU-X",
                             summary="intake case")
        case_y = create_case(school["id"], subject_alias="STU-Y",
                             summary="triaged case")
        triage_case(case_y["id"])

        referral_resp = api.create_referral(
            create_referral_payload(case_x["id"]), TA1)
        validate_error(referral_resp, ApiErrorId.ERR_CASE_NOT_OPEN)

        interview_resp = api.create_interview(
            create_interview_payload(case_y["id"]), TA1)
        validate_error(interview_resp, ApiErrorId.ERR_CASE_NOT_UNDER_ASSESSMENT)

        assessment_resp = api.create_assessment(
            create_assessment_payload(
                case_y["id"],
                factors=[{"factor_code": "PEER_REPORTS", "severity": 1}]),
            TA1,
        )
        validate_error(assessment_resp, ApiErrorId.ERR_CASE_NOT_ASSESSABLE)

        plan_resp = api.create_plan(
            create_plan_payload(case_y["id"], conditions=["x"]), TA1)
        validate_error(plan_resp, ApiErrorId.ERR_CASE_NOT_PLANNABLE)

    def test_case_state_guards_on_case_actions(self, api):
        """PRD: "A `ThreatAssessor` creates one against a `PLAN_ACTIVE` case
        (`ERR_CASE_NOT_PLAN_ACTIVE` otherwise) by supplying `case_id` and a
        `due_date` calendar date."
        PRD: "The case must be `UNDER_ASSESSMENT` or `PLAN_ACTIVE`
        (`ERR_CASE_NOT_REMOVABLE` otherwise), and the call supplies a
        `removal_type` of `EMERGENCY_REMOVAL` or `DISCIPLINARY_EXCLUSION`
        (any other value is `ERR_INVALID_REQUEST`) along with a free-text
        `removal_reason`."
        PRD: "Closure is the managed end-state for a case that is
        `PLAN_ACTIVE` (`ERR_CASE_NOT_CLOSABLE` from anywhere else)."

        Design: Corner/errors/case_state_guards_return_domain_errors
        """
        school = create_school(name="Guards HS 2", school_code="GR2")
        case_y = create_case(school["id"], subject_alias="STU-Y2",
                             summary="triaged case")
        triage_case(case_y["id"])
        case_z = setup_case_under_assessment(school_id=school["id"])

        checkin_resp = api.create_checkin(
            create_checkin_payload(case_z["id"], "2026-08-10"), TA1)
        validate_error(checkin_resp, ApiErrorId.ERR_CASE_NOT_PLAN_ACTIVE)

        remove_resp = api.remove_case(
            case_y["id"],
            {"removal_type": "EMERGENCY_REMOVAL", "removal_reason": "too early"},
            TL,
        )
        validate_error(remove_resp, ApiErrorId.ERR_CASE_NOT_REMOVABLE)

        close_resp = api.close_case(case_z["id"], TL)
        validate_error(close_resp, ApiErrorId.ERR_CASE_NOT_CLOSABLE)


class TestResourceStateGuards:
    def test_submit_and_activate_on_terminal_states(self, api):
        """PRD: "Submitting moves the assessment from `DRAFT` to `SUBMITTED`
        for team-lead review."
        PRD: "While the assessment remains `DRAFT`, the assessor may replace
        its `variant`, its `factors`, or both; the server recomputes the
        scores on every such update, and an update attempted on a non-`DRAFT`
        assessment is `ERR_ASSESSMENT_NOT_DRAFT`."
        PRD: "After the stale-version check, the gates evaluate in order: the
        plan must be `DRAFT` (`ERR_PLAN_NOT_DRAFT`); the case must be
        `UNDER_ASSESSMENT` or `PLAN_ACTIVE` (`ERR_CASE_NOT_PLANNABLE`); when
        the case's `risk_level` is `HIGH` or `IMMINENT`, a law-enforcement
        referral in `ACKNOWLEDGED` status must exist for the case
        (`ERR_LE_REFERRAL_REQUIRED`); and a `FINALIZED` assessment must exist
        for the case (`ERR_NO_FINALIZED_ASSESSMENT`)."

        Design: Corner/errors/resource_state_guards_return_domain_errors
        """
        case, _ra, plan, _chk = setup_case_plan_active(cadence_days=7)
        assessments, _meta = list_case_assessments(case["id"],
                                                   status="FINALIZED")
        finalized_id = assessments[0]["id"]

        submit_resp = api.submit_assessment(finalized_id, TA1)
        validate_error(submit_resp, ApiErrorId.ERR_ASSESSMENT_NOT_DRAFT)

        # The OCC check passes with the fresh version, then the plan-state
        # gate fires.
        activate_resp = api.activate_plan(
            plan["id"], get_case(case["id"])["version"], TL)
        validate_error(activate_resp, ApiErrorId.ERR_PLAN_NOT_DRAFT)

    def test_complete_on_cancelled_and_ghost_interview(self, api):
        """PRD: "Completing an interview — again `ThreatAssessor` work —
        requires it to still be `SCHEDULED` (`ERR_INTERVIEW_NOT_SCHEDULED`
        otherwise) and records the assessor's `findings_score`, an integer
        rating from 0 to 10 inclusive, together with a non-empty `summary`; an
        out-of-range score or empty summary is `ERR_INVALID_REQUEST`."
        PRD: "Fourth, path identifiers are resolved left to right, and the
        first identifier that does not correspond to an existing resource
        produces a 404: `ERR_CASE_NOT_FOUND` when the missing resource is a
        threat case (whether referenced in the path or through a body
        `case_id`), `ERR_SCHOOL_NOT_FOUND` when a body `school_id` references
        a school that does not exist, `ERR_CONDITION_NOT_FOUND` when a
        `conditionIndex` path segment falls outside the referenced plan's
        `conditions` array, and `ERR_NOT_FOUND` for any other missing path
        resource."

        Design: Corner/errors/resource_state_guards_return_domain_errors
        """
        case = setup_case_under_assessment()
        interview = schedule_interview(case["id"])
        validate_success(api.cancel_interview(interview["id"], TA1), 200)

        cancelled_resp = api.complete_interview(
            interview["id"],
            complete_interview_payload(findings_score=5, summary="too late"),
            TA1,
        )
        validate_error(cancelled_resp, ApiErrorId.ERR_INTERVIEW_NOT_SCHEDULED)

        ghost_resp = api.complete_interview(
            NON_EXISTENT_UUID,
            complete_interview_payload(findings_score=5, summary="ghost"),
            TA1,
        )
        validate_error(ghost_resp, ApiErrorId.ERR_NOT_FOUND)


class TestOpenUniquenessGuards:
    def test_open_assessment_and_reentry_uniqueness(self, api):
        """PRD: "A `ThreatAssessor` drafts a risk assessment for a case that
        is `UNDER_ASSESSMENT` or `PLAN_ACTIVE` (any other state is
        `ERR_CASE_NOT_ASSESSABLE`), provided the case does not already have an
        open assessment — one in `DRAFT` or `SUBMITTED` — in which case the
        create is rejected with `ERR_OPEN_ASSESSMENT_EXISTS`."
        PRD: "Drafting requires the case to be `UNDER_ASSESSMENT` or
        `PLAN_ACTIVE` (`ERR_CASE_NOT_PLANNABLE` otherwise) and requires that
        some assessment for the case has actually been finalized
        (`ERR_NO_FINALIZED_ASSESSMENT` otherwise)."
        PRD: "A `ThreatAssessor` proposes a re-entry plan for a `REMOVED` case
        (`ERR_CASE_NOT_REMOVED` otherwise), provided no other re-entry plan
        for the case is still open in `PROPOSED` or `APPROVED`
        (`ERR_OPEN_REENTRY_PLAN_EXISTS`)."

        Design: Corner/errors/open_uniqueness_guards_return_domain_errors
        """
        school = create_school(name="Unique HS", school_code="UNQ")
        case_a = setup_case_under_assessment(school_id=school["id"])
        validate_success(
            api.create_assessment(
                create_assessment_payload(
                    case_a["id"],
                    factors=[{"factor_code": "PEER_REPORTS", "severity": 1}]),
                TA1),
            201,
        )

        second_resp = api.create_assessment(
            create_assessment_payload(
                case_a["id"],
                factors=[{"factor_code": "PEER_REPORTS", "severity": 2}]),
            TA1,
        )
        validate_error(second_resp, ApiErrorId.ERR_OPEN_ASSESSMENT_EXISTS)

        plan_resp = api.create_plan(
            create_plan_payload(case_a["id"], conditions=["x"]), TA1)
        validate_error(plan_resp, ApiErrorId.ERR_NO_FINALIZED_ASSESSMENT)

        case_b, _plan = setup_case_removed()
        propose_reentry_plan(case_b["id"], conditions=["cond zero", "cond one"])
        dup_resp = api.create_reentry_plan(
            create_reentry_plan_payload(case_b["id"], conditions=["another plan"]),
            TA1,
        )
        validate_error(dup_resp, ApiErrorId.ERR_OPEN_REENTRY_PLAN_EXISTS)

    def test_complete_reentry_requires_approved_plan_and_met_conditions(self, api):
        """PRD: "It requires the plan to be `APPROVED`
        (`ERR_REENTRY_NOT_APPROVED`), the case to be `REMOVED`
        (`ERR_CASE_NOT_REMOVED`), and every condition's `status` to be `MET` —
        a single `UNMET` condition blocks completion with
        `ERR_REENTRY_CONDITIONS_UNMET`."

        Design: Corner/errors/open_uniqueness_guards_return_domain_errors
        """
        case, _plan = setup_case_removed()
        plan = propose_reentry_plan(case["id"], conditions=["cond zero", "cond one"])

        early_resp = api.complete_reentry(plan["id"], TL2)
        validate_error(early_resp, ApiErrorId.ERR_REENTRY_NOT_APPROVED)

        validate_success(api.approve_reentry_plan(plan["id"], TL2), 200)
        validate_success(
            api.verify_reentry_condition(plan["id"], 0,
                                         {"evidence_note": "done"}, TA1),
            200,
        )
        unmet_resp = api.complete_reentry(plan["id"], TL2)
        validate_error(unmet_resp, ApiErrorId.ERR_REENTRY_CONDITIONS_UNMET)


class TestRbac:
    def test_intake_coordinator_cannot_finalize_assessment(self, api):
        """PRD: "A request whose role is not permitted for the target
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4 endpoint table: "POST | `/risk-assessments/{id}/finalize` |
        Finalize a submitted assessment; sets case risk level and fires the
        imminent cascade | TeamLead".

        Design: Corner/rbac/intake_coordinator_cannot_finalize_assessment
        """
        case = setup_case_under_assessment()
        assessment = validate_success(
            api.create_assessment(
                create_assessment_payload(
                    case["id"],
                    factors=[{"factor_code": "PEER_REPORTS", "severity": 1}]),
                TA1),
            201,
        )
        validate_success(api.submit_assessment(assessment["id"], TA1), 200)

        resp = api.finalize_assessment(assessment["id"], IC)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        _still, meta = list_case_assessments(case["id"], status="SUBMITTED")
        assert meta["total_count"] == 1, "a forbidden finalize changes nothing"

    def test_threat_assessor_cannot_triage_or_close(self, api):
        """PRD: "A request whose role is not permitted for the target
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4 endpoint table: "POST | `/threat-cases/{id}/triage` | Triage an
        `INTAKE` case | IntakeCoordinator".
        PRD §4 endpoint table: "POST | `/threat-cases/{id}/close` | Close a
        `PLAN_ACTIVE` case as managed | TeamLead".

        Design: Corner/rbac/threat_assessor_cannot_triage_or_close
        """
        school = create_school(name="RbacB HS", school_code="RBB")
        case_x = create_case(school["id"], subject_alias="STU-RBX", summary="x")
        case_y = setup_case_under_assessment(school_id=school["id"])

        triage_resp = api.triage_case(
            case_x["id"],
            triage_payload(triage_priority="ROUTINE",
                           triage_notes="assessor trying"),
            TA,
        )
        validate_error(triage_resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        close_resp = api.close_case(case_y["id"], TA)
        validate_error(close_resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_assessor_and_intake_cannot_read_audit_events(self, api):
        """PRD: "The audit trail is confidential: only `TeamLead` and
        `DistrictAdministrator` may read it, and the audit list accepts an
        optional `action` filter."

        Design: Corner/rbac/assessor_and_intake_cannot_read_audit_events
        """
        school = create_school(name="RbacC HS", school_code="RBC")
        case = create_case(school["id"], subject_alias="STU-RBC",
                           summary="audit rbac")

        assessor_resp = api.list_case_audit_events(case["id"], TA)
        validate_error(assessor_resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        intake_resp = api.list_case_audit_events(case["id"], IC)
        validate_error(intake_resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        events, meta = validate_paginated(
            api.list_case_audit_events(case["id"], DA))
        assert meta["total_count"] == 1
        assert events[0]["action"] == "CASE_CREATED"

    def test_sealed_documents_hidden_from_assessor_and_intake(self, api):
        """PRD: "Case documents may be marked `sealed`; sealed documents are
        withheld from list responses for `IntakeCoordinator` and
        `ThreatAssessor` callers and are visible only to `TeamLead` and
        `DistrictAdministrator` callers."

        Design: Corner/rbac/sealed_documents_hidden_from_assessor_and_intake
        """
        school = create_school(name="Seal HS", school_code="SEA")
        case = create_case(school["id"], subject_alias="STU-SEA",
                           summary="sealed docs")
        append_document(case["id"], doc_type="INTAKE_NOTE", body="visible note",
                        author=IC)
        append_document(case["id"], doc_type="LEGAL_HOLD", body="privileged",
                        sealed=True, author=TL)

        assessor_docs, assessor_meta = validate_paginated(
            api.list_case_documents(case["id"], TA))
        assert assessor_meta["total_count"] == 1
        assert assessor_docs[0]["doc_type"] == "INTAKE_NOTE"
        assert assessor_docs[0]["sealed"] is False

        intake_docs, intake_meta = validate_paginated(
            api.list_case_documents(case["id"], IC))
        assert intake_meta["total_count"] == 1

        lead_docs, lead_meta = validate_paginated(
            api.list_case_documents(case["id"], TL))
        assert lead_meta["total_count"] == 2
        sealed_docs = [d for d in lead_docs if d["sealed"]]
        assert len(sealed_docs) == 1
        assert sealed_docs[0]["doc_type"] == "LEGAL_HOLD"
        assert sealed_docs[0]["body"] == "privileged"

    def test_district_admin_cannot_perform_case_work(self, api):
        """PRD: "A request whose role is not permitted for the target
        operation is rejected with `ERR_INSUFFICIENT_PERMISSIONS`."
        PRD §4 endpoint table: "POST | `/threat-cases` | Intake a threat case
        from a tip line or staff referral | IntakeCoordinator".
        PRD §4 endpoint table: "POST | `/threat-cases/{id}/screening` | Record
        the initial screening for a `TRIAGED` case | ThreatAssessor".

        Design: Corner/rbac/district_admin_cannot_perform_case_work
        """
        school = create_school(name="RbacD HS", school_code="RBD")
        case = create_case(school["id"], subject_alias="STU-RBD",
                           summary="admin denial")

        create_resp = api.create_case(
            create_case_payload(school["id"], subject_alias="STU-RBD2",
                                summary="admin creating"),
            DA,
        )
        validate_error(create_resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

        screening_resp = api.record_screening(
            case["id"], screening_payload(3), DA)
        validate_error(screening_resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
