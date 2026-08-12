"""Application and interview workflow guards: invalid states, role denials,
panel membership, and bad enums (PRD §2.1, §2.8, §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_application, create_application_under_review,
    create_board_ready_application, create_denied_application,
    create_score_payload, create_interview_payload,
    make_applicant_headers, make_staff_headers, make_reviewer_headers,
    make_board_headers, api_client,
)

STAFF = make_staff_headers("staff_1")


class TestDecideFromSubmittedRejected:
    def test_decide_before_board_review_rejected_and_no_school_created(self, api):
        """PRD §3.1: "Approval requires the application to sit in `BOARD_REVIEW`
        and its `composite_score` to reach at least 75.0 — the threshold is
        inclusive — so a composite below 75.0 is rejected with
        `ERR_COMPOSITE_BELOW_THRESHOLD`."
        PRD §2.9: "then state preconditions (the various invalid-state
        conflicts, plus `ERR_TARGET_NOT_APPEALABLE` and `ERR_SCHOOL_NOT_OPEN`)"

        Design: Corner/state_machines/sm_decide_from_submitted_rejected
        """
        app = create_application(school_name="SM Early Decide",
                                 applicant_id="applicant_s1")
        assert app["status"] == "SUBMITTED"
        res = api.decide_application(app["id"], {"outcome": "APPROVED"},
                                     make_board_headers("board_1"))
        validate_error(res, ApiErrorId.ERR_APPLICATION_INVALID_STATE,
                       expected_status=409)
        schools = validate_success(api.list_application_schools(app["id"], STAFF), 200)
        assert schools == []


class TestInterviewDoubleScoreRejected:
    def test_second_score_on_scored_interview_rejected(self, api):
        """PRD §3.1: "The caller must be an `ApplicationReviewer` whose
        `X-User-ID` appears in `panelist_user_ids` (else `ERR_NOT_PANELIST`),
        the interview must still be `SCHEDULED` (else
        `ERR_INTERVIEW_INVALID_STATE`), and the `panel_score` must fall between
        0 and 100 inclusive (else `ERR_INVALID_REQUEST`)."

        Design: Corner/state_machines/sm_interview_double_score_rejected
        """
        app = create_application_under_review(school_name="SM Double Score",
                                              applicant_id="applicant_s2")
        interview = validate_success(
            api.schedule_interview(
                app["id"],
                create_interview_payload(scheduled_start="2026-05-22T10:00:00Z",
                                         scheduled_end="2026-05-22T11:00:00Z",
                                         panelist_user_ids=["rev_panel_s2"]),
                STAFF), 201)
        scored = validate_success(
            api.score_interview(interview["id"], {"panel_score": 70},
                                make_reviewer_headers("rev_panel_s2")), 200)
        assert scored["status"] == "SCORED"

        res = api.score_interview(interview["id"], {"panel_score": 95},
                                  make_reviewer_headers("rev_panel_s2"))
        validate_error(res, ApiErrorId.ERR_INTERVIEW_INVALID_STATE, expected_status=409)

        interviews = validate_success(api.list_interviews(app["id"], STAFF), 200)
        assert len(interviews) == 1
        assert interviews[0]["panel_score"] == 70


class TestScoresAfterDeniedRejected:
    def test_score_on_denied_application_rejected(self, api):
        """PRD §3.1: "Scores are accepted only while the application is
        `UNDER_REVIEW`; against any other status the submission draws
        `ERR_APPLICATION_INVALID_STATE`."

        Design: Corner/state_machines/sm_scores_after_denied_rejected
        """
        app = create_denied_application(school_name="SM Denied Academy",
                                        applicant_id="applicant_s16",
                                        reviewer_id="rev_s16",
                                        panelist_id="rev_panel_s16",
                                        denial_reason="Governance concerns",
                                        interview_start="2026-06-07T10:00:00Z",
                                        interview_end="2026-06-07T11:00:00Z")
        assert app["status"] == "DENIED"
        res = api.post_application_score(
            app["id"], create_score_payload(criterion="ACADEMIC_PLAN", score=95),
            make_reviewer_headers("rev_other_s16"))
        validate_error(res, ApiErrorId.ERR_APPLICATION_INVALID_STATE,
                       expected_status=409)
        current = validate_success(api.get_application(app["id"], STAFF), 200)
        assert current["status"] == "DENIED"
        assert current["rubric_score"] == pytest.approx(80.0, abs=0.001)


class TestRoleDenialsOnApplicationWorkflow:
    def test_reviewer_cannot_decide(self, api):
        """PRD §2.1: "A caller whose role is not in the endpoint's authorized
        list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §2.9: "A request that would fail both an authorization check and a
        state check therefore always surfaces the authorization error"

        Design: Corner/validations/val_role_denied_reviewer_cannot_decide
        """
        app, _interview = create_board_ready_application(
            school_name="Val Role Academy", applicant_id="applicant_v1",
            reviewer_id="rev_v1", rubric_scores=(80, 80, 80, 80, 80),
            panelist_id="rev_panel_v1", panel_score=80,
            interview_start="2026-06-11T10:00:00Z",
            interview_end="2026-06-11T11:00:00Z")
        assert app["status"] == "BOARD_REVIEW"
        res = api.decide_application(app["id"], {"outcome": "APPROVED"},
                                     make_reviewer_headers("rev_v1"))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)
        current = validate_success(api.get_application(app["id"], STAFF), 200)
        assert current["status"] == "BOARD_REVIEW"

    def test_applicant_cannot_accept_intake(self, api):
        """PRD §2.1: "A caller whose role is not in the endpoint's authorized
        list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.1: "Completeness review is a staff function: when
        `AuthorizerStaff` accepts intake, the application moves `SUBMITTED` →
        `UNDER_REVIEW`"

        Design: Corner/rbac/rbac_applicant_cannot_accept_intake
        """
        app = create_application(school_name="RBAC Intake Academy",
                                 applicant_id="applicant_b1")
        res = api.accept_intake(app["id"], make_applicant_headers("applicant_b1"))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)
        current = validate_success(api.get_application(app["id"], STAFF), 200)
        assert current["status"] == "SUBMITTED"

    def test_board_member_cannot_post_rubric_score(self, api):
        """PRD §2.1: "A caller whose role is not in the endpoint's authorized
        list is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §3.1: "While an application is `UNDER_REVIEW`, each
        `ApplicationReviewer` posts one score per rubric criterion."

        Design: Corner/rbac/rbac_board_cannot_score
        """
        app = create_application_under_review(school_name="RBAC Score Academy",
                                              applicant_id="applicant_b2")
        res = api.post_application_score(
            app["id"], create_score_payload(criterion="ACADEMIC_PLAN", score=90),
            make_board_headers("board_1"))
        validate_error(res, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS,
                       expected_status=403)
        current = validate_success(api.get_application(app["id"], STAFF), 200)
        assert current["review_scores"] == []


class TestPanelAndInterviewConstraints:
    def test_second_active_interview_rejected(self, api):
        """PRD §3.1: "the application may have at most one interview that is
        not `CANCELLED`, else `ERR_INTERVIEW_ALREADY_ACTIVE`"

        Design: Corner/validations/val_second_active_interview_rejected
        """
        app = create_application_under_review(school_name="Val TwoInt Academy",
                                              applicant_id="applicant_v5")
        validate_success(
            api.schedule_interview(
                app["id"],
                create_interview_payload(scheduled_start="2026-06-15T10:00:00Z",
                                         scheduled_end="2026-06-15T11:00:00Z",
                                         panelist_user_ids=["rev_panel_v5"]),
                STAFF), 201)
        res = api.schedule_interview(
            app["id"],
            create_interview_payload(scheduled_start="2026-06-16T10:00:00Z",
                                     scheduled_end="2026-06-16T11:00:00Z",
                                     panelist_user_ids=["rev_panel_v5b"]),
            STAFF)
        validate_error(res, ApiErrorId.ERR_INTERVIEW_ALREADY_ACTIVE,
                       expected_status=409)

    def test_non_panelist_cannot_score_interview(self, api):
        """PRD §2.8: "Only a listed panelist may record an interview's
        `panel_score`; a scorer whose `X-User-ID` is absent from
        `panelist_user_ids` is rejected with `ERR_NOT_PANELIST` (HTTP 403)."

        Design: Corner/rbac/rbac_non_panelist_cannot_score_interview
        """
        app = create_application_under_review(school_name="RBAC Panel Academy",
                                              applicant_id="applicant_b5")
        interview = validate_success(
            api.schedule_interview(
                app["id"],
                create_interview_payload(scheduled_start="2026-06-23T10:00:00Z",
                                         scheduled_end="2026-06-23T11:00:00Z",
                                         panelist_user_ids=["rev_panel_b5"]),
                STAFF), 201)
        res = api.score_interview(interview["id"], {"panel_score": 88},
                                  make_reviewer_headers("rev_outsider_b5"))
        validate_error(res, ApiErrorId.ERR_NOT_PANELIST, expected_status=403)
        interviews = validate_success(api.list_interviews(app["id"], STAFF), 200)
        assert interviews[0]["status"] == "SCHEDULED"
        assert interviews[0]["panel_score"] is None


class TestInvalidEnumOnDecide:
    def test_outcome_outside_enum_rejected(self, api):
        """PRD §4: "Board decision: APPROVED or DENIED (reason required for
        denial)" — an `outcome` outside that pair is an invalid request, and
        PRD §5 assigns HTTP 400 to ERR_INVALID_REQUEST.

        Design: Corner/errors/error_invalid_enum_on_decide
        """
        app, _interview = create_board_ready_application(
            school_name="Err Enum Academy", applicant_id="applicant_r1",
            reviewer_id="rev_r1", rubric_scores=(80, 80, 80, 80, 80),
            panelist_id="rev_panel_r1", panel_score=80,
            interview_start="2026-06-20T10:00:00Z",
            interview_end="2026-06-20T11:00:00Z")
        res = api.decide_application(app["id"], {"outcome": "MAYBE"},
                                     make_board_headers("board_1"))
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST, expected_status=400)
        current = validate_success(api.get_application(app["id"], STAFF), 200)
        assert current["status"] == "BOARD_REVIEW"
