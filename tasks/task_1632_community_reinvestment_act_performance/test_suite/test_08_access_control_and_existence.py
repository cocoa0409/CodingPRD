"""Authentication, authorization, shared reads, per-resource 404 codes, and
existence-before-business-rule ordering."""
from test_helpers import (
    ApiErrorId,
    NO_AUTH_HEADERS,
    TEST_USERS,
    create_active_area,
    create_assessment_area_payload,
    create_area,
    create_branch_payload,
    create_cd_activity_payload,
    create_exam_cycle_payload,
    create_loan_record_payload,
    create_public_file_payload,
    create_submitted_activity,
    review_decision_payload,
    validate_error,
    validate_success,
)

MISSING = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


# ---------------------------------------------------------------------------
# Queue B — Corner/validations
# ---------------------------------------------------------------------------

def test_request_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "Every request must carry two HTTP headers: `X-User-ID`,
    identifying the acting operator, and `X-User-Role`, declaring the capacity
    in which that operator acts."
    PRD §2.1: "A request that is missing either header, or whose role value is
    not one of these six, is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/request_missing_auth_headers_unauthenticated
    """
    resp = api.create_assessment_area(
        create_assessment_area_payload(area_code="AA-V1", name="No Auth"),
        NO_AUTH_HEADERS,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


def test_rbac_exclusive_operations_forbidden(api):
    """PRD §2.1: "A properly authenticated request whose role is not permitted
    for the target endpoint is rejected with `ERR_FORBIDDEN`."
    PRD §2.1: "All read endpoints are open to every role; write endpoints are
    restricted as summarized in §4."

    Design: Corner/validations/rbac_exclusive_operations_forbidden
    """
    area = create_active_area(area_code="AA-V2", census_tracts=["T1"])
    activity = create_submitted_activity(
        area["id"], submitter_user_id="analyst-1", amount_cents=100000,
        activity_date="2026-01-10",
    )

    # ComplianceAnalyst may not create assessment areas (CRAOfficer exclusive).
    r1 = api.create_assessment_area(
        create_assessment_area_payload(
            area_code="AA-V2B", census_tracts=["T2"], annual_cd_budget_cents=1
        ),
        TEST_USERS["compliance_analyst_headers"],
    )
    # QualificationReviewer may not record loans (ComplianceAnalyst exclusive).
    r2 = api.create_loan_record(
        create_loan_record_payload(area["id"], census_tract="T1"),
        TEST_USERS["qualification_reviewer_headers"],
    )
    # BankExecutive may not schedule exams (BankExaminer exclusive).
    r3 = api.create_exam_cycle(
        create_exam_cycle_payload(), TEST_USERS["bank_executive_headers"]
    )
    # BankExaminer may not create branches (BankExecutive exclusive).
    r4 = api.create_branch(
        create_branch_payload(area["id"], branch_code="BR-F"),
        TEST_USERS["bank_examiner_headers"],
    )
    # CRAOfficer may not render review decisions (QualificationReviewer exclusive).
    r5 = api.review_cd_activity(
        activity["id"],
        review_decision_payload("QUALIFY", allocation_method="PRO_RATA"),
        TEST_USERS["cra_officer_headers"],
    )
    # PlatformAdmin may not create the public file (CRAOfficer exclusive).
    r6 = api.create_public_file(
        create_public_file_payload(bank_name="Forbidden File"),
        TEST_USERS["platform_admin_headers"],
    )
    for resp in (r1, r2, r3, r4, r5, r6):
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


def test_existence_checked_before_business_rules(api, bank_examiner_headers):
    """PRD §2.6: "The server resolves each path-template identifier in sequence
    and rejects the request at the first identifier that does not resolve,
    returning that segment's not-found error".
    PRD §2.11: "When several rules could reject the same request, the server
    evaluates them in a fixed tier order so that the surfaced error is
    deterministic" (existence tier 3 precedes the business-safety tier 5
    public-file gate).

    Design: Corner/validations/existence_checked_before_business_rules
    """
    # No public file exists, so the fieldwork gate would also fail; the
    # existence check on the exam id must surface first.
    resp = api.begin_fieldwork(MISSING, bank_examiner_headers)
    validate_error(resp, ApiErrorId.ERR_EXAM_CYCLE_NOT_FOUND)


# ---------------------------------------------------------------------------
# Queue B — Corner/errors
# ---------------------------------------------------------------------------

def test_not_found_errors_across_remaining_entities(api):
    """PRD §2.6: "The server resolves each path-template identifier in sequence
    and rejects the request at the first identifier that does not resolve,
    returning that segment's not-found error: `ERR_ASSESSMENT_AREA_NOT_FOUND`
    for an assessment area segment, `ERR_LOAN_RECORD_NOT_FOUND` for a loan
    record, `ERR_ACTIVITY_NOT_FOUND` for a community development activity,
    `ERR_BRANCH_NOT_FOUND` for a branch, `ERR_PUBLIC_COMMENT_NOT_FOUND` for a
    public comment, `ERR_PUBLIC_FILE_NOT_FOUND` for the public file,
    `ERR_EXAM_CYCLE_NOT_FOUND` for an exam cycle, and
    `ERR_APPLICATION_NOT_FOUND` for an expansion application."

    Design: Corner/errors/not_found_errors_across_remaining_entities
    """
    analyst = TEST_USERS["compliance_analyst_headers"]
    officer = TEST_USERS["cra_officer_headers"]
    executive = TEST_USERS["bank_executive_headers"]

    validate_error(api.get_loan_record(MISSING, analyst),
                   ApiErrorId.ERR_LOAN_RECORD_NOT_FOUND)
    validate_error(api.resubmit_cd_activity(MISSING, analyst),
                   ApiErrorId.ERR_ACTIVITY_NOT_FOUND)
    validate_error(api.get_branch(MISSING, executive),
                   ApiErrorId.ERR_BRANCH_NOT_FOUND)
    validate_error(api.publish_public_comment(MISSING, officer),
                   ApiErrorId.ERR_PUBLIC_COMMENT_NOT_FOUND)
    validate_error(api.get_public_file(MISSING, officer),
                   ApiErrorId.ERR_PUBLIC_FILE_NOT_FOUND)
    validate_error(api.get_expansion_application(MISSING, executive),
                   ApiErrorId.ERR_APPLICATION_NOT_FOUND)


# ---------------------------------------------------------------------------
# Queue B — Corner/rbac
# ---------------------------------------------------------------------------

def test_get_reads_shared_across_all_roles(api):
    """PRD §2.1: "All read endpoints are open to every role; write endpoints are
    restricted as summarized in §4."

    Design: Corner/rbac/get_reads_shared_across_all_roles
    """
    area = create_area(area_code="AA-R1", name="Shared Read Area")
    readers = [
        TEST_USERS["compliance_analyst_headers"],
        TEST_USERS["qualification_reviewer_headers"],
        TEST_USERS["bank_examiner_headers"],
        TEST_USERS["bank_executive_headers"],
        TEST_USERS["platform_admin_headers"],
    ]
    baseline = validate_success(api.get_assessment_area(area["id"], readers[0]))
    for headers in readers:
        data = validate_success(api.get_assessment_area(area["id"], headers))
        assert data == baseline
