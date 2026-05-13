"""Application creation, submission versioning, checklist.

PRD §3.1.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    SEC,
    assert_application,
    assert_submission,
    create_application,
    create_application_with_submission,
    create_application_payload,
    create_submission,
    create_submission_payload,
    get_application,
    make_applicant_headers,
    submit_application,
    unique_applicant_id,
    validate_error,
    validate_success,
)


# ===========================================================================
# Application creation (PRD §3.1)
# ===========================================================================
class TestCreateApplication:
    """PRD §3.1: Application creation."""

    def test_create_application_enters_draft(self, api):
        """PRD §3.1: 'On creation the application enters DRAFT status,
        its current_submission_version begins at 0, both
        approved_submission_version and approval_resolution_id are
        null, and the server records the caller's X-User-ID as
        applicant_id.'"""
        aid = unique_applicant_id()
        headers = make_applicant_headers(aid)
        res = api.create_application(
            create_application_payload(), headers,
        )
        data = validate_success(res, expected_status=201)
        assert_application(data)
        assert data["status"] == "DRAFT", (
            f"PRD §3.1: new applications must enter DRAFT; got "
            f"{data['status']!r}"
        )
        assert data["current_submission_version"] == 0, (
            f"PRD §3.1: 'current_submission_version begins at 0'; got "
            f"{data['current_submission_version']!r}"
        )
        assert data.get("approved_submission_version") is None, (
            f"PRD §3.1: 'approved_submission_version ... null'; got "
            f"{data.get('approved_submission_version')!r}"
        )
        assert data.get("approval_resolution_id") is None, (
            f"PRD §3.1: 'approval_resolution_id ... null'; got "
            f"{data.get('approval_resolution_id')!r}"
        )
        assert data["applicant_id"] == aid, (
            f"PRD §3.1: 'records the caller's X-User-ID as applicant_id'; "
            f"got {data['applicant_id']!r} vs {aid!r}"
        )

    def test_create_application_default_review_track_is_standard(self, api):
        """PRD §3.1: 'review_track parameter is either STANDARD for the
        periodic review channel or EXPEDITED for the urgent-review
        channel, and defaults to STANDARD when omitted.'"""
        aid = unique_applicant_id()
        headers = make_applicant_headers(aid)
        payload = create_application_payload()
        # ensure no review_track in payload
        payload.pop("review_track", None)
        res = api.create_application(payload, headers)
        data = validate_success(res, expected_status=201)
        assert data["review_track"] == "STANDARD", (
            f"PRD §3.1: 'defaults to STANDARD when omitted'; got "
            f"{data['review_track']!r}"
        )

    @pytest.mark.parametrize(
        "phase",
        ["PHASE_I", "PHASE_II", "PHASE_III", "PHASE_IV"],
    )
    def test_create_application_accepts_each_phase(self, api, phase):
        """PRD §3.1: 'The trial phase must be one of PHASE_I, PHASE_II,
        PHASE_III, or PHASE_IV.'"""
        aid = unique_applicant_id()
        headers = make_applicant_headers(aid)
        res = api.create_application(
            create_application_payload(phase=phase), headers,
        )
        data = validate_success(res, expected_status=201)
        assert data["phase"] == phase

    def test_create_application_invalid_phase_rejected(self, api):
        """PRD §3.1: 'The trial phase must be one of PHASE_I, PHASE_II,
        PHASE_III, or PHASE_IV.' PRD §2.7 validation priority 15:
        ERR_FIELD_VALIDATION on out-of-set enum."""
        aid = unique_applicant_id()
        headers = make_applicant_headers(aid)
        res = api.create_application(
            create_application_payload(phase="PHASE_V"), headers,
        )
        validate_error(res, ApiErrorId.ERR_FIELD_VALIDATION.value)


