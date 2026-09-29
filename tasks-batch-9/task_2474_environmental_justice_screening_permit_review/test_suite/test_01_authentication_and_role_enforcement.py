"""Authentication, role authorisation, ownership and segregation of duties.

These are the first rungs of the rejection ladder: nothing downstream of them
can be reached until they pass.
"""

from test_helpers import (
    ANALYST_USER_ID,
    APP_DRAFT,
    APP_ENHANCED_REVIEW,
    APP_SUBMITTED,
    ASSESSMENT_SUBMITTED_FOR_QA,
    ANALYST_HEADERS,
    ApiErrorId,
    COMPLAINT_TYPE_ODOR,
    FINDING_VIOLATION_CONFIRMED,
    INSPECTION_SCHEDULED,
    INSPECTOR_1_USER_ID,
    INSPECTOR_2_HEADERS,
    NO_AUTH_HEADERS,
    QA_OUTCOME_ACCEPT,
    SEVERITY_HIGH,
    TRACK_UNDETERMINED,
    UNKNOWN_AREA_ID_FOR_AUTH,
    UNKNOWN_ROLE_HEADERS,
    add_complaint,
    assert_empty_listing,
    assert_field,
    assert_rejected,
    assign_next,
    complete_inspection_payload,
    find_assessment,
    find_inspection,
    make_applicant_headers,
    make_qa_headers,
    read_application,
    read_area,
    read_facility,
    submit_assessment_for_qa,
    triage_accept,
)


class TestAuthenticationHeaders:
    """PRD §2.2 gates every endpoint on the two identity headers."""

    def test_request_without_identity_headers_is_rejected(self, api):
        """A call carrying neither identity header never reaches the resource.

        PRD §2.2: "If either header is absent or empty, the request is rejected
        with `ERR_MISSING_AUTH_HEADERS`."

        Design: Corner/errors/request_without_auth_headers_rejected
        """
        response = api.get_screening_area(UNKNOWN_AREA_ID_FOR_AUTH, NO_AUTH_HEADERS)

        assert_rejected(response, ApiErrorId.MISSING_AUTH_HEADERS)

    def test_request_with_an_undeclared_role_is_rejected(self, api, area_h):
        """A role string outside the declared eight is refused before lookup.

        PRD §2.2: "If `X-User-Role` is present but is not one of the eight roles
        below, the request is rejected with `ERR_UNKNOWN_ROLE`."

        Design: Corner/errors/request_with_undeclared_role_rejected
        """
        response = api.get_screening_area(area_h["area_id"], UNKNOWN_ROLE_HEADERS)

        assert_rejected(response, ApiErrorId.UNKNOWN_ROLE)


class TestEndpointRoleAuthorisation:
    """PRD §4 fixes which role may drive which endpoint."""

    def test_applicant_representative_cannot_run_the_screen(
        self, api, area_k_submitted_application
    ):
        """Screening belongs to the analyst, so the applicant is refused the fork.

        PRD §3.2: "Screening is the fork in the road, and it belongs to the
        `EJAnalyst`."
        PRD §2.10: "The role is authorised for the endpoint — otherwise
        `ERR_ROLE_NOT_PERMITTED` (403). Applies to every endpoint."

        Design: Corner/rbac/applicant_representative_cannot_screen_an_application
        """
        state = area_k_submitted_application
        response = api.screen_application(
            state["app_id"], make_applicant_headers(state["facility_id"])
        )

        assert_rejected(response, ApiErrorId.ROLE_NOT_PERMITTED)

        application = read_application(api, state["app_id"])
        assert_field(application, "status", APP_SUBMITTED)
        assert_field(application, "review_track", TRACK_UNDETERMINED)
        assert_empty_listing(
            # PRD §4 authorises ProgramAdmin, EJAnalyst, QAReviewer, PermitManager,
            # CommunityLiaison and ApplicantRepresentative on this listing; Inspector
            # is not among them, so the read is taken as the analyst.
            api.list_applicability_determinations(state["app_id"], ANALYST_HEADERS)
        )


