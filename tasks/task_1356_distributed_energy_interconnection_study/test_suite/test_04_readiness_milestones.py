"""Readiness milestone submission, review, and the reject/resubmit cycle."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_milestone_submission,
    create_project,
    create_queued_project,
    get_project,
    make_developer_headers,
    review_milestone,
    satisfy_readiness,
    scope_study,
    setup_developer_and_cluster,
    setup_study_scenario,
    submit_milestone,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["queue_admin_headers"]


class TestRejectResubmitCycle:
    def test_milestone_reject_records_note_and_status(self, api):
        """PRD §3.3: "Rejection records the note and moves the submission to
        `REJECTED`"

        Design: Difficulty/non_linear_state_machine/milestone_reject_resubmit_cycle
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_queued_project(developer["id"], cluster["id"])
        submission = submit_milestone(project["id"], developer["id"], "SITE_CONTROL",
                                      evidence_uri="s3://ev/site-v1.pdf")

        resp = api.review_milestone_submission(
            submission["id"],
            {"decision": "REJECTED", "review_note": "lease expires too soon"},
            ADMIN)
        data = validate_success(resp, expected_status=200)
        assert_milestone_submission(data)
        assert data["status"] == "REJECTED"
        assert data["review_note"] == "lease expires too soon"

    def test_milestone_resubmit_restores_pending_then_accept(self, api):
        """PRD §3.3: "the resubmission supplies a new `evidence_uri`, which replaces
        the old one, clears the recorded `review_note` back to null, and returns
        the submission to `PENDING_REVIEW`."
        PRD §3.3: "Acceptance has a cascade: when every required milestone type for
        the project has an `ACCEPTED` submission, the project's
        `readiness_satisfied` flips to true, and if the project is `QUEUED` at that
        moment it advances automatically to `READY`."

        Design: Difficulty/non_linear_state_machine/milestone_reject_resubmit_cycle
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_queued_project(developer["id"], cluster["id"])
        submission = submit_milestone(project["id"], developer["id"], "SITE_CONTROL",
                                      evidence_uri="s3://ev/site-v1.pdf")
        review_milestone(submission["id"], "REJECTED",
                         review_note="lease expires too soon")

        resp = api.resubmit_milestone_submission(
            submission["id"], {"evidence_uri": "s3://ev/site-v2.pdf"},
            make_developer_headers(developer["id"]))
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "PENDING_REVIEW", "REJECTED -> PENDING_REVIEW cycle edge"
        assert data["evidence_uri"] == "s3://ev/site-v2.pdf", "evidence replaced"
        assert data["review_note"] is None, "review_note cleared to null"

        resp = api.review_milestone_submission(
            submission["id"], {"decision": "ACCEPTED", "review_note": "ok"}, ADMIN)
        assert validate_success(resp, expected_status=200)["status"] == "ACCEPTED"

        # TECHNICAL_DATA is still missing, so readiness is not satisfied and the
        # project stays QUEUED.
        after = get_project(project["id"])
        assert after["status"] == "QUEUED"
        assert after["readiness_satisfied"] is False


class TestReviewAndResubmitGates:
    def test_milestone_review_after_accept_rejected(self, api):
        """PRD §3.3: "reviewing a submission that is no longer pending is refused
        with `ERR_MILESTONE_NOT_PENDING_REVIEW`."

        Design: Corner/state_machines/milestone_review_after_accept_rejected
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_queued_project(developer["id"], cluster["id"])
        submission = submit_milestone(project["id"], developer["id"], "SITE_CONTROL")
        review_milestone(submission["id"], "ACCEPTED")

        resp = api.review_milestone_submission(
            submission["id"],
            {"decision": "REJECTED", "review_note": "changed my mind"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_PENDING_REVIEW)

        submissions = _list_submissions(api, project["id"])
        assert submissions[0]["status"] == "ACCEPTED", "no state change on failed review"

    def test_milestone_resubmit_from_pending_rejected(self, api):
        """PRD §3.3: "Resubmitting a submission that is not currently `REJECTED` is
        refused with `ERR_MILESTONE_NOT_REJECTED`"

        Design: Corner/state_machines/milestone_resubmit_from_pending_rejected
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_queued_project(developer["id"], cluster["id"])
        submission = submit_milestone(project["id"], developer["id"], "SITE_CONTROL",
                                      evidence_uri="s3://ev/site.pdf")

        resp = api.resubmit_milestone_submission(
            submission["id"], {"evidence_uri": "s3://ev/site-v2.pdf"},
            make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_MILESTONE_NOT_REJECTED)

        submissions = _list_submissions(api, project["id"])
        assert submissions[0]["status"] == "PENDING_REVIEW"
        assert submissions[0]["evidence_uri"] == "s3://ev/site.pdf", (
            "failed resubmit did not replace the evidence"
        )


class TestSubmissionConstraints:
    def test_milestone_submission_conflict_rejected(self, api):
        """PRD §3.3: "At most one submission per project and `milestone_type` may
        be live at once — that is, in `PENDING_REVIEW` or `ACCEPTED`; a duplicate
        attempt fails with `ERR_MILESTONE_SUBMISSION_CONFLICT`."

        Design: Corner/validations/milestone_submission_conflict_rejected
        """
        developer, cluster = setup_developer_and_cluster()
        project = create_queued_project(developer["id"], cluster["id"])
        submit_milestone(project["id"], developer["id"], "SITE_CONTROL",
                         evidence_uri="s3://ev/site.pdf")

        resp = api.create_milestone_submission(
            project["id"],
            {"milestone_type": "SITE_CONTROL", "evidence_uri": "s3://ev/site-dup.pdf"},
            make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_MILESTONE_SUBMISSION_CONFLICT)

        submissions = _list_submissions(api, project["id"])
        site = [s for s in submissions if s["milestone_type"] == "SITE_CONTROL"]
        assert len(site) == 1, "exactly one SITE_CONTROL submission exists"

    def test_milestone_submission_wrong_state_rejected(self, api):
        """PRD §3.3: "A submission is accepted only while the project is in
        `SUBMITTED` or `QUEUED`; later it is rejected with
        `ERR_PROJECT_NOT_ACCEPTING_MILESTONES`."

        Design: Corner/validations/milestone_submission_wrong_state_rejected
        """
        scenario = setup_study_scenario([{"capacity_mw": 10}], publish=False)
        project = scenario["projects"][0]
        developer = scenario["developer"]
        assert project["status"] == "IN_STUDY"

        resp = api.create_milestone_submission(
            project["id"],
            {"milestone_type": "SITE_CONTROL", "evidence_uri": "s3://ev/late.pdf"},
            make_developer_headers(developer["id"]))
        validate_error(resp, ApiErrorId.ERR_PROJECT_NOT_ACCEPTING_MILESTONES)


def _list_submissions(api, project_id):
    data, _meta = validate_paginated(api.list_milestone_submissions(project_id, ADMIN))
    return data
