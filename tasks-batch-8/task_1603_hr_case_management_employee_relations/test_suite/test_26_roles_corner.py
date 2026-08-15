"""Corner tests — roles (RBAC) section."""
import pytest

from test_helpers import (
    api_client,
    TEST_USERS,
    make_investigator_headers,
    make_legal_counsel_headers,
    make_hr_analyst_headers,
    setup_intake_channel,
    setup_employee,
    setup_investigator,
    setup_case,
    run_case_to_closed,
    create_closure_notice_payload,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)


class TestInvestigatorCannotAssign:
    def test_investigator_cannot_assign_cases(self):
        """PRD §2.1: "A request whose role is not permitted to invoke the
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST /er/cases/{id}/assign — Authorized Role(s): ERManager."

        Design: Corner/roles/investigator_cannot_assign_cases
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot RB",
            default_category="HARASSMENT", default_severity="LOW",
            sla_business_days=10,
        )
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        case = setup_case(channel["id"], subject["id"],
                          category="HARASSMENT", severity="LOW")
        resp = api_client.assign_case(
            case["id"],
            {"investigator_id": inv2["id"], "expected_case_version": case["version"]},
            make_investigator_headers(inv1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        after = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert after["status"] == "TRIAGE"


class TestHRAnalystCannotCreateEmployees:
    def test_hr_analyst_cannot_create_employees(self):
        """PRD §2.1: "A request whose role is not permitted to invoke the
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: "POST /er/employees — Authorized Role(s): ERManager."

        Design: Corner/roles/hr_analyst_cannot_create_employees
        """
        resp = api_client.create_employee(
            {"employee_number": "E-9801", "full_name": "RBAC Test",
             "email": "e9801@example.com", "location_code": "SF",
             "department": "Ops", "hire_date": "2021-01-01T00:00:00Z"},
            make_hr_analyst_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)


class TestLegalCounselCannotClose:
    def test_legal_counsel_can_read_cases_but_not_close(self):
        """PRD §2.1: "A request whose role is not permitted to invoke the
        endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §2.6: "Authentication comes first: a request without a valid
        `X-User-Role` fails with `ERR_UNAUTHENTICATED`, then a request without
        `X-User-ID` fails the same way, and only then is the role's permission
        to invoke the endpoint examined (`ERR_UNAUTHORIZED`)."
        PRD §4: "POST /er/cases/{id}/close — Authorized Role(s): ERManager."

        Design: Corner/roles/legal_counsel_can_read_cases_but_not_close
        """
        channel = setup_intake_channel(
            channel_code="ANONYMOUS_LETTER", display_name="Anon LC",
            default_category="SAFETY", default_severity="MEDIUM",
            sla_business_days=10,
        )
        subject = setup_employee()
        _, inv1 = setup_investigator()
        _, inv2 = setup_investigator()
        _, inv3 = setup_investigator()
        # Drive case to PENDING_CLOSURE: full pipeline minus the actual close.
        from test_helpers import (
            setup_investigating_case, schedule_interview, complete_interview,
            log_evidence, admit_evidence, create_assessment, create_draft_finding,
            substantiate_finding, propose_action, submit_for_calibration,
            approve_finding_as,
        )
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
        # Subject notice SENT
        notice = get_success_data(api_client.create_closure_notice(
            case["id"],
            create_closure_notice_payload(
                subject["id"], recipient_role="SUBJECT",
                confidentiality_tier="TIER_2_LIMITED",
            ),
            TEST_USERS["er_manager_headers"],
        ))
        api_client.send_notice(notice["id"], TEST_USERS["er_manager_headers"])
        # LegalCounsel CAN read the case
        case_read = get_success_data(api_client.get_case(case["id"], make_legal_counsel_headers()))
        assert case_read["status"] == "PENDING_CLOSURE"
        # But cannot close it
        resp = api_client.close_case(
            case["id"], {"expected_case_version": case_read["version"]},
            make_legal_counsel_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)
        after = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert after["status"] == "PENDING_CLOSURE"
