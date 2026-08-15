"""Corner tests — state_machines section (invalid transitions, terminal lockdown, idempotency)."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_investigator_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    setup_case,
    setup_investigating_case,
    assign_case_to,
    schedule_interview,
    complete_interview,
    run_case_to_closed,
    create_draft_finding,
    substantiate_finding,
    propose_action,
    submit_for_calibration,
    approve_finding_as,
    log_evidence,
    admit_evidence,
    create_assessment,
    create_closure_notice_payload,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)


class TestCaseAssignFromInvestigating:
    def test_case_assign_from_investigating_returns_invalid_state(self):
        """PRD §3.2: "Assignment moves a case from `TRIAGE` to `ASSIGNED`, and
        the same action with the same rules also moves a `REOPENED` case back
        to `ASSIGNED`."
        PRD §2.6: "State legality follows existence: the requested transition
        must be defined from the resource's current state, or the request
        fails with `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/case_assign_from_investigating_returns_invalid_state
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot X",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="MEDIUM",
        )
        current = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        resp = api_client.assign_case(
            case["id"],
            {"investigator_id": inv2["id"], "expected_case_version": current["version"]},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        # assigned_investigator_id unchanged
        after = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert after["assigned_investigator_id"] == inv1["id"]
        inv2_after = get_success_data(
            api_client.get_investigator(inv2["id"], TEST_USERS["er_manager_headers"])
        )
        assert inv2_after["active_case_count"] == 0


class TestCaseTerminalLockdown:
    def test_case_terminal_closed_lockdown(self):
        """PRD §3.2: "Once assigned, the investigator personally opens the
        file: beginning the investigation moves `ASSIGNED` to `INVESTIGATING`."
        PRD §2.6: "the requested transition must be defined from the resource's
        current state, or the request fails with `ERR_INVALID_STATE` (HTTP
        409)."

        Design: Corner/state_machines/case_terminal_closed_lockdown
        """
        channel = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon T",
            default_category="SAFETY", default_severity="MEDIUM",
            sla_business_days=10,
        )
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        case, _, _, _, _ = run_case_to_closed(
            channel["id"], subject["id"], inv1, inv2, inv3,
            category="SAFETY", severity="MEDIUM",
            action_type="POLICY_CHANGE", severity_points=30,
            substantiation_outcome="SUBSTANTIATED",
            assessment_kwargs={"corroboration_count": 4, "contradiction_count": 0,
                                "account_age_days": 2},
        )
        assert case["status"] == "CLOSED"
        # Attempt to begin-investigation on a CLOSED case
        resp = api_client.begin_investigation(
            case["id"], make_investigator_headers(inv1["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        after = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert after["status"] == "CLOSED"


class TestInterviewCompleteTwice:
    def test_interview_complete_twice_rejected(self):
        """PRD §3.3: "All three of `COMPLETED`, `NO_SHOW`, and `CANCELLED` are
        terminal."
        PRD §2.6: "the requested transition must be defined from the resource's
        current state, or the request fails with `ERR_INVALID_STATE` (HTTP
        409)."

        Design: Corner/state_machines/interview_complete_twice_rejected
        """
        channel = setup_intake_channel(
            channel_code="WEB_PORTAL", display_name="Portal I",
            default_category="POLICY_VIOLATION", default_severity="LOW",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="POLICY_VIOLATION", severity="LOW",
        )
        iv = schedule_interview(case["id"], inv1["id"], subject["id"])
        doc1 = "First completion documentation text with more than fifty characters to satisfy the standard."
        done1 = complete_interview(iv["id"], inv1["id"], documentation_text=doc1)
        assert done1["status"] == "COMPLETED"
        first_completed_at = done1["completed_at"]
        # Try completing again
        doc2 = "Second completion attempt with different documentation text also exceeding fifty characters."
        resp = api_client.complete_interview(
            iv["id"], {"documentation_text": doc2}, make_investigator_headers(inv1["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        # completed_at unchanged
        iv_after = get_success_data(api_client.get_interview(iv["id"], TEST_USERS["er_manager_headers"]))
        assert iv_after["completed_at"] == first_completed_at


class TestNoticeRetryFromQueued:
    def test_notice_retry_from_queued_rejected(self):
        """PRD §3.6: "A dispatch problem is recorded by marking the notice
        `FAILED` with a `failure_reason`, and a failed notice may be retried
        back into `QUEUED`."
        PRD §2.6: "the requested transition must be defined from the resource's
        current state, or the request fails with `ERR_INVALID_STATE` (HTTP
        409)."

        Retry is defined only from FAILED, not QUEUED.

        Design: Corner/state_machines/notice_retry_from_queued_rejected
        """
        channel = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon N",
            default_category="SAFETY", default_severity="MEDIUM",
            sla_business_days=10,
        )
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        # Drive to PENDING_CLOSURE without sending the notice
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
        # Draft a QUEUED notice
        notice_resp = api_client.create_closure_notice(
            case["id"],
            create_closure_notice_payload(
                subject["id"], recipient_role="SUBJECT",
                confidentiality_tier="TIER_2_LIMITED",
            ),
            TEST_USERS["er_manager_headers"],
        )
        notice = get_success_data(notice_resp)
        assert notice["delivery_status"] == "QUEUED"
        # Retry a QUEUED notice — invalid
        resp = api_client.retry_notice(notice["id"], TEST_USERS["er_manager_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
        # Status remains QUEUED
        after = get_success_data(api_client.get_closure_notice(notice["id"], TEST_USERS["er_manager_headers"]))
        assert after["delivery_status"] == "QUEUED"


class TestEvidenceBeginReviewBindsReviewer:
    def test_evidence_begin_review_binds_reviewer(self):
        """PRD §3.3: "Moving an item from `LOGGED` to `UNDER_REVIEW` is
        permitted to the case's assigned investigator while the case is
        `INVESTIGATING` or in `FINDINGS_DRAFT`, and it writes the acting
        investigator into the item's `reviewed_by_investigator_id`."
        PRD §2.8: "on the evidence side the investigator who began reviewing an
        item is the only investigator permitted to admit or exclude it."

        Design: Corner/state_machines/evidence_begin_review_binds_reviewer
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot S",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        case = setup_investigating_case(
            channel["id"], subject["id"], inv1["id"],
            reporter_employee_id=reporter["id"],
            category="HARASSMENT", severity="MEDIUM",
        )
        ev = log_evidence(case["id"], inv1["id"], reporter["id"], evidence_type="EMAIL")
        review_resp = api_client.begin_review(ev["id"], make_investigator_headers(inv1["id"]))
        reviewed = validate_success(review_resp, 200)
        assert reviewed["reviewed_by_investigator_id"] == inv1["id"]
        # INV2 tries to admit — must fail
        resp = api_client.admit_evidence(
            ev["id"], {"weight": 0.5}, make_investigator_headers(inv2["id"])
        )
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 422)
        # Status remains UNDER_REVIEW
        after = get_success_data(api_client.get_evidence_item(ev["id"], TEST_USERS["er_manager_headers"]))
        assert after["status"] == "UNDER_REVIEW"