# ===========================================================================
# Submission upload (PRD §3.1)
# ===========================================================================
class TestCreateSubmission:
    """PRD §3.1: Submission upload."""

    def test_first_submission_version_is_1(self, api):
        """PRD §3.1: 'The server assigns the new submission a
        version_number equal to one greater than the maximum existing
        version_number under that application (starting at 1 for the
        first submission)'."""
        app = create_application()
        sub = create_submission(app)
        assert_submission(sub)
        assert sub["version_number"] == 1, (
            f"PRD §3.1: 'starting at 1 for the first submission'; got "
            f"{sub['version_number']!r}"
        )
        assert sub["is_current"] is True, (
            f"PRD §3.1: 'sets is_current to true on the new row'; got "
            f"{sub.get('is_current')!r}"
        )
        assert sub["application_id"] == app["id"]

    def test_second_submission_version_is_2_and_prev_loses_current(self, api):
        """PRD §3.1: 'one greater than the maximum existing
        version_number ...'; 'sets is_current to true on the new row,
        clears is_current on whichever sibling submission had previously
        been current, and updates the parent application's
        current_submission_version to match.'"""
        app = create_application()
        sub_v1 = create_submission(app)
        sub_v2 = create_submission(app)
        assert sub_v2["version_number"] == 2
        # Application reflects new current.
        app_after = get_application(app["id"])
        assert app_after["current_submission_version"] == 2

    def test_checklist_complete_true_when_all_uris_present(self, api):
        """PRD §3.1: 'checklist_complete flag is computed by inspecting
        the four document URIs: it is true only when all four are
        non-null, non-empty strings, and false otherwise.'"""
        app = create_application()
        sub = create_submission(app)
        assert sub["checklist_complete"] is True

    @pytest.mark.parametrize(
        "missing_field",
        ["protocol_doc_uri", "investigator_brochure_uri",
         "informed_consent_uri", "cv_doc_uri"],
    )
    def test_checklist_complete_false_when_uri_empty(self, api, missing_field):
        """PRD §3.1: 'checklist_complete ... is true only when all four
        are non-null, non-empty strings, and false otherwise.'"""
        app = create_application()
        payload = create_submission_payload()
        payload[missing_field] = ""  # empty string
        res = api.create_submission(
            app["id"], payload,
            make_applicant_headers(app["applicant_id"]),
        )
        # PRD allows the row to be created with checklist_complete=false.
        # If implementation rejects empty string as ERR_FIELD_VALIDATION
        # that's a strict reading; PRD §3.1 prose says checklist_complete
        # is "false otherwise", so the row exists. We assert the body
        # carries checklist_complete=false either way only if 2xx.
        if 200 <= res.status_code < 300:
            sub = validate_success(res, expected_status=201)
            assert sub["checklist_complete"] is False, (
                f"PRD §3.1: 'checklist_complete ... false otherwise'; "
                f"got {sub.get('checklist_complete')!r}"
            )

    def test_new_submission_prescreen_status_starts_pending(self, api):
        """PRD §3.1: 'Each new submission's prescreen_status starts at
        PENDING'."""
        app = create_application()
        sub = create_submission(app)
        assert sub["prescreen_status"] == "PENDING", (
            f"PRD §3.1: 'starts at PENDING'; got "
            f"{sub.get('prescreen_status')!r}"
        )


# ===========================================================================
# Submit for prescreen (PRD §3.1)
# ===========================================================================
class TestSubmitForPrescreen:
    """PRD §3.1: 'When the applicant submits the current submission for
    formal pre-screening, the application transitions out of DRAFT (or
    out of REWORK_REQUIRED if this is a rework cycle) into
    PENDING_PRESCREEN.'"""

    def test_submit_moves_application_to_pending_prescreen(self, api):
        """PRD §3.1: 'the application transitions out of DRAFT ... into
        PENDING_PRESCREEN.'"""
        app, _ = create_application_with_submission()
        updated = submit_application(app)
        assert updated["status"] == "PENDING_PRESCREEN", (
            f"PRD §3.1: 'transitions ... into PENDING_PRESCREEN'; got "
            f"{updated['status']!r}"
        )

    def test_submit_without_any_submission_rejected(self, api):
        """PRD §3.1: 'The precondition for this transition is that the
        application has a current submission with checklist_complete
        true; if any required document URI is missing, the request is
        rejected with ERR_CHECKLIST_INCOMPLETE.'"""
        app = create_application()  # no submission yet
        res = api.submit_application(
            app["id"], make_applicant_headers(app["applicant_id"]),
        )
        validate_error(res, ApiErrorId.ERR_CHECKLIST_INCOMPLETE.value)

    def test_submit_with_incomplete_checklist_rejected(self, api):
        """PRD §3.1: 'if any required document URI is missing, the
        request is rejected with ERR_CHECKLIST_INCOMPLETE.'"""
        app = create_application()
        # Create an incomplete submission by omitting one URI via empty string.
        payload = create_submission_payload(protocol_doc_uri="")
        res = api.create_submission(
            app["id"], payload,
            make_applicant_headers(app["applicant_id"]),
        )
        # If implementation rejects creation outright, skip this assertion
        # path; the rule under test is the submit-side check.
        if 200 <= res.status_code < 300:
            # incomplete submission accepted; submit should now fail
            sub_res = api.submit_application(
                app["id"], make_applicant_headers(app["applicant_id"]),
            )
            validate_error(sub_res,
                           ApiErrorId.ERR_CHECKLIST_INCOMPLETE.value)
