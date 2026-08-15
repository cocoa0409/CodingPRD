"""Corner tests — errors section (certification, conflict, invalid request, insufficient credibility)."""
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
    schedule_interview,
    complete_interview,
    log_evidence,
    admit_evidence,
    create_assessment,
    create_draft_finding,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
)


class TestCertificationInsufficient:
    def test_error_certification_insufficient_triggerable(self):
        """PRD §3.1: "The profile's `certification_level` declares the most
        severe caseload the investigator may lead: `LEVEL_1` may lead only
        `LOW` cases, `LEVEL_2` may lead `LOW` and `MEDIUM`, and `LEVEL_3` may
        lead any severity including `HIGH` and `CRITICAL`."
        PRD §3.2: "Certification comes next: the candidate's
        `certification_level` must cover the case's `severity` per the ladder
        of §3.1, or the request fails with `ERR_CERTIFICATION_INSUFFICIENT`."

        Design: Corner/errors/error_certification_insufficient_triggerable
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot Cert",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        subject = setup_employee()
        _, inv1 = setup_investigator(certification_level="LEVEL_1", max_active_cases=5)
        case = setup_case(channel["id"], subject["id"],
                          category="HARASSMENT", severity="MEDIUM")
        resp = api_client.assign_case(
            case["id"],
            {"investigator_id": inv1["id"], "expected_case_version": case["version"]},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATION_INSUFFICIENT, 422)
        after = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert after["status"] == "TRIAGE"


class TestInvestigatorConflictOnReporter:
    def test_error_investigator_conflict_on_reporter(self):
        """PRD §2.8: "If the case's subject employee — or its reporter, when
        the report is not anonymous — appears in the acting investigator's
        conflict list, the request fails with `ERR_INVESTIGATOR_CONFLICT`
        (HTTP 422)."

        Design: Corner/errors/error_investigator_conflict_on_reporter
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot CF",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        reporter = setup_employee()
        subject = setup_employee()
        _, inv1 = setup_investigator(conflicted_employee_ids=[reporter["id"]])
        case = setup_case(channel["id"], subject["id"],
                          reporter_employee_id=reporter["id"],
                          category="HARASSMENT", severity="MEDIUM")
        resp = api_client.assign_case(
            case["id"],
            {"investigator_id": inv1["id"], "expected_case_version": case["version"]},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVESTIGATOR_CONFLICT, 422)
        after = get_success_data(api_client.get_case(case["id"], TEST_USERS["er_manager_headers"]))
        assert after["status"] == "TRIAGE"


class TestInvalidRequestOnBadEnum:
    def test_error_invalid_request_on_bad_enum(self):
        """PRD §2.6: "syntactic validity (required fields present, values
        well-typed, enum values within their declared sets, failing with
        `ERR_INVALID_REQUEST`, HTTP 400) is the final screen of all."

        Design: Corner/errors/error_invalid_request_on_bad_enum
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot IR",
            default_category="HARASSMENT", default_severity="MEDIUM",
            sla_business_days=10,
        )
        subject = setup_employee()
        resp = api_client.create_case(
            {"intake_channel_id": channel["id"],
             "subject_employee_id": subject["id"],
             "category": "HARASSMENT", "severity": "SEVERE"},
            TEST_USERS["er_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)


class TestInsufficientCredibility:
    def test_error_insufficient_credibility_triggerable(self):
        """PRD §3.5: "One consistency gate then applies: when every
        credibility assessment on the case has its active score — the score
        named by its `active_variant` — below 0.50, the outcome may not be
        `SUBSTANTIATED`, and the attempt fails with
        `ERR_INSUFFICIENT_CREDIBILITY` (HTTP 422)."

        Design: Corner/errors/error_insufficient_credibility_triggerable
        """
        channel = setup_intake_channel(
            channel_code="HOTLINE", display_name="Hot IC",
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
        complete_interview(iv["id"], inv1["id"])
        ev = log_evidence(case["id"], inv1["id"], reporter["id"])
        admit_evidence(ev["id"], inv1["id"], weight=0.4)
        # Score = 0.50 + 0.10*1 - 0.15*1 = 0.45 < 0.50
        ca = create_assessment(case["id"], inv1["id"], subject["id"],
                                corroboration_count=1, contradiction_count=1,
                                account_age_days=0)
        assert ca["score_corroboration"] == pytest.approx(0.45, abs=1e-6)
        finding = create_draft_finding(case["id"], inv1["id"])
        resp = api_client.substantiate_finding(
            finding["id"], {"outcome": "SUBSTANTIATED"},
            make_investigator_headers(inv1["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_CREDIBILITY, 422)
        after = get_success_data(api_client.get_finding(finding["id"], TEST_USERS["er_manager_headers"]))
        assert after["substantiation_status"] == "DRAFT"
