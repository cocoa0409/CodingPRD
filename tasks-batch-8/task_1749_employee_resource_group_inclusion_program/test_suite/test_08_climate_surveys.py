"""Climate surveys: response scoring, provisional/final index, close gates,
the CLIMATE_REVIEW posture cascade, and the append-only response resource."""
import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock,
    assert_survey_response,
    create_group_payload,
    create_open_program,
    create_survey,
    create_survey_response_payload,
    make_employee_headers,
    make_group_leader_headers,
    open_survey,
    setup_open_survey,
    submit_response,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import DEI_HEADERS


class TestResponseSubmission:
    def test_survey_response_gates(self, api):
        """PRD §3.9: "Employees respond while the survey is `OPEN` (`ERR_SURVEY_NOT_OPEN` otherwise) and while the current logical time is inside the window — at or after `opens_at` and strictly before `closes_at` (`ERR_SURVEY_WINDOW_CLOSED` outside)."
        PRD §3.9: "One response per respondent per survey: a repeat submission from the same `X-User-ID` is rejected with `ERR_DUPLICATE_RESPONSE`."

        Design: Corner/validations/survey_response_state_window_and_duplicate_gates
        """
        program = create_open_program(100000)
        survey = create_survey(
            program["id"], title="Gates",
            opens_at="2026-08-01T00:00:00Z", closes_at="2026-08-05T00:00:00Z",
            min_responses=1,
        )

        # DRAFT surveys reject responses.
        resp = api.create_survey_response(
            create_survey_response_payload(survey["id"], 4, 4, 4, 4),
            make_employee_headers("emp_r1"),
        )
        validate_error(resp, ApiErrorId.ERR_SURVEY_NOT_OPEN.value, 409)

        open_survey(survey["id"])
        resp = api.create_survey_response(
            create_survey_response_payload(survey["id"], 4, 4, 4, 4),
            make_employee_headers("emp_r1"),
        )
        validate_success(resp, 201)

        # One response per respondent per survey.
        resp = api.create_survey_response(
            create_survey_response_payload(survey["id"], 3, 3, 3, 3),
            make_employee_headers("emp_r1"),
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_RESPONSE.value, 409)

        # The window is half-open: at exactly closes_at it is already closed.
        advance_clock("2026-08-05T00:00:00Z")
        resp = api.create_survey_response(
            create_survey_response_payload(survey["id"], 2, 2, 2, 2),
            make_employee_headers("emp_r2"),
        )
        validate_error(resp, ApiErrorId.ERR_SURVEY_WINDOW_CLOSED.value, 409)

    def test_survey_response_is_append_only(self, api):
        """PRD §2.4: "`SurveyResponse` carries only `id` and `created_at` — both `updated_at` and `version` are absent from it."
        PRD §3.9: "Each response's `response_score` is the weighted blend — 30% belonging, 30% growth, 20% fairness, 20% safety — rounded half-up to 2 decimal places, and the survey's `response_count` rises by 1."

        Design: Corner/entities/survey_response_immutable_common_fields_false
        """
        program = create_open_program(100000)
        survey = setup_open_survey(program["id"], title="S", min_responses=1)
        resp = api.create_survey_response(
            create_survey_response_payload(survey["id"], 4, 4, 4, 4),
            make_employee_headers("emp_r9"),
        )
        data = validate_success(resp, 201)
        assert_survey_response(data)
        assert data["response_score"] == pytest.approx(4.00), "weighted score of all-4s"


class TestProvisionalIndex:
    def test_provisional_index_while_open(self, api):
        """PRD §3.9: "While a survey is `OPEN`, every read exposes `provisional_index`, the mean of `response_score` over the responses received so far, rounded half-up to 2 decimal places — null when there are no responses yet and null again after the survey closes."

        Design: Corner/calculations/climate_provisional_index_while_open
        """
        program = create_open_program(100000)
        survey = setup_open_survey(program["id"], title="Prov", min_responses=2)
        # (5,4,3,2) -> 0.3*5 + 0.3*4 + 0.2*3 + 0.2*2 = 3.70
        submit_response(survey["id"], "emp_r1", 5, 4, 3, 2)

        data = validate_success(api.get_climate_survey(survey["id"], DEI_HEADERS), 200)
        assert data["provisional_index"] == pytest.approx(3.70)
        assert data["final_index"] is None
        assert data["response_count"] == 1


