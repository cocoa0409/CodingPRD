"""Corner tests — validations section (FK resolution, documentation, capacity, reopen, confidentiality, recipient, closure gate, overlap, timing, scope)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_investigator_headers,
    make_hr_analyst_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    setup_case,
    setup_investigating_case,
    assign_case_to,
    begin_investigation,
    schedule_interview,
    complete_interview,
    log_evidence,
    admit_evidence,
    create_assessment,
    create_draft_finding,
    substantiate_finding,
    propose_action,
    submit_for_calibration,
    approve_finding_as,
    create_closure_notice_payload,
    run_case_to_closed,
    set_clock,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    NON_EXISTENT_UUID,
)


class TestReferencedEmployeeMissing:
    def test_referenced_employee_missing_returns_422(self):
        """PRD §2.11: "An employee id, intake channel id, investigator id, or
        finding id carried in a payload must resolve to an existing row; one
        that does not fails with `ERR_REFERENCED_NOT_FOUND` (HTTP 422)."

        Design: Corner/validations/referenced_employee_missing_returns_422
        """
        ch = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot V",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        resp = api_client.create_case(
            {"intake_channel_id": ch["id"],
             "subject_employee_id": NON_EXISTENT_UUID,
             "category": "HARASSMENT", "severity": "MEDIUM"},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND, 422)


class TestInterviewDocumentationMinimum:
    def test_interview_documentation_below_minimum_rejected(self):
        """PRD §3.3: "the payload carries `documentation_text` of at least
        fifty characters (a shorter account fails with
        `ERR_DOCUMENTATION_STANDARD`)."

        Design: Corner/validations/interview_documentation_below_minimum_rejected
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot Doc",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="MEDIUM",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        short_doc = "Too short to satisfy the fifty char rule."  # 43 chars
        assert len(short_doc) < 50
        resp = api_client.complete_interview(
            iv["id"], {"documentation_text": short_doc},
            make_investigator_headers(inv1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DOCUMENTATION_STANDARD, 422)
        # Interview remains SCHEDULED
        after = get_success_data(api_client.get_interview(iv["id"], TEST_USERS["er_manager_headers"]))
        assert after["status"] == "SCHEDULED"


class TestCapacityBoundary:
    def test_capacity_boundary_assign_at_max_minus_one_then_at_max(self):
        """PRD §3.2: "Capacity follows: the candidate's `active_case_count`
        must still be below their `max_active_cases`, or the request fails
        with `ERR_CAPACITY_EXCEEDED`."

        Design: Corner/validations/capacity_boundary_assign_at_max_minus_one_then_at_max
        """
        channel = setup_intake_channel(
            channel_code="WEB_PORTAL", display_name="Portal Cap",
            default_category="COMPENSATION", default_severity="LOW",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator(max_active_cases=1)
        c1 = setup_case(channel["id"], subject["id"],
                        reporter_employee_id=reporter["id"],
                        category="COMPENSATION", severity="LOW")
        c2 = setup_case(channel["id"], subject["id"],
                        reporter_employee_id=reporter["id"],
                        category="COMPENSATION", severity="LOW")
        # First assign succeeds
        r1 = api_client.assign_case(
            c1["id"],
            {"investigator_id": inv1["id"], "expected_case_version": c1["version"]},
            TEST_USERS["er_manager_headers"],
        )
        assigned = validate_success(r1, 200)
        assert assigned["status"] == "ASSIGNED"
        # Second assign to same investigator — capacity exceeded
        r2 = api_client.assign_case(
            c2["id"],
            {"investigator_id": inv1["id"], "expected_case_version": c2["version"]},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(r2, ApiErrorId.ERR_CAPACITY_EXCEEDED, 422)
        after = get_success_data(api_client.get_case(c2["id"], TEST_USERS["er_manager_headers"]))
        assert after["status"] == "TRIAGE"


class TestReopenThirdTime:
    def test_reopen_third_time_rejected(self):
        """PRD §3.6: "A `CLOSED` case may be reopened by an `ERManager` at
        most twice — a case whose `reopen_count` has already reached two
        refuses with `ERR_REOPEN_LIMIT` (HTTP 422)."
        PRD §3.6: "From `REOPENED` the case flows back through assignment
        exactly as if it were in `TRIAGE`, per §3.2, and a later closure mints
        a fresh round of notices under the next `closure_sequence`."

        Design: Corner/validations/reopen_third_time_rejected
        """
        channel = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon R",
            default_category="SAFETY", default_severity="MEDIUM",
            sla_business_days=10,
        )
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()

        def run_findings_pipeline(case_id):
            """INVESTIGATING -> CLOSED for the case identified by case_id:
            interview, evidence, finding, calibration quorum, subject notice,
            close. The pass-1 credibility assessment (active score 0.73 under
            RECENCY_WEIGHTED after reopen) keeps the substantiation gate
            satisfied on later passes."""
            iv = schedule_interview(case_id, inv1["id"], subject["id"])
            complete_interview(iv["id"], inv1["id"])
            ev = log_evidence(case_id, inv1["id"], subject["id"], evidence_type="PHOTO")
            admit_evidence(ev["id"], inv1["id"], weight=0.8)
            finding = create_draft_finding(case_id, inv1["id"])
            substantiate_finding(finding["id"], inv1["id"], outcome="SUBSTANTIATED")
            propose_action(finding["id"], inv1["id"],
                            action_type="POLICY_CHANGE", severity_points=30)
            submit_for_calibration(finding["id"], inv1["id"])
            approve_finding_as(finding["id"], inv2["id"])
            approve_finding_as(finding["id"], inv3["id"])
            notice = get_success_data(api_client.create_closure_notice(
                case_id,
                create_closure_notice_payload(
                    subject["id"], recipient_role="SUBJECT",
                    confidentiality_tier="TIER_2_LIMITED",
                ),
                TEST_USERS["er_manager_headers"],
            ))
            api_client.send_notice(notice["id"], TEST_USERS["er_manager_headers"])
            cur = get_success_data(api_client.get_case(case_id, TEST_USERS["er_manager_headers"]))
            closed = api_client.close_case(
                case_id, {"expected_case_version": cur["version"]},
                TEST_USERS["er_manager_headers"],
            )
            return get_success_data(closed)

        def drive_new_case_to_closed():
            """First pass: a brand-new case from intake to CLOSED."""
            case = setup_investigating_case(
                channel["id"], subject["id"], inv1["id"],
                category="SAFETY", severity="MEDIUM",
            )
            create_assessment(case["id"], inv1["id"], subject["id"],
                              corroboration_count=4, contradiction_count=0, account_age_days=2)
            return run_findings_pipeline(case["id"])

        def redrive_same_case_to_closed(case_id):
            """Later pass: the SAME case, reopened, flows back through
            assignment exactly as if it were in TRIAGE (PRD §3.6/§3.2)."""
            cur = get_success_data(api_client.get_case(case_id, TEST_USERS["er_manager_headers"]))
            assign_case_to(case_id, inv1["id"], cur["version"])
            begin_investigation(case_id, inv1["id"])
            return run_findings_pipeline(case_id)

        # Pass 1
        case = drive_new_case_to_closed()
        case_id = case["id"]
        assert case["reopen_count"] == 0
        # Reopen 1 and close
        r1 = api_client.reopen_case(case_id,
            {"reopen_reason": "Pass two: new witness evidence emerged after the first closure."},
            TEST_USERS["er_manager_headers"])
        get_success_data(r1)
        case = redrive_same_case_to_closed(case_id)
        assert case["reopen_count"] == 1
        # Reopen 2 and close
        r2 = api_client.reopen_case(case_id,
            {"reopen_reason": "Pass three: additional documentary evidence emerged after second closure."},
            TEST_USERS["er_manager_headers"])
        get_success_data(r2)
        case = redrive_same_case_to_closed(case_id)
        assert case["reopen_count"] == 2
        # Third reopen — must fail
        resp = api_client.reopen_case(
            case_id,
            {"reopen_reason": "Third reopen attempt must be rejected by the two-reopen cap."},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_REOPEN_LIMIT, 422)
        after = get_success_data(api_client.get_case(case_id, TEST_USERS["er_manager_headers"]))
        assert after["status"] == "CLOSED"
        assert after["reopen_count"] == 2


class TestConfidentialityTier3ToSubject:
    def test_confidentiality_tier3_to_subject_rejected(self):
        """PRD §3.6: "Confidentiality is enforced in two rules, both failing
        with `ERR_CONFIDENTIALITY_VIOLATION` (HTTP 422): a `SUBJECT` recipient
        may receive at most `TIER_2_LIMITED` — never `TIER_3_FULL`."

        Design: Corner/validations/confidentiality_tier3_to_subject_rejected
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot Conf",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        # Drive to PENDING_CLOSURE
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="MEDIUM",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        complete_interview(iv["id"], inv1["id"])
        ev = log_evidence(case["id"], inv1["id"], reporter["id"], evidence_type="EMAIL")
        admit_evidence(ev["id"], inv1["id"], weight=0.8)
        create_assessment(case["id"], inv1["id"], subject["id"],
                          corroboration_count=4, contradiction_count=0, account_age_days=2)
        finding = create_draft_finding(case["id"], inv1["id"])
        substantiate_finding(finding["id"], inv1["id"], outcome="SUBSTANTIATED")
        propose_action(finding["id"], inv1["id"],
                        action_type="WRITTEN_WARNING", severity_points=40)
        submit_for_calibration(finding["id"], inv1["id"])
        approve_finding_as(finding["id"], inv2["id"])
        approve_finding_as(finding["id"], inv3["id"])
        # Now in PENDING_CLOSURE — attempt TIER_3_FULL to SUBJECT
        resp = api_client.create_closure_notice(
            case["id"],
            {"recipient_employee_id": subject["id"],
             "recipient_role": "SUBJECT",
             "confidentiality_tier": "TIER_3_FULL",
             "body_text": "Full-file disclosure attempted to the subject."},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CONFIDENTIALITY_VIOLATION, 422)
        # No notice row was created
        notices = get_success_data(api_client.list_case_notices(case["id"], TEST_USERS["er_manager_headers"]))
        items = notices if isinstance(notices, list) else notices.get("data", [])
        assert len(items) == 0


class TestNoticeRecipientMismatch:
    def test_notice_recipient_must_be_reporter_or_subject(self):
        """PRD §3.6: "The recipient must actually be the case's reporter or
        subject employee; anyone else fails with `ERR_RECIPIENT_MISMATCH`
        (HTTP 422)."

        Design: Corner/validations/notice_recipient_must_be_reporter_or_subject
        """
        channel = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon RM",
            default_category="SAFETY", default_severity="MEDIUM",
            sla_business_days=10,
        )
        subject = setup_employee()
        third = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            category="SAFETY", severity="MEDIUM",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        complete_interview(iv["id"], inv1["id"])
        ev = log_evidence(case["id"], inv1["id"], subject["id"], evidence_type="PHOTO")
        admit_evidence(ev["id"], inv1["id"], weight=0.8)
        create_assessment(case["id"], inv1["id"], subject["id"],
                          corroboration_count=4, contradiction_count=0, account_age_days=2)
        finding = create_draft_finding(case["id"], inv1["id"])
        substantiate_finding(finding["id"], inv1["id"], outcome="SUBSTANTIATED")
        propose_action(finding["id"], inv1["id"],
                        action_type="POLICY_CHANGE", severity_points=30)
        submit_for_calibration(finding["id"], inv1["id"])
        approve_finding_as(finding["id"], inv2["id"])
        approve_finding_as(finding["id"], inv3["id"])
        # Draft notice to third party (neither reporter nor subject)
        resp = api_client.create_closure_notice(
            case["id"],
            {"recipient_employee_id": third["id"],
             "recipient_role": "SUBJECT",
             "confidentiality_tier": "TIER_2_LIMITED",
             "body_text": "Notice addressed to an uninvolved third party."},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_RECIPIENT_MISMATCH, 422)


class TestClosureGate:
    def test_closure_gate_missing_sent_notices(self):
        """PRD §3.6: "Closing moves a case from `PENDING_CLOSURE` to `CLOSED`
        and demands, in order: a finding on the case whose `approval_status`
        is `APPROVED`; at least one notice to the `SUBJECT` whose
        `delivery_status` is `SENT`; and at least one `SENT` notice to the
        `REPORTER` — a requirement skipped entirely for anonymous cases whose
        `reporter_employee_id` is null. An unmet gate fails with
        `ERR_CLOSURE_GATE` (HTTP 422)."

        Design: Corner/validations/closure_gate_missing_sent_notices
        """
        channel = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon CG",
            default_category="SAFETY", default_severity="MEDIUM",
            sla_business_days=10,
        )
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            category="SAFETY", severity="MEDIUM",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        complete_interview(iv["id"], inv1["id"])
        ev = log_evidence(case["id"], inv1["id"], subject["id"], evidence_type="PHOTO")
        admit_evidence(ev["id"], inv1["id"], weight=0.8)
        create_assessment(case["id"], inv1["id"], subject["id"],
                          corroboration_count=4, contradiction_count=0, account_age_days=2)
        finding = create_draft_finding(case["id"], inv1["id"])
        substantiate_finding(finding["id"], inv1["id"], outcome="SUBSTANTIATED")
        propose_action(finding["id"], inv1["id"],
                        action_type="POLICY_CHANGE", severity_points=30)
        submit_for_calibration(finding["id"], inv1["id"])
        approve_finding_as(finding["id"], inv2["id"])
        approve_finding_as(finding["id"], inv3["id"])
        # Draft a QUEUED subject notice but do not send it
        notice = get_success_data(api_client.create_closure_notice(
            case["id"],
            create_closure_notice_payload(
                subject["id"], recipient_role="SUBJECT",
                confidentiality_tier="TIER_2_LIMITED",
            ),
            TEST_USERS["er_manager_headers"],
        ))
        # Try to close
        cur = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        resp = api_client.close_case(
            case["id"], {"expected_case_version": cur["version"]},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CLOSURE_GATE, 422)
        after = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert after["status"] == "PENDING_CLOSURE"


class TestInterviewEndNotAfterStart:
    def test_interview_end_not_after_start_rejected(self):
        """PRD §3.3: "the end must fall strictly after the start."

        Design: Corner/validations/interview_end_not_after_start_rejected
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot ZL",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="MEDIUM",
        )
        resp = api_client.create_interview(
            case["id"],
            {"interviewee_employee_id": subject["id"],
             "scheduled_start": "2026-07-31T09:00:00Z",
             "scheduled_end": "2026-07-31T09:00:00Z"},
            make_investigator_headers(inv1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INTERVIEW_OVERLAP, 422)


class TestNoShowGraceWindow:
    def test_no_show_before_grace_window_rejected(self):
        """PRD §3.3: "When an interviewee does not appear, the interviewer
        marks the interview `NO_SHOW`, but only once the logical clock has
        passed thirty minutes beyond the `scheduled_end` — earlier attempts
        fail with `ERR_TIMING_VIOLATION`."

        Design: Corner/validations/no_show_before_grace_window_rejected
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot NS",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        witness = setup_employee()
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="MEDIUM",
        )
        iv_a = schedule_interview(case["id"], inv1["id"], subject["id"],
                                    scheduled_start="2026-08-10T09:00:00Z",
                                    scheduled_end="2026-08-10T10:00:00Z")
        iv_b = schedule_interview(case["id"], inv1["id"], witness["id"],
                                    scheduled_start="2026-08-10T12:00:00Z",
                                    scheduled_end="2026-08-10T13:00:00Z")
        # At end+29min — too early
        set_clock("2026-08-10T10:29:00Z")
        resp_a = api_client.mark_no_show(iv_a["id"], make_investigator_headers(inv1["id"]))
        validate_error(resp_a, ApiErrorId.ERR_TIMING_VIOLATION, 422)
        after_a = get_success_data(api_client.get_interview(iv_a["id"], TEST_USERS["er_manager_headers"]))
        assert after_a["status"] == "SCHEDULED"
        # At end+31min — succeeds
        set_clock("2026-08-10T13:31:00Z")
        resp_b = api_client.mark_no_show(iv_b["id"], make_investigator_headers(inv1["id"]))
        done_b = validate_success(resp_b, 200)
        assert done_b["status"] == "NO_SHOW"


class TestTrendScopeKeyUnresolvable:
    def test_trend_scope_key_unresolvable_rejected(self):
        """PRD §3.7: "The scope key must resolve: a `MANAGER` scope requires
        the id of an existing employee, and a `LOCATION` scope requires a
        `location_code` present on at least one employee; an unresolvable key
        fails with `ERR_SCOPE_NOT_FOUND` (HTTP 422)."

        Design: Corner/validations/trend_scope_key_unresolvable_rejected
        """
        setup_employee(location_code="SF")
        # MANAGER scope with unknown employee id
        r1 = api_client.create_trend_snapshot(
            {"scope_type": "MANAGER", "scope_key": NON_EXISTENT_UUID,
             "window_kind": "ROLLING_90D"},
            make_hr_analyst_headers(),
        )
        validate_error(r1, ApiErrorId.ERR_SCOPE_NOT_FOUND, 422)
        # LOCATION scope with unknown location code
        r2 = api_client.create_trend_snapshot(
            {"scope_type": "LOCATION", "scope_key": "ZZZ",
             "window_kind": "CALENDAR_QUARTER"},
            make_hr_analyst_headers(),
        )
        validate_error(r2, ApiErrorId.ERR_SCOPE_NOT_FOUND, 422)
