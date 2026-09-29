"""Contractor screening inputs and the two access-control rules that outrank everything else."""

from typing import Any, Dict

import pytest

from test_helpers import (
    AUDITOR_HEADERS,
    CLASSIFICATION_REVIEWER_HEADERS,
    COMPENSATION_MANAGER_HEADERS,
    COMPLIANCE_ANALYST_HEADERS,
    DEFAULT_CLOCK_STAMP,
    EMPLOYEE_RELATIONS_LEAD_HEADERS,
    NON_EXISTENT_UUID,
    NO_USER_ID_HEADERS,
    AnalysisStatus,
    ClassificationStatus,
    CommunicationStatus,
    ContractorOutcome,
    ContractorReviewStatus,
    ErrorId,
    IcTest,
    InterviewStatus,
    NoticeChannel,
    PayConversionStatus,
    RemediationPosture,
    assert_error_envelope,
    assert_project_ledgers,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)


def _review_missing_the_third_prong(project_id: str, state_code: str) -> Dict[str, Any]:
    """Economic-reality factors supplied, `independent_trade` deliberately absent."""
    payload = factories.contractor_review_payload(
        project_id,
        engagement_state_code=state_code,
        free_from_control=True,
        outside_usual_course=True,
        economic_reality_factors=factories.economic_reality_factors(),
    )
    payload.pop("independent_trade")
    return payload


@pytest.fixture
def two_jurisdiction_engagement(api, pinned_clock) -> Dict[str, Any]:
    """Two jurisdictions with different contractor tests and one engagement in PLANNING."""
    fixtures.register_state_rule(api, factories.california_rule_payload())
    fixtures.register_state_rule(api, factories.texas_rule_payload())
    project = fixtures.create_project(api)
    return {"project_id": project["id"]}


@pytest.fixture
def unreferenced_family(api, pinned_clock) -> Dict[str, Any]:
    """An engagement in PLANNING holding one real, still-empty job family."""
    fixtures.register_state_rule(api, factories.california_rule_payload())
    project = fixtures.create_project(api)
    family = fixtures.create_family(api, project["id"])
    return {"project_id": project["id"], "family_id": family["id"]}


def test_the_same_contractor_payload_fails_under_abc_and_passes_under_economic_reality(
    api, two_jurisdiction_engagement
):
    """The jurisdiction chooses the test, so the identical body is complete in one state only.

    PRD: "Which inputs are required depends entirely on the selected test, and the review must
    supply exactly the set that test needs -- a mismatch is `ERR_IC_TEST_INPUTS_MISSING`."

    PRD: "The `outcome` is `CONTRACTOR` when the score is 5 or more, `EMPLOYEE` when it is 2 or
    less, and `INDETERMINATE` at 3 or 4."

    Design: Corner/validations/abc_jurisdiction_demands_the_three_prongs_while_economic_reality_does_not
    """
    project_id = two_jurisdiction_engagement["project_id"]

    validate_error(
        api.create_contractor_review(
            _review_missing_the_third_prong(project_id, "CA"), COMPLIANCE_ANALYST_HEADERS
        ),
        ErrorId.IC_TEST_INPUTS_MISSING,
        409,
    )

    accepted = validate_success(
        api.create_contractor_review(
            _review_missing_the_third_prong(project_id, "TX"), COMPLIANCE_ANALYST_HEADERS
        ),
        201,
    )

    assert accepted["applied_ic_test"] == IcTest.ECONOMIC_REALITY, (
        f"the Texas rule selects the economic-reality test, got {accepted['applied_ic_test']}"
    )
    assert accepted["ic_score"] == 5, (
        f"five of the six factors are true, got {accepted['ic_score']!r}"
    )
    assert accepted["outcome"] == ContractorOutcome.CONTRACTOR, (
        f"a score of 5 yields CONTRACTOR, got {accepted['outcome']}"
    )
    assert accepted["status"] == ContractorReviewStatus.DRAFT, (
        f"a new review opens in DRAFT, got {accepted['status']}"
    )

    rows, meta = validate_paginated(api.list_project_contractor_reviews(project_id, AUDITOR_HEADERS))
    assert meta["total_count"] == 1, (
        f"only the Texas review may have been written, got {meta['total_count']} rows"
    )
    assert rows[0]["id"] == accepted["id"], "the surviving review is the Texas one"

    project = fixtures.read_project(api, project_id)
    assert_project_ledgers(project, posture=RemediationPosture.OPEN)