class TestCloseGates:
    def test_close_below_min_responses_rejected(self, api):
        """PRD §3.9: "Closing requires `response_count` to be at least `min_responses`, with equality allowed (`ERR_MIN_RESPONSES_NOT_MET` below the threshold)."

        Design: Corner/validations/survey_close_below_min_responses_rejected
        """
        program = create_open_program(100000)
        survey = setup_open_survey(program["id"], title="Thin", min_responses=2)
        submit_response(survey["id"], "emp_r1", 5, 5, 5, 5)

        resp = api.close_climate_survey(survey["id"], DEI_HEADERS)
        validate_error(resp, ApiErrorId.ERR_MIN_RESPONSES_NOT_MET.value, 409)

        data = validate_success(api.get_climate_survey(survey["id"], DEI_HEADERS), 200)
        assert data["status"] == "OPEN", "rejected close leaves the survey OPEN"

    def test_close_at_exact_min_responses(self, api):
        """PRD §3.9: "Closing requires `response_count` to be at least `min_responses`, with equality allowed (`ERR_MIN_RESPONSES_NOT_MET` below the threshold)."
        PRD §3.9: "Each response's `response_score` is the weighted blend — 30% belonging, 30% growth, 20% fairness, 20% safety — rounded half-up to 2 decimal places, and the survey's `response_count` rises by 1."

        Design: Difficulty/boundary_precision_check/survey_close_at_exact_min_responses
        """
        program = create_open_program(100000)
        survey = setup_open_survey(program["id"], title="Pulse", min_responses=2)
        r1 = submit_response(survey["id"], "emp_r1", 5, 4, 3, 2)
        r2 = submit_response(survey["id"], "emp_r2", 3, 3, 4, 4)
        assert r1["response_score"] == pytest.approx(3.70)
        assert r2["response_score"] == pytest.approx(3.40)

        # response_count 2 == min_responses 2: the boundary satisfies the gate.
        data = validate_success(api.close_climate_survey(survey["id"], DEI_HEADERS), 200)
        assert data["status"] == "CLOSED"
        assert data["response_count"] == 2

    def test_close_freezes_final_index_and_clears_provisional(self, api):
        """PRD §3.9: "Closing moves the survey to the terminal `CLOSED` state, freezes `final_index` as the mean of `response_score` over all responses rounded half-up to 2 decimal places, and clears `provisional_index` to null."
        PRD §2.9: "A `final_index` of exactly 3.00 leaves posture untouched."

        Design: Difficulty/boundary_precision_check/survey_close_at_exact_min_responses
        """
        program = create_open_program(100000)
        survey = setup_open_survey(program["id"], title="Pulse", min_responses=2)
        submit_response(survey["id"], "emp_r1", 5, 4, 3, 2)  # 3.70
        submit_response(survey["id"], "emp_r2", 3, 3, 4, 4)  # 3.40

        data = validate_success(api.close_climate_survey(survey["id"], DEI_HEADERS), 200)
        assert data["final_index"] == pytest.approx(3.55), "mean of 3.70 and 3.40"
        assert data["provisional_index"] is None

        program_data = validate_success(api.get_program(program["id"], DEI_HEADERS), 200)
        assert program_data["posture"] == "NORMAL", "3.55 >= 3.00 threshold"

    def test_second_survey_open_rejected(self, api):
        """PRD §3.9: "Opening a survey requires the program to be in `OPEN` or `ALLOCATION_LOCKED` (`ERR_PROGRAM_NOT_OPEN`) and that no other survey of the same program is already `OPEN` (`ERR_SURVEY_ALREADY_OPEN`); opening moves `DRAFT` → `OPEN`."

        Design: Corner/validations/second_survey_open_rejected
        """
        program = create_open_program(100000)
        s1 = create_survey(program["id"], title="S1", min_responses=1)
        s2 = create_survey(program["id"], title="S2", min_responses=1)
        open_survey(s1["id"])

        resp = api.open_climate_survey(s2["id"], DEI_HEADERS)
        validate_error(resp, ApiErrorId.ERR_SURVEY_ALREADY_OPEN.value, 409)


class TestClimateReviewPosture:
    def test_low_final_index_gates_group_creation_until_cleared(self, api):
        """PRD §3.9: "When the frozen `final_index` is strictly below 3.00, the program's `posture` automatically flips to `CLIMATE_REVIEW`, blocking new group chartering (§2.9) until a `DeiAdmin` clears the review."
        PRD §2.9: "`posture` cycles freely between `NORMAL` and `CLIMATE_REVIEW` and gates new group chartering: while a program's `posture` is `CLIMATE_REVIEW`, creating a new `ErgGroup` in that program is rejected with `ERR_PROGRAM_IN_CLIMATE_REVIEW` (HTTP 409)."
        PRD §2.9: "Posture flips to `CLIMATE_REVIEW` automatically when a climate survey of that program closes with a `final_index` strictly below 3.00, and returns to `NORMAL` only through an explicit `DeiAdmin` clear action carrying a `remediation_note`."

        Design: Corner/calculations/climate_review_posture_gates_group_creation
        """
        program = create_open_program(100000)
        survey = setup_open_survey(program["id"], title="Low Pulse", min_responses=2)
        submit_response(survey["id"], "emp_r1", 1, 1, 1, 1)  # 1.00
        submit_response(survey["id"], "emp_r2", 2, 2, 2, 2)  # 2.00

        data = validate_success(api.close_climate_survey(survey["id"], DEI_HEADERS), 200)
        assert data["final_index"] == pytest.approx(1.50), "below the 3.00 threshold"

        # While CLIMATE_REVIEW, new group chartering is blocked.
        resp = api.create_group(
            create_group_payload(program["id"], "Blocked Group", "m", "AFFINITY"),
            make_group_leader_headers("emp_l31"),
        )
        validate_error(resp, ApiErrorId.ERR_PROGRAM_IN_CLIMATE_REVIEW.value, 409)

        data = validate_success(
            api.clear_climate_review(
                program["id"], {"remediation_note": "Action plan filed"}, DEI_HEADERS
            ),
            200,
        )
        assert data["posture"] == "NORMAL"

        resp = api.create_group(
            create_group_payload(program["id"], "Unblocked Group", "m", "AFFINITY"),
            make_group_leader_headers("emp_l32"),
        )
        validate_success(resp, 201)