class TestApplicationOwnership:
    """PRD §2.10 rung 7 binds an applicant's calls to their own facility."""

    def test_applicant_cannot_submit_another_facilitys_application(
        self, api, area_k_draft_application
    ):
        """A representative of a different facility cannot submit this file.

        PRD §2.9/§2.10: "Filing an application for a facility other than the
        caller's own, or submitting, resubmitting or withdrawing an application
        whose `facility_id` is not the caller's `X-User-ID`, is rejected with
        `ERR_NOT_APPLICATION_OWNER`."

        Design: Corner/rbac/applicant_cannot_submit_another_facilitys_application
        """
        state = area_k_draft_application
        response = api.submit_application(
            state["app_id"], make_applicant_headers(state["facility_other_id"])
        )

        assert_rejected(response, ApiErrorId.NOT_APPLICATION_OWNER)

        application = read_application(api, state["app_id"])
        assert_field(application, "status", APP_DRAFT)
        assert_field(application, "facility_id", state["facility_id"])
        assert_field(application, "version", 1)


class TestSegregationOfDuties:
    """PRD §2.11 keeps the author out of the QA seat."""

    def test_qa_decision_by_the_assessment_author_is_rejected(
        self, api, app_a_screening_assessment
    ):
        """A reviewer presenting the author's own user id cannot accept the work.

        PRD §2.11: "A `QAReviewer` whose `X-User-ID` equals the assessment's
        `author_user_id` may not take a QA decision on it." and "Both refusals
        carry `ERR_SEGREGATION_OF_DUTIES`."

        Design: Corner/state_machines/qa_decision_by_the_assessment_author_rejected
        """
        state = app_a_screening_assessment
        submit_assessment_for_qa(api, state)

        response = api.decide_assessment_qa(
            state["assessment_id"],
            {"outcome": QA_OUTCOME_ACCEPT},
            make_qa_headers(ANALYST_USER_ID),
        )

        assert_rejected(response, ApiErrorId.SEGREGATION_OF_DUTIES)

        assessment = find_assessment(api, state["app_id"], state["assessment_id"])
        assert_field(assessment, "status", ASSESSMENT_SUBMITTED_FOR_QA)
        assert_field(assessment, "qa_user_id", None)
        assert_field(assessment, "author_user_id", ANALYST_USER_ID)
        assert_field(read_application(api, state["app_id"]), "status", APP_ENHANCED_REVIEW)


class TestAssignedInspectorOnly:
    """PRD §2.10 rung 8 binds completion to the assigned inspector."""

    def test_unassigned_inspector_cannot_complete_the_inspection(
        self, api, area_m_facility
    ):
        """A second inspector cannot close another inspector's visit.

        PRD §2.2: "an `Inspector` may only complete an inspection whose
        `inspector_user_id` equals their `X-User-ID`; any other inspector is
        rejected with `ERR_NOT_ASSIGNED_INSPECTOR`"

        Design: Corner/errors/unassigned_inspector_cannot_complete_the_inspection
        """
        state = area_m_facility
        complaint = add_complaint(
            api, state, COMPLAINT_TYPE_ODOR, SEVERITY_HIGH, "Feed odor at dawn", resident=11
        )
        triage_accept(api, complaint["id"])
        inspection = assign_next(
            api, state, INSPECTOR_1_USER_ID, "2026-08-05", narrow_to_area=True
        )

        response = api.complete_inspection(
            inspection["id"],
            complete_inspection_payload(
                FINDING_VIOLATION_CONFIRMED, notes="Observed from a different route"
            ),
            INSPECTOR_2_HEADERS,
        )

        assert_rejected(response, ApiErrorId.NOT_ASSIGNED_INSPECTOR)

        stored = find_inspection(api, complaint["id"], inspection["id"])
        assert_field(stored, "status", INSPECTION_SCHEDULED)
        assert_field(stored, "finding", None)
        assert_field(stored, "inspector_user_id", INSPECTOR_1_USER_ID)
        assert_field(read_facility(api, state["facility_id"]), "compliance_status", "IN_COMPLIANCE")
        assert_field(read_area(api, state["area_id"]), "enforcement_burden_points", 0)
