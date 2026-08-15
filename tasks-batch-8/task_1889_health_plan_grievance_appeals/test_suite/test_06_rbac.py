"""Corner queue: RBAC denials and segregation of duties (PRD §2.1, §2.10, §4)."""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    CLOCK_DEFAULT_ISO,
    TEST_USERS, make_case_analyst_headers, make_medical_director_headers,
    create_member, create_provider, create_policy, set_clock,
    intake_case, triage_case, begin_review, create_in_review_case,
    decide_grievance_from_in_review, create_and_send_decision_notification,
    request_clinical_review, setup_notified_case,
)

ADMIN = TEST_USERS["platform_admin_headers"]
INTAKE = TEST_USERS["intake_specialist_headers"]
ANALYST = TEST_USERS["case_analyst_headers"]
MD = TEST_USERS["medical_director_headers"]
MSR = TEST_USERS["member_services_rep_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]
CLAIMS = TEST_USERS["claims_processor_headers"]


def test_intake_specialist_cannot_decide(api):
    """PRD §2.1: "A well-authenticated request whose role is not permitted to call the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 authorizes the decide endpoint for MedicalDirector and CaseAnalyst
    only.

    Design: Corner/rbac/intake_specialist_cannot_decide
    """
    member = create_member("MBR-RB1", full_name="Rbac One", program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = create_in_review_case(member["id"], case_kind="GRIEVANCE")
    validate_error(
        api.decide_case(case["id"], {"decision_outcome": "UNFAVORABLE"},
                        INTAKE),
        ApiErrorId.ERR_UNAUTHORIZED)


def test_case_analyst_cannot_expedite(api):
    """PRD §2.1: "A well-authenticated request whose role is not permitted to call the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 authorizes the expedite endpoint for MedicalDirector only.

    Design: Corner/rbac/case_analyst_cannot_expedite
    """
    member = create_member("MBR-RB2", full_name="Rbac Two", program="MEDICARE")
    provider = create_provider("9988776655", legal_name="Rbac Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    create_policy("MEDICARE", "APPEAL", "EXPEDITED", resolution_hours=72,
                  extension_hours=0, effectuation_hours=24)
    set_clock(CLOCK_DEFAULT_ISO)
    case = triage_case(intake_case(member["id"], case_kind="APPEAL",
                                   provider_id=provider["id"])["id"])
    validate_error(api.expedite_case(case["id"], ANALYST),
                   ApiErrorId.ERR_UNAUTHORIZED)


def test_member_services_rep_cannot_close(api):
    """PRD §2.1: "A well-authenticated request whose role is not permitted to call the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 authorizes the close endpoint for ComplianceOfficer only.

    Design: Corner/rbac/member_services_rep_cannot_close
    """
    member = create_member("MBR-RB3", full_name="Rbac Three",
                           program="MEDICARE")
    create_policy("MEDICARE", "GRIEVANCE", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = setup_notified_case(member["id"], case_kind="GRIEVANCE",
                               decision_outcome="UNFAVORABLE")
    validate_error(api.close_case(case["id"], MSR),
                   ApiErrorId.ERR_UNAUTHORIZED)


def test_claims_processor_cannot_snapshot_audit(api):
    """PRD §2.1: "A well-authenticated request whose role is not permitted to call the
    target endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
    PRD §4 authorizes the audit-universe snapshot endpoint for
    ComplianceOfficer only.

    Design: Corner/rbac/claims_processor_cannot_snapshot_audit
    """
    validate_error(api.create_audit_snapshot({"report_period": "2026-08"},
                                             CLAIMS),
                   ApiErrorId.ERR_UNAUTHORIZED)


def test_segregation_of_duties_self_assign_blocked(api):
    """PRD §2.10: "And when a clinical review is assigned, the named `reviewer_physician_id`
    must belong to an operator acting in the `MedicalDirector` role whose
    `X-User-ID` differs from the `CaseAnalyst` who requested the review;
    self-assignment is forbidden."
PRD §2.10: "Either violation is rejected with `ERR_DUTY_SEGREGATION` (HTTP 422)."

    Design: Corner/rbac/segregation_of_duties_self_assign_blocked
    """
    member = create_member("MBR-RB5", full_name="Sod Assign", program="MEDICARE")
    provider = create_provider("8877665544", legal_name="Sod Clinic",
                               w9_on_file=True)
    create_policy("MEDICARE", "APPEAL", "STANDARD", resolution_hours=720,
                  extension_hours=0, effectuation_hours=72)
    set_clock(CLOCK_DEFAULT_ISO)
    case = triage_case(intake_case(member["id"], case_kind="APPEAL",
                                   provider_id=provider["id"])["id"])
    begin_review(case["id"])
    # The requesting analyst's X-User-ID is 'analyst-7'.
    review = get_success_data(api.request_clinical_review(
        case["id"], make_case_analyst_headers("analyst-7")),
        expected_status=201)
    # Assigning the review to the same operator id violates self-assignment.
    validate_error(
        api.assign_clinical_review(
            review["id"], {"reviewer_physician_id": "analyst-7"},
            make_medical_director_headers("md-admin")),
        ApiErrorId.ERR_DUTY_SEGREGATION)
