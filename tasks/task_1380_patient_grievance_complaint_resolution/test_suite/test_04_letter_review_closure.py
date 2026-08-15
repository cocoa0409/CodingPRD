"""Response-letter drafting, the review loop, approval gates, issuance,
closure cascades, and the complaint fast-track path."""
from test_helpers import (
    add_sufficient_notes,
    ApiErrorId,
    approve_letter,
    classify_case,
    create_case,
    create_letter_payload,
    create_staff,
    create_unit,
    draft_letter,
    FULL_LETTER_SECTIONS,
    get_case,
    get_case_version,
    get_follow_up_for_case,
    get_staff,
    get_success_data,
    make_director_headers,
    make_investigator_headers,
    make_qro_headers,
    open_investigation,
    set_clock,
    setup_assigned_case,
    setup_classified_case,
    setup_complaint_response_drafting,
    setup_letter_approved,
    setup_letter_in_review,
    setup_response_drafting,
    submit_findings,
    submit_letter_review,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["system_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


class TestLetterRevisionLoop:
    def test_letter_return_and_resubmit_cycle(self, api):
        """PRD §3.4: "Returning the letter (payload `return_reason`, which the
        letter stores on its own `return_reason` field) requires `IN_REVIEW`
        and moves the letter to `RETURNED` while the case falls back
        `RESPONSE_REVIEW` → `RESPONSE_DRAFTING`; the pair resubmits through
        the same content standard." and "Approval stamps `approved_by_id`,
        moves the letter to `APPROVED`, and the case `RESPONSE_REVIEW` →
        `PENDING_CLOSURE`."

        Design: Difficulty/non_linear_state_machine/response_letter_revision_loop_cycle
        """
        base = setup_letter_in_review(
            complaint=True, unit_name="Clinic West", unit_category="OUTPATIENT",
            patient_ref="P-5002", channel="PORTAL",
            description="Appointment rescheduling annoyance",
            grievance_category="ACCESS_DELAY")
        letter_id = base.letter["id"]

        returned = validate_success(api.return_letter(
            letter_id, {"return_reason": "Tone needs work"},
            make_director_headers(base.director["id"])))
        assert returned["status"] == "RETURNED", "revision loop edge IN_REVIEW -> RETURNED"
        assert returned["return_reason"] == "Tone needs work"

        resubmitted = submit_letter_review(letter_id, base.inv["id"])
        assert resubmitted["status"] == "IN_REVIEW", (
            "loop edge RETURNED -> IN_REVIEW taken a second time")

        approved = approve_letter(letter_id, base.director["id"])
        assert approved["status"] == "APPROVED"
        assert get_case(base.case["id"])["lifecycle_status"] == "PENDING_CLOSURE"

    def test_letter_version_increments_on_every_hop(self, api):
        """PRD §2.5: "The `version` is an integer that increments by one on
        every mutation of the resource and anchors optimistic concurrency
        control where §2.7 applies."

        Design: Difficulty/non_linear_state_machine/response_letter_revision_loop_cycle
        """
        base = setup_complaint_response_drafting(
            unit_name="Clinic West", unit_category="OUTPATIENT",
            patient_ref="P-5002", channel="PORTAL",
            description="Appointment rescheduling annoyance",
            grievance_category="ACCESS_DELAY")
        letter = draft_letter(base.case["id"], base.inv["id"],
                              body_summary="Courtesy response letter")
        created_version = letter["version"]

        submit_letter_review(letter["id"], base.inv["id"])
        get_success_data(api.return_letter(
            letter["id"], {"return_reason": "Tone needs work"},
            make_director_headers(base.director["id"])))
        submit_letter_review(letter["id"], base.inv["id"])
        final = approve_letter(letter["id"], base.director["id"])

        assert final["version"] == created_version + 4, (
            "four mutations after creation (submit, return, resubmit, approve) "
            "must each increment the letter version by one")


class TestIssuanceDeadlineBoundary:
    def _setup_two_approved_grievances(self, api):
        case_x = setup_letter_approved(
            unit_name="ED North", unit_category="EMERGENCY",
            clock="2026-08-03T12:00:00.000Z", received_at="2026-08-03T10:00:00.000Z",
            patient_ref="P-8001", description="Case X noise complaint",
            grievance_category="OTHER")
        case_y = setup_letter_approved(
            unit_name="ED North", unit_category="EMERGENCY",
            clock="2026-08-03T12:00:00.000Z", received_at="2026-08-03T10:00:00.000Z",
            patient_ref="P-8002", channel="EMAIL",
            description="Case Y food quality", grievance_category="OTHER")
        return case_x, case_y

    def test_issue_at_exact_deadline_is_on_time(self, api):
        """PRD §3.4: "Timeliness is judged against the binding calendar due —
        `resolution_timeliness` reads `ON_TIME` when issuance lands on or
        before `response_due_calendar_at` (equality is on time) and `LATE`
        otherwise; it had read `NA` until closure."

        Design: Difficulty/boundary_precision_check/issue_at_exact_deadline_on_time_one_second_late
        """
        case_x, _case_y = self._setup_two_approved_grievances(api)
        # STANDARD grievance received 2026-08-03T10:00:00Z -> due 2026-09-02T10:00:00Z.
        set_clock("2026-09-02T10:00:00.000Z")
        issued = validate_success(api.issue_letter(case_x.letter["id"], INTAKE))
        assert issued["issued_at"] == "2026-09-02T10:00:00.000Z"
        case_after = get_case(case_x.case["id"])
        assert case_after["lifecycle_status"] == "CLOSED"
        assert case_after["resolution_timeliness"] == "ON_TIME", (
            "issuance exactly at the binding due is on time (equality is ON_TIME)")

    def test_issue_one_second_late_is_late(self, api):
        """PRD §3.4: "Timeliness is judged against the binding calendar due —
        `resolution_timeliness` reads `ON_TIME` when issuance lands on or
        before `response_due_calendar_at` (equality is on time) and `LATE`
        otherwise; it had read `NA` until closure."

        Design: Difficulty/boundary_precision_check/issue_at_exact_deadline_on_time_one_second_late
        """
        _case_x, case_y = self._setup_two_approved_grievances(api)
        set_clock("2026-09-02T10:00:01.000Z")
        validate_success(api.issue_letter(case_y.letter["id"], INTAKE))
        case_after = get_case(case_y.case["id"])
        assert case_after["resolution_timeliness"] == "LATE", (
            "issued one second after the 2026-09-02T10:00:00Z deadline")


class TestContentStandard:
    def test_content_standard_missing_required_section(self, api):
        """PRD §3.4: "the five sections `PATIENT_SUMMARY`,
        `INVESTIGATION_STEPS`, `FINDINGS`, `RESOLUTION`, and `CONTACT_INFO` are
        always required, and two more — `RISK_DISCLOSURE` and `QAPI_REFERENCE`
        — become mandatory whenever the case's `requires_qro_cosign` is true or
        any `CARE_CONCERN` escalation for the case is still open or has been
        adjudicated substantiated. A letter failing the standard is rejected
        with `ERR_CONTENT_STANDARD_VIOLATION` (HTTP 422)."

        Design: Corner/validations/content_standard_missing_required_section
        """
        base = setup_complaint_response_drafting(
            unit_name="Clinic", unit_category="OUTPATIENT", patient_ref="P-0306",
            channel="PORTAL", description="Billing question",
            grievance_category="BILLING")
        letter = draft_letter(
            base.case["id"], base.inv["id"],
            sections=["PATIENT_SUMMARY", "INVESTIGATION_STEPS", "FINDINGS",
                      "RESOLUTION"],
            body_summary="Missing contact info section")
        resp = api.submit_letter_review(
            letter["id"], make_investigator_headers(base.inv["id"]))
        validate_error(resp, ApiErrorId.ERR_CONTENT_STANDARD_VIOLATION)

    def test_content_standard_critical_case_requires_risk_sections(self, api):
        """PRD §3.4: "the five sections `PATIENT_SUMMARY`,
        `INVESTIGATION_STEPS`, `FINDINGS`, `RESOLUTION`, and `CONTACT_INFO` are
        always required, and two more — `RISK_DISCLOSURE` and `QAPI_REFERENCE`
        — become mandatory whenever the case's `requires_qro_cosign` is true or
        any `CARE_CONCERN` escalation for the case is still open or has been
        adjudicated substantiated. A letter failing the standard is rejected
        with `ERR_CONTENT_STANDARD_VIOLATION` (HTTP 422)."

        Design: Corner/validations/content_standard_critical_case_requires_risk_sections
        """
        base = setup_response_drafting(
            unit_name="ICU", unit_category="ICU", patient_ref="P-0307",
            description="Critical care concern", grievance_category="CARE_QUALITY",
            severity_tier="CRITICAL")
        letter = draft_letter(base.case["id"], base.inv["id"],
                              body_summary="Letter without risk sections")
        resp = api.submit_letter_review(
            letter["id"], make_investigator_headers(base.inv["id"]))
        validate_error(resp, ApiErrorId.ERR_CONTENT_STANDARD_VIOLATION)


class TestApprovalGates:
    def _setup_hybrid_letter_in_review(self, api):
        """One staff member holding INVESTIGATOR+DIRECTOR runs the whole
        workflow, so only the segregation rule can block the approval."""
        set_clock("2026-08-03T10:00:00.000Z")
        unit = create_unit("ICU", "ICU")
        hybrid = create_staff("Ivy Hybrid", ["INVESTIGATOR", "DIRECTOR"])
        hybrid_director = make_director_headers(hybrid["id"])
        hybrid_inv = make_investigator_headers(hybrid["id"])
        case = create_case(unit["id"], patient_ref="P-0303",
                           received_at="2026-08-03T09:00:00.000Z",
                           description="Concern", grievance_category="OTHER")
        classify_case(case["id"], "GRIEVANCE")
        validate_success(api.create_assignment(
            case["id"], {"investigator_id": hybrid["id"],
                         "expected_case_version": get_case_version(case["id"])},
            hybrid_director), expected_status=201)
        investigation = open_investigation(case["id"], hybrid["id"])
        add_sufficient_notes(investigation["id"], hybrid["id"])
        submit_findings(investigation["id"], hybrid["id"])
        get_success_data(api.accept_findings(investigation["id"], hybrid_director))
        letter = draft_letter(case["id"], hybrid["id"],
                              body_summary="Letter content")
        submit_letter_review(letter["id"], hybrid["id"])
        return case, letter, hybrid, hybrid_director, hybrid_inv

    def test_sod_letter_approve_by_findings_submitter(self, api):
        """PRD §2.10: "The letter approver must differ from the investigation's
        findings submitter (`submitted_by_id`)." and "Each violation is
        rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Corner/validations/sod_letter_approve_by_findings_submitter
        """
        _case, letter, _hybrid, hybrid_director, _hi = (
            self._setup_hybrid_letter_in_review(api))
        resp = api.approve_letter(letter["id"], hybrid_director)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

    def test_investigator_approve_letter_forbidden(self, api):
        """PRD §2.1: "Authorization is then checked against the endpoint's
        permitted role list; a caller whose role is not listed is rejected with
        `ERR_UNAUTHORIZED_ROLE` (HTTP 403)."

        Design: Corner/rbac/investigator_approve_letter_forbidden
        """
        base = setup_letter_in_review(
            complaint=True, unit_name="Clinic", unit_category="OUTPATIENT",
            patient_ref="P-0502", channel="PORTAL", description="Billing question",
            grievance_category="BILLING")
        resp = api.approve_letter(base.letter["id"],
                                  make_investigator_headers(base.inv["id"]))
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE)

    def test_qro_cosign_required_blocks_director(self, api):
        """PRD §3.4: "when the case's `requires_qro_cosign` is true — which
        holds whenever `severity_tier` is `CRITICAL` or any escalation of the
        case stands `ADJUDICATED_SUBSTANTIATED` — the approving caller must be
        a `QualityRiskOfficer` (`ERR_QRO_COSIGN_REQUIRED`, HTTP 403)"

        Design: Corner/rbac/qro_cosign_required_blocks_director
        """
        base = setup_letter_in_review(
            unit_name="ICU", unit_category="ICU", patient_ref="P-0503",
            description="Critical concern", grievance_category="CARE_QUALITY",
            severity_tier="CRITICAL", sections=list(FULL_LETTER_SECTIONS))
        assert get_case(base.case["id"])["requires_qro_cosign"] is True

        blocked = api.approve_letter(
            base.letter["id"], make_director_headers(base.director["id"]))
        validate_error(blocked, ApiErrorId.ERR_QRO_COSIGN_REQUIRED)

        qro = create_staff("Quinn Risk", ["QRO"])
        approved = validate_success(api.approve_letter(
            base.letter["id"], make_qro_headers(qro["id"])))
        assert approved["status"] == "APPROVED", "the QRO co-sign path succeeds"


class TestFastTrackAndDirectClose:
    def test_fast_track_grievance_rejected(self, api):
        """PRD §3.4: "While a case is `ASSIGNED`, an `IntakeCoordinator` may
        fast-track a case whose `classification` is `COMPLAINT` straight to
        `RESPONSE_DRAFTING` — attempting it on a grievance is rejected with
        `ERR_FAST_TRACK_COMPLAINT_ONLY`"

        Design: Corner/validations/fast_track_grievance_rejected
        """
        base = setup_assigned_case(decision="GRIEVANCE", unit_name="ED",
                                   unit_category="EMERGENCY", patient_ref="P-0309",
                                   description="Concern", grievance_category="OTHER")
        resp = api.fast_track_case(base.case["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_FAST_TRACK_COMPLAINT_ONLY)

    def test_grievance_direct_close_rejected(self, api):
        """PRD §3.4: "A grievance may never take this door — the attempt is
        rejected with `ERR_GRIEVANCE_REQUIRES_WRITTEN_RESPONSE`, because a
        grievance closes only through an issued letter."

        Design: Corner/validations/grievance_direct_close_rejected
        """
        base = setup_response_drafting(unit_name="ED", unit_category="EMERGENCY",
                                       patient_ref="P-0308", description="Concern",
                                       grievance_category="OTHER")
        resp = api.close_case(
            base.case["id"],
            {"closure_note": "Trying to close without letter"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_GRIEVANCE_REQUIRES_WRITTEN_RESPONSE)

    def test_second_active_letter_rejected(self, api):
        """PRD §3.4: "A case may hold only one non-terminal letter at a time —
        a second draft while one is alive in `DRAFT`, `IN_REVIEW`, or
        `RETURNED` is rejected with `ERR_ACTIVE_LETTER_EXISTS`"

        Design: Corner/validations/second_active_letter_rejected
        """
        base = setup_complaint_response_drafting(
            unit_name="Clinic", unit_category="OUTPATIENT", patient_ref="P-0318",
            channel="PORTAL", description="Billing question",
            grievance_category="BILLING")
        draft_letter(base.case["id"], base.inv["id"], body_summary="First letter draft")
        resp = api.create_letter(
            base.case["id"],
            create_letter_payload(body_summary="Second concurrent draft"),
            make_investigator_headers(base.inv["id"]))
        validate_error(resp, ApiErrorId.ERR_ACTIVE_LETTER_EXISTS)


class TestClosureCascade:
    def test_closure_completes_assignments_and_creates_followup(self, api):
        """PRD §3.4: "Closure then sweeps the case's dependents: every `ACTIVE`
        assignment on the case moves to `COMPLETED` and each investigator's
        `open_assignment_count` falls by one; every `OPEN` clock suspension
        closes at the closure instant, freezing the tolling credit (§3.5); a
        satisfaction follow-up is created on the schedule of §3.9; and the
        unit's `open_case_count` falls by one." PRD §3.9: "Every closure — by
        issued letter or by complaint fast-track — spawns a **satisfaction
        follow-up** in `PENDING`, with `due_at` set five business days after
        `closed_at` and `expires_at` ten business days after `due_at`, both on
        the business-day arithmetic of §2.8 at the same time of day as their
        base."

        Design: Corner/state_machines/closure_completes_assignments_and_creates_followup
        """
        base = setup_letter_approved(
            unit_name="ED Main", unit_category="EMERGENCY", patient_ref="P-0106",
            channel="EMAIL", description="Billing concern",
            grievance_category="BILLING")
        set_clock("2026-08-10T09:00:00.000Z")
        letter = validate_success(api.issue_letter(base.letter["id"], INTAKE))
        assert letter["status"] == "ISSUED"

        assignment = get_success_data(api.get_assignment(base.assignment["id"], INTAKE))
        assert assignment["status"] == "COMPLETED"
        assert get_staff(base.inv["id"])["open_assignment_count"] == 0
        unit = get_success_data(api.get_unit(base.unit["id"], INTAKE))
        assert unit["open_case_count"] == 0

        follow_up = get_follow_up_for_case(base.case["id"])
        assert follow_up["status"] == "PENDING"
        assert follow_up["due_at"] == "2026-08-17T09:00:00.000Z", (
            "closed 2026-08-10T09:00:00Z (Monday) + 5 business days")
        assert follow_up["expires_at"] == "2026-08-31T09:00:00.000Z", (
            "due_at + 10 business days")

    def test_immediate_closure_visibility_on_read(self, api):
        """PRD §3.4: "Fast-track closure performs the same closure cascade as
        issuance: `closed_at` is stamped, timeliness judged against
        `response_due_calendar_at` with equality on time, active assignments
        complete, open suspensions close, the follow-up is created, the unit
        count falls, and the case `version` advances by one."

        Design: Corner/consistency_model/immediate_closure_visibility_on_read
        """
        base = setup_complaint_response_drafting(
            unit_name="Clinic", unit_category="OUTPATIENT", patient_ref="P-0701",
            channel="PORTAL", description="Billing question",
            grievance_category="BILLING")
        closed = validate_success(api.close_case(
            base.case["id"], {"closure_note": "Resolved at the desk immediately"},
            INTAKE))
        assert closed["lifecycle_status"] == "CLOSED"
        assert closed["closed_at"] == "2026-08-03T10:00:00.000Z"
        assert closed["resolution_timeliness"] == "ON_TIME", (
            "within the three-day complaint window")

        reread = get_case(base.case["id"])
        assert reread["lifecycle_status"] == "CLOSED", (
            "the write response and an immediately-following read must agree")
        follow_up = get_follow_up_for_case(base.case["id"])
        assert follow_up["status"] == "PENDING", (
            "the follow-up is materialized in the same transaction")

    def test_reopen_from_non_closed_rejected(self, api):
        """PRD §3.9: "Reopening — whether fired by a low score or invoked
        directly by a `PatientRelationsDirector` with an optional
        `reopen_reason` — is permitted only from `CLOSED`
        (`ERR_CASE_INVALID_STATE` otherwise)"

        Design: Corner/state_machines/reopen_from_non_closed_rejected
        """
        base = setup_classified_case(decision="GRIEVANCE", unit_name="ED Main",
                                     unit_category="EMERGENCY",
                                     patient_ref="P-0104", description="Concern",
                                     grievance_category="OTHER")
        director = create_staff("Dana Director", ["DIRECTOR"])
        resp = api.reopen_case(base.case["id"], {"reopen_reason": "Too early"},
                               make_director_headers(director["id"]))
        validate_error(resp, ApiErrorId.ERR_CASE_INVALID_STATE)