def test_a_read_only_auditor_is_refused_before_the_family_reference_is_resolved(
    api, unreferenced_family
):
    """One request breaks the role rule and the reference rule; the role rule answers first.

    PRD: "The checks below are evaluated **strictly in this order**; the first rule that is violated
    determines the response, and no later rule runs."

    PRD: "**Role authorization.** `X-User-Role` is one of the seven declared roles and is authorized
    for the target endpoint, else `ERR_ROLE_NOT_PERMITTED` (403)."

    Design: Corner/validations/role_check_runs_before_the_family_lookup_so_an_auditor_is_rejected
    """
    error_data = validate_error(
        api.create_position(
            factories.position_payload(
                NON_EXISTENT_UUID,
                title="Ghost Supervisor",
                job_code="GH-000",
                incumbent_count=1,
                avg_weekly_hours=45,
            ),
            AUDITOR_HEADERS,
        ),
        ErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    assert error_data["error_id"] != ErrorId.JOB_FAMILY_NOT_FOUND, (
        "resolving the reference before authorizing would leak whether the family exists"
    )

    rows, meta = validate_paginated(
        api.list_family_positions(unreferenced_family["family_id"], AUDITOR_HEADERS)
    )
    assert meta["total_count"] == 0, (
        f"the refused create must have written nothing, got {meta['total_count']} rows"
    )
    assert rows == [], f"the real family must still be empty, got {rows}"


def test_five_roles_each_run_their_own_exclusive_write_in_one_walk(api, ca_engagement):
    """Write authority is partitioned, so each of these calls is authorized for exactly its caller.

    PRD: "Write authority is otherwise partitioned: `ProgramAdmin` alone registers jurisdiction
    rules, opens engagements, drives engagement stage, and creates job families and positions;
    `ComplianceAnalyst` alone records duty statements, books interviews, completes and attests them,
    opens and submits exemption analyses, opens contractor reviews and records job-change triggers;
    `ClassificationReviewer` alone returns and determines analyses, voids interviews and finalizes
    contractor reviews; `CompensationManager` alone opens reclassification cases, performs and
    reverts pay conversion and creates back-wage estimates; `EmployeeRelationsLead` alone drives the
    communication dimension of a case; and `LegalCounsel` alone decides a proposed correction."

    Design: Corner/rbac/every_role_can_run_its_own_exclusive_operations
    """
    position_id = ca_engagement["position_id"]

    duty_response = api.create_duty_statement(
        factories.duty_statement_payload(position_id), COMPLIANCE_ANALYST_HEADERS
    )
    assert duty_response.status_code != 403, "the analyst owns duty statements"
    duty = validate_success(duty_response, 201)

    interview_response = api.create_interview(
        factories.interview_payload(
            position_id, "int-51", "2026-09-19T09:00:00Z", "2026-09-19T10:00:00Z"
        ),
        COMPLIANCE_ANALYST_HEADERS,
    )
    assert interview_response.status_code != 403, "the analyst books interviews"
    interview = validate_success(interview_response, 201)

    void_response = api.void_interview(
        interview["id"], {"void_reason": "RESPONDENT_UNAVAILABLE"}, CLASSIFICATION_REVIEWER_HEADERS
    )
    assert void_response.status_code != 403, "the reviewer voids interviews"
    voided = validate_success(void_response, 200)
    assert voided["status"] == InterviewStatus.VOIDED, (
        f"the interview must reach VOIDED, got {voided['status']}"
    )

    case_response = api.create_reclassification_case(
        factories.reclassification_case_payload(position_id), COMPENSATION_MANAGER_HEADERS
    )
    assert case_response.status_code != 403, "the compensation manager opens cases"
    case = validate_success(case_response, 201)

    notice_response = api.case_communication(
        case["id"], factories.communication_payload(), EMPLOYEE_RELATIONS_LEAD_HEADERS
    )
    assert notice_response.status_code != 403, "the employee-relations lead drives communication"
    noticed = validate_success(notice_response, 200)

    assert noticed["communication_status"] == CommunicationStatus.NOTICE_SENT, (
        f"the notice must move the axis to NOTICE_SENT, got {noticed['communication_status']}"
    )
    assert noticed["notice_channel"] == NoticeChannel.EMAIL, (
        f"the requested channel must be recorded, got {noticed['notice_channel']!r}"
    )
    assert noticed["notice_sent_at"] == DEFAULT_CLOCK_STAMP, (
        f"the send is stamped from the logical clock, got {noticed['notice_sent_at']!r}"
    )
    assert noticed["pay_conversion_status"] == PayConversionStatus.PENDING, (
        f"the pay axis is untouched, got {noticed['pay_conversion_status']}"
    )

    duties, _ = validate_paginated(api.list_position_duty_statements(position_id, AUDITOR_HEADERS))
    assert [row["id"] for row in duties] == [duty["id"]], (
        f"the analyst's duty statement must persist, got {duties}"
    )


def test_no_role_inherits_another_roles_exclusive_write(api, submitted_analysis):
    """Determining and attesting each belong to one role, and neither lends them out.

    PRD: "If `X-User-Role` is not one of the seven declared role names, or is a valid role that is
    not authorized for the endpoint being called, the request fails with `ERR_ROLE_NOT_PERMITTED`
    (HTTP 403)."

    Design: Corner/rbac/employee_relations_lead_cannot_determine_an_exemption_analysis
    """
    validate_error(
        api.determine_exemption_analysis(
            submitted_analysis["analysis_id"], EMPLOYEE_RELATIONS_LEAD_HEADERS
        ),
        ErrorId.ROLE_NOT_PERMITTED,
        403,
    )
    validate_error(
        api.attest_interview(submitted_analysis["interviews"]["manager"]["id"], AUDITOR_HEADERS),
        ErrorId.ROLE_NOT_PERMITTED,
        403,
    )

    analysis = fixtures.read_analysis(api, submitted_analysis["analysis_id"])
    assert analysis["status"] == AnalysisStatus.SUBMITTED, (
        f"the analysis must stay SUBMITTED, got {analysis['status']}"
    )
    assert analysis["reviewer_user_id"] is None, (
        f"no reviewer may be recorded, got {analysis['reviewer_user_id']!r}"
    )

    position = fixtures.read_position(api, submitted_analysis["position_id"])
    assert position["classification_status"] == ClassificationStatus.UNREVIEWED, (
        f"the job must stay UNREVIEWED, got {position['classification_status']}"
    )

    project = fixtures.read_project(api, submitted_analysis["project_id"])
    assert_project_ledgers(project, headcount=0, posture=RemediationPosture.OPEN)


def test_a_request_without_a_user_id_header_never_reaches_the_role_check(api, pinned_clock):
    """The identity rule is rank one, so an otherwise perfect payload still fails on the header.

    PRD: "If either header is absent or present but empty, the request fails immediately with
    `ERR_MISSING_USER_CONTEXT` (HTTP 400)."

    Design: Corner/errors/audit_project_create_without_a_user_header_is_rejected
    """
    response = api.create_audit_project(
        factories.audit_project_payload(), NO_USER_ID_HEADERS
    )
    error_data = validate_error(response, ErrorId.MISSING_USER_CONTEXT, 400)

    assert_error_envelope(response.json())
    assert error_data["error_id"] != ErrorId.ROLE_NOT_PERMITTED, (
        "the identity rule must answer before the role rule is consulted"
    )
    assert "id" not in error_data, (
        f"the failure envelope must carry no created row, got {error_data}"
    )
