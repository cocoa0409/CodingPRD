"""Evaluation surveys: immutability and rating validation (PRD §2.5, §3.8)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_evaluation_survey,
    create_survey_payload,
    make_participant_headers,
    setup_completed_session_with_attendance,
    validate_error,
    validate_success,
)


class TestSurveyImmutability:
    def test_survey_carries_no_updated_at_or_version(self, api):
        """PRD §2.5: "Two resources are deliberately lighter:
        ConfidentialityAgreement and EvaluationSurvey are immutable once
        created. They carry only `id` and `created_at`; both `updated_at` and
        `version` are absent from them."
        PRD §3.8: "the server stamps `submitted_at` at submission."

        Design: Corner/entities/evaluation_survey_immutable_no_update_endpoint
        """
        env = setup_completed_session_with_attendance()
        survey = validate_success(api.create_survey(
            env.program["id"], env.group["id"], env.session["id"],
            create_survey_payload(env.participant["id"]),
            make_participant_headers(env.participant["id"])), expected_status=201)
        assert_evaluation_survey(survey)
        assert "updated_at" not in survey
        assert "version" not in survey
        assert survey["submitted_at"], "submitted_at must be server-stamped"

        fetched = validate_success(api.get_survey(
            env.program["id"], env.group["id"], env.session["id"],
            survey["id"], ADMIN))
        assert fetched["id"] == survey["id"]
        assert "updated_at" not in fetched
        assert "version" not in fetched


class TestSurveyValidation:
    def test_rating_zero_rejected(self, api):
        """PRD §3.8: "The survey carries `participant_id`, an `overall_rating`,
        a `facilitator_rating`, and a `modality_rating`, each an integer
        between 1 and 5 inclusive, plus an optional `free_text` comment"
        PRD §3.8: "A rating outside the 1-to-5 range, or a submission from a
        participant who did not attend the session, is rejected with
        `ERR_SURVEY_INVALID` (HTTP 422)."

        Design: Corner/errors/error_survey_invalid_rating_out_of_range
        """
        env = setup_completed_session_with_attendance()
        resp = api.create_survey(
            env.program["id"], env.group["id"], env.session["id"],
            create_survey_payload(env.participant["id"], overall_rating=0),
            make_participant_headers(env.participant["id"]))
        validate_error(resp, ApiErrorId.ERR_SURVEY_INVALID)
