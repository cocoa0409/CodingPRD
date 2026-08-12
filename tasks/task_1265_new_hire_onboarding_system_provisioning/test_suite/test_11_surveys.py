"""Survey lifecycle: submission, weighted score, expiry, and idempotency."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    TEST_USERS,
    ApiErrorId,
    setup_in_progress,
    make_new_hire_headers,
)

HR = TEST_USERS["hr_admin_headers"]


def _get_survey(api, case_id):
    surveys = get_success_data(api.list_case_surveys(case_id, HR))
    assert len(surveys) == 1
    return surveys[0]


def test_survey_overall_score_weighted_half_up(api):
    """PRD §3.9: "the server computes `overall_score` as the weighted blend: the
    experience rating at 0.4, the manager-support rating at 0.3, and the
    resources rating at 0.3, summed and rounded half-up to 2 decimal places."

    ratings 5/4/3 -> 0.4*5 + 0.3*4 + 0.3*3 = 2.0 + 1.2 + 0.9 = 4.10

    Design: Corner/calculations/survey_overall_score_weighted_half_up
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    survey = _get_survey(api, case_id)
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    resp = api.submit_survey(survey["id"], {
        "onboarding_experience_rating": 5,
        "manager_support_rating": 4,
        "resources_rating": 3,
    }, nh)
    data = validate_success(resp)
    assert data["status"] == "SUBMITTED"
    assert data["overall_score"] == pytest.approx(4.10, abs=0.001)


def test_survey_expires_and_locks_submission(api):
    """PRD §3.9: "Unsubmitted, the survey moves automatically from `SENT` to
    `EXPIRED` once the logical time passes `expires_at`, fourteen days after it
    was sent"
    PRD §3.9: "only while it is `SENT`; an expired, submitted, or cancelled
    survey draws `ERR_INVALID_SURVEY_STATE`."

    Design: Corner/state_machines/survey_expires_and_locks_submission
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    survey = _get_survey(api, case_id)
    # Survey sent 2026-05-04T00:00:00Z; expires 2026-05-18T00:00:00Z.
    get_success_data(api.set_current_utc({"to_iso8601": "2026-05-19T00:00:00Z"}, HR))
    surveys = get_success_data(api.list_case_surveys(case_id, HR))
    assert surveys[0]["status"] == "EXPIRED"

    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    resp = api.submit_survey(survey["id"], {
        "onboarding_experience_rating": 5,
        "manager_support_rating": 4,
        "resources_rating": 4,
    }, nh)
    validate_error(resp, ApiErrorId.ERR_INVALID_SURVEY_STATE)


def test_survey_double_submit_idempotency_rejected(api):
    """PRD §3.9: "only while it is `SENT`; an expired, submitted, or cancelled
    survey draws `ERR_INVALID_SURVEY_STATE`."

    First submit succeeds; the second draw the same error because the survey is
    now SUBMITTED.

    Design: Corner/state_machines/survey_double_submit_idempotency_rejected
    """
    ctx = setup_in_progress()
    case_id = ctx["case"]["id"]
    survey = _get_survey(api, case_id)
    nh = make_new_hire_headers(ctx["new_hire"]["id"])
    r1 = api.submit_survey(survey["id"], {
        "onboarding_experience_rating": 5,
        "manager_support_rating": 4,
        "resources_rating": 3,
    }, nh)
    assert validate_success(r1)["status"] == "SUBMITTED"

    r2 = api.submit_survey(survey["id"], {
        "onboarding_experience_rating": 1,
        "manager_support_rating": 1,
        "resources_rating": 1,
    }, nh)
    validate_error(r2, ApiErrorId.ERR_INVALID_SURVEY_STATE)
